from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .models import AnalyticsReport


def compute_report(history: pd.DataFrame, ml_history: pd.DataFrame | None = None) -> AnalyticsReport:
    """Compute full analytics report from a trade history DataFrame."""
    closed = history[history["status"] == "closed"].copy() if not history.empty else pd.DataFrame()
    total = len(history)
    n_closed = len(closed)

    if closed.empty:
        return AnalyticsReport(
            generated_at=datetime.now(timezone.utc),
            total_trades=total,
            closed_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_rr=0.0,
            total_pnl=0.0,
            max_drawdown=0.0,
            monthly=[],
            by_regime=[],
            by_session=[],
            by_side=[],
        )

    pnl = closed["pnl"].fillna(0.0)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    win_rate = float((pnl > 0).mean())
    profit_factor = float(wins.sum() / losses.abs().sum()) if not losses.empty else float("inf")
    avg_rr = float(closed["reward_risk_ratio"].dropna().mean()) if "reward_risk_ratio" in closed.columns else 0.0
    total_pnl = float(pnl.sum())

    # Max drawdown
    equity = pnl.cumsum()
    peak = equity.cummax()
    drawdown = peak - equity
    max_dd = float(drawdown.max())

    # Monthly breakdown
    closed["_month"] = pd.to_datetime(closed["opened_at"]).dt.to_period("M").astype(str)
    monthly = (
        closed.groupby("_month")
        .apply(_group_stats, include_groups=False)
        .reset_index()
        .rename(columns={"_month": "month"})
        .to_dict(orient="records")
    )

    # By regime
    by_regime: list[dict] = []
    if "market_regime" in closed.columns:
        by_regime = (
            closed.groupby("market_regime")
            .apply(_group_stats, include_groups=False)
            .reset_index()
            .rename(columns={"market_regime": "regime"})
            .to_dict(orient="records")
        )

    # By session hour
    closed["_hour"] = pd.to_datetime(closed["opened_at"]).dt.hour
    by_session = (
        closed.groupby("_hour")
        .apply(_group_stats, include_groups=False)
        .reset_index()
        .rename(columns={"_hour": "hour"})
        .to_dict(orient="records")
    )

    # By side
    by_side: list[dict] = []
    if "side" in closed.columns:
        by_side = (
            closed.groupby("side")
            .apply(_group_stats, include_groups=False)
            .reset_index()
            .to_dict(orient="records")
        )

    # ML snapshots
    ml_records: list[dict] = []
    if ml_history is not None and not ml_history.empty:
        for _, row in ml_history.iterrows():
            ml_records.append({
                "trained_at": str(row.get("trained_at", "")),
                "accuracy": round(float(row.get("accuracy", 0)), 4),
                "precision": round(float(row.get("precision", 0)), 4),
                "recall": round(float(row.get("recall", 0)), 4),
                "f1_score": round(float(row.get("f1_score", 0)), 4),
                "sample_count": int(row.get("sample_count", 0)),
            })

    return AnalyticsReport(
        generated_at=datetime.now(timezone.utc),
        total_trades=total,
        closed_trades=n_closed,
        win_rate=win_rate,
        profit_factor=profit_factor if np.isfinite(profit_factor) else 99.0,
        avg_rr=avg_rr,
        total_pnl=total_pnl,
        max_drawdown=max_dd,
        monthly=monthly,
        by_regime=by_regime,
        by_session=by_session,
        by_side=by_side,
        ml_snapshots=ml_records,
    )


def _group_stats(group: pd.DataFrame) -> pd.Series:
    pnl = group["pnl"].fillna(0.0)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = float(wins.sum() / losses.abs().sum()) if not losses.empty and losses.abs().sum() > 0 else 99.0
    return pd.Series({
        "trades": int(len(group)),
        "win_rate": round(float((pnl > 0).mean()), 4),
        "pnl": round(float(pnl.sum()), 2),
        "avg_pnl": round(float(pnl.mean()), 2),
        "profit_factor": round(min(pf, 99.0), 4),
    })
