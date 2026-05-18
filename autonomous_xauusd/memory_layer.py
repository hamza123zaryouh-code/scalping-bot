from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

import pandas as pd
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .models import ClosedTradeResult, ExecutionResult, StrategyParameters, TrainingOutcome


class Base(DeclarativeBase):
    pass


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker_ticket: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    market_regime: Mapped[str] = mapped_column(String(32), default="unknown")
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi_fast: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_fast: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_slow: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_trend: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    h4_atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    h4_adx: Mapped[float | None] = mapped_column(Float, nullable=True)
    d1_trend: Mapped[str | None] = mapped_column(String(8), nullable=True)
    signal_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    volatility: Mapped[float | None] = mapped_column(Float, nullable=True)
    reward_risk_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelSnapshot(Base):
    __tablename__ = "model_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    sample_count: Mapped[int] = mapped_column(Integer)
    accuracy: Mapped[float] = mapped_column(Float)
    precision: Mapped[float] = mapped_column(Float)
    recall: Mapped[float] = mapped_column(Float)
    f1_score: Mapped[float] = mapped_column(Float)
    feature_importances: Mapped[dict[str, Any]] = mapped_column(JSON)
    parameter_overrides: Mapped[dict[str, Any]] = mapped_column(JSON)
    model_path: Mapped[str] = mapped_column(String(512))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuntimeState(Base):
    __tablename__ = "runtime_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ControlCommand(Base):
    __tablename__ = "control_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    command: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True, default="telegram")
    requested_by: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TelegramActionLog(Base):
    __tablename__ = "telegram_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[str] = mapped_column(String(64), index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MemoryLayer:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, future=True)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    def initialize(self) -> None:
        """
        Initialize database tables.
        NOTE: This should be called during application startup or via a dedicated
        provisioning script (init_db.py), NOT in the request path.
        """
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def load_strategy_parameters(self, fallback: StrategyParameters) -> StrategyParameters:
        record = self.get_runtime_state("strategy_parameters")
        if not record:
            return fallback
        return StrategyParameters.from_record(record.get("parameters"))

    def save_strategy_parameters(self, parameters: StrategyParameters, source: str) -> None:
        self.set_runtime_state(
            "strategy_parameters",
            {
                "parameters": parameters.to_record(),
                "source": source,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def get_runtime_state(self, key: str) -> dict[str, Any] | None:
        with self.session_scope() as session:
            state = session.get(RuntimeState, key)
            return dict(state.value) if state else None

    def set_runtime_state(self, key: str, value: dict[str, Any]) -> None:
        with self.session_scope() as session:
            state = session.get(RuntimeState, key)
            if state is None:
                state = RuntimeState(key=key, value=value)
                session.add(state)
            else:
                state.value = value

    def get_bot_control_state(self) -> dict[str, Any]:
        return self.get_runtime_state("bot_control") or {
            "bot_active": True,
            "trading_paused": False,
            "signals_enabled": True,
            "emergency_stop": False,
        }

    def set_bot_control_state(self, **updates: Any) -> dict[str, Any]:
        current = self.get_bot_control_state()
        merged = {
            **current,
            **updates,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.set_runtime_state("bot_control", merged)
        return merged

    def enqueue_control_command(
        self,
        command: str,
        requested_by: str,
        payload: dict[str, Any] | None = None,
        source: str = "telegram",
    ) -> dict[str, Any]:
        with self.session_scope() as session:
            row = ControlCommand(
                command=command,
                source=source,
                requested_by=requested_by,
                payload=payload or {},
                status="pending",
            )
            session.add(row)
            session.flush()
            return {
                "id": row.id,
                "command": row.command,
                "status": row.status,
                "requested_by": row.requested_by,
                "payload": dict(row.payload or {}),
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }

    def fetch_pending_control_commands(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch and atomically claim pending commands (sets status→executing in same TX)."""
        with self.session_scope() as session:
            rows = session.scalars(
                select(ControlCommand)
                .where(ControlCommand.status == "pending")
                .order_by(ControlCommand.created_at.asc(), ControlCommand.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            now = datetime.now(timezone.utc)
            for row in rows:
                row.status = "executing"
                row.result_message = "Command in uitvoering."
                row.executed_at = now
            return [
                {
                    "id": row.id,
                    "command": row.command,
                    "status": "executing",
                    "requested_by": row.requested_by,
                    "payload": dict(row.payload or {}),
                    "source": row.source,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    def update_control_command(
        self,
        command_id: int,
        status: str,
        result_message: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.session_scope() as session:
            row = session.get(ControlCommand, command_id)
            if row is None:
                return
            row.status = status
            row.result_message = result_message
            row.error_message = error_message
            row.executed_at = datetime.now(timezone.utc)

    def recent_control_commands(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(ControlCommand)
                .order_by(ControlCommand.created_at.desc(), ControlCommand.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": row.id,
                    "command": row.command,
                    "status": row.status,
                    "requested_by": row.requested_by,
                    "payload": dict(row.payload or {}),
                    "source": row.source,
                    "result_message": row.result_message,
                    "error_message": row.error_message,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "executed_at": row.executed_at.isoformat() if row.executed_at else None,
                }
                for row in rows
            ]

    def log_telegram_action(
        self,
        telegram_user_id: str,
        action: str,
        status: str,
        details: dict[str, Any] | None = None,
        telegram_username: str | None = None,
    ) -> None:
        with self.session_scope() as session:
            session.add(
                TelegramActionLog(
                    telegram_user_id=telegram_user_id,
                    telegram_username=telegram_username,
                    action=action,
                    status=status,
                    details=details or {},
                )
            )

    def recent_telegram_actions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.scalars(
                select(TelegramActionLog)
                .order_by(TelegramActionLog.created_at.desc(), TelegramActionLog.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": row.id,
                    "telegram_user_id": row.telegram_user_id,
                    "telegram_username": row.telegram_username,
                    "action": row.action,
                    "status": row.status,
                    "details": dict(row.details or {}),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    def log_trade_open(self, execution: ExecutionResult, sentiment_score: float | None = None) -> None:
        features = execution.features
        stop_distance = abs(execution.entry_price - execution.stop_loss)
        target_distance = abs(execution.take_profit - execution.entry_price)
        reward_risk_ratio = (target_distance / stop_distance) if stop_distance > 0 else None

        with self.session_scope() as session:
            trade = TradeLog(
                broker_ticket=execution.broker_ticket,
                symbol=execution.symbol,
                timeframe=execution.timeframe,
                side=execution.side,
                mode=execution.mode,
                status=execution.status,
                market_regime=execution.market_regime,
                opened_at=execution.opened_at,
                entry_price=execution.entry_price,
                stop_loss=execution.stop_loss,
                take_profit=execution.take_profit,
                volume=execution.volume,
                rsi=features.get("rsi"),
                rsi_fast=features.get("rsi_fast"),
                ema_fast=features.get("ema_fast"),
                ema_slow=features.get("ema_slow"),
                ema_trend=features.get("ema_trend"),
                atr=features.get("atr"),
                h4_atr=features.get("h4_atr"),
                h4_adx=features.get("h4_adx"),
                d1_trend=str(features.get("d1_trend", "")) or None,
                signal_type=str(features.get("signal_type", "")) or None,
                sentiment_score=sentiment_score,
                volatility=features.get("volatility"),
                reward_risk_ratio=reward_risk_ratio,
                notes=execution.reason,
                meta=execution.meta,
            )
            session.add(trade)

    def log_trade_close(self, closed_trade: ClosedTradeResult) -> None:
        with self.session_scope() as session:
            trade = session.scalar(select(TradeLog).where(TradeLog.broker_ticket == closed_trade.broker_ticket))
            if trade is None:
                return
            trade.closed_at = closed_trade.closed_at
            trade.exit_price = closed_trade.exit_price
            trade.pnl = closed_trade.pnl
            trade.status = closed_trade.status
            trade.notes = (trade.notes or "") + f"\nExit: {closed_trade.close_reason}"
            trade.meta = {**(trade.meta or {}), **closed_trade.meta}

    def list_open_trades(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            query = select(TradeLog).where(TradeLog.status == "open")
            if symbol:
                query = query.where(TradeLog.symbol == symbol)
            rows = session.scalars(query).all()
            return [
                {
                    "broker_ticket": row.broker_ticket,
                    "symbol": row.symbol,
                    "side": row.side,
                    "entry_price": row.entry_price,
                    "stop_loss": row.stop_loss,
                    "take_profit": row.take_profit,
                    "volume": row.volume,
                    "opened_at": row.opened_at,
                }
                for row in rows
            ]

    def fetch_training_frame(self) -> pd.DataFrame:
        _REGIME_SCORE = {
            "STERK_BULL": 2, "ZWAK_BULL": 1, "CHOPPY": 0, "ZWAK_BEAR": -1, "STERK_BEAR": -2,
        }
        with self.session_scope() as session:
            rows = session.scalars(select(TradeLog).where(TradeLog.status == "closed")).all()
            payload = []
            for row in rows:
                if row.closed_at is None or row.pnl is None:
                    continue
                holding_minutes = max((row.closed_at - row.opened_at).total_seconds() / 60.0, 0.0)
                payload.append({
                    "broker_ticket": row.broker_ticket,
                    "symbol": row.symbol,
                    "side": row.side,
                    "pnl": row.pnl,
                    "rsi": row.rsi,
                    "rsi_fast": row.rsi_fast,
                    "ema_gap": (row.ema_fast or 0.0) - (row.ema_slow or 0.0),
                    "trend_gap": (row.ema_slow or 0.0) - (row.ema_trend or 0.0),
                    "atr": row.atr,
                    "h4_atr": row.h4_atr,
                    "h4_adx": row.h4_adx,
                    "h4_regime_score": _REGIME_SCORE.get(row.market_regime or "", 0),
                    "d1_bull": 1.0 if (row.d1_trend or "") == "bull" else 0.0,
                    "volatility": row.volatility,
                    "reward_risk_ratio": row.reward_risk_ratio,
                    "holding_minutes": holding_minutes,
                })
            return pd.DataFrame(payload)

    def fetch_analytics_frame(self, limit: int = 5000) -> pd.DataFrame:
        return self.trade_history(limit=limit)

    def save_model_snapshot(self, outcome: TrainingOutcome) -> None:
        with self.session_scope() as session:
            session.add(
                ModelSnapshot(
                    trained_at=outcome.trained_at,
                    sample_count=outcome.sample_count,
                    accuracy=outcome.accuracy,
                    precision=outcome.precision,
                    recall=outcome.recall,
                    f1_score=outcome.f1_score,
                    feature_importances=outcome.feature_importances,
                    parameter_overrides=outcome.parameter_overrides,
                    model_path=outcome.model_path,
                    notes=outcome.notes,
                )
            )

    def trade_history(self, limit: int = 500) -> pd.DataFrame:
        with self.session_scope() as session:
            rows = session.scalars(select(TradeLog).order_by(TradeLog.opened_at.desc()).limit(limit)).all()
            payload = [
                {
                    "broker_ticket": row.broker_ticket,
                    "symbol": row.symbol,
                    "side": row.side,
                    "mode": row.mode,
                    "status": row.status,
                    "opened_at": row.opened_at,
                    "closed_at": row.closed_at,
                    "entry_price": row.entry_price,
                    "exit_price": row.exit_price,
                    "stop_loss": row.stop_loss,
                    "take_profit": row.take_profit,
                    "volume": row.volume,
                    "pnl": row.pnl,
                    "rsi": row.rsi,
                    "ema_fast": row.ema_fast,
                    "ema_slow": row.ema_slow,
                    "ema_trend": row.ema_trend,
                    "atr": row.atr,
                    "volatility": row.volatility,
                    "market_regime": row.market_regime,
                    "reward_risk_ratio": row.reward_risk_ratio,
                    "rsi_fast": row.rsi_fast,
                    "h4_atr": row.h4_atr,
                    "h4_adx": row.h4_adx,
                    "d1_trend": row.d1_trend,
                    "signal_type": row.signal_type,
                    "sentiment_score": row.sentiment_score,
                }
                for row in reversed(rows)
            ]
            return pd.DataFrame(payload)

    def model_history(self) -> pd.DataFrame:
        with self.session_scope() as session:
            rows = session.scalars(select(ModelSnapshot).order_by(ModelSnapshot.trained_at.asc())).all()
            return pd.DataFrame(
                [
                    {
                        "trained_at": row.trained_at,
                        "sample_count": row.sample_count,
                        "accuracy": row.accuracy,
                        "precision": row.precision,
                        "recall": row.recall,
                        "f1_score": row.f1_score,
                    }
                    for row in rows
                ]
            )

    def daily_summary(self, for_day: date) -> dict[str, Any]:
        history = self.trade_history(limit=5000)
        if history.empty:
            return {"day": for_day.isoformat(), "trade_count": 0, "realized_pnl": 0.0, "win_rate": 0.0}

        history["closed_day"] = pd.to_datetime(history["closed_at"]).dt.date
        day_frame = history[history["closed_day"] == for_day]
        if day_frame.empty:
            return {"day": for_day.isoformat(), "trade_count": 0, "realized_pnl": 0.0, "win_rate": 0.0}

        realized_pnl = float(day_frame["pnl"].fillna(0.0).sum())
        win_rate = float((day_frame["pnl"].fillna(0.0) > 0).mean())
        return {
            "day": for_day.isoformat(),
            "trade_count": int(len(day_frame)),
            "realized_pnl": realized_pnl,
            "win_rate": win_rate,
        }
