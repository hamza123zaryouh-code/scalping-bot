"""
Optimizer Service — Async Parameter Sweep voor V17 Strategy Engine
==================================================================
Voert grid-search en walk-forward optimalisatie uit op de V17 engine.

Features:
  - Async job queue (achtergrond optimalisatie)
  - Grid search over strategy parameters
  - Walk-forward validatie (in-sample / out-of-sample)
  - Overfitting detectie (IS/OOS Sharpe ratio vergelijking)
  - Performance ranking per parameter set
  - Optuna integratie (optioneel — valt terug op grid search)
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core.strategy_engine import DEFAULT_CFG, StrategyEngine

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("results/optimizer")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────


@dataclass
class OptimizerRequest:
    """Configuratie voor een optimalisatierun."""

    start_date: date
    end_date: date
    symbol: str = "XAUUSD"
    starting_capital: float = 160_000.0

    # Grid search parameters
    param_grid: dict = field(
        default_factory=lambda: {
            "risk_a": [0.003, 0.004, 0.005],
            "risk_b": [0.002, 0.003, 0.004],
            "risk_c": [0.0015, 0.002, 0.0025],
            "sl_atr": [1.2, 1.5, 1.8],
            "tp1_r": [1.2, 1.5, 2.0],
            "tp2_r": [2.0, 2.5, 3.0],
            "adx_min": [12, 14, 18],
        }
    )

    # Walk-forward configuratie
    walk_forward_splits: int = 3
    is_pct: float = 0.70  # In-sample percentage
    max_combinations: int = 50  # Max combinaties te testen

    # Doelmetriek
    objective: str = "sharpe"  # "sharpe" | "profit_factor" | "monthly_return"

    # Overfitting filter
    min_oos_sharpe: float = 0.5
    max_is_oos_ratio: float = 2.5  # IS Sharpe / OOS Sharpe moet < 2.5 zijn


@dataclass
class ParameterSetResult:
    """Resultaat van één parameter combinatie."""

    params: dict
    is_sharpe: float
    oos_sharpe: float
    total_return: float
    monthly_return: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    trade_count: int
    is_overfitted: bool
    overfitting_score: float  # 0.0 (goed) - 1.0 (slecht)
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            "params": self.params,
            "is_sharpe": round(self.is_sharpe, 3),
            "oos_sharpe": round(self.oos_sharpe, 3),
            "total_return": round(self.total_return, 4),
            "monthly_return_pct": round(self.monthly_return * 100, 2),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 3),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "trade_count": self.trade_count,
            "is_overfitted": self.is_overfitted,
            "overfitting_score": round(self.overfitting_score, 3),
            "rank": self.rank,
        }


@dataclass
class OptimizerResult:
    """Volledig resultaat van een optimalisatierun."""

    job_id: str
    request: OptimizerRequest
    best_params: dict
    results: list[ParameterSetResult]
    total_combinations_tested: int
    duration_seconds: float
    completed_at: datetime
    summary: dict

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "best_params": self.best_params,
            "top_results": [r.to_dict() for r in self.results[:10]],
            "total_tested": self.total_combinations_tested,
            "duration_seconds": round(self.duration_seconds, 1),
            "completed_at": self.completed_at.isoformat(),
            "summary": self.summary,
        }


@dataclass
class OptimizerJob:
    """Achtergrond optimalisatie job."""

    job_id: str
    request: OptimizerRequest
    status: str = "pending"  # pending | running | completed | failed
    progress: float = 0.0  # 0.0 - 1.0
    message: str = ""
    result: OptimizerResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": self.result.to_dict() if self.result else None,
        }


# ─────────────────────────────────────────────────────────────────
# OPTIMIZER SERVICE
# ─────────────────────────────────────────────────────────────────


class OptimizerService:
    """
    Async optimizer service — werkt volledig op achtergrond.

    Gebruik:
        svc = OptimizerService()
        job_id = await svc.start_job(request)
        status = svc.get_job(job_id)
        results = svc.get_top_results(job_id)
    """

    def __init__(self) -> None:
        self._engine = StrategyEngine()
        self._jobs: dict[str, OptimizerJob] = {}
        self._history: list[dict] = []
        self._load_history()

    async def start_job(self, request: OptimizerRequest) -> str:
        """Start een async optimalisatie job. Retourneert job_id."""
        job_id = uuid.uuid4().hex[:12]
        job = OptimizerJob(job_id=job_id, request=request)
        self._jobs[job_id] = job

        asyncio.create_task(self._run_job(job))
        logger.info("Optimizer job gestart: %s", job_id)
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        """Geeft job status terug."""
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self, limit: int = 20) -> list[dict]:
        """Geeft alle jobs terug, meest recent eerst."""
        return [
            j.to_dict()
            for j in sorted(
                self._jobs.values(),
                key=lambda j: j.created_at,
                reverse=True,
            )
        ][:limit]

    def get_history(self, limit: int = 50) -> list[dict]:
        """Geeft de optimalisatie history terug."""
        return self._history[-limit:]

    def get_best_params(self) -> dict:
        """Geeft de best gevonden parameters terug uit alle runs."""
        completed_jobs = [j for j in self._jobs.values() if j.status == "completed" and j.result is not None]
        if not completed_jobs:
            return DEFAULT_CFG.copy()

        best_job = max(
            completed_jobs,
            key=lambda j: j.result.results[0].oos_sharpe if j.result and j.result.results else 0.0,
        )
        if best_job.result:
            return best_job.result.best_params
        return DEFAULT_CFG.copy()

    # ─────────────────────────────────────────────────────────────
    # ASYNC JOB RUNNER
    # ─────────────────────────────────────────────────────────────

    async def _run_job(self, job: OptimizerJob) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        start_time = datetime.now(timezone.utc)

        try:
            job.message = "Marktdata ophalen..."
            df = await asyncio.to_thread(self._fetch_data, job.request.start_date, job.request.end_date)

            if df.empty or len(df) < 300:
                raise ValueError(f"Onvoldoende data: {len(df)} bars (minimum 300)")

            job.message = "Indicatoren berekenen..."
            df_feat = await asyncio.to_thread(self._engine.prepare_features, df)

            if df_feat.empty:
                raise ValueError("Feature preparation mislukt — te weinig data")

            combinations = self._build_combinations(job.request)
            total = len(combinations)
            job.message = f"Optimaliseren: {total} combinaties testen..."
            logger.info("Optimizer: %d combinaties te testen", total)

            results: list[ParameterSetResult] = []

            for i, params in enumerate(combinations):
                try:
                    result = await asyncio.to_thread(
                        self._evaluate_params,
                        df_feat,
                        params,
                        job.request.starting_capital,
                        job.request.walk_forward_splits,
                        job.request.is_pct,
                    )
                    results.append(result)
                except Exception as exc:
                    logger.debug("Parameter combo %d mislukt: %s", i, exc)

                job.progress = (i + 1) / total
                job.message = f"Getest: {i + 1}/{total} combinaties"

                # Yield na elke 5 combinaties zodat andere coroutines kunnen draaien
                if i % 5 == 0:
                    await asyncio.sleep(0)

            # Filteren en sorteren
            valid = [r for r in results if not r.is_overfitted and r.trade_count >= 10]
            if not valid:
                valid = sorted(results, key=lambda r: r.oos_sharpe, reverse=True)

            valid.sort(key=lambda r: r.oos_sharpe, reverse=True)
            for rank, r in enumerate(valid, 1):
                r.rank = rank

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            best_params = valid[0].params if valid else DEFAULT_CFG.copy()

            summary = self._build_summary(valid, job.request)
            opt_result = OptimizerResult(
                job_id=job.job_id,
                request=job.request,
                best_params=best_params,
                results=valid,
                total_combinations_tested=len(results),
                duration_seconds=duration,
                completed_at=datetime.now(timezone.utc),
                summary=summary,
            )

            job.result = opt_result
            job.status = "completed"
            job.progress = 1.0
            job.message = f"Klaar: {len(valid)} geldige parametersets gevonden"
            job.finished_at = datetime.now(timezone.utc)

            self._save_result(opt_result)
            self._history.append(
                {"job_id": job.job_id, "completed_at": datetime.now(timezone.utc).isoformat(), "summary": summary}
            )

            logger.info(
                "Optimizer job %s klaar: %d resultaten in %.0fs",
                job.job_id,
                len(valid),
                duration,
            )

        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            logger.exception("Optimizer job %s mislukt: %s", job.job_id, exc)

    # ─────────────────────────────────────────────────────────────
    # PARAMETER EVALUATIE
    # ─────────────────────────────────────────────────────────────

    def _build_combinations(self, request: OptimizerRequest) -> list[dict]:
        """Bouw alle parameter combinaties op."""
        import itertools

        grid = request.param_grid
        keys = list(grid.keys())
        values = list(grid.values())

        all_combos = list(itertools.product(*values))

        # Shuffle en beperk tot max_combinations
        rng = np.random.default_rng(42)
        if len(all_combos) > request.max_combinations:
            idx = rng.choice(len(all_combos), request.max_combinations, replace=False)
            all_combos = [all_combos[i] for i in idx]

        return [{**DEFAULT_CFG, **dict(zip(keys, combo))} for combo in all_combos]

    def _evaluate_params(
        self,
        df_feat: pd.DataFrame,
        params: dict,
        starting_capital: float,
        n_splits: int,
        is_pct: float,
    ) -> ParameterSetResult:
        """Evalueer één parameter set via walk-forward testing."""
        n = len(df_feat)
        split_size = n // n_splits

        is_sharpes = []
        oos_sharpes = []
        all_returns = []

        for split in range(n_splits):
            split_start = split * split_size
            split_end = split_start + split_size if split < n_splits - 1 else n
            window = df_feat.iloc[split_start:split_end]

            if len(window) < 100:
                continue

            is_end = int(len(window) * is_pct)
            is_data = window.iloc[:is_end]
            oos_data = window.iloc[is_end:]

            is_returns = self._run_mini_backtest(is_data, params, starting_capital)
            oos_returns = self._run_mini_backtest(oos_data, params, starting_capital)

            if is_returns:
                is_sharpes.append(self._sharpe(is_returns))
            if oos_returns:
                oos_sharpes.append(self._sharpe(oos_returns))
                all_returns.extend(oos_returns)

        avg_is_sharpe = float(np.mean(is_sharpes)) if is_sharpes else 0.0
        avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0

        overfitting_ratio = (avg_is_sharpe / max(avg_oos_sharpe, 0.01)) if avg_oos_sharpe > 0 else 99.0
        is_overfitted = (
            overfitting_ratio > 2.5 or avg_oos_sharpe < 0.5 or (avg_is_sharpe > 1.0 and avg_oos_sharpe < 0.3)
        )
        overfitting_score = min(1.0, max(0.0, (overfitting_ratio - 1.0) / 4.0))

        # Full backtest op volledige dataset voor metrics
        full_returns = self._run_mini_backtest(df_feat, params, starting_capital)
        total_return = sum(full_returns) / starting_capital if full_returns else 0.0
        n_months = max(1, len(df_feat) / (24 * 30))
        monthly_return = (1 + total_return) ** (1 / n_months) - 1 if total_return > -1 else -1.0

        wins = [r for r in full_returns if r > 0]
        losses = [r for r in full_returns if r < 0]
        win_rate = len(wins) / len(full_returns) if full_returns else 0.0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses else 10.0

        # Max drawdown
        equity = [starting_capital]
        for r in full_returns:
            equity.append(equity[-1] + r)
        peak = starting_capital
        max_dd = 0.0
        for e in equity:
            peak = max(peak, e)
            dd = (peak - e) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        return ParameterSetResult(
            params={k: params[k] for k in list(DEFAULT_CFG.keys()) if k in params},
            is_sharpe=avg_is_sharpe,
            oos_sharpe=avg_oos_sharpe,
            total_return=total_return,
            monthly_return=monthly_return,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
            trade_count=len(full_returns),
            is_overfitted=is_overfitted,
            overfitting_score=overfitting_score,
        )

    def _run_mini_backtest(
        self,
        df: pd.DataFrame,
        params: dict,
        capital: float,
    ) -> list[float]:
        """Snelle backtest — retourneert lijst van PnL per trade."""
        returns = []
        if len(df) < 4:
            return returns

        sl_atr_mult = float(params.get("sl_atr", 1.5))
        tp1_r = float(params.get("tp1_r", 1.5))
        tp2_r = float(params.get("tp2_r", 2.5))
        tp1_pct = float(params.get("tp1_pct", 0.30))
        tp2_pct = float(params.get("tp2_pct", 0.30))

        for i in range(4, len(df)):
            window = df.iloc[: i + 1]
            try:
                sig = self._engine.generate_signal(window, cfg=params)
            except Exception:
                continue

            if sig is None:
                continue

            atr = sig.atr if sig.atr > 0 else 1.0
            risk_pct = sig.risk_pct
            risk_usd = capital * risk_pct
            sl_dist = sl_atr_mult * atr

            if sl_dist <= 0:
                continue

            if i + 1 >= len(df):
                break

            next_bar = df.iloc[i + 1]
            hi = float(next_bar["high"])
            lo = float(next_bar["low"])
            tp1_price = sig.take_profit_1
            tp2_price = sig.take_profit_2
            sl_price = sig.stop_loss

            pnl = 0.0
            if sig.direction == "long":
                if lo <= sl_price:
                    pnl = -risk_usd
                elif hi >= tp2_price:
                    pnl = risk_usd * (tp1_r * tp1_pct + tp2_r * tp2_pct + tp2_r * (1 - tp1_pct - tp2_pct))
                elif hi >= tp1_price:
                    pnl = risk_usd * tp1_r * tp1_pct
            else:
                if hi >= sl_price:
                    pnl = -risk_usd
                elif lo <= tp2_price:
                    pnl = risk_usd * (tp1_r * tp1_pct + tp2_r * tp2_pct + tp2_r * (1 - tp1_pct - tp2_pct))
                elif lo <= tp1_price:
                    pnl = risk_usd * tp1_r * tp1_pct

            if pnl != 0.0:
                returns.append(pnl)
                capital += pnl

        return returns

    @staticmethod
    def _sharpe(returns: list[float], risk_free: float = 0.0) -> float:
        if len(returns) < 3:
            return 0.0
        arr = np.array(returns)
        mean = arr.mean()
        std = arr.std()
        if std <= 0:
            return 0.0
        return float((mean - risk_free) / std * math.sqrt(252))

    def _fetch_data(self, start_date: date, end_date: date) -> pd.DataFrame:
        """Haal historische XAUUSD data op via yfinance."""
        try:
            import yfinance as yf

            days = (end_date - start_date).days + 30
            period = f"{days}d"
            df = yf.download("GC=F", period=period, interval="1h", progress=False, auto_adjust=False)
            if df.empty:
                return pd.DataFrame()
            df = df.rename(columns=str.lower)
            if "volume" not in df.columns:
                df["volume"] = 0.0
            df["spread"] = 0.0
            idx = pd.to_datetime(df.index)
            df.index = idx.tz_convert(None) if idx.tz is not None else idx
            df = df[["open", "high", "low", "close", "volume", "spread"]]
            mask = (df.index.date >= start_date) & (df.index.date <= end_date)
            return df[mask].sort_index()
        except Exception as exc:
            logger.warning("Data ophalen mislukt in optimizer: %s", exc)
            return pd.DataFrame()

    def _build_summary(self, results: list[ParameterSetResult], request: OptimizerRequest) -> dict:
        if not results:
            return {"best_oos_sharpe": 0.0, "avg_oos_sharpe": 0.0, "tested": 0}

        best = results[0]
        return {
            "best_oos_sharpe": round(best.oos_sharpe, 3),
            "best_monthly_return_pct": round(best.monthly_return * 100, 2),
            "best_win_rate": round(best.win_rate, 4),
            "best_max_drawdown_pct": round(best.max_drawdown * 100, 2),
            "avg_oos_sharpe": round(float(np.mean([r.oos_sharpe for r in results])), 3),
            "tested_combinations": len(results),
            "valid_non_overfitted": sum(1 for r in results if not r.is_overfitted),
            "period": f"{request.start_date} → {request.end_date}",
        }

    def _save_result(self, result: OptimizerResult) -> None:
        try:
            import json

            path = RESULTS_DIR / f"optimizer_{result.job_id}.json"
            path.write_text(
                json.dumps(result.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Optimizer resultaat opslaan mislukt: %s", exc)

    def _load_history(self) -> None:
        try:
            import json

            for path in sorted(RESULTS_DIR.glob("optimizer_*.json"))[-20:]:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self._history.append(
                        {
                            "job_id": data.get("job_id"),
                            "completed_at": data.get("completed_at"),
                            "summary": data.get("summary", {}),
                        }
                    )
                except Exception:
                    continue
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────

_optimizer_service: OptimizerService | None = None


def get_optimizer_service() -> OptimizerService:
    global _optimizer_service
    if _optimizer_service is None:
        _optimizer_service = OptimizerService()
    return _optimizer_service
