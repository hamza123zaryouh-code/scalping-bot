"""Telegram control service backed by FastAPI endpoints and shared runtime state."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings
from backend.api.schemas.backtest import BacktestRequest
from backend.services.backtest_service import BacktestService
from backend.services.risk_service import RiskService
from backend.services.signal_service import SignalService
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

STATE_PATH = Path("live_logs/bot_state.json")
MEMORY_DIR = Path("memory")
REPORTS_DIR = Path("reports")

FTMO_MONTHLY_TARGET = 8_000.0
_DANGEROUS_ACTIONS = {"emergency_stop", "close_all_positions"}
_BACKTEST_SERVICE = BacktestService()


class TelegramService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._memory = MemoryLayer(load_settings().database_url)
        self._risk = RiskService()
        self._signals = SignalService()
        self._backtests = _BACKTEST_SERVICE

    def get_status_overview(self) -> dict[str, Any]:
        state = self._load_state()
        control = self._memory.get_bot_control_state()
        history = self._trade_history(limit=5000)
        account = state.get("balance", self._settings.starting_capital)
        equity = state.get("equity", account)
        positions = state.get("open_positions", [])
        floating_pnl = round(sum(float(p.get("profit", 0.0)) for p in positions), 2)
        daily_pnl = self._period_pnl(history, "D")
        weekly_pnl = self._period_pnl(history, "W")
        monthly_pnl = self._period_pnl(history, "M")
        drawdown = max(self._settings.starting_capital - float(equity), 0.0)
        drawdown_pct = (drawdown / self._settings.starting_capital * 100) if self._settings.starting_capital else 0.0
        ftmo = self._ftmo_snapshot(state)

        summary = "\n".join(
            [
                "STATUS",
                f"Account status: {'RUNNING' if control.get('bot_active', True) else 'STOPPED'}",
                f"Equity: {self._money(equity)}",
                f"Balance: {self._money(account)}",
                f"Open PnL: {self._money(floating_pnl)}",
                f"Daily PnL: {self._money(daily_pnl)}",
                f"Weekly PnL: {self._money(weekly_pnl)}",
                f"Monthly PnL: {self._money(monthly_pnl)}",
                f"Drawdown: {self._money(drawdown)} ({drawdown_pct:.2f}%)",
                f"FTMO status: {ftmo['status']}",
            ]
        )
        return {
            "summary": summary,
            "account_status": "running" if control.get("bot_active", True) else "stopped",
            "equity": round(float(equity), 2),
            "balance": round(float(account), 2),
            "open_pnl": floating_pnl,
            "daily_pnl": round(daily_pnl, 2),
            "weekly_pnl": round(weekly_pnl, 2),
            "monthly_pnl": round(monthly_pnl, 2),
            "drawdown": round(drawdown, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "ftmo_status": ftmo,
            "control_state": control,
        }

    def handle_control_action(
        self,
        action: str,
        telegram_user_id: str,
        telegram_username: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if action in _DANGEROUS_ACTIONS and not confirmed:
            self._log_action(
                telegram_user_id,
                telegram_username,
                action,
                "confirmation_required",
                {"confirmed": False},
            )
            return {
                "action": action,
                "status": "confirmation_required",
                "summary": "Bevestiging vereist voor deze actie.",
                "requires_confirmation": True,
                "command_id": None,
                "data": {},
            }

        control_updates: dict[str, Any] = {}
        if action == "start_bot":
            control_updates = {"bot_active": True, "trading_paused": False, "emergency_stop": False}
        elif action == "stop_bot":
            control_updates = {"bot_active": False}
        elif action == "pause_trading":
            control_updates = {"trading_paused": True}
        elif action == "resume_trading":
            control_updates = {"bot_active": True, "trading_paused": False, "emergency_stop": False}
        elif action == "emergency_stop":
            control_updates = {"bot_active": False, "trading_paused": True, "emergency_stop": True}
        elif action == "train_ai":
            control_updates = {}
        elif action == "close_all_positions":
            control_updates = {}
        else:
            raise ValueError(f"Unsupported control action: {action}")

        if control_updates:
            self._memory.set_bot_control_state(**control_updates)

        command = self._memory.enqueue_control_command(
            command=action,
            requested_by=telegram_user_id,
            payload={
                "telegram_username": telegram_username,
                "confirmed": confirmed,
                "control_updates": control_updates,
            },
            source="telegram",
        )
        summary = self._control_summary(action, command["id"])
        self._log_action(
            telegram_user_id,
            telegram_username,
            action,
            "accepted",
            {"command_id": command["id"], "confirmed": confirmed},
        )
        return {
            "action": action,
            "status": "accepted",
            "summary": summary,
            "requires_confirmation": False,
            "command_id": command["id"],
            "data": {"control_state": self._memory.get_bot_control_state()},
        }

    def toggle_signals(
        self,
        enabled: bool,
        telegram_user_id: str,
        telegram_username: str | None = None,
    ) -> dict[str, Any]:
        control = self._memory.set_bot_control_state(signals_enabled=enabled)
        summary = "Signalverwerking ingeschakeld." if enabled else "Signalverwerking uitgeschakeld."
        self._log_action(
            telegram_user_id,
            telegram_username,
            "signals_toggle",
            "success",
            {"enabled": enabled},
        )
        return {
            "summary": summary,
            "enabled": enabled,
            "control_state": control,
        }

    def get_risk_status(self, section: str) -> dict[str, Any]:
        history = self._trade_history(limit=5000)
        state = self._load_state()
        ftmo = self._ftmo_snapshot(state)
        daily_pnl = self._period_pnl(history, "D")
        weekly_pnl = self._period_pnl(history, "W")
        monthly_pnl = self._period_pnl(history, "M")
        drawdown = max(self._settings.starting_capital - float(state.get("equity", self._settings.starting_capital)), 0.0)
        drawdown_pct = (drawdown / self._settings.starting_capital * 100) if self._settings.starting_capital else 0.0
        loss_streak = self._loss_streak(history)

        mapping: dict[str, tuple[str, dict[str, Any]]] = {
            "daily": (
                f"Daily Risk Status\nPnL vandaag: {self._money(daily_pnl)}\n"
                f"Dagverlies gebruikt: {self._money(ftmo['daily_loss_used'])}\n"
                f"Resterend: {self._money(ftmo['daily_remaining'])}",
                {"daily_pnl": round(daily_pnl, 2), **ftmo},
            ),
            "weekly": (
                f"Weekly Risk Status\nPnL deze week: {self._money(weekly_pnl)}\n"
                f"Actieve verliesstreak: {loss_streak}",
                {"weekly_pnl": round(weekly_pnl, 2), "loss_streak": loss_streak},
            ),
            "monthly_target": (
                f"Monthly Target Status\nPnL deze maand: {self._money(monthly_pnl)}\n"
                f"Doel: {self._money(FTMO_MONTHLY_TARGET)}\n"
                f"Resterend: {self._money(max(FTMO_MONTHLY_TARGET - monthly_pnl, 0.0))}",
                {"monthly_pnl": round(monthly_pnl, 2), "target": FTMO_MONTHLY_TARGET},
            ),
            "drawdown": (
                f"Drawdown Check\nHuidige drawdown: {self._money(drawdown)} ({drawdown_pct:.2f}%)\n"
                f"FTMO limiet: 10.00%",
                {"drawdown": round(drawdown, 2), "drawdown_pct": round(drawdown_pct, 2)},
            ),
            "loss_streak": (
                f"Loss Streak Check\nConsecutieve verliestrades: {loss_streak}",
                {"loss_streak": loss_streak},
            ),
            "ftmo_rules": (
                f"FTMO Rules Check\nStatus: {ftmo['status']}\n"
                f"Can trade: {'YES' if ftmo['can_trade'] else 'NO'}\n"
                f"Warnings: {', '.join(ftmo['warnings']) if ftmo['warnings'] else 'none'}",
                ftmo,
            ),
        }
        if section not in mapping:
            raise ValueError(f"Unsupported risk section: {section}")
        summary, data = mapping[section]
        return {"summary": summary, "data": data}

    def get_signal_snapshot(self, section: str) -> dict[str, Any]:
        state = self._load_state()
        latest = state.get("last_signal") or {}
        if not isinstance(latest, dict):
            latest = {}
        today_signals = self._signals_today(state)
        control = self._memory.get_bot_control_state()

        mapping: dict[str, tuple[str, dict[str, Any]]] = {
            "latest": (
                f"Latest Signal\nSide: {str(latest.get('side', 'unknown')).upper()}\n"
                f"Reason: {latest.get('reason', 'Geen signaal beschikbaar')}",
                latest,
            ),
            "confidence": (
                f"Signal Confidence\nConfidence: {float(latest.get('confidence', 0.0)):.2f}",
                {"confidence": float(latest.get("confidence", 0.0)), "latest_signal": latest},
            ),
            "today": (
                f"Signals Today\nAantal: {len(today_signals)}\n"
                f"Enabled: {'YES' if control.get('signals_enabled', True) else 'NO'}",
                {"count": len(today_signals), "signals": today_signals, "enabled": control.get("signals_enabled", True)},
            ),
        }
        if section not in mapping:
            raise ValueError(f"Unsupported signal section: {section}")
        summary, data = mapping[section]
        return {"summary": summary, "data": data}

    def run_quick_backtest(self, telegram_user_id: str, telegram_username: str | None = None) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        request = BacktestRequest(
            start_date=today - timedelta(days=120),
            end_date=today,
            starting_capital=self._settings.starting_capital,
            symbol="XAUUSD",
        )
        result = self._backtests.run(request)
        self._memory.set_runtime_state(
            "last_backtest",
            {
                "task_id": result.task_id,
                "metrics": result.metrics.model_dump(),
                "ran_at": datetime.utcnow().isoformat(),
            },
        )
        self._log_action(
            telegram_user_id,
            telegram_username,
            "quick_backtest",
            "success",
            {"task_id": result.task_id, "total_trades": result.metrics.total_trades},
        )
        return {
            "summary": (
                f"Quick Backtest klaar\nTrades: {result.metrics.total_trades}\n"
                f"WR: {result.metrics.win_rate:.2%}\nPF: {result.metrics.profit_factor:.2f}\n"
                f"Return: {result.metrics.total_return_pct:.2f}%"
            ),
            "result": result.model_dump(),
        }

    def get_latest_backtest_result(self) -> dict[str, Any]:
        history = self._backtests.get_history()
        latest = history[0] if history else (self._memory.get_runtime_state("last_backtest") or {})
        if not latest:
            return {"summary": "Nog geen backtestresultaat beschikbaar.", "data": {}}
        return {
            "summary": (
                f"Latest Backtest Result\nTask: {latest.get('task_id', 'unknown')}\n"
                f"Trades: {latest.get('total_trades', latest.get('metrics', {}).get('total_trades', 0))}\n"
                f"WR: {float(latest.get('win_rate', latest.get('metrics', {}).get('win_rate', 0.0))):.2%}"
            ),
            "data": latest,
        }

    def compare_v16_vs_v17(self) -> dict[str, Any]:
        v16 = self._best_v16_summary()
        v17 = self._backtests.get_history()[0] if self._backtests.get_history() else None
        if not v16 or not v17:
            return {"summary": "Vergelijking V16 vs V17 nog niet beschikbaar.", "data": {}}

        summary = "\n".join(
            [
                "Compare V16 vs V17",
                f"V16 best: {v16.get('variant', 'unknown')} | PF {float(v16.get('pf', 0.0)):.2f} | DD {float(v16.get('max_dd', 0.0)):.2f}%",
                f"V17 latest: PF {float(v17.get('profit_factor', 0.0)):.2f} | DD {float(v17.get('max_drawdown_pct', 0.0)):.2f}%",
                f"PnL/Return: V16 {self._money(v16.get('pnl_eur', 0.0))} | V17 {float(v17.get('total_return_pct', 0.0)):.2f}%",
            ]
        )
        return {"summary": summary, "data": {"v16": v16, "v17": v17}}

    def get_equity_curve_summary(self) -> dict[str, Any]:
        latest = self.get_latest_backtest_result()["data"]
        curve = latest.get("equity_curve") or latest.get("result", {}).get("equity_curve") or []
        if not curve:
            return {"summary": "Geen equity curve beschikbaar.", "data": {}}
        start = curve[0]["capital"]
        end = curve[-1]["capital"]
        peak = max(point["capital"] for point in curve)
        trough = min(point["capital"] for point in curve)
        return {
            "summary": (
                f"Equity Curve Summary\nStart: {self._money(start)}\nEnd: {self._money(end)}\n"
                f"Peak: {self._money(peak)}\nTrough: {self._money(trough)}"
            ),
            "data": {"start": start, "end": end, "peak": peak, "trough": trough, "points": len(curve)},
        }

    def get_memory_snapshot(self, section: str) -> dict[str, Any]:
        runtime = self._memory.get_runtime_state("runtime_state") or {}
        training = self._memory.get_runtime_state("last_training") or {}
        optimizer = self._memory.get_runtime_state("optimizer_state") or {}
        model_history = self._memory.model_history()
        winning = self._read_json(MEMORY_DIR / "winning_setups.json")
        losing = self._read_json(MEMORY_DIR / "failed_setups.json")

        progress = {
            "model_snapshots": int(len(model_history)),
            "last_training": training,
        }
        mapping: dict[str, tuple[str, dict[str, Any]]] = {
            "best_setups": (
                f"Best Setups\nCount: {len(winning) if isinstance(winning, list) else 0}",
                {"setups": winning},
            ),
            "losing_setups": (
                f"Losing Setups\nCount: {len(losing) if isinstance(losing, list) else 0}",
                {"setups": losing},
            ),
            "optimizer_status": (
                f"Optimizer Status\nState: {optimizer.get('status', 'idle')}\n"
                f"Last run: {optimizer.get('updated_at', 'unknown')}",
                optimizer,
            ),
            "learning_progress": (
                f"Learning Progress\nModel snapshots: {progress['model_snapshots']}\n"
                f"Last training: {training.get('trained_at', 'never')}",
                progress,
            ),
            "runtime": (
                f"AI Runtime\nKnown keys: {len(runtime)}",
                runtime,
            ),
        }
        if section not in mapping:
            raise ValueError(f"Unsupported memory section: {section}")
        summary, data = mapping[section]
        return {"summary": summary, "data": data}

    def build_report_snapshot(self, period: str) -> dict[str, Any]:
        history = self._trade_history(limit=5000)
        now = datetime.now(timezone.utc)
        if period == "daily":
            start = pd.Timestamp(now.date(), tz=timezone.utc)
            label = now.strftime("%Y-%m-%d")
        elif period == "weekly":
            start = pd.Timestamp((now - timedelta(days=now.weekday())).date(), tz=timezone.utc)
            label = f"{now:%G-W%V}"
        elif period == "monthly":
            start = pd.Timestamp(date(now.year, now.month, 1), tz=timezone.utc)
            label = now.strftime("%Y-%m")
        else:
            raise ValueError(f"Unsupported report period: {period}")

        period_frame = self._filter_since(history, start)
        pnl = float(period_frame["pnl"].fillna(0.0).sum()) if not period_frame.empty else 0.0
        trades = int(len(period_frame))
        wins = int((period_frame["pnl"].fillna(0.0) > 0).sum()) if not period_frame.empty else 0
        win_rate = (wins / trades * 100) if trades else 0.0
        return {
            "summary": (
                f"{period.title()} Report\nPeriod: {label}\nTrades: {trades}\n"
                f"PnL: {self._money(pnl)}\nWin rate: {win_rate:.1f}%"
            ),
            "data": {"period": label, "trades": trades, "pnl": round(pnl, 2), "win_rate": round(win_rate, 1)},
        }

    def export_trade_log(self, telegram_user_id: str, telegram_username: str | None = None) -> dict[str, Any]:
        history = self._trade_history(limit=10000)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"telegram_trade_log_{datetime.utcnow():%Y%m%d_%H%M%S}.csv"
        path = REPORTS_DIR / filename
        history.to_csv(path, index=False)
        self._log_action(
            telegram_user_id,
            telegram_username,
            "export_trade_log",
            "success",
            {"path": str(path)},
        )
        return {
            "summary": f"Trade log geexporteerd naar {path}",
            "data": {"filename": filename, "path": str(path), "rows": int(len(history))},
        }

    def recent_action_logs(self) -> dict[str, Any]:
        logs = self._memory.recent_telegram_actions(limit=20)
        commands = self._memory.recent_control_commands(limit=20)
        return {"logs": logs, "commands": commands}

    def _control_summary(self, action: str, command_id: int) -> str:
        labels = {
            "start_bot": "Start Bot",
            "stop_bot": "Stop Bot",
            "pause_trading": "Pause Trading",
            "resume_trading": "Resume Trading",
            "emergency_stop": "Emergency Stop",
            "close_all_positions": "Close All Positions",
            "train_ai": "Train AI",
        }
        return f"{labels.get(action, action)} command geaccepteerd. Command ID: {command_id}."

    def _signals_today(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        history = state.get("signal_history", [])
        if not isinstance(history, list):
            return []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [row for row in history if str(row.get("time", "")).startswith(today)]

    def _trade_history(self, limit: int) -> pd.DataFrame:
        try:
            return self._memory.trade_history(limit=limit)
        except Exception as exc:
            logger.warning("Could not load trade history for Telegram service: %s", exc)
            return pd.DataFrame()

    def _ftmo_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        equity = float(state.get("equity", self._settings.starting_capital))
        day_start = float(state.get("day_start_equity", self._settings.starting_capital))
        result = self._risk.compute_ftmo_buffers(
            equity=equity,
            day_start_equity=day_start,
            estimated_trade_risk=self._settings.starting_capital * 0.0025,
        )
        payload = result.model_dump()
        payload["status"] = payload["risk_level"].upper()
        payload["can_trade"] = payload["overall_ok"]
        warnings = []
        if not payload["daily_ok"]:
            warnings.append("daily_loss_limit")
        if not payload["total_ok"]:
            warnings.append("total_loss_limit")
        payload["warnings"] = warnings
        return payload

    def _period_pnl(self, history: pd.DataFrame, freq: str) -> float:
        if history.empty or "closed_at" not in history.columns or "pnl" not in history.columns:
            return 0.0
        frame = history.dropna(subset=["closed_at"]).copy()
        if frame.empty:
            return 0.0
        closed = pd.to_datetime(frame["closed_at"], utc=True, errors="coerce")
        now = pd.Timestamp.now(tz="UTC")
        if freq == "D":
            mask = closed.dt.date == now.date()
        elif freq == "W":
            mask = closed.dt.isocalendar().week == now.isocalendar().week
            mask &= closed.dt.isocalendar().year == now.isocalendar().year
        else:
            mask = (closed.dt.month == now.month) & (closed.dt.year == now.year)
        return float(frame.loc[mask.fillna(False), "pnl"].fillna(0.0).sum())

    def _loss_streak(self, history: pd.DataFrame) -> int:
        if history.empty or "pnl" not in history.columns:
            return 0
        streak = 0
        for pnl in reversed(history["pnl"].fillna(0.0).tolist()):
            if pnl < 0:
                streak += 1
                continue
            break
        return streak

    def _filter_since(self, history: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
        if history.empty or "closed_at" not in history.columns:
            return pd.DataFrame(columns=history.columns)
        frame = history.copy()
        closed = pd.to_datetime(frame["closed_at"], utc=True, errors="coerce")
        return frame.loc[closed >= start]

    def _best_v16_summary(self) -> dict[str, Any] | None:
        data = self._read_json(REPORTS_DIR / "latest_summary.json")
        if not isinstance(data, list) or not data:
            return None
        return max(data, key=lambda row: float(row.get("pf", 0.0)))

    def _load_state(self) -> dict[str, Any]:
        if not STATE_PATH.exists():
            return {}
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _read_json(self, path: Path) -> Any:
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _log_action(
        self,
        telegram_user_id: str,
        telegram_username: str | None,
        action: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        self._memory.log_telegram_action(
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            action=action,
            status=status,
            details=details,
        )

    @staticmethod
    def _money(value: Any) -> str:
        try:
            return f"${float(value):,.2f}"
        except Exception:
            return "$0.00"
