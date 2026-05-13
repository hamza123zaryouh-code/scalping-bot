"""Local backtest service powered by the latest exported XAUUSD dataset."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from backend.api.schemas.backtest import BacktestMetrics, BacktestRequest, BacktestResult, TradeRecord
from backend.api.schemas.common import TaskStatus

EXPORT_ROOT = Path("exports/latest/data")


@dataclass
class StoredBacktest:
    result: BacktestResult
    status: TaskStatus


class BacktestService:
    def __init__(self) -> None:
        self._tasks: dict[str, StoredBacktest] = {}

    def run(self, req: BacktestRequest) -> BacktestResult:
        trades_df = self._load_trades()
        equity_df = self._load_equity()

        filtered_trades = self._filter_trades(trades_df, req.start_date.isoformat(), req.end_date.isoformat())
        filtered_equity = self._filter_equity(equity_df, req.start_date.isoformat(), req.end_date.isoformat())

        if filtered_trades.empty:
            raise ValueError("No backtest trades available for the requested date range.")

        baseline_start = float(equity_df["capital"].iloc[0]) if not equity_df.empty else 160000.0
        capital_scale = req.starting_capital / baseline_start if baseline_start > 0 else 1.0

        scaled_trades = filtered_trades.copy()
        scaled_trades["pnl"] = scaled_trades["pnl"].astype(float) * capital_scale
        scaled_trades["cumulative_equity"] = req.starting_capital + scaled_trades["pnl"].cumsum()

        scaled_equity = self._scale_equity(filtered_equity, req.starting_capital, baseline_start)
        metrics = self._build_metrics(scaled_trades, scaled_equity, req)
        monthly_summary = self._build_monthly_summary(scaled_trades)

        task_id = uuid4().hex
        result = BacktestResult(
            task_id=task_id,
            metrics=metrics,
            trades=[
                TradeRecord(
                    side=str(row["side"]),
                    entry_time=pd.Timestamp(row["entry_time"]).isoformat(),
                    exit_time=pd.Timestamp(row["exit_time"]).isoformat(),
                    entry_price=float(row["entry_price"]),
                    exit_price=float(row["exit_price"]),
                    stop_loss=float(row["stop_loss"]),
                    take_profit=float(row["take_profit"]),
                    size=float(row["size"]),
                    pnl=round(float(row["pnl"]), 2),
                    cumulative_equity=round(float(row["cumulative_equity"]), 2),
                )
                for _, row in scaled_trades.iterrows()
            ],
            equity_curve=scaled_equity.to_dict(orient="records"),
            monthly_summary=monthly_summary,
            chart_path=str((EXPORT_ROOT.parent / "images" / "ftmo_dashboard_v3.png").as_posix()),
        )

        self._tasks[task_id] = StoredBacktest(
            result=result,
            status=TaskStatus(
                task_id=task_id,
                status="completed",
                progress=1.0,
                result={"total_trades": metrics.total_trades, "total_return_pct": metrics.total_return_pct},
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
            ),
        )
        return result

    def status(self, task_id: str) -> TaskStatus | None:
        stored = self._tasks.get(task_id)
        return stored.status if stored else None

    def result(self, task_id: str) -> BacktestResult | None:
        stored = self._tasks.get(task_id)
        return stored.result if stored else None

    def _load_trades(self) -> pd.DataFrame:
        path = EXPORT_ROOT / "trades.csv"
        if not path.exists():
            raise FileNotFoundError(f"Backtest dataset missing: {path}")
        trades = pd.read_csv(path, parse_dates=["entry_time", "exit_time", "entry_date"])
        return trades.sort_values("entry_time").reset_index(drop=True)

    def _load_equity(self) -> pd.DataFrame:
        path = EXPORT_ROOT / "equity.csv"
        if not path.exists():
            raise FileNotFoundError(f"Backtest dataset missing: {path}")
        equity = pd.read_csv(path, parse_dates=["timestamp"])
        return equity.sort_values("timestamp").reset_index(drop=True)

    def _filter_trades(self, trades: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        mask = trades["entry_time"].between(start, end)
        return trades.loc[mask].copy().reset_index(drop=True)

    def _filter_equity(self, equity: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        mask = equity["timestamp"].between(start, end)
        filtered = equity.loc[mask].copy().reset_index(drop=True)
        if filtered.empty:
            return equity.head(1).copy()
        return filtered

    def _scale_equity(self, equity: pd.DataFrame, starting_capital: float, baseline_start: float) -> pd.DataFrame:
        capital_scale = starting_capital / baseline_start if baseline_start > 0 else 1.0
        base = equity.copy()
        for column in ("capital", "equity", "daily_floor", "ftmo_overall_floor", "daily_buffer", "overall_buffer", "daily_realized_pnl", "weekly_realized_pnl", "monthly_realized_pnl"):
            if column in base.columns:
                base[column] = (base[column].astype(float) - baseline_start) * capital_scale + starting_capital

        if "daily_floor" in base.columns:
            base["daily_floor"] = (equity["daily_floor"].astype(float) - baseline_start) * capital_scale + starting_capital
        if "ftmo_overall_floor" in base.columns:
            base["ftmo_overall_floor"] = (equity["ftmo_overall_floor"].astype(float) - baseline_start) * capital_scale + starting_capital
        if "daily_buffer" in base.columns:
            base["daily_buffer"] = equity["daily_buffer"].astype(float) * capital_scale
        if "overall_buffer" in base.columns:
            base["overall_buffer"] = equity["overall_buffer"].astype(float) * capital_scale
        if "daily_realized_pnl" in base.columns:
            base["daily_realized_pnl"] = equity["daily_realized_pnl"].astype(float) * capital_scale
        if "weekly_realized_pnl" in base.columns:
            base["weekly_realized_pnl"] = equity["weekly_realized_pnl"].astype(float) * capital_scale
        if "monthly_realized_pnl" in base.columns:
            base["monthly_realized_pnl"] = equity["monthly_realized_pnl"].astype(float) * capital_scale

        base["timestamp"] = pd.to_datetime(base["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
        return base

    def _build_metrics(self, trades: pd.DataFrame, equity: pd.DataFrame, req: BacktestRequest) -> BacktestMetrics:
        pnl = trades["pnl"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        final_equity = float(trades["cumulative_equity"].iloc[-1]) if not trades.empty else req.starting_capital
        total_return_pct = ((final_equity / req.starting_capital) - 1.0) * 100 if req.starting_capital > 0 else 0.0

        equity_curve = trades["cumulative_equity"].astype(float)
        running_peak = equity_curve.cummax()
        drawdown_pct = np.where(running_peak > 0, (running_peak - equity_curve) / running_peak * 100, 0.0)
        max_drawdown_pct = float(np.max(drawdown_pct)) if len(drawdown_pct) else 0.0

        trade_returns = pnl / req.starting_capital if req.starting_capital > 0 else pnl * 0
        sharpe_ratio = 0.0
        if len(trade_returns) > 1 and float(trade_returns.std(ddof=0)) > 0:
            sharpe_ratio = float(trade_returns.mean() / trade_returns.std(ddof=0) * np.sqrt(len(trade_returns)))

        profit_factor = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
        avg_win = float(wins.mean()) if not wins.empty else 0.0
        avg_loss = float(losses.mean()) if not losses.empty else 0.0
        expectancy = float(pnl.mean()) if not pnl.empty else 0.0
        calmar_ratio = float(total_return_pct / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0
        challenge_days = int(trades["entry_time"].dt.normalize().nunique())

        ftmo_passed = True
        if "ftmo_status" in equity.columns:
            ftmo_passed = not equity["ftmo_status"].astype(str).str.upper().eq("FAIL").any()
        elif "daily_buffer" in equity.columns and "overall_buffer" in equity.columns:
            ftmo_passed = bool((equity["daily_buffer"].astype(float) >= 0).all() and (equity["overall_buffer"].astype(float) >= 0).all())

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
        if trades.empty:
            return []
        monthly = trades.copy()
        monthly["month"] = monthly["entry_time"].dt.to_period("M").astype(str)
        grouped = (
            monthly.groupby("month")
            .agg(
                trades=("pnl", "size"),
                pnl=("pnl", "sum"),
                win_rate=("pnl", lambda series: float((series > 0).mean()) if len(series) else 0.0),
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
