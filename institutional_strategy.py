from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATA_ROOT = Path("exports/latest/data")
RESULTS_ROOT = Path("results")
RESULTS_ROOT.mkdir(exist_ok=True)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    down = (-delta).clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    rs = up / down.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - frame["close"].shift(1)).abs(),
            (frame["low"] - frame["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(com=period - 1, adjust=False).mean()


def percentile_rank(series: pd.Series, window: int) -> pd.Series:
    def _rank(values: np.ndarray) -> float:
        if len(values) <= 1:
            return 0.0
        arr = pd.Series(values)
        return float(arr.rank(pct=True).iloc[-1] * 100.0)

    return series.rolling(window, min_periods=max(5, window // 4)).apply(_rank, raw=True)


def build_ohlcv(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    aggregated = (
        frame.resample(timeframe)
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "spread": "mean",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
    )
    aggregated["atr"] = atr(aggregated, 14)
    aggregated["rsi"] = rsi(aggregated["close"], 14)
    aggregated["ema20"] = ema(aggregated["close"], 20)
    aggregated["ema50"] = ema(aggregated["close"], 50)
    aggregated["ema200"] = ema(aggregated["close"], 200)
    aggregated["volume_ma20"] = aggregated["volume"].rolling(20).mean()
    aggregated["range"] = aggregated["high"] - aggregated["low"]
    aggregated["body"] = (aggregated["close"] - aggregated["open"]).abs()
    aggregated["body_ratio"] = aggregated["body"] / aggregated["range"].replace(0, np.nan)
    aggregated["atr_pct"] = percentile_rank(aggregated["atr"], 120)
    aggregated["spread_pct"] = percentile_rank(aggregated["spread"], 120)
    aggregated["vol_ratio"] = aggregated["volume"] / aggregated["volume_ma20"].replace(0, np.nan)
    aggregated["swing_high"] = aggregated["high"].shift(1).rolling(4).max()
    aggregated["swing_low"] = aggregated["low"].shift(1).rolling(4).min()
    aggregated["trend_slope"] = aggregated["ema20"] - aggregated["ema20"].shift(4)
    aggregated["bull_trend"] = (
        (aggregated["ema20"] > aggregated["ema50"])
        & (aggregated["ema50"] > aggregated["ema200"])
        & (aggregated["trend_slope"] > 0)
    )
    aggregated["bear_trend"] = (
        (aggregated["ema20"] < aggregated["ema50"])
        & (aggregated["ema50"] < aggregated["ema200"])
        & (aggregated["trend_slope"] < 0)
    )
    aggregated["liq_sweep_low"] = (
        (aggregated["low"] < aggregated["swing_low"])
        & (aggregated["close"] > aggregated["swing_low"])
    )
    aggregated["liq_sweep_high"] = (
        (aggregated["high"] > aggregated["swing_high"])
        & (aggregated["close"] < aggregated["swing_high"])
    )
    aggregated["bos_up"] = aggregated["close"] > aggregated["swing_high"]
    aggregated["bos_down"] = aggregated["close"] < aggregated["swing_low"]
    aggregated["disp_up"] = (
        (aggregated["close"] > aggregated["open"])
        & (aggregated["body"] > aggregated["atr"] * 0.30)
        & (aggregated["body_ratio"] > 0.32)
    )
    aggregated["disp_down"] = (
        (aggregated["close"] < aggregated["open"])
        & (aggregated["body"] > aggregated["atr"] * 0.30)
        & (aggregated["body_ratio"] > 0.32)
    )
    aggregated["bull_fvg_low"] = np.where(
        aggregated["low"] > aggregated["high"].shift(2),
        aggregated["high"].shift(2),
        np.nan,
    )
    aggregated["bull_fvg_high"] = np.where(
        aggregated["low"] > aggregated["high"].shift(2),
        aggregated["low"],
        np.nan,
    )
    aggregated["bear_fvg_high"] = np.where(
        aggregated["high"] < aggregated["low"].shift(2),
        aggregated["low"].shift(2),
        np.nan,
    )
    aggregated["bear_fvg_low"] = np.where(
        aggregated["high"] < aggregated["low"].shift(2),
        aggregated["high"],
        np.nan,
    )
    aggregated["bull_ob_low"] = np.where(
        (aggregated["open"].shift(1) > aggregated["close"].shift(1)) & aggregated["disp_up"],
        aggregated["low"].shift(1),
        np.nan,
    )
    aggregated["bull_ob_high"] = np.where(
        (aggregated["open"].shift(1) > aggregated["close"].shift(1)) & aggregated["disp_up"],
        aggregated["high"].shift(1),
        np.nan,
    )
    aggregated["bear_ob_low"] = np.where(
        (aggregated["open"].shift(1) < aggregated["close"].shift(1)) & aggregated["disp_down"],
        aggregated["low"].shift(1),
        np.nan,
    )
    aggregated["bear_ob_high"] = np.where(
        (aggregated["open"].shift(1) < aggregated["close"].shift(1)) & aggregated["disp_down"],
        aggregated["high"].shift(1),
        np.nan,
    )
    return aggregated


def map_session(hour: int) -> str:
    if 3 <= hour < 4:
        return "asia"
    if 4 <= hour < 6:
        return "london"
    if 6 <= hour < 8:
        return "overlap"
    if 8 <= hour < 10:
        return "new_york"
    return "off"


@dataclass
class StrategyConfig:
    name: str
    risk_base: float = 0.0025
    risk_high_quality: float = 0.0040
    risk_reduced: float = 0.0015
    max_daily_loss: float = 2000.0
    max_weekly_loss: float = 4000.0
    daily_profit_lock: float = 1200.0
    weekly_profit_lock: float = 4200.0
    monthly_profit_lock: float = 16000.0
    max_trades_per_day: int = 5
    max_consecutive_losses: int = 2
    min_quality_score: float = 6.5
    min_h1_atr_pct: float = 40.0
    max_spread: float = 1.75
    min_volume_ratio: float = 1.05
    stop_atr_multiple: float = 1.30
    min_stop_distance: float = 2.8
    rr_tp1: float = 1.0
    rr_tp2: float = 2.0
    rr_tp3: float = 3.1
    retrace_depth: float = 0.35
    entry_confirmation_body: float = 0.10
    news_spread_pct: float = 97.0
    news_atr_pct: float = 96.0
    session_allow_overlap: bool = True


@dataclass
class TradeRecord:
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_loss: float
    initial_stop: float
    quantity: float
    realized_pnl: float
    r_multiple: float
    holding_minutes: int
    exit_reason: str
    quality_score: float
    risk_pct: float
    session: str
    spread: float
    news_proxy: bool
    max_favourable_excursion: float
    max_adverse_excursion: float
    partials_taken: int


class ExportMarketLoader:
    def __init__(self, root: Path = DATA_ROOT) -> None:
        self.root = root

    def load(self) -> pd.DataFrame:
        market = pd.read_csv(self.root / "market.csv")
        equity = pd.read_csv(self.root / "equity.csv", parse_dates=["timestamp"])

        if "timestamp" not in market.columns:
            extra_rows = len(market) - len(equity)
            if extra_rows < 0 or extra_rows > 10:
                raise ValueError("Could not align export market bars to equity timestamps.")
            market = market.iloc[extra_rows:].reset_index(drop=True)
            market["timestamp"] = equity["timestamp"].values

        frame = market.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.set_index("timestamp").sort_index()
        numeric_columns = ["open", "high", "low", "close", "volume", "spread"]
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        frame["session"] = [map_session(ts.hour) for ts in frame.index]
        frame["bar_range"] = frame["high"] - frame["low"]
        frame["bar_range_pct"] = percentile_rank(frame["bar_range"], 240)
        frame["spread_pct"] = percentile_rank(frame["spread"], 240)
        frame["vol_ratio"] = frame["volume"] / frame["volume"].rolling(20).mean().replace(0, np.nan)
        frame["news_proxy"] = (
            (frame["spread_pct"] >= 97.0)
            & (frame["bar_range_pct"] >= 96.0)
            & (frame["vol_ratio"].fillna(0) >= 1.8)
        )
        return frame


class InstitutionalResearchEngine:
    def __init__(self, market: pd.DataFrame, starting_capital: float = 160_000.0) -> None:
        self.market = market.copy()
        self.starting_capital = float(starting_capital)
        self.prepared = self._prepare_market(self.market)

    def _prepare_market(self, market: pd.DataFrame) -> pd.DataFrame:
        base = market.copy()
        base["atr_m1"] = atr(base, 14)
        base["rsi_m1"] = rsi(base["close"], 14)
        base["body"] = (base["close"] - base["open"]).abs()
        base["body_ratio"] = base["body"] / base["bar_range"].replace(0, np.nan)
        m5 = build_ohlcv(base, "5min").add_prefix("m5_")
        m15 = build_ohlcv(base, "15min").add_prefix("m15_")
        h1 = build_ohlcv(base, "1h").add_prefix("h1_")
        h4 = build_ohlcv(base, "4h").add_prefix("h4_")

        prepared = pd.merge_asof(
            base.sort_index(),
            m5.sort_index(),
            left_index=True,
            right_index=True,
            direction="backward",
        )
        prepared = pd.merge_asof(
            prepared.sort_index(),
            m15.sort_index(),
            left_index=True,
            right_index=True,
            direction="backward",
        )
        prepared = pd.merge_asof(
            prepared.sort_index(),
            h1.sort_index(),
            left_index=True,
            right_index=True,
            direction="backward",
        )
        prepared = pd.merge_asof(
            prepared.sort_index(),
            h4.sort_index(),
            left_index=True,
            right_index=True,
            direction="backward",
        )

        prepared["m15_recent_sweep_low"] = prepared["m15_liq_sweep_low"].rolling(8).max().fillna(0).astype(bool)
        prepared["m15_recent_sweep_high"] = prepared["m15_liq_sweep_high"].rolling(8).max().fillna(0).astype(bool)
        prepared["m5_recent_bos_up"] = prepared["m5_bos_up"].rolling(6).max().fillna(0).astype(bool)
        prepared["m5_recent_bos_down"] = prepared["m5_bos_down"].rolling(6).max().fillna(0).astype(bool)
        prepared["m5_recent_disp_up"] = prepared["m5_disp_up"].rolling(8).max().fillna(0).astype(bool)
        prepared["m5_recent_disp_down"] = prepared["m5_disp_down"].rolling(8).max().fillna(0).astype(bool)
        prepared["bull_zone_low"] = (
            prepared["m5_bull_fvg_low"].ffill().combine_first(prepared["m5_bull_ob_low"].ffill())
        )
        prepared["bull_zone_high"] = (
            prepared["m5_bull_fvg_high"].ffill().combine_first(prepared["m5_bull_ob_high"].ffill())
        )
        prepared["bear_zone_low"] = (
            prepared["m5_bear_fvg_low"].ffill().combine_first(prepared["m5_bear_ob_low"].ffill())
        )
        prepared["bear_zone_high"] = (
            prepared["m5_bear_fvg_high"].ffill().combine_first(prepared["m5_bear_ob_high"].ffill())
        )

        prepared["bull_zone_fresh"] = (
            prepared["m5_bull_fvg_low"].notna().rolling(30).max().fillna(0).astype(bool)
            | prepared["m5_bull_ob_low"].notna().rolling(30).max().fillna(0).astype(bool)
        )
        prepared["bear_zone_fresh"] = (
            prepared["m5_bear_fvg_low"].notna().rolling(30).max().fillna(0).astype(bool)
            | prepared["m5_bear_ob_low"].notna().rolling(30).max().fillna(0).astype(bool)
        )
        prepared["quality_long"] = self._build_quality_scores(prepared, "long")
        prepared["quality_short"] = self._build_quality_scores(prepared, "short")
        return prepared.dropna(
            subset=[
                "atr_m1",
                "m5_atr",
                "m15_atr",
                "h1_atr",
                "h4_atr",
                "h1_ema20",
                "h4_ema20",
            ]
        )

    def _build_quality_scores(self, prepared: pd.DataFrame, direction: str) -> pd.Series:
        bullish = direction == "long"
        quality = pd.Series(0.0, index=prepared.index)
        quality += np.where(prepared["h4_bull_trend"] if bullish else prepared["h4_bear_trend"], 2.0, -2.0)
        quality += np.where(prepared["h1_bull_trend"] if bullish else prepared["h1_bear_trend"], 1.5, -1.5)
        quality += np.where(prepared["m15_recent_sweep_low"] if bullish else prepared["m15_recent_sweep_high"], 1.5, 0.0)
        quality += np.where(prepared["m5_recent_bos_up"] if bullish else prepared["m5_recent_bos_down"], 1.0, 0.0)
        quality += np.where(prepared["m5_recent_disp_up"] if bullish else prepared["m5_recent_disp_down"], 1.0, 0.0)
        quality += np.where(prepared["bull_zone_fresh"] if bullish else prepared["bear_zone_fresh"], 0.75, 0.0)
        if bullish:
            quality += np.where((prepared["m5_rsi"] >= 52) & (prepared["m5_rsi"] <= 66), 0.75, -0.5)
        else:
            quality += np.where((prepared["m5_rsi"] >= 34) & (prepared["m5_rsi"] <= 48), 0.75, -0.5)
        quality += np.where(prepared["h1_atr_pct"] >= 45.0, 0.5, -0.5)
        quality += np.where(prepared["vol_ratio"].fillna(0) >= 1.05, 0.5, 0.0)
        quality += np.where(prepared["spread"] <= 0.95, 0.25, -0.75)
        return quality

    def _entry_signal(self, row: pd.Series, cfg: StrategyConfig) -> tuple[str | None, float]:
        allowed_session = row["session"] in {"london", "new_york"} or (
            cfg.session_allow_overlap and row["session"] == "overlap"
        )
        if not allowed_session:
            return None, 0.0
        if bool(row["news_proxy"]) or float(row["spread"]) > cfg.max_spread:
            return None, 0.0
        if float(row["h1_atr_pct"]) < cfg.min_h1_atr_pct:
            return None, 0.0
        if float(row["vol_ratio"]) < cfg.min_volume_ratio:
            return None, 0.0

        if self._valid_long_setup(row, cfg):
            return "long", float(row["quality_long"])
        if self._valid_short_setup(row, cfg):
            return "short", float(row["quality_short"])
        return None, 0.0

    def _valid_long_setup(self, row: pd.Series, cfg: StrategyConfig) -> bool:
        zone_low = float(row["bull_zone_low"]) if pd.notna(row["bull_zone_low"]) else math.nan
        zone_high = float(row["bull_zone_high"]) if pd.notna(row["bull_zone_high"]) else math.nan
        if math.isnan(zone_low) or math.isnan(zone_high):
            return False
        zone_size = max(zone_high - zone_low, 1e-6)
        retrace_level = zone_low + zone_size * cfg.retrace_depth
        reversal_ok = bool(row["m15_recent_sweep_low"])
        continuation_ok = bool(row["h4_bull_trend"] and row["h1_bull_trend"] and row["bull_zone_fresh"])
        return bool(
            row["quality_long"] >= cfg.min_quality_score
            and row["h4_bull_trend"]
            and row["h1_bull_trend"]
            and (reversal_ok or continuation_ok)
            and row["m5_recent_bos_up"]
            and row["m5_recent_disp_up"]
            and row["low"] <= zone_high + float(row["m5_atr"]) * 0.25
            and row["close"] >= max(retrace_level, zone_low - float(row["m5_atr"]) * 0.15)
            and row["close"] > row["open"]
            and row["body_ratio"] >= cfg.entry_confirmation_body
            and row["rsi_m1"] >= 48
        )

    def _valid_short_setup(self, row: pd.Series, cfg: StrategyConfig) -> bool:
        zone_low = float(row["bear_zone_low"]) if pd.notna(row["bear_zone_low"]) else math.nan
        zone_high = float(row["bear_zone_high"]) if pd.notna(row["bear_zone_high"]) else math.nan
        if math.isnan(zone_low) or math.isnan(zone_high):
            return False
        zone_size = max(zone_high - zone_low, 1e-6)
        retrace_level = zone_high - zone_size * cfg.retrace_depth
        reversal_ok = bool(row["m15_recent_sweep_high"])
        continuation_ok = bool(row["h1_bear_trend"] and row["bear_zone_fresh"])
        return bool(
            row["quality_short"] >= max(3.5, cfg.min_quality_score - 2.0)
            and row["h1_bear_trend"]
            and (row["h4_bear_trend"] or reversal_ok or continuation_ok)
            and row["m5_recent_bos_down"]
            and row["m5_recent_disp_down"]
            and row["high"] >= zone_low - float(row["m5_atr"]) * 0.25
            and row["close"] <= min(retrace_level, zone_high + float(row["m5_atr"]) * 0.15)
            and row["close"] < row["open"]
            and row["body_ratio"] >= cfg.entry_confirmation_body
            and row["rsi_m1"] <= 54
        )

    def _risk_pct(self, quality_score: float, consecutive_losses: int, cfg: StrategyConfig) -> float:
        if consecutive_losses >= cfg.max_consecutive_losses:
            return 0.0
        if quality_score >= cfg.min_quality_score + 1.5:
            return cfg.risk_high_quality
        if quality_score >= cfg.min_quality_score:
            return cfg.risk_base
        return cfg.risk_reduced

    def run_backtest(self, cfg: StrategyConfig) -> dict[str, Any]:
        frame = self.prepared.copy()
        capital = self.starting_capital
        equity_curve: list[dict[str, Any]] = []
        trades: list[TradeRecord] = []
        position: dict[str, Any] | None = None
        daily_trade_counter: dict[str, int] = {}
        daily_realized: dict[str, float] = {}
        weekly_realized: dict[str, float] = {}
        monthly_realized: dict[str, float] = {}
        consecutive_losses = 0
        blocked_reasons: dict[str, int] = {}

        for timestamp, row in frame.iterrows():
            day_key = timestamp.date().isoformat()
            week_key = f"{timestamp.isocalendar().year}-W{timestamp.isocalendar().week:02d}"
            month_key = timestamp.strftime("%Y-%m")
            daily_realized.setdefault(day_key, 0.0)
            weekly_realized.setdefault(week_key, 0.0)
            monthly_realized.setdefault(month_key, 0.0)
            daily_trade_counter.setdefault(day_key, 0)

            if position is not None:
                capital, position, maybe_trade = self._manage_position(timestamp, row, capital, position)
                if maybe_trade is not None:
                    trades.append(maybe_trade)
                    daily_realized[day_key] += maybe_trade.realized_pnl
                    weekly_realized[week_key] += maybe_trade.realized_pnl
                    monthly_realized[month_key] += maybe_trade.realized_pnl
                    consecutive_losses = consecutive_losses + 1 if maybe_trade.realized_pnl <= 0 else 0

            open_pnl = self._mark_to_market(position, row["close"]) if position else 0.0
            equity_curve.append(
                {
                    "timestamp": timestamp,
                    "capital": capital,
                    "equity": capital + open_pnl,
                    "daily_pnl": daily_realized[day_key],
                    "weekly_pnl": weekly_realized[week_key],
                    "monthly_pnl": monthly_realized[month_key],
                    "session": row["session"],
                }
            )

            if position is not None:
                continue

            if daily_trade_counter[day_key] >= cfg.max_trades_per_day:
                blocked_reasons["max_trades_day"] = blocked_reasons.get("max_trades_day", 0) + 1
                continue
            if daily_realized[day_key] <= -cfg.max_daily_loss:
                blocked_reasons["daily_loss_limit"] = blocked_reasons.get("daily_loss_limit", 0) + 1
                continue
            if weekly_realized[week_key] <= -cfg.max_weekly_loss:
                blocked_reasons["weekly_loss_limit"] = blocked_reasons.get("weekly_loss_limit", 0) + 1
                continue
            if daily_realized[day_key] >= cfg.daily_profit_lock:
                blocked_reasons["daily_profit_lock"] = blocked_reasons.get("daily_profit_lock", 0) + 1
                continue
            if weekly_realized[week_key] >= cfg.weekly_profit_lock:
                blocked_reasons["weekly_profit_lock"] = blocked_reasons.get("weekly_profit_lock", 0) + 1
                continue
            if monthly_realized[month_key] >= cfg.monthly_profit_lock:
                blocked_reasons["monthly_profit_lock"] = blocked_reasons.get("monthly_profit_lock", 0) + 1
                continue
            if consecutive_losses >= cfg.max_consecutive_losses:
                blocked_reasons["consecutive_losses"] = blocked_reasons.get("consecutive_losses", 0) + 1
                continue

            signal, quality_score = self._entry_signal(row, cfg)
            if signal is None:
                continue

            risk_pct = self._risk_pct(quality_score, consecutive_losses, cfg)
            if risk_pct <= 0:
                blocked_reasons["risk_off"] = blocked_reasons.get("risk_off", 0) + 1
                continue

            stop_distance = max(float(row["m5_atr"]) * cfg.stop_atr_multiple, cfg.min_stop_distance)
            risk_amount = capital * risk_pct
            quantity = risk_amount / stop_distance
            if quantity <= 0:
                continue

            entry_price = float(row["close"])
            stop_loss = entry_price - stop_distance if signal == "long" else entry_price + stop_distance
            tp1 = entry_price + stop_distance * cfg.rr_tp1 if signal == "long" else entry_price - stop_distance * cfg.rr_tp1
            tp2 = entry_price + stop_distance * cfg.rr_tp2 if signal == "long" else entry_price - stop_distance * cfg.rr_tp2
            tp3 = entry_price + stop_distance * cfg.rr_tp3 if signal == "long" else entry_price - stop_distance * cfg.rr_tp3

            position = {
                "side": signal,
                "entry_time": timestamp,
                "entry_price": entry_price,
                "initial_stop": stop_loss,
                "stop_loss": stop_loss,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "remaining_qty": quantity,
                "initial_qty": quantity,
                "realized_pnl": 0.0,
                "risk_amount": risk_amount,
                "risk_pct": risk_pct,
                "quality_score": quality_score,
                "session": row["session"],
                "spread": float(row["spread"]),
                "news_proxy": bool(row["news_proxy"]),
                "partials_taken": 0,
                "max_favourable_excursion": 0.0,
                "max_adverse_excursion": 0.0,
                "best_open_pnl": 0.0,
                "worst_open_pnl": 0.0,
            }
            daily_trade_counter[day_key] += 1

        if position is not None:
            last_time = frame.index[-1]
            last_close = float(frame["close"].iloc[-1])
            capital, _, maybe_trade = self._force_close(last_time, last_close, capital, position, "EndOfData")
            if maybe_trade is not None:
                trades.append(maybe_trade)

        trades_df = pd.DataFrame([asdict(trade) for trade in trades])
        equity_df = pd.DataFrame(equity_curve)
        analytics = self._compute_analytics(trades_df, equity_df, blocked_reasons)
        analytics["config"] = asdict(cfg)
        return analytics

    def _mark_to_market(self, position: dict[str, Any] | None, close_price: float) -> float:
        if position is None:
            return 0.0
        direction = 1.0 if position["side"] == "long" else -1.0
        return (float(close_price) - position["entry_price"]) * direction * position["remaining_qty"] + position["realized_pnl"]

    def _trail_stop(self, position: dict[str, Any], open_pnl: float) -> None:
        if open_pnl < 300:
            return
        locked_profit = 100.0
        if open_pnl >= 500:
            locked_profit = 300.0 + max(0.0, math.floor((open_pnl - 500.0) / 300.0) * 200.0)
        price_lock = locked_profit / position["remaining_qty"] if position["remaining_qty"] > 0 else 0.0
        if position["side"] == "long":
            position["stop_loss"] = max(position["stop_loss"], position["entry_price"] + price_lock)
        else:
            position["stop_loss"] = min(position["stop_loss"], position["entry_price"] - price_lock)

    def _manage_position(
        self,
        timestamp: pd.Timestamp,
        row: pd.Series,
        capital: float,
        position: dict[str, Any],
    ) -> tuple[float, dict[str, Any] | None, TradeRecord | None]:
        side_mult = 1.0 if position["side"] == "long" else -1.0
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        favourable = ((high - position["entry_price"]) if position["side"] == "long" else (position["entry_price"] - low))
        adverse = ((position["entry_price"] - low) if position["side"] == "long" else (high - position["entry_price"]))
        position["max_favourable_excursion"] = max(position["max_favourable_excursion"], favourable)
        position["max_adverse_excursion"] = max(position["max_adverse_excursion"], adverse)

        open_pnl_best = favourable * position["remaining_qty"]
        position["best_open_pnl"] = max(position["best_open_pnl"], open_pnl_best)
        self._trail_stop(position, position["best_open_pnl"])

        stop_hit = low <= position["stop_loss"] if position["side"] == "long" else high >= position["stop_loss"]
        tp1_hit = high >= position["tp1"] if position["side"] == "long" else low <= position["tp1"]
        tp2_hit = high >= position["tp2"] if position["side"] == "long" else low <= position["tp2"]
        tp3_hit = high >= position["tp3"] if position["side"] == "long" else low <= position["tp3"]

        # Conservative intrabar sequencing: stop first, then partials.
        if stop_hit:
            exit_price = position["stop_loss"]
            capital, _, trade = self._force_close(timestamp, exit_price, capital, position, "StopLoss")
            return capital, None, trade

        if position["partials_taken"] == 0 and tp1_hit:
            qty = position["initial_qty"] * 0.30
            pnl = (position["tp1"] - position["entry_price"]) * side_mult * qty
            capital += pnl
            position["realized_pnl"] += pnl
            position["remaining_qty"] -= qty
            position["partials_taken"] = 1
            if position["side"] == "long":
                position["stop_loss"] = max(position["stop_loss"], position["entry_price"])
            else:
                position["stop_loss"] = min(position["stop_loss"], position["entry_price"])

        if position["partials_taken"] == 1 and tp2_hit:
            qty = position["initial_qty"] * 0.30
            pnl = (position["tp2"] - position["entry_price"]) * side_mult * qty
            capital += pnl
            position["realized_pnl"] += pnl
            position["remaining_qty"] -= qty
            position["partials_taken"] = 2

        if tp3_hit:
            capital, _, trade = self._force_close(timestamp, position["tp3"], capital, position, "TP3")
            return capital, None, trade

        if row["session"] == "off":
            capital, _, trade = self._force_close(timestamp, close, capital, position, "SessionClose")
            return capital, None, trade

        return capital, position, None

    def _force_close(
        self,
        timestamp: pd.Timestamp,
        exit_price: float,
        capital: float,
        position: dict[str, Any],
        reason: str,
    ) -> tuple[float, None, TradeRecord]:
        side_mult = 1.0 if position["side"] == "long" else -1.0
        pnl = (float(exit_price) - position["entry_price"]) * side_mult * position["remaining_qty"]
        total_pnl = position["realized_pnl"] + pnl
        capital += pnl
        trade = TradeRecord(
            side=position["side"],
            entry_time=position["entry_time"],
            exit_time=timestamp,
            entry_price=position["entry_price"],
            exit_price=float(exit_price),
            stop_loss=float(position["stop_loss"]),
            initial_stop=float(position["initial_stop"]),
            quantity=float(position["initial_qty"]),
            realized_pnl=float(total_pnl),
            r_multiple=float(total_pnl / position["risk_amount"]) if position["risk_amount"] > 0 else 0.0,
            holding_minutes=int((timestamp - position["entry_time"]).total_seconds() // 60),
            exit_reason=reason,
            quality_score=float(position["quality_score"]),
            risk_pct=float(position["risk_pct"]),
            session=str(position["session"]),
            spread=float(position["spread"]),
            news_proxy=bool(position["news_proxy"]),
            max_favourable_excursion=float(position["max_favourable_excursion"]),
            max_adverse_excursion=float(position["max_adverse_excursion"]),
            partials_taken=int(position["partials_taken"]),
        )
        return capital, None, trade

    def _compute_analytics(
        self,
        trades_df: pd.DataFrame,
        equity_df: pd.DataFrame,
        blocked_reasons: dict[str, int],
    ) -> dict[str, Any]:
        if equity_df.empty:
            raise ValueError("No equity points generated.")

        if trades_df.empty:
            return {
                "trades": [],
                "equity_curve": equity_df.to_dict(orient="records"),
                "summary": {
                    "starting_capital": self.starting_capital,
                    "ending_capital": float(equity_df["equity"].iloc[-1]),
                    "total_return_pct": 0.0,
                    "avg_monthly_return_pct": 0.0,
                    "profit_factor": 0.0,
                    "win_rate": 0.0,
                    "max_drawdown_pct": 0.0,
                    "avg_rr": 0.0,
                    "max_daily_loss": 0.0,
                    "max_weekly_loss": 0.0,
                    "trade_frequency_per_day": 0.0,
                    "worst_consecutive_losses": 0,
                    "equity_curve_stability": 0.0,
                    "overtrading_flag": False,
                    "news_impact_pnl": 0.0,
                    "news_trade_count": 0,
                    "days_traded": 0,
                    "total_trades": 0,
                },
                "blocked_reasons": blocked_reasons,
            }

        trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
        trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])
        trades_df["month"] = trades_df["entry_time"].dt.to_period("M").astype(str)
        trades_df["week"] = trades_df["entry_time"].dt.strftime("%G-W%V")
        trades_df["day"] = trades_df["entry_time"].dt.date.astype(str)
        pnl = trades_df["realized_pnl"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]

        equity = equity_df["equity"].astype(float)
        running_peak = equity.cummax()
        drawdown = np.where(running_peak > 0, (running_peak - equity) / running_peak * 100.0, 0.0)
        max_drawdown_pct = float(np.max(drawdown)) if len(drawdown) else 0.0

        total_return_pct = ((equity.iloc[-1] / self.starting_capital) - 1.0) * 100.0
        monthly_returns = (
            trades_df.groupby("month")["realized_pnl"].sum().div(self.starting_capital).mul(100.0).reset_index(name="return_pct")
        )
        monthly_stats = (
            trades_df.groupby("month")
            .agg(
                trades=("realized_pnl", "size"),
                pnl=("realized_pnl", "sum"),
                win_rate=("realized_pnl", lambda s: float((s > 0).mean()) * 100.0),
                profit_factor=("realized_pnl", lambda s: float(s[s > 0].sum() / abs(s[s < 0].sum())) if (s < 0).any() else 99.0),
                avg_rr=("r_multiple", "mean"),
            )
            .reset_index()
        )
        daily_stats = trades_df.groupby("day")["realized_pnl"].sum()
        weekly_stats = trades_df.groupby("week")["realized_pnl"].sum()
        session_stats = (
            trades_df.groupby("session")
            .agg(
                trades=("realized_pnl", "size"),
                pnl=("realized_pnl", "sum"),
                win_rate=("realized_pnl", lambda s: float((s > 0).mean()) * 100.0),
                avg_rr=("r_multiple", "mean"),
            )
            .reset_index()
        )
        spread_buckets = pd.cut(trades_df["spread"], bins=[-np.inf, 0.35, 0.60, 0.90, np.inf], labels=["tight", "normal", "wide", "extreme"])
        spread_stats = (
            trades_df.assign(spread_bucket=spread_buckets)
            .groupby("spread_bucket", observed=False)
            .agg(trades=("realized_pnl", "size"), pnl=("realized_pnl", "sum"), win_rate=("realized_pnl", lambda s: float((s > 0).mean()) * 100.0))
            .reset_index()
        )

        pnl_sign = np.where(pnl <= 0, 1, 0)
        streak = 0
        worst_streak = 0
        for loss_flag in pnl_sign:
            if loss_flag:
                streak += 1
                worst_streak = max(worst_streak, streak)
            else:
                streak = 0

        returns = equity.pct_change().dropna()
        stability = 0.0
        if not returns.empty and float(returns.std(ddof=0)) > 0:
            stability = float(returns.mean() / returns.std(ddof=0) * np.sqrt(len(returns)))

        summary = {
            "starting_capital": self.starting_capital,
            "ending_capital": float(equity.iloc[-1]),
            "total_return_pct": round(float(total_return_pct), 4),
            "avg_monthly_return_pct": round(float(monthly_returns["return_pct"].mean()) if not monthly_returns.empty else 0.0, 4),
            "profit_factor": round(float(wins.sum() / abs(losses.sum())) if not losses.empty else 99.0, 4),
            "win_rate": round(float((pnl > 0).mean()) * 100.0, 4),
            "max_drawdown_pct": round(float(max_drawdown_pct), 4),
            "avg_rr": round(float(trades_df["r_multiple"].mean()), 4),
            "max_daily_loss": round(float(abs(daily_stats.min())) if not daily_stats.empty else 0.0, 2),
            "max_weekly_loss": round(float(abs(weekly_stats.min())) if not weekly_stats.empty else 0.0, 2),
            "trade_frequency_per_day": round(float(trades_df.groupby("day").size().mean()), 4),
            "worst_consecutive_losses": int(worst_streak),
            "equity_curve_stability": round(stability, 4),
            "overtrading_flag": bool(trades_df.groupby("day").size().max() > 5 if not trades_df.empty else False),
            "news_impact_pnl": round(float(trades_df.loc[trades_df["news_proxy"], "realized_pnl"].sum()), 2),
            "news_trade_count": int(trades_df["news_proxy"].sum()),
            "days_traded": int(trades_df["day"].nunique()),
            "total_trades": int(len(trades_df)),
        }

        return {
            "summary": summary,
            "monthly_stats": monthly_stats.to_dict(orient="records"),
            "session_stats": session_stats.to_dict(orient="records"),
            "spread_stats": spread_stats.to_dict(orient="records"),
            "blocked_reasons": blocked_reasons,
            "trades": trades_df.sort_values("entry_time").to_dict(orient="records"),
            "equity_curve": equity_df.to_dict(orient="records"),
        }

    def optimize(self, configs: list[StrategyConfig]) -> dict[str, Any]:
        runs = []
        best_payload: dict[str, Any] | None = None
        best_score = -10**9
        for cfg in configs:
            payload = self.run_backtest(cfg)
            score = self._score_run(payload["summary"])
            runs.append(
                {
                    "name": cfg.name,
                    "score": score,
                    **payload["summary"],
                }
            )
            if score > best_score:
                best_score = score
                best_payload = payload
        if best_payload is None:
            raise ValueError("No optimization runs completed.")
        return {
            "leaderboard": sorted(runs, key=lambda item: item["score"], reverse=True),
            "best_run": best_payload,
        }

    def _score_run(self, summary: dict[str, Any]) -> float:
        effective_pf = min(summary["profit_factor"], 3.0)
        effective_win_rate = min(summary["win_rate"], 75.0)
        score = 0.0
        score += summary["avg_monthly_return_pct"] * 18.0
        score += effective_pf * 25.0
        score += (effective_win_rate / 100.0) * 15.0
        score += summary["avg_rr"] * 10.0
        score += summary["equity_curve_stability"] * 4.0
        score -= max(summary["max_drawdown_pct"] - 6.0, 0.0) * 30.0
        score -= max(summary["max_daily_loss"] - 2000.0, 0.0) * 0.03
        score -= max(summary["max_weekly_loss"] - 4000.0, 0.0) * 0.02
        score -= 15.0 if summary["overtrading_flag"] else 0.0
        score -= 12.0 if summary["worst_consecutive_losses"] > 2 else 0.0
        score -= max(8 - summary["total_trades"], 0) * 18.0
        score -= 60.0 if summary["win_rate"] >= 90.0 and summary["profit_factor"] >= 10.0 else 0.0
        score -= 40.0 if summary["total_trades"] < 4 else 0.0
        return round(score, 4)


def candidate_configs() -> list[StrategyConfig]:
    return [
        StrategyConfig(name="v1_balanced"),
        StrategyConfig(
            name="v2_selective",
            min_quality_score=7.1,
            min_h1_atr_pct=48.0,
            min_volume_ratio=1.10,
            max_spread=1.55,
            stop_atr_multiple=1.25,
            rr_tp3=3.3,
            entry_confirmation_body=0.14,
        ),
        StrategyConfig(
            name="v3_aggressive",
            min_quality_score=6.1,
            min_h1_atr_pct=35.0,
            min_volume_ratio=1.00,
            max_spread=2.30,
            risk_high_quality=0.0045,
            stop_atr_multiple=1.15,
            rr_tp3=3.0,
            entry_confirmation_body=0.08,
        ),
        StrategyConfig(
            name="v4_ftmo_safe",
            min_quality_score=6.8,
            min_h1_atr_pct=42.0,
            min_volume_ratio=1.08,
            max_spread=1.45,
            risk_high_quality=0.0035,
            risk_base=0.0020,
            daily_profit_lock=1000.0,
            stop_atr_multiple=1.35,
            entry_confirmation_body=0.12,
        ),
        StrategyConfig(
            name="v5_overlap_off",
            min_quality_score=6.7,
            session_allow_overlap=False,
            min_h1_atr_pct=44.0,
            max_spread=1.50,
            rr_tp3=3.4,
            entry_confirmation_body=0.12,
        ),
        StrategyConfig(
            name="v6_research",
            min_quality_score=4.0,
            min_h1_atr_pct=25.0,
            min_volume_ratio=0.80,
            max_spread=2.30,
            risk_base=0.0025,
            risk_high_quality=0.0040,
            stop_atr_multiple=1.10,
            entry_confirmation_body=0.06,
        ),
    ]


def save_payload(payload: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def main() -> None:
    loader = ExportMarketLoader()
    market = loader.load()
    engine = InstitutionalResearchEngine(market)
    optimisation = engine.optimize(candidate_configs())

    leaderboard_path = RESULTS_ROOT / "institutional_strategy_leaderboard.json"
    best_run_path = RESULTS_ROOT / "institutional_strategy_best_run.json"
    save_payload(optimisation["leaderboard"], leaderboard_path)
    save_payload(optimisation["best_run"], best_run_path)

    leaderboard = pd.DataFrame(optimisation["leaderboard"])
    print("\nInstitutional XAUUSD Strategy Leaderboard")
    print(leaderboard[["name", "score", "avg_monthly_return_pct", "profit_factor", "win_rate", "max_drawdown_pct", "avg_rr", "total_trades"]].to_string(index=False))
    print(f"\nSaved leaderboard to {leaderboard_path}")
    print(f"Saved best run to {best_run_path}")


if __name__ == "__main__":
    main()
