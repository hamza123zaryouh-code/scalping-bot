from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from core.risk_manager import calculate_position_size

from .models import ClosedTradeResult, ExecutionResult, SignalDecision, StrategyParameters
from .settings import XAUUSDSettings

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


logger = logging.getLogger(__name__)


class DataExecutionLayer:
    def __init__(self, settings: XAUUSDSettings) -> None:
        self.settings = settings
        self.connected = False
        self.paper_balance = settings.paper_starting_balance
        self.paper_positions: dict[str, dict[str, Any]] = {}

    def connect(self) -> bool:
        if mt5 is None:
            logger.warning("MetaTrader5 package not installed. Falling back to paper/yfinance feed when possible.")
            return self.settings.mode == "paper"
        if not self.settings.mt5_ready:
            logger.warning("MT5 credentials missing. Using paper mode fallback only.")
            return self.settings.mode == "paper"
        if not mt5.initialize():
            logger.error("MT5 initialize failed: %s", mt5.last_error())
            return False
        if not mt5.login(self.settings.mt5_login, password=self.settings.mt5_password, server=self.settings.mt5_server):
            logger.error("MT5 login failed: %s", mt5.last_error())
            mt5.shutdown()
            return False
        if not mt5.symbol_select(self.settings.symbol, True):
            logger.error("Could not select symbol %s", self.settings.symbol)
            mt5.shutdown()
            return False
        self.connected = True
        return True

    def shutdown(self) -> None:
        if mt5 is not None and self.connected:
            mt5.shutdown()
            self.connected = False

    def fetch_recent_candles(self) -> pd.DataFrame:
        if mt5 is not None and self.connected:
            timeframe = self._resolve_mt5_timeframe(self.settings.timeframe)
            rates = mt5.copy_rates_from_pos(self.settings.symbol, timeframe, 0, self.settings.history_bars)
            if rates is None:
                raise RuntimeError(f"MT5 returned no rates: {mt5.last_error()}")
            frame = pd.DataFrame(rates)
            if frame.empty:
                return frame
            frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True).dt.tz_localize(None)
            return (
                frame.rename(columns={"tick_volume": "volume"})
                .assign(spread=lambda data: data.get("spread", 0.0))
                .loc[:, ["time", "open", "high", "low", "close", "volume", "spread"]]
                .set_index("time")
                .sort_index()
            )

        interval = self._resolve_yfinance_interval(self.settings.timeframe)
        ticker = self._resolve_yfinance_symbol(self.settings.symbol)
        period = self._resolve_yfinance_period(self.settings.timeframe)
        frame = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
        if frame.empty:
            raise RuntimeError(f"No market data returned for {ticker}")
        frame = frame.rename(columns=str.lower)
        if "volume" not in frame.columns:
            frame["volume"] = 0.0
        frame["spread"] = 0.0
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        return frame.loc[:, ["open", "high", "low", "close", "volume", "spread"]].sort_index()

    def account_status(self) -> dict[str, Any]:
        if self.settings.mode == "paper" or mt5 is None or not self.connected:
            positions = [
                {
                    "ticket": ticket,
                    "symbol": position["symbol"],
                    "type": position["side"],
                    "volume": position["volume"],
                    "price_open": position["entry_price"],
                    "price_current": position["entry_price"],
                    "sl": position["stop_loss"],
                    "tp": position["take_profit"],
                    "profit": 0.0,
                    "time": int(position["opened_at"].timestamp()) if hasattr(position["opened_at"], "timestamp") else 0,
                }
                for ticket, position in self.paper_positions.items()
            ]
            return {
                "balance": float(self.paper_balance),
                "equity": float(self.paper_balance),
                "free_margin": float(self.paper_balance),
                "open_positions": len(self.paper_positions),
                "positions": positions,
                "mode": self.settings.mode,
            }
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("MT5 account info unavailable")
        positions = mt5.positions_get(symbol=self.settings.symbol) or []
        return {
            "balance": float(getattr(account, "balance", 0.0)),
            "equity": float(getattr(account, "equity", 0.0)),
            "free_margin": float(getattr(account, "margin_free", 0.0)),
            "open_positions": len(positions),
            "positions": [
                {
                    "ticket": int(position.ticket),
                    "symbol": str(position.symbol),
                    "type": "buy" if int(position.type) == 0 else "sell",
                    "volume": float(position.volume),
                    "price_open": float(position.price_open),
                    "price_current": float(position.price_current),
                    "sl": float(position.sl),
                    "tp": float(position.tp),
                    "profit": float(position.profit),
                    "time": int(position.time),
                    "swap": float(getattr(position, "swap", 0.0)),
                }
                for position in positions
            ],
            "mode": self.settings.mode,
        }

    def has_open_position(self, symbol: str) -> bool:
        if self.settings.mode == "paper" or mt5 is None or not self.connected:
            return any(position["symbol"] == symbol for position in self.paper_positions.values())
        positions = mt5.positions_get(symbol=symbol)
        return bool(positions)

    def execute_trade(
        self,
        signal: SignalDecision,
        parameters: StrategyParameters,
        account_equity: float,
    ) -> ExecutionResult:
        volume = self._calculate_volume(account_equity, signal, parameters)
        if volume <= 0:
            raise RuntimeError("Calculated volume is zero; trade is blocked.")

        if self.settings.mode == "paper" or mt5 is None or not self.connected:
            ticket = f"paper-{int(time.time() * 1000)}"
            result = ExecutionResult(
                broker_ticket=ticket,
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                side=signal.side,
                mode="paper",
                volume=volume,
                opened_at=signal.opened_at,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                status="open",
                market_regime=signal.market_regime,
                reason=signal.reason,
                features=signal.features,
                meta={"execution": "paper"},
            )
            self.paper_positions[ticket] = {
                "symbol": signal.symbol,
                "side": signal.side,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "volume": volume,
                "opened_at": signal.opened_at,
            }
            return result

        tick = mt5.symbol_info_tick(signal.symbol)
        if tick is None:
            raise RuntimeError("MT5 tick unavailable")
        symbol_info = mt5.symbol_info(signal.symbol)
        if symbol_info is None:
            raise RuntimeError("MT5 symbol info unavailable")

        side_type = mt5.ORDER_TYPE_BUY if signal.side == "buy" else mt5.ORDER_TYPE_SELL
        price = float(getattr(tick, "ask" if signal.side == "buy" else "bid"))
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": signal.symbol,
            "volume": volume,
            "type": side_type,
            "price": price,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "deviation": self.settings.max_slippage_points,
            "magic": self.settings.magic_number,
            "comment": self.settings.order_comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": getattr(symbol_info, "filling_mode", mt5.ORDER_FILLING_IOC),
        }
        response = mt5.order_send(request)
        if response is None:
            raise RuntimeError(f"MT5 order_send returned None: {mt5.last_error()}")
        retcode = int(getattr(response, "retcode", 0))
        if retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order failed, retcode={retcode}")

        return ExecutionResult(
            broker_ticket=str(getattr(response, "order", getattr(response, "deal", ""))),
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            side=signal.side,
            mode=self.settings.mode,
            volume=volume,
            opened_at=datetime.utcnow(),
            entry_price=price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status="open",
            market_regime=signal.market_regime,
            reason=signal.reason,
            features=signal.features,
            meta={"execution": "mt5", "retcode": retcode},
        )

    def sync_trade_closures(
        self,
        open_trades: list[dict[str, Any]],
        latest_bar: pd.Series | None = None,
    ) -> list[ClosedTradeResult]:
        if self.settings.mode == "paper" or mt5 is None or not self.connected:
            return self._sync_paper_positions(latest_bar)
        return self._sync_mt5_positions(open_trades)

    def close_all_positions(self, symbol: str | None = None, reason: str = "manual_close") -> list[ClosedTradeResult]:
        if self.settings.mode == "paper" or mt5 is None or not self.connected:
            return self._close_all_paper_positions(symbol=symbol, reason=reason)
        return self._close_all_mt5_positions(symbol=symbol, reason=reason)

    def _sync_paper_positions(self, latest_bar: pd.Series | None) -> list[ClosedTradeResult]:
        if latest_bar is None:
            return []

        closed: list[ClosedTradeResult] = []
        for ticket, position in list(self.paper_positions.items()):
            high = float(latest_bar["high"])
            low = float(latest_bar["low"])
            exit_price = None
            close_reason = None

            if position["side"] == "buy":
                if low <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    close_reason = "stop_loss"
                elif high >= position["take_profit"]:
                    exit_price = position["take_profit"]
                    close_reason = "take_profit"
            else:
                if high >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    close_reason = "stop_loss"
                elif low <= position["take_profit"]:
                    exit_price = position["take_profit"]
                    close_reason = "take_profit"

            if exit_price is None:
                continue

            direction = 1 if position["side"] == "buy" else -1
            pnl = (exit_price - position["entry_price"]) * direction * position["volume"]
            self.paper_balance += pnl
            closed.append(
                ClosedTradeResult(
                    broker_ticket=ticket,
                    closed_at=pd.Timestamp(latest_bar.name).to_pydatetime(),
                    exit_price=float(exit_price),
                    pnl=float(pnl),
                    status="closed",
                    close_reason=close_reason,
                    meta={"execution": "paper"},
                )
            )
            self.paper_positions.pop(ticket, None)

        return closed

    def _sync_mt5_positions(self, open_trades: list[dict[str, Any]]) -> list[ClosedTradeResult]:
        if not open_trades:
            return []

        closed: list[ClosedTradeResult] = []
        for trade in open_trades:
            ticket = trade["broker_ticket"]
            live_position = mt5.positions_get(ticket=int(ticket))
            if live_position:
                continue

            window_start = datetime.utcnow() - timedelta(days=7)
            deals = mt5.history_deals_get(window_start, datetime.utcnow(), position=int(ticket))
            if not deals:
                continue

            final_deal = deals[-1]
            closed.append(
                ClosedTradeResult(
                    broker_ticket=ticket,
                    closed_at=datetime.utcfromtimestamp(int(getattr(final_deal, "time", time.time()))),
                    exit_price=float(getattr(final_deal, "price", 0.0)),
                    pnl=float(getattr(final_deal, "profit", 0.0)),
                    status="closed",
                    close_reason="broker_close",
                    meta={"execution": "mt5"},
                )
            )
        return closed

    def _close_all_paper_positions(self, symbol: str | None, reason: str) -> list[ClosedTradeResult]:
        closed: list[ClosedTradeResult] = []
        for ticket, position in list(self.paper_positions.items()):
            if symbol and position["symbol"] != symbol:
                continue

            exit_price = float(position["entry_price"])
            pnl = 0.0
            closed.append(
                ClosedTradeResult(
                    broker_ticket=ticket,
                    closed_at=datetime.utcnow(),
                    exit_price=exit_price,
                    pnl=pnl,
                    status="closed",
                    close_reason=reason,
                    meta={"execution": "paper", "forced_close": True},
                )
            )
            self.paper_positions.pop(ticket, None)
        return closed

    def _close_all_mt5_positions(self, symbol: str | None, reason: str) -> list[ClosedTradeResult]:
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if not positions:
            return []

        closed: list[ClosedTradeResult] = []
        for position in positions:
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                raise RuntimeError(f"MT5 tick unavailable for {position.symbol}")

            side_type = mt5.ORDER_TYPE_SELL if int(position.type) == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = float(tick.bid if side_type == mt5.ORDER_TYPE_SELL else tick.ask)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "volume": float(position.volume),
                "type": side_type,
                "position": int(position.ticket),
                "price": price,
                "deviation": self.settings.max_slippage_points,
                "magic": self.settings.magic_number,
                "comment": f"{self.settings.order_comment} {reason}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            response = mt5.order_send(request)
            if response is None:
                raise RuntimeError(f"MT5 close order returned None: {mt5.last_error()}")

            retcode = int(getattr(response, "retcode", 0))
            if retcode != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"MT5 close failed for ticket {position.ticket}, retcode={retcode}")

            closed.append(
                ClosedTradeResult(
                    broker_ticket=str(position.ticket),
                    closed_at=datetime.utcnow(),
                    exit_price=price,
                    pnl=float(getattr(position, "profit", 0.0)),
                    status="closed",
                    close_reason=reason,
                    meta={"execution": "mt5", "retcode": retcode, "forced_close": True},
                )
            )
        return closed

    def _resolve_risk_pct(self, signal: SignalDecision, parameters: StrategyParameters) -> float:
        # Gebruik V18 risk_pct uit signaal indien beschikbaar (gezet door strategy_engine/brain_layer)
        if isinstance(signal.features, dict):
            v18_risk = signal.features.get("risk_pct")
            if v18_risk and float(v18_risk) > 0:
                return float(v18_risk)
        # Fallback op settings-based risico
        sig_type = signal.features.get("signal_type", "") if isinstance(signal.features, dict) else ""
        if isinstance(sig_type, str) and sig_type.startswith("STERK"):
            return parameters.risk_strong_regime
        if isinstance(sig_type, str) and sig_type.startswith("ZWAK"):
            return parameters.risk_weak_regime
        return parameters.risk_per_trade

    def _calculate_volume(self, equity: float, signal: SignalDecision, parameters: StrategyParameters) -> float:
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        risk_pct = self._resolve_risk_pct(signal, parameters)
        max_lot = float(os.getenv("MAX_LOT_SIZE", "6.0"))

        if mt5 is not None and self.connected:
            symbol_info = mt5.symbol_info(signal.symbol)
            if symbol_info is not None:
                raw = float(calculate_position_size(equity, risk_pct, stop_distance, symbol_info))
                return round(min(max(raw, 0.01), max_lot), 2)
        risk_amount = max(equity * risk_pct, 0.0)
        if stop_distance <= 0:
            return 0.0
        raw = risk_amount / stop_distance
        return round(min(max(raw, 0.01), max_lot), 2)

    def _resolve_mt5_timeframe(self, timeframe_name: str) -> int:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package not installed")
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
        }
        if timeframe_name not in mapping:
            raise ValueError(f"Unsupported timeframe: {timeframe_name}")
        return mapping[timeframe_name]

    def _resolve_yfinance_interval(self, timeframe_name: str) -> str:
        mapping = {
            "M1": "1m",
            "M5": "5m",
            "M15": "15m",
            "M30": "30m",
            "H1": "60m",
            "H4": "60m",
        }
        return mapping.get(timeframe_name, "60m")

    def _resolve_yfinance_period(self, timeframe_name: str) -> str:
        # H1/H4: fetch 90 days so H4 and D1 indicators are well-warmed
        if timeframe_name in ("H1", "H4"):
            return "90d"
        if timeframe_name in ("M15", "M30"):
            return "30d"
        return "7d"

    def _resolve_yfinance_symbol(self, symbol: str) -> str:
        # XAUUSD / forex paren → yfinance tickers (paper mode / fallback)
        aliases = {
            "XAUUSD": "GC=F",       # Gold futures — primair
            "XAGUSD": "SI=F",        # Silver futures
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",
            "USDCHF": "CHF=X",
            "AUDUSD": "AUDUSD=X",
            "NZDUSD": "NZDUSD=X",
            "USDCAD": "CAD=X",
            "EURGBP": "EURGBP=X",
            "GBPJPY": "GBPJPY=X",
            "EURJPY": "EURJPY=X",
        }
        return aliases.get(symbol.upper(), symbol)

