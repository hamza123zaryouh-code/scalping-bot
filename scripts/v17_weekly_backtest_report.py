from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EXPORTS_DIR = ROOT / "exports" / "history"
REPORTS_DIR = ROOT / "reports"


def find_latest_export() -> Path:
    candidates = sorted(p for p in EXPORTS_DIR.iterdir() if p.is_dir())
    if not candidates:
        raise FileNotFoundError(f"Geen exportmappen gevonden in {EXPORTS_DIR}")
    return candidates[-1]


def read_trades(data_dir: Path) -> pd.DataFrame:
    trades_path = data_dir / "trades.csv"
    trades = pd.read_csv(trades_path, parse_dates=["entry_time", "exit_time"])
    if trades.empty:
        raise ValueError(f"Geen trades gevonden in {trades_path}")
    trades["week"] = trades["entry_time"].dt.strftime("%G-W%V")
    trades["week_start"] = (
        trades["entry_time"].dt.normalize() - pd.to_timedelta(trades["entry_time"].dt.weekday, unit="D")
    )
    return trades


def read_equity(data_dir: Path) -> pd.DataFrame:
    equity_path = data_dir / "equity.csv"
    equity = pd.read_csv(equity_path, parse_dates=["timestamp"])
    if equity.empty:
        raise ValueError(f"Geen equity-curve gevonden in {equity_path}")
    equity["week"] = equity["timestamp"].dt.strftime("%G-W%V")
    equity["week_start"] = (
        equity["timestamp"].dt.normalize() - pd.to_timedelta(equity["timestamp"].dt.weekday, unit="D")
    )
    return equity


def build_trade_summary(trades: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        trades.groupby(["week", "week_start"], as_index=False)
        .agg(
            trades=("pnl", "size"),
            weekly_pnl=("pnl", "sum"),
            gross_profit=("pnl", lambda s: float(s[s > 0].sum())),
            gross_loss=("pnl", lambda s: float(abs(s[s < 0].sum()))),
            worst_trade=("pnl", "min"),
            best_trade=("pnl", "max"),
            win_rate=("pnl", lambda s: float((s > 0).mean()) if len(s) else 0.0),
        )
        .sort_values("week_start")
    )
    grouped["profit_factor"] = grouped.apply(
        lambda row: (row["gross_profit"] / row["gross_loss"]) if row["gross_loss"] > 0 else float("inf"),
        axis=1,
    )
    return grouped


def build_drawdown_summary(equity: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (week, week_start), chunk in equity.groupby(["week", "week_start"]):
        chunk = chunk.sort_values("timestamp").copy()
        start_equity = float(chunk["equity"].iloc[0])
        running_peak = pd.concat(
            [pd.Series([start_equity], dtype=float), chunk["equity"].astype(float)],
            ignore_index=True,
        ).cummax()
        equity_values = pd.concat(
            [pd.Series([start_equity], dtype=float), chunk["equity"].astype(float)],
            ignore_index=True,
        )
        drawdown_eur = running_peak - equity_values
        drawdown_pct = drawdown_eur / running_peak.where(running_peak > 0, other=1.0) * 100.0
        rows.append(
            {
                "week": week,
                "week_start": week_start,
                "start_equity": start_equity,
                "end_equity": float(chunk["equity"].iloc[-1]),
                "max_drawdown_eur": float(drawdown_eur.max()),
                "max_drawdown_pct": float(drawdown_pct.max()),
            }
        )
    return pd.DataFrame(rows).sort_values("week_start")


def build_weekly_report(trades: pd.DataFrame, equity: pd.DataFrame) -> pd.DataFrame:
    trade_summary = build_trade_summary(trades)
    drawdown_summary = build_drawdown_summary(equity)
    report = trade_summary.merge(drawdown_summary, on=["week", "week_start"], how="left")
    report["weekly_return_pct"] = (
        (report["end_equity"] - report["start_equity"]) / report["start_equity"].where(report["start_equity"] > 0, 1.0)
    ) * 100.0

    ordered_cols = [
        "week",
        "week_start",
        "trades",
        "weekly_pnl",
        "weekly_return_pct",
        "win_rate",
        "profit_factor",
        "gross_loss",
        "worst_trade",
        "best_trade",
        "max_drawdown_eur",
        "max_drawdown_pct",
        "start_equity",
        "end_equity",
    ]
    report = report[ordered_cols].sort_values("week_start").reset_index(drop=True)
    return report.round(
        {
            "weekly_pnl": 2,
            "weekly_return_pct": 2,
            "win_rate": 4,
            "profit_factor": 2,
            "gross_loss": 2,
            "worst_trade": 2,
            "best_trade": 2,
            "max_drawdown_eur": 2,
            "max_drawdown_pct": 2,
            "start_equity": 2,
            "end_equity": 2,
        }
    )


def format_console_table(report: pd.DataFrame) -> str:
    view = report.copy()
    view["week_start"] = view["week_start"].dt.strftime("%Y-%m-%d")
    view["win_rate"] = (view["win_rate"] * 100).map(lambda value: f"{value:.1f}%")
    return view.to_string(index=False)


def save_report(report: pd.DataFrame) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS_DIR / f"v17_weekly_backtest_{timestamp}.csv"
    report.to_csv(out_path, index=False)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Maak een weekrapport van de nieuwste lokale V17 backtest-export."
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Pad naar de exportmap, bijvoorbeeld exports/history/2026-05-11_12-42-47",
    )
    args = parser.parse_args()

    export_dir = args.export_dir.resolve() if args.export_dir else find_latest_export()
    data_dir = export_dir / "data"

    trades = read_trades(data_dir)
    equity = read_equity(data_dir)
    report = build_weekly_report(trades, equity)
    out_path = save_report(report)

    print(f"Bron export : {export_dir}")
    print(f"Periode     : {trades['entry_time'].min():%Y-%m-%d} t/m {trades['entry_time'].max():%Y-%m-%d}")
    print(f"CSV rapport : {out_path}")
    print()
    print(format_console_table(report))
    print()
    print(f"Slechtste week op PnL : {report.loc[report['weekly_pnl'].idxmin(), 'week']}")
    print(f"Grootste week-drawdown: {report.loc[report['max_drawdown_eur'].idxmax(), 'week']}")


if __name__ == "__main__":
    main()
