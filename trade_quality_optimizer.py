from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATA_PATH = Path("exports/latest/data/trade_quality.csv")
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

START_CAPITAL = 160_000.0
MAX_DAILY_LOSS = 2_000.0
MAX_WEEKLY_LOSS = 4_000.0
DAILY_PROFIT_LOCK = 1_200.0
WEEKLY_PROFIT_LOCK = 4_200.0
MONTHLY_PROFIT_LOCK = 16_000.0
MAX_TRADES_PER_DAY = 5
MAX_CONSECUTIVE_LOSSES = 2


SESSION_PRESETS: dict[str, set[str]] = {
    "ldn_only": {"London"},
    "ldn_overlap": {"London", "London/NY overlap"},
    "ldn_overlap_ny": {"London", "London/NY overlap", "New York"},
}

REGIME_PRESETS: dict[str, dict[str, float]] = {
    "exp_only": {"EXPANSION": 1.25, "RANGE": 0.0, "CHOP": 0.0, "HIGH_RISK": 0.0, "TREND": 0.0, "NO_TRADE": 0.0},
    "exp_range": {"EXPANSION": 1.20, "RANGE": 0.80, "CHOP": 0.0, "HIGH_RISK": 0.0, "TREND": 0.0, "NO_TRADE": 0.0},
    "ldn_selective": {"EXPANSION": 1.25, "RANGE": 0.70, "CHOP": 0.35, "HIGH_RISK": 0.0, "TREND": 0.0, "NO_TRADE": 0.0},
    "balanced": {"EXPANSION": 1.10, "RANGE": 0.85, "CHOP": 0.25, "HIGH_RISK": 0.0, "TREND": 0.0, "NO_TRADE": 0.0},
}

QUALITY_PRESETS: dict[str, dict[str, float]] = {
    "bc_focus": {"A": 0.5, "B": 1.25, "C": 1.20, "D": 0.50, "F": 0.0},
    "bcd_focus": {"A": 0.3, "B": 1.20, "C": 1.10, "D": 0.75, "F": 0.15},
    "quality40": {"A": 1.0, "B": 1.10, "C": 1.05, "D": 0.0, "F": 0.0},
    "broad": {"A": 0.6, "B": 1.10, "C": 1.05, "D": 0.60, "F": 0.20},
}

LOSS_SCALE_PRESETS: dict[str, dict[int, float]] = {
    "strict": {0: 1.0, 1: 0.50, 2: 0.0, 3: 0.0},
    "normal": {0: 1.0, 1: 0.70, 2: 0.0, 3: 0.0},
    "loose": {0: 1.0, 1: 0.85, 2: 0.0, 3: 0.0},
}


@dataclass(frozen=True)
class Profile:
    name: str
    quality_floor: float
    suppression_ceiling: float
    spread_ceiling: float
    min_regime_score: float
    base_scale: float
    session_preset: str
    regime_preset: str
    quality_preset: str
    loss_scale_preset: str
    allow_recovery: bool = False


def load_trade_quality(path: Path = DATA_PATH) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["entry_time", "exit_time"])
    frame = frame.sort_values("entry_time").reset_index(drop=True)
    frame["day"] = frame["entry_time"].dt.date.astype(str)
    frame["week"] = frame["entry_time"].dt.strftime("%G-W%V")
    frame["month_key"] = frame["entry_time"].dt.to_period("M").astype(str)
    frame["spread_percentile"] = pd.to_numeric(frame["spread_percentile"], errors="coerce").fillna(1.0)
    frame["trade_quality_score"] = pd.to_numeric(frame["trade_quality_score"], errors="coerce").fillna(0.0)
    frame["suppression_score"] = pd.to_numeric(frame["suppression_score"], errors="coerce").fillna(100.0)
    frame["regime_score"] = pd.to_numeric(frame["regime_score"], errors="coerce").fillna(0.0)
    frame["consecutive_losses_prior"] = pd.to_numeric(frame["consecutive_losses_prior"], errors="coerce").fillna(0).astype(int)
    frame["news_window"] = frame["news_window"].fillna(False).astype(bool)
    return frame


def generate_profiles() -> list[Profile]:
    profiles: list[Profile] = []
    for quality_floor, suppression_ceiling, spread_ceiling, min_regime_score, base_scale, session_preset, regime_preset, quality_preset, loss_preset in product(
        [10.0, 20.0, 30.0, 40.0],
        [35.0, 45.0, 55.0, 70.0],
        [0.65, 0.75, 0.85, 0.95],
        [30.0, 35.0, 40.0],
        [0.80, 1.00, 1.20],
        SESSION_PRESETS.keys(),
        REGIME_PRESETS.keys(),
        QUALITY_PRESETS.keys(),
        LOSS_SCALE_PRESETS.keys(),
    ):
        name = "|".join(
            [
                f"q{int(quality_floor)}",
                f"s{int(suppression_ceiling)}",
                f"sp{int(spread_ceiling * 100)}",
                f"rg{int(min_regime_score)}",
                f"b{int(base_scale * 100)}",
                session_preset,
                regime_preset,
                quality_preset,
                loss_preset,
            ]
        )
        profiles.append(
            Profile(
                name=name,
                quality_floor=quality_floor,
                suppression_ceiling=suppression_ceiling,
                spread_ceiling=spread_ceiling,
                min_regime_score=min_regime_score,
                base_scale=base_scale,
                session_preset=session_preset,
                regime_preset=regime_preset,
                quality_preset=quality_preset,
                loss_scale_preset=loss_preset,
            )
        )
    return profiles


def should_take_trade(row: pd.Series, profile: Profile) -> bool:
    if bool(row["news_window"]):
        return False
    if not profile.allow_recovery and str(row["risk_mode_live"]) == "RECOVERY":
        return False
    if str(row["session_label"]) not in SESSION_PRESETS[profile.session_preset]:
        return False
    if float(row["trade_quality_score"]) < profile.quality_floor:
        return False
    if float(row["suppression_score"]) > profile.suppression_ceiling:
        return False
    if float(row["spread_percentile"]) > profile.spread_ceiling:
        return False
    if float(row["regime_score"]) < profile.min_regime_score:
        return False
    return True


def trade_multiplier(row: pd.Series, profile: Profile) -> float:
    regime_weight = REGIME_PRESETS[profile.regime_preset].get(str(row["regime_label"]), 0.0)
    quality_weight = QUALITY_PRESETS[profile.quality_preset].get(str(row["quality_bucket"]), 0.0)
    loss_weight = LOSS_SCALE_PRESETS[profile.loss_scale_preset].get(int(row["consecutive_losses_prior"]), 0.0)
    return float(profile.base_scale * regime_weight * quality_weight * loss_weight)


def simulate_profile(frame: pd.DataFrame, profile: Profile) -> dict[str, Any]:
    capital = START_CAPITAL
    equity_curve: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []

    day_pnl = 0.0
    week_pnl = 0.0
    month_pnl = 0.0
    trades_today = 0
    consecutive_losses = 0
    current_day = None
    current_week = None
    current_month = None

    for _, row in frame.iterrows():
        day_key = str(row["day"])
        week_key = str(row["week"])
        month_key = str(row["month_key"])

        if day_key != current_day:
            current_day = day_key
            day_pnl = 0.0
            trades_today = 0
        if week_key != current_week:
            current_week = week_key
            week_pnl = 0.0
        if month_key != current_month:
            current_month = month_key
            month_pnl = 0.0

        if trades_today >= MAX_TRADES_PER_DAY:
            continue
        if day_pnl <= -MAX_DAILY_LOSS or week_pnl <= -MAX_WEEKLY_LOSS:
            continue
        if day_pnl >= DAILY_PROFIT_LOCK or week_pnl >= WEEKLY_PROFIT_LOCK or month_pnl >= MONTHLY_PROFIT_LOCK:
            continue
        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            continue

        if not should_take_trade(row, profile):
            continue

        multiplier = trade_multiplier(row, profile)
        if multiplier <= 0.0:
            continue

        scaled_pnl = float(row["pnl"]) * multiplier
        capital += scaled_pnl
        day_pnl += scaled_pnl
        week_pnl += scaled_pnl
        month_pnl += scaled_pnl
        trades_today += 1
        consecutive_losses = consecutive_losses + 1 if scaled_pnl <= 0 else 0

        executed.append(
            {
                "entry_time": pd.Timestamp(row["entry_time"]),
                "month": month_key,
                "day": day_key,
                "session": str(row["session_label"]),
                "regime": str(row["regime_label"]),
                "quality_bucket": str(row["quality_bucket"]),
                "base_pnl": float(row["pnl"]),
                "scaled_pnl": scaled_pnl,
                "multiplier": multiplier,
                "capital": capital,
            }
        )
        equity_curve.append({"timestamp": pd.Timestamp(row["entry_time"]), "capital": capital})

    executed_df = pd.DataFrame(executed)
    equity_df = pd.DataFrame(equity_curve)
    return summarize_profile(executed_df, equity_df, profile)


def summarize_profile(executed_df: pd.DataFrame, equity_df: pd.DataFrame, profile: Profile) -> dict[str, Any]:
    if executed_df.empty:
        return {
            "profile": asdict(profile),
            "summary": {
                "total_pnl": 0.0,
                "avg_monthly_pnl": 0.0,
                "min_monthly_pnl": 0.0,
                "max_monthly_pnl": 0.0,
                "profit_factor": 0.0,
                "win_rate": 0.0,
                "max_drawdown_pct": 0.0,
                "max_daily_loss": 0.0,
                "max_weekly_loss": 0.0,
                "total_trades": 0,
                "target_months_hit": 0,
            },
            "monthly": [],
        }

    pnl = executed_df["scaled_pnl"].astype(float)
    monthly = executed_df.groupby("month")["scaled_pnl"].sum().round(2)
    daily = executed_df.groupby("day")["scaled_pnl"].sum()
    weekly = executed_df.groupby(executed_df["entry_time"].dt.strftime("%G-W%V"))["scaled_pnl"].sum()
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = float(wins.sum() / abs(losses.sum())) if not losses.empty else 99.0
    win_rate = float((pnl > 0).mean() * 100.0)

    capital = equity_df["capital"].astype(float)
    running_peak = capital.cummax()
    dd_pct = np.where(running_peak > 0, (running_peak - capital) / running_peak * 100.0, 0.0)
    max_dd_pct = float(np.max(dd_pct)) if len(dd_pct) else 0.0

    monthly_records = [{"month": month, "pnl": float(value)} for month, value in monthly.items()]
    summary = {
        "total_pnl": round(float(pnl.sum()), 2),
        "avg_monthly_pnl": round(float(monthly.mean()), 2),
        "min_monthly_pnl": round(float(monthly.min()), 2),
        "max_monthly_pnl": round(float(monthly.max()), 2),
        "profit_factor": round(min(pf, 99.0), 4),
        "win_rate": round(win_rate, 4),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "max_daily_loss": round(float(abs(daily.min())) if not daily.empty else 0.0, 2),
        "max_weekly_loss": round(float(abs(weekly.min())) if not weekly.empty else 0.0, 2),
        "total_trades": int(len(executed_df)),
        "target_months_hit": int(((monthly >= 8_000.0) & (monthly <= 12_000.0)).sum()),
    }
    return {
        "profile": asdict(profile),
        "summary": summary,
        "monthly": monthly_records,
    }


def score_result(result: dict[str, Any]) -> float:
    summary = result["summary"]
    monthly = pd.Series({item["month"]: item["pnl"] for item in result["monthly"]}, dtype=float)
    if monthly.empty:
        return -10_000.0

    target_center = 10_000.0
    distance_penalty = float(np.abs(monthly - target_center).sum()) / 400.0
    below_floor_penalty = float(np.maximum(8_000.0 - monthly, 0.0).sum()) / 120.0
    above_ceiling_penalty = float(np.maximum(monthly - 12_000.0, 0.0).sum()) / 200.0

    score = 0.0
    score += summary["target_months_hit"] * 80.0
    score += min(summary["profit_factor"], 4.0) * 20.0
    score += min(summary["win_rate"], 70.0) * 0.5
    score += min(summary["avg_monthly_pnl"], 12_000.0) / 250.0
    score -= distance_penalty
    score -= below_floor_penalty
    score -= above_ceiling_penalty
    score -= max(summary["max_drawdown_pct"] - 6.0, 0.0) * 25.0
    score -= max(summary["max_daily_loss"] - MAX_DAILY_LOSS, 0.0) / 25.0
    score -= max(summary["max_weekly_loss"] - MAX_WEEKLY_LOSS, 0.0) / 50.0
    score -= max(10 - summary["total_trades"], 0) * 4.0
    return round(float(score), 4)


def optimize(frame: pd.DataFrame) -> dict[str, Any]:
    best_result: dict[str, Any] | None = None
    leaderboard: list[dict[str, Any]] = []
    for profile in generate_profiles():
        result = simulate_profile(frame, profile)
        score = score_result(result)
        leaderboard.append(
            {
                "name": profile.name,
                "score": score,
                **result["summary"],
            }
        )
        if best_result is None or score > best_result["score"]:
            best_result = {
                "score": score,
                **result,
            }

    if best_result is None:
        raise ValueError("No optimization results generated.")

    leaderboard = sorted(leaderboard, key=lambda item: item["score"], reverse=True)
    return {"best": best_result, "leaderboard": leaderboard[:20]}


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def main() -> None:
    frame = load_trade_quality()
    result = optimize(frame)
    leaderboard_path = RESULTS_DIR / "trade_quality_optimizer_leaderboard.json"
    best_path = RESULTS_DIR / "trade_quality_optimizer_best.json"
    save_json(leaderboard_path, result["leaderboard"])
    save_json(best_path, result["best"])

    leaderboard = pd.DataFrame(result["leaderboard"])
    print("\nTrade Quality Optimizer Leaderboard")
    print(
        leaderboard[
            [
                "name",
                "score",
                "avg_monthly_pnl",
                "min_monthly_pnl",
                "max_monthly_pnl",
                "profit_factor",
                "max_drawdown_pct",
                "max_daily_loss",
                "max_weekly_loss",
                "total_trades",
                "target_months_hit",
            ]
        ].head(10).to_string(index=False)
    )
    print(f"\nSaved leaderboard to {leaderboard_path}")
    print(f"Saved best profile to {best_path}")


if __name__ == "__main__":
    main()
