"""
XAUUSD V17 Backtest Service — Volledig Herbouwd
===============================================
Gebruikt core.strategy_engine voor backtests — dezelfde logica als live trading.

Features:
  - Live backtest via yfinance (geen CSV dependentie)
  - Async queue systeem met progress tracking
  - WebSocket progress updates
  - Parameter input API
  - Backtest history opslag
  - Downloadbare rapporten
  - V16 backtest engine (partiële TP, trailing stop, FTMO guardrails)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backend.api.schemas.backtest import BacktestMetrics, BacktestRequest, BacktestResult, TradeRecord, WeeklySummary
from backend.api.schemas.common import TaskStatus
from core.config_watcher import StrategyConfigManager
from core.strategy_engine import DEFAULT_CFG, V18_CFG, StrategyEngine

logger = logging.getLogger(__name__)

FTMO_STARTING_CAPITAL = 160_000.0
FTMO_DAG_EUR = 8_000.0  # 5% van €160k — echte FTMO daggrens
FTMO_DD_PCT = 0.10  # 10% max totaal verlies vanaf startkapitaal (echte FTMO regel)

_EUR_USD_RATE = 1.10  # EUR/USD rate voor lot-grootte conversie (update periodiek)

RESULTS_DIR = Path("results/backtests")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
LATEST_RESULT_PATH = RESULTS_DIR / "latest_backtest.json"
YFINANCE_CACHE_DIR = RESULTS_DIR / ".yfinance_tz_cache"


@dataclass
class BacktestProgress:
    task_id: str
    status: str = "pending"  # pending | running | completed | failed
    progress: float = 0.0  # 0.0 - 1.0
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: BacktestResult | None = None
    error: str | None = None


@dataclass
class StoredBacktest:
    task_id: str
    result: BacktestResult | None
    status: TaskStatus
    created_at: datetime = field(default_factory=datetime.utcnow)


class BacktestService:
    """
    V17 Backtest Service — gebruikt strategy_engine voor live backtests.

    Alle backtests gebruiken DEZELFDE logica als de live trading engine,
    gegarandeerd door de unified core/strategy_engine.py.
    """

    def __init__(self) -> None:
        self._engine = StrategyEngine()
        self._strategy_config = StrategyConfigManager()
        self._tasks: dict[str, StoredBacktest] = {}
        self._progress: dict[str, BacktestProgress] = {}
        self._history: list[dict] = []
        self._latest_result: BacktestResult | None = self._load_latest_result()

    def run(self, req: BacktestRequest) -> BacktestResult:
        """
        Synchrone backtest — haalt data op en runt de V16 engine.
        Retourneert BacktestResult met volledige metrics.
        """
        task_id = uuid.uuid4().hex

        try:
            # Data ophalen
            logger.info("Backtest gestart: %s - %s", req.start_date, req.end_date)
            df = self._fetch_data(req.start_date, req.end_date)

            if df.empty or len(df) < 200:
                raise ValueError(f"Onvoldoende data: {len(df)} bars. Minimaal 200 H1 bars vereist.")

            # Indicatoren berekenen
            df_feat = self._engine.prepare_features(df)

            # Parameters instellen
            cfg = self._build_cfg(req)

            # Backtest uitvoeren
            trades, final_capital = self._run_backtest_engine(df_feat, cfg, req.starting_capital)

            if not trades:
                raise ValueError("Geen trades gegenereerd in de opgegeven periode.")

            # Metrics berekenen
            trades_df = pd.DataFrame(trades)
            metrics = self._build_metrics(trades_df, req.starting_capital, final_capital)
            monthly_summary = self._build_monthly_summary(trades_df)
            weekly_summary = self._build_weekly_summary(trades_df, req.starting_capital)

            # TradeRecord objecten
            trade_records = [
                TradeRecord(
                    side="buy" if t["rich"] == 1 else "sell",
                    entry_time=str(t["in"]),
                    exit_time=str(t["uit"]),
                    entry_price=t["entry"],
                    exit_price=t["exit"],
                    stop_loss=t.get("sl", 0.0),
                    take_profit=t.get("tp1", 0.0),
                    size=t.get("lot_size", 0.01),
                    pnl=round(float(t["pnl"]), 2),
                    cumulative_equity=round(float(t.get("cum_equity", req.starting_capital)), 2),
                )
                for t in trades
            ]

            result = BacktestResult(
                task_id=task_id,
                metrics=metrics,
                trades=trade_records,
                equity_curve=self._build_equity_curve(trades_df, req.starting_capital),
                monthly_summary=monthly_summary,
                weekly_summary=weekly_summary,
                chart_path="",
            )
            self._latest_result = result
            self._persist_result(result)

            # ML memory bridge — backtest trades voeden pattern memory + feedback engine
            self._feed_ml_memory(trades, df_feat)

            # Opslaan in memory
            self._tasks[task_id] = StoredBacktest(
                task_id=task_id,
                result=result,
                status=TaskStatus(
                    task_id=task_id,
                    status="completed",
                    progress=1.0,
                    result={
                        "total_trades": metrics.total_trades,
                        "total_return_pct": metrics.total_return_pct,
                        "win_rate": metrics.win_rate,
                        "profit_factor": metrics.profit_factor,
                        "max_drawdown_pct": metrics.max_drawdown_pct,
                    },
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                ),
            )

            # History opslaan
            self._history.append(
                {
                    "task_id": task_id,
                    "start_date": str(req.start_date),
                    "end_date": str(req.end_date),
                    "starting_capital": req.starting_capital,
                    "total_trades": metrics.total_trades,
                    "win_rate": metrics.win_rate,
                    "profit_factor": metrics.profit_factor,
                    "total_return_pct": metrics.total_return_pct,
                    "max_drawdown_pct": metrics.max_drawdown_pct,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )

            logger.info(
                "Backtest voltooid: %d trades, WR=%.1f%%, PF=%.2f, DD=%.1f%%",
                metrics.total_trades,
                metrics.win_rate * 100,
                metrics.profit_factor,
                metrics.max_drawdown_pct,
            )

            return result

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.exception("Backtest mislukt: %s", e)
            raise ValueError(f"Backtest fout: {str(e)}") from e

    async def run_async(self, req: BacktestRequest) -> str:
        """
        Async backtest — retourneert task_id onmiddellijk.
        Progress is op te vragen via status(task_id).
        """
        task_id = uuid.uuid4().hex
        prog = BacktestProgress(
            task_id=task_id,
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
        self._progress[task_id] = prog

        # Start in background
        asyncio.create_task(self._run_async_task(task_id, req, prog))
        return task_id

    async def _run_async_task(
        self,
        task_id: str,
        req: BacktestRequest,
        prog: BacktestProgress,
    ) -> None:
        prog.status = "running"
        prog.progress = 0.05
        prog.message = "Data ophalen..."

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: self.run(req))
            prog.result = result
            prog.status = "completed"
            prog.progress = 1.0
            prog.message = f"Voltooid: {result.metrics.total_trades} trades"
            prog.finished_at = datetime.now(timezone.utc)
        except Exception as e:
            prog.status = "failed"
            prog.error = str(e)
            prog.message = f"Fout: {e}"
            prog.finished_at = datetime.now(timezone.utc)
            logger.error("Async backtest mislukt [%s]: %s", task_id, e)

    def status(self, task_id: str) -> TaskStatus | None:
        stored = self._tasks.get(task_id)
        if stored:
            return stored.status

        prog = self._progress.get(task_id)
        if prog:
            return TaskStatus(
                task_id=task_id,
                status=prog.status,
                progress=prog.progress,
                result={"message": prog.message},
                started_at=prog.started_at,
                finished_at=prog.finished_at,
            )
        return None

    def result(self, task_id: str) -> BacktestResult | None:
        stored = self._tasks.get(task_id)
        if stored:
            return stored.result

        prog = self._progress.get(task_id)
        if prog and prog.result:
            return prog.result
        return None

    def get_history(self) -> list[dict]:
        return list(reversed(self._history[-50:]))  # Laatste 50

    def get_latest_result(self) -> BacktestResult | None:
        if self._latest_result is not None:
            return self._latest_result
        self._latest_result = self._load_latest_result()
        return self._latest_result

    def get_progress(self, task_id: str) -> dict | None:
        prog = self._progress.get(task_id)
        if prog:
            return {
                "task_id": prog.task_id,
                "status": prog.status,
                "progress": prog.progress,
                "message": prog.message,
                "error": prog.error,
            }
        return None

    # ─────────────────────────────────────────────────────────────
    # DATA OPHALEN
    # ─────────────────────────────────────────────────────────────

    def _fetch_data(self, start_date, end_date) -> pd.DataFrame:
        """Haalt H1 XAUUSD data op via yfinance (GC=F).

        Probeert maximaal 3 keer; bij een SQLite cache-fout wordt de cache
        uitgeschakeld voor de herhalingspogingen.
        """
        try:
            import yfinance as yf
        except ImportError:
            raise FileNotFoundError("yfinance niet beschikbaar — pip install yfinance")

        start_with_buffer = pd.Timestamp(start_date) - pd.Timedelta(days=90)
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        start_str = start_with_buffer.strftime("%Y-%m-%d")
        end_str = end_ts.strftime("%Y-%m-%d")

        last_exc: Exception | None = None
        df = pd.DataFrame()
        for attempt in range(3):
            try:
                cache_dir = YFINANCE_CACHE_DIR / f"attempt_{attempt + 1}"
                cache_dir.mkdir(parents=True, exist_ok=True)
                try:
                    yf.set_tz_cache_location(str(cache_dir))  # type: ignore[attr-defined]
                except AttributeError:
                    pass

                df = yf.download(
                    "GC=F",
                    start=start_str,
                    end=end_str,
                    interval="1h",
                    progress=False,
                    auto_adjust=True,
                )
                if df.empty:
                    last_exc = FileNotFoundError("yfinance returned an empty dataset")
                    logger.warning("yfinance poging %d gaf een lege dataset terug", attempt + 1)
                    continue
                break
            except Exception as e:
                last_exc = e
                logger.warning("yfinance poging %d mislukt: %s", attempt + 1, e)
        else:
            if os.getenv("APP_ENV", "").strip().lower() == "test":
                logger.warning("yfinance niet beschikbaar in testomgeving; gebruik synthetische H1 data")
                return self._build_synthetic_test_data(start_date, end_date)
            raise FileNotFoundError(f"Data ophalen mislukt na 3 pogingen: {last_exc}") from last_exc

        if df.empty:
            if os.getenv("APP_ENV", "").strip().lower() == "test":
                logger.warning("Lege yfinance dataset in testomgeving; gebruik synthetische H1 data")
                return self._build_synthetic_test_data(start_date, end_date)
            raise FileNotFoundError("Geen data beschikbaar voor GC=F (Gold Futures). Controleer internetverbinding.")

        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index, utc=True)
        df = df[["open", "high", "low", "close", "volume"]].dropna()

        logger.info("Data geladen: %d H1 bars (%s → %s)", len(df), df.index[0].date(), df.index[-1].date())
        return df

    def _build_synthetic_test_data(self, start_date, end_date) -> pd.DataFrame:
        """Deterministische offline fallback voor test/CI-omgevingen zonder netwerk."""
        start_with_buffer = pd.Timestamp(start_date, tz="UTC") - pd.Timedelta(days=90)
        end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)
        index = pd.date_range(start=start_with_buffer, end=end_ts, freq="1h", inclusive="left", tz="UTC")
        if len(index) < 250:
            index = pd.date_range(start=start_with_buffer, periods=250, freq="1h", tz="UTC")

        rng = np.random.default_rng(42)
        n = len(index)
        trend = np.linspace(0.0, 120.0, n)
        slow_wave = 18.0 * np.sin(np.linspace(0.0, 16.0 * np.pi, n))
        fast_wave = 7.0 * np.sin(np.linspace(0.0, 40.0 * np.pi, n))
        noise = rng.normal(0.0, 3.5, n).cumsum() * 0.15
        close = 2050.0 + trend + slow_wave + fast_wave + noise
        open_ = np.roll(close, 1)
        open_[0] = close[0] - 1.2
        open_ = open_ + rng.normal(0.0, 1.2, n)
        spread = np.abs(rng.normal(2.8, 1.0, n)) + 0.6
        high = np.maximum(open_, close) + spread
        low = np.minimum(open_, close) - spread
        volume = rng.integers(900, 4500, n).astype(float)

        frame = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
            index=index,
        )
        logger.info(
            "Synthetische testdata geladen: %d H1 bars (%s -> %s)",
            len(frame),
            frame.index[0].date(),
            frame.index[-1].date(),
        )
        return frame

    # ─────────────────────────────────────────────────────────────
    # BACKTEST ENGINE (V16 logica — identiek aan strategy_v16.py)
    # ─────────────────────────────────────────────────────────────

    def _build_cfg(self, req: BacktestRequest, use_v18: bool = False) -> dict:
        """Bouw strategie config vanuit BacktestRequest."""
        if use_v18:
            base = dict(V18_CFG)
        else:
            base = self._strategy_config.get_strategy_cfg() or dict(DEFAULT_CFG)
        params = getattr(req, "strategy_params", None) or {}
        if isinstance(params, dict):
            for key, value in params.items():
                if str(key).startswith("_"):
                    continue
                base[key] = value
        return base

    def _run_backtest_engine(
        self,
        df: pd.DataFrame,
        cfg: dict,
        starting_capital: float,
        ftmo_floor_pct: float = FTMO_DD_PCT,
        ftmo_balance_based: bool = True,  # True = correcte FTMO regel (max 10% van startkapitaal)
    ) -> tuple[list[dict], float]:
        """
        V16 backtest engine — exact dezelfde logica als strategy_v16.py.
        Gebruikt core.strategy_engine.generate_signal() voor signalen.
        """
        tp1_pct = cfg.get("tp1_pct", 0.30)
        tp2_pct = cfg.get("tp2_pct", 0.30)
        tp3_pct = 1.0 - tp1_pct - tp2_pct
        max_dag = cfg.get("max_dag", 6)
        sl_dag_max = cfg.get("sl_dag_max", 2)
        cool_h = cfg.get("cooldown_h", 2)
        trail_on = cfg.get("trailing", True)
        weekly_compound = cfg.get("weekly_compound", False)
        compound_boost = cfg.get("compound_boost", 1.10)
        compound_decay = float(cfg.get("compound_decay", 0.95))
        max_lot_size = float(cfg.get("max_lot_size", 4.0))
        # FTMO dagelijkse limiet (default €6,000 = 3.75% van €160k)
        ftmo_dag_eur = float(cfg.get("max_daily_loss_eur", 6_000.0))
        # balance_based: max verlies t.o.v. startkapitaal (echte FTMO-regel)
        # peak_based: max verlies t.o.v. equity-piek (conservatief, default)
        ftmo_tot_eur = starting_capital * ftmo_floor_pct
        ftmo_floor_eur = starting_capital * (1.0 - ftmo_floor_pct)  # voor balance_based
        # Verliesweek- en verliesdag-bescherming
        weekly_loss_threshold = float(cfg.get("weekly_loss_threshold", 0.0))
        weekly_loss_risk_scale = float(cfg.get("weekly_loss_risk_scale", 1.0))
        loss_day_filter = bool(cfg.get("loss_day_filter", False))
        # V20: maanddoel + 3-weken reset
        monthly_profit_target = float(cfg.get("monthly_profit_target", 0.0))  # 0 = uitgeschakeld
        reset_weeks = int(cfg.get("reset_weeks", 0))  # 0 = geen reset
        reset_capital_amount = float(cfg.get("reset_capital", starting_capital))

        kap = float(starting_capital)
        piek = kap
        trs: list[dict] = []
        dag: dict[date, dict] = {}

        # V20: banked profit (winst van eerdere reset-cycli) + maand-tracking
        _banked_profit: float = 0.0
        _next_reset_date: date | None = None  # wordt gezet bij eerste bar
        _current_month_str: str = ""
        _month_start_equity: float = kap  # equity bij begin van maand (banked=0 bij start)

        ip = False
        entry = sl = tp1 = tp2 = tp3 = None
        richting = sig_type = ot = None
        risk_rem = 0.0
        tp1_hit = tp2_hit = False
        last_i = -999
        cum_equity = _banked_profit + kap
        _open_lot_size = 0.01

        # Weekly compound tracking
        _week_start_equity = kap
        _current_week: int | None = None
        _compound_multiplier = 1.0
        # Weekly & daily PnL tracking voor verliesbescherming
        _week_pnl: dict[int, float] = {}  # week_num → gerealiseerde PnL deze week
        _day_net_pnl: dict[date, float] = {}  # datum → netto PnL die dag

        for i in range(120, len(df)):
            b = df.iloc[i]
            bar_date = b.name.date()

            if bar_date not in dag:
                dag[bar_date] = {"loss": 0.0, "n": 0, "sl": 0}

            # V20: initialiseer reset-datum bij eerste bar
            if reset_weeks > 0 and _next_reset_date is None:
                _next_reset_date = bar_date + timedelta(weeks=reset_weeks)

            # V20: maand-tracking
            bar_month_str = bar_date.strftime("%Y-%m")
            if bar_month_str != _current_month_str:
                _current_month_str = bar_month_str
                _month_start_equity = _banked_profit + kap

            # V20: 3-weken reset
            if reset_weeks > 0 and _next_reset_date is not None and bar_date >= _next_reset_date:
                if ip:
                    ep = float(b["close"])
                    sl_dist_r = abs(entry - sl)
                    pnl_r = risk_rem * ((ep - entry) / max(sl_dist_r, 0.001) * richting)
                    kap += pnl_r
                    cum_equity = _banked_profit + kap
                    trs.append(
                        self._make_tr(
                            ot,
                            b.name,
                            richting,
                            entry,
                            ep,
                            pnl_r,
                            "RESET",
                            sig_type,
                            sl,
                            tp1,
                            cum_equity,
                            _open_lot_size,
                        )
                    )
                    ip = False
                # Bankeer alles boven reset_capital_amount
                _banked_profit += max(0.0, kap - reset_capital_amount)
                kap = min(kap, reset_capital_amount)
                piek = kap
                _compound_multiplier = 1.0
                _week_pnl.clear()
                _day_net_pnl.clear()
                _current_week = None
                _week_start_equity = kap
                _month_start_equity = _banked_profit + kap
                _next_reset_date = bar_date + timedelta(weeks=reset_weeks)

            # Weekly compound boost: na elke winstgevende week → multiplier omhoog
            if weekly_compound:
                bar_week = b.name.isocalendar()[1]
                if _current_week is None:
                    _current_week = bar_week
                    _week_start_equity = kap
                elif bar_week != _current_week:
                    # Nieuwe week begint
                    if kap > _week_start_equity:
                        _compound_multiplier = min(_compound_multiplier * compound_boost, 1.30)
                    else:
                        _compound_multiplier = max(_compound_multiplier * compound_decay, 1.0)
                    _current_week = bar_week
                    _week_start_equity = kap

            # FTMO stop check
            if ftmo_balance_based:
                ftmo_breached = kap < ftmo_floor_eur  # equity < startkapitaal * (1 - ftmo_floor_pct)
            else:
                dd_eur = piek - kap
                ftmo_breached = dd_eur >= ftmo_tot_eur
            if ftmo_breached:
                if ip:
                    ep = float(b["close"])
                    pnl = richting * (ep - entry) / max(abs(entry - sl), 0.001) * risk_rem
                    kap += pnl
                    cum_equity = _banked_profit + kap
                    trs.append(
                        self._make_tr(
                            ot, b.name, richting, entry, ep, pnl, "FAIL", sig_type, sl, tp1, cum_equity, _open_lot_size
                        )
                    )
                    ip = False
                break

            # Beheer open positie
            if ip:
                hi = float(b["high"])
                lo = float(b["low"])
                cl = float(b["close"])
                sl_dist = abs(entry - sl)
                if sl_dist <= 0:
                    ip = False
                    continue

                # Break-even na TP1
                if tp1_hit and not tp2_hit:
                    if richting == 1 and sl < entry:
                        sl = entry + 0.05 * sl_dist
                    elif richting == -1 and sl > entry:
                        sl = entry - 0.05 * sl_dist

                # Trailing stop na TP1
                if trail_on and tp1_hit:
                    float_pnl = richting * (cl - entry) / sl_dist * risk_rem
                    if float_pnl > 500 and not tp2_hit:
                        new_sl_trail = entry + richting * 0.4 * sl_dist
                        if richting == 1:
                            sl = max(sl, new_sl_trail)
                        else:
                            sl = min(sl, new_sl_trail)

                # TP1
                if not tp1_hit:
                    if (richting == 1 and hi >= tp1) or (richting == -1 and lo <= tp1):
                        if not ((richting == 1 and lo <= sl) or (richting == -1 and hi >= sl)):
                            pnl_tp1 = tp1_pct * risk_rem * ((tp1 - entry) / sl_dist * richting)
                            kap += pnl_tp1
                            if kap > piek:
                                piek = kap
                            cum_equity = _banked_profit + kap
                            trs.append(
                                self._make_tr(
                                    ot,
                                    b.name,
                                    richting,
                                    entry,
                                    tp1,
                                    pnl_tp1,
                                    "TP1",
                                    sig_type,
                                    sl,
                                    tp1,
                                    cum_equity,
                                    _open_lot_size,
                                )
                            )
                            risk_rem *= 1.0 - tp1_pct
                            tp1_hit = True
                            _day_net_pnl[bar_date] = _day_net_pnl.get(bar_date, 0.0) + pnl_tp1
                            if _current_week:
                                _week_pnl[_current_week] = _week_pnl.get(_current_week, 0.0) + pnl_tp1

                # TP2
                if tp1_hit and not tp2_hit:
                    tp2_frac = tp2_pct / (tp2_pct + tp3_pct)
                    if (richting == 1 and hi >= tp2) or (richting == -1 and lo <= tp2):
                        pnl_tp2 = tp2_frac * risk_rem * ((tp2 - entry) / sl_dist * richting)
                        kap += pnl_tp2
                        if kap > piek:
                            piek = kap
                        cum_equity = _banked_profit + kap
                        trs.append(
                            self._make_tr(
                                ot,
                                b.name,
                                richting,
                                entry,
                                tp2,
                                pnl_tp2,
                                "TP2",
                                sig_type,
                                sl,
                                tp2,
                                cum_equity,
                                _open_lot_size,
                            )
                        )
                        risk_rem *= 1.0 - tp2_frac
                        tp2_hit = True
                        _day_net_pnl[bar_date] = _day_net_pnl.get(bar_date, 0.0) + pnl_tp2
                        if _current_week:
                            _week_pnl[_current_week] = _week_pnl.get(_current_week, 0.0) + pnl_tp2

                # TP3
                if tp1_hit and tp2_hit:
                    if (richting == 1 and hi >= tp3) or (richting == -1 and lo <= tp3):
                        pnl_tp3 = risk_rem * ((tp3 - entry) / sl_dist * richting)
                        kap += pnl_tp3
                        if kap > piek:
                            piek = kap
                        cum_equity = _banked_profit + kap
                        trs.append(
                            self._make_tr(
                                ot,
                                b.name,
                                richting,
                                entry,
                                tp3,
                                pnl_tp3,
                                "TP3",
                                sig_type,
                                sl,
                                tp3,
                                cum_equity,
                                _open_lot_size,
                            )
                        )
                        ip = False
                        _day_net_pnl[bar_date] = _day_net_pnl.get(bar_date, 0.0) + pnl_tp3
                        if _current_week:
                            _week_pnl[_current_week] = _week_pnl.get(_current_week, 0.0) + pnl_tp3
                        continue

                # SL check
                hit_sl = (richting == 1 and lo <= sl) or (richting == -1 and hi >= sl)
                if hit_sl:
                    pnl_sl = risk_rem * ((sl - entry) / sl_dist * richting)
                    if pnl_sl < 0:
                        rem_loss = max(0, ftmo_dag_eur - dag[bar_date]["loss"])
                        if abs(pnl_sl) > rem_loss:
                            pnl_sl = -rem_loss
                        dag[bar_date]["loss"] += abs(pnl_sl)
                        dag[bar_date]["sl"] += 1
                    kap += pnl_sl
                    if kap > piek:
                        piek = kap
                    cum_equity = _banked_profit + kap
                    trs.append(
                        self._make_tr(
                            ot, b.name, richting, entry, sl, pnl_sl, "SL", sig_type, sl, tp1, cum_equity, _open_lot_size
                        )
                    )
                    ip = False
                    _day_net_pnl[bar_date] = _day_net_pnl.get(bar_date, 0.0) + pnl_sl
                    if _current_week:
                        _week_pnl[_current_week] = _week_pnl.get(_current_week, 0.0) + pnl_sl

            if ip:
                continue

            # V20: stop nieuwe trades als maanddoel bereikt
            if monthly_profit_target > 0:
                _month_pnl = (_banked_profit + kap) - _month_start_equity
                if _month_pnl >= monthly_profit_target:
                    continue

            # Entry condities
            if dag[bar_date]["loss"] >= ftmo_dag_eur * 0.65:
                continue
            if dag[bar_date]["n"] >= max_dag:
                continue
            if dag[bar_date]["sl"] >= sl_dag_max:
                continue
            if (i - last_i) < cool_h:
                continue

            # Sessie check
            tier = self._engine.get_session(b.name.to_pydatetime())
            if tier == "blocked":
                continue

            # ── Signaal genereren ───────────────────────────────────
            signal = self._engine.generate_signal(df.iloc[max(0, i - 300) : i + 1], cfg=cfg)

            if signal is None:
                continue

            sig_type = signal.signal_type
            rich_str = signal.direction
            risk_pct = signal.risk_pct

            # Standaard sessie: alleen A of B signalen
            if tier == "standard" and sig_type not in ("A_EMACROSS", "B_MACDCROSS"):
                continue

            # ── Verliesdag-filter: na 2 opeenvolgende verlies-dagen → alleen A/B/F ──
            if loss_day_filter:
                prev_days = sorted(d for d in _day_net_pnl if d < bar_date)[-2:]
                if (
                    len(prev_days) >= 2
                    and all(_day_net_pnl[d] < 0 for d in prev_days)
                    and sig_type not in ("A_EMACROSS", "B_MACDCROSS", "F_MSS")
                ):
                    continue

            # Drawdown risk scaling
            dd_pct = (piek - kap) / max(piek, 1)
            if dd_pct > 0.05:
                risk_pct *= 0.25
            elif dd_pct > 0.04:
                risk_pct *= 0.40
            elif dd_pct > 0.03:
                risk_pct *= 0.60
            elif dd_pct > 0.01:
                risk_pct *= 0.80

            # Loss streak scaling
            recent_sl = sum(1 for t in trs[-4:] if t["result"] == "SL" and t["pnl"] < 0)
            if recent_sl >= 3:
                risk_pct *= 0.50

            # ── Verliesweek-bescherming: risico verlagen als week al in de min zit ──
            if weekly_loss_threshold > 0 and _current_week is not None:
                _this_week_pnl = _week_pnl.get(_current_week, 0.0)
                _week_loss_pct = _this_week_pnl / max(_week_start_equity, 1)
                if _week_loss_pct < -weekly_loss_threshold:
                    risk_pct *= weekly_loss_risk_scale

            richting = 1 if rich_str == "long" else -1
            cl_pr = float(b["close"])

            # SL/TP niveaus uit signal
            sl = signal.stop_loss
            tp1 = signal.take_profit_1
            tp2 = signal.take_profit_2
            tp3 = signal.take_profit_3

            sl_dist = abs(cl_pr - sl)
            if sl_dist <= 0:
                continue

            risk_usd = kap * risk_pct * _compound_multiplier
            risk_rem = risk_usd
            entry = cl_pr
            ot = b.name
            ip = True
            tp1_hit = tp2_hit = False
            last_i = i
            dag[bar_date]["n"] += 1

            # Echte lotsize berekening — zelfde formule als live MT5 bot
            # XAUUSD: 1 lot = 100 oz, P&L = lot × 100 × ΔP (in USD)
            # risk_eur → risk_usd via _EUR_USD_RATE
            _risk_usd_mt5 = risk_usd * _EUR_USD_RATE
            _raw_lot = _risk_usd_mt5 / (sl_dist * 100)
            _open_lot_size = round(max(min(_raw_lot, max_lot_size), 0.01), 2)
            # Als lot cap aanslaat: risk_rem aanpassen zodat P&L realistisch is
            if _raw_lot > max_lot_size:
                risk_rem = (_open_lot_size * sl_dist * 100) / _EUR_USD_RATE

        # Sluit open positie
        if ip and len(df) > 0:
            ep = float(df.iloc[-1]["close"])
            sl_dist = abs(entry - sl)
            pnl = risk_rem * ((ep - entry) / max(sl_dist, 0.001) * richting)
            kap += pnl
            cum_equity = _banked_profit + kap
            trs.append(
                self._make_tr(
                    ot, df.index[-1], richting, entry, ep, pnl, "OPEN", sig_type, sl, tp1, cum_equity, _open_lot_size
                )
            )

        return trs, _banked_profit + kap

    @staticmethod
    def _make_tr(ti, to, rich, entry, exit_p, pnl, result, stype, sl=0, tp1=0, cum_equity=0, lot_size=0.01) -> dict:
        return {
            "in": str(ti),
            "uit": str(to),
            "rich": rich,
            "entry": round(float(entry), 2),
            "exit": round(float(exit_p), 2),
            "sl": round(float(sl), 2),
            "tp1": round(float(tp1), 2),
            "pnl": round(float(pnl), 2),
            "result": result,
            "type": stype,
            "cum_equity": round(float(cum_equity), 2),
            "lot_size": round(float(lot_size), 2),
        }

    # ─────────────────────────────────────────────────────────────
    # METRICS & RAPPORTEN
    # ─────────────────────────────────────────────────────────────

    def _build_metrics(self, trades: pd.DataFrame, starting: float, final: float) -> BacktestMetrics:
        pnl = trades["pnl"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]

        total_return_pct = ((final / starting) - 1.0) * 100 if starting > 0 else 0.0

        cum_equity = pnl.cumsum() + starting
        running_peak = cum_equity.cummax()
        dd_series = np.where(running_peak > 0, (running_peak - cum_equity) / running_peak * 100, 0.0)
        max_drawdown_pct = float(np.max(dd_series)) if len(dd_series) else 0.0

        profit_factor = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
        avg_win = float(wins.mean()) if not wins.empty else 0.0
        avg_loss = float(losses.mean()) if not losses.empty else 0.0
        expectancy = float(pnl.mean()) if not pnl.empty else 0.0

        trade_returns = pnl / starting if starting > 0 else pnl * 0
        sharpe_ratio = 0.0
        if len(trade_returns) > 1 and float(trade_returns.std(ddof=0)) > 0:
            sharpe_ratio = float(trade_returns.mean() / trade_returns.std(ddof=0) * np.sqrt(252))

        calmar_ratio = float(total_return_pct / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0

        if "in" in trades.columns:
            challenge_days = int(pd.to_datetime(trades["in"]).dt.normalize().nunique())
        else:
            challenge_days = 0

        ftmo_passed = max_drawdown_pct < FTMO_DD_PCT * 100  # < 10%

        return BacktestMetrics(
            total_trades=int(len(trades)),
            win_rate=round(float((pnl > 0).mean()), 4) if not pnl.empty else 0.0,
            profit_factor=round(min(profit_factor, 99.0), 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
            total_return_pct=round(total_return_pct, 4),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            expectancy=round(expectancy, 2),
            calmar_ratio=round(calmar_ratio, 4),
            ftmo_passed=ftmo_passed,
            challenge_days=challenge_days,
        )

    def _build_monthly_summary(self, trades: pd.DataFrame) -> list[dict]:
        if trades.empty or "in" not in trades.columns:
            return []
        monthly = trades.copy()
        monthly["month"] = pd.to_datetime(monthly["in"], utc=True).dt.tz_convert(None).dt.to_period("M").astype(str)
        grouped = (
            monthly.groupby("month")
            .agg(
                trades=("pnl", "size"),
                pnl=("pnl", "sum"),
                win_rate=("pnl", lambda s: float((s > 0).mean()) if len(s) else 0.0),
                avg_trade=("pnl", "mean"),
            )
            .reset_index()
        )
        return [
            {
                "month": row["month"],
                "trades": int(row["trades"]),
                "pnl": round(float(row["pnl"]), 2),
                "win_rate": round(float(row["win_rate"]), 4),
                "avg_trade": round(float(row["avg_trade"]), 2),
            }
            for _, row in grouped.iterrows()
        ]

    def _build_weekly_summary(self, trades: pd.DataFrame, starting: float) -> list[WeeklySummary]:
        if trades.empty or "uit" not in trades.columns or "pnl" not in trades.columns:
            return []

        weekly = trades.copy()
        weekly["closed_at"] = pd.to_datetime(weekly["uit"], utc=True, errors="coerce")
        weekly = weekly.dropna(subset=["closed_at"]).sort_values("closed_at").reset_index(drop=True)
        if weekly.empty:
            return []

        weekly["pnl"] = weekly["pnl"].astype(float)
        weekly["equity_before"] = starting + weekly["pnl"].cumsum().shift(fill_value=0.0)
        weekly["equity_after"] = starting + weekly["pnl"].cumsum()
        iso = weekly["closed_at"].dt.isocalendar()
        weekly["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
        weekly["week_start"] = weekly["closed_at"].dt.normalize() - pd.to_timedelta(
            weekly["closed_at"].dt.weekday, unit="D"
        )

        grouped = (
            weekly.groupby(["week", "week_start"], as_index=False)
            .agg(
                trades=("pnl", "size"),
                pnl=("pnl", "sum"),
                start_equity=("equity_before", "first"),
                end_equity=("equity_after", "last"),
                win_rate=("pnl", lambda s: float((s > 0).mean()) if len(s) else 0.0),
            )
            .sort_values("week_start")
        )
        grouped["return_pct"] = np.where(
            grouped["start_equity"] > 0,
            grouped["pnl"] / grouped["start_equity"] * 100.0,
            0.0,
        )

        return [
            WeeklySummary(
                week=str(row["week"]),
                week_start=pd.Timestamp(row["week_start"]).date().isoformat(),
                trades=int(row["trades"]),
                pnl=round(float(row["pnl"]), 2),
                return_pct=round(float(row["return_pct"]), 2),
                start_equity=round(float(row["start_equity"]), 2),
                end_equity=round(float(row["end_equity"]), 2),
                win_rate=round(float(row["win_rate"]), 4),
            )
            for _, row in grouped.iterrows()
        ]

    def _build_equity_curve(self, trades: pd.DataFrame, starting: float) -> list[dict]:
        if trades.empty:
            return []
        result = []
        equity = starting
        for _, row in trades.iterrows():
            equity += float(row.get("pnl", 0))
            result.append(
                {
                    "timestamp": str(row.get("uit", "")),
                    "capital": round(equity, 2),
                    "pnl": round(float(row.get("pnl", 0)), 2),
                }
            )
        return result

    def _feed_ml_memory(self, trades: list[dict], df_feat: pd.DataFrame) -> None:
        """
        Voert backtest trades in de ML memory systemen:
          - PatternMemory: patroonstatistieken per setup type
          - FeedbackEngine: feature records voor model training

        Alle trades worden gemarkeerd als source='backtest' zodat
        het live model ze kan onderscheiden van echte trades.
        """
        try:
            from ml.feedback_engine import FeedbackEngine, TradeFeatureRecord
            from ml.pattern_memory import PatternMemory
        except ImportError:
            logger.debug("ML modules niet beschikbaar — backtest bridge overgeslagen")
            return

        if not trades:
            return

        pattern_mem = PatternMemory()
        feedback_eng = FeedbackEngine()

        recorded = 0
        for t in trades:
            try:
                signal_type = str(t.get("type", "D_PULLBACK"))
                direction = "long" if t.get("rich", 1) == 1 else "short"
                pnl = float(t.get("pnl", 0.0))

                # Tsd ophalen uit de feature dataframe op entry tijdstip
                in_time = pd.to_datetime(t.get("in"))
                out_time = pd.to_datetime(t.get("uit"))
                holding_min = max(0.0, (out_time - in_time).total_seconds() / 60.0) if pd.notna(out_time) else 60.0

                # Features ophalen van de bar op entry tijdstip
                feat_row = None
                if in_time in df_feat.index:
                    feat_row = df_feat.loc[in_time]
                elif not df_feat.empty:
                    # Dichtste bar vinden
                    idx = df_feat.index.searchsorted(in_time)
                    if idx < len(df_feat):
                        feat_row = df_feat.iloc[idx]

                rsi14 = float(feat_row["rsi14"]) if feat_row is not None and "rsi14" in feat_row else 50.0
                adx14 = float(feat_row["adx14"]) if feat_row is not None and "adx14" in feat_row else 14.0
                h4_regime = str(feat_row.get("h4_regime", "CHOPPY")) if feat_row is not None else "CHOPPY"
                d1_trend = str(feat_row.get("d1_trend", "neutral")) if feat_row is not None else "neutral"
                atr14 = float(feat_row["atr14"]) if feat_row is not None and "atr14" in feat_row else 5.0
                hour = in_time.hour if hasattr(in_time, "hour") else 10
                session = "london" if 7 <= hour < 12 else ("ny" if 13 <= hour <= 17 else "any")

                entry_price = float(t.get("entry", 1))
                sl_price = float(t.get("sl", entry_price))
                sl_dist = abs(entry_price - sl_price)
                rr = abs(pnl) / (sl_dist * 100) if sl_dist > 0 else 1.0

                # PatternMemory
                pattern_mem.record(
                    signal_type=signal_type,
                    direction=direction,
                    h4_regime=h4_regime,
                    d1_trend=d1_trend,
                    rsi14=rsi14,
                    session=session,
                    pnl=pnl,
                    rr=rr,
                    holding_minutes=holding_min,
                )

                # FeedbackEngine
                rec = TradeFeatureRecord(
                    broker_ticket=f"BT_{t.get('in', '')}_{signal_type}",
                    signal_type=signal_type,
                    direction=direction,
                    rsi14=rsi14,
                    adx14=adx14,
                    macd_hist=0.0,
                    h4_adx=adx14,
                    h4_regime=h4_regime,
                    d1_trend=d1_trend,
                    dist21=float(feat_row.get("dist21", 0.0)) if feat_row is not None else 0.0,
                    atr14=atr14,
                    volatility_ratio=1.0,
                    hour_of_day=hour,
                    day_of_week=in_time.weekday() if hasattr(in_time, "weekday") else 0,
                    sentiment_score=0.0,
                    pnl=pnl,
                    rr_ratio=rr,
                    market_regime=h4_regime,
                    holding_minutes=holding_min,
                    source="backtest",
                )
                feedback_eng.record_trade(rec)
                recorded += 1

            except Exception as exc:
                logger.debug("ML bridge: trade overgeslagen: %s", exc)
                continue

        logger.info("ML memory bridge: %d/%d trades ingevoerd vanuit backtest", recorded, len(trades))

        # Model hertrainen als genoeg data
        if feedback_eng.get_record_count() >= 20:
            feedback_eng.train()

    def _persist_result(self, result: BacktestResult) -> None:
        payload = result.model_dump(mode="json")
        LATEST_RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_latest_result(self) -> BacktestResult | None:
        if not LATEST_RESULT_PATH.exists():
            return None
        try:
            payload = json.loads(LATEST_RESULT_PATH.read_text(encoding="utf-8"))
            return BacktestResult.model_validate(payload)
        except Exception as exc:
            logger.warning("Could not load persisted latest backtest result: %s", exc)
            return None
