from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any, List


@dataclass(frozen=True)
class StrategyParameters:
    ema_fast: int = 8
    ema_slow: int = 21
    ema_trend: int = 50
    rsi_period: int = 14
    rsi_fast_period: int = 5
    atr_period: int = 14
    volatility_window: int = 20
    rsi_buy_threshold: float = 56.0
    rsi_sell_threshold: float = 44.0
    rsi_pullback_strong: float = 30.0
    rsi_pullback_weak: float = 35.0
    h4_adx_strong: float = 26.0
    h4_adx_weak: float = 18.0
    stop_loss_atr: float = 1.0
    take_profit_atr: float = 3.0
    risk_per_trade: float = 0.005
    risk_strong_regime: float = 0.015
    risk_weak_regime: float = 0.008

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, payload: dict[str, Any] | None) -> "StrategyParameters":
        if not payload:
            return cls()
        supported = {key: value for key, value in payload.items() if key in cls.__dataclass_fields__}
        return cls(**supported)

    def with_overrides(self, overrides: dict[str, Any] | None) -> "StrategyParameters":
        if not overrides:
            return self
        supported = {key: value for key, value in overrides.items() if key in self.__dataclass_fields__}
        return replace(self, **supported)


@dataclass(frozen=True)
class SignalDecision:
    symbol: str
    timeframe: str
    side: str
    opened_at: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    market_regime: str
    reason: str
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    broker_ticket: str
    symbol: str
    timeframe: str
    side: str
    mode: str
    volume: float
    opened_at: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    status: str
    market_regime: str
    reason: str
    features: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClosedTradeResult:
    broker_ticket: str
    closed_at: datetime
    exit_price: float
    pnl: float
    status: str
    close_reason: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SentimentScore:
    score: float
    label: str
    headline_count: int
    sources: List[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AnalyticsReport:
    generated_at: datetime
    total_trades: int
    closed_trades: int
    win_rate: float
    profit_factor: float
    avg_rr: float
    total_pnl: float
    max_drawdown: float
    monthly: List[dict]
    by_regime: List[dict]
    by_session: List[dict]
    by_side: List[dict]
    ml_snapshots: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_trades": self.total_trades,
            "closed_trades": self.closed_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "avg_rr": round(self.avg_rr, 4),
            "total_pnl": round(self.total_pnl, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "monthly": self.monthly,
            "by_regime": self.by_regime,
            "by_session": self.by_session,
            "by_side": self.by_side,
            "ml_snapshots": self.ml_snapshots,
        }


@dataclass(frozen=True)
class TrainingOutcome:
    trained_at: datetime
    sample_count: int
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    feature_importances: dict[str, float]
    parameter_overrides: dict[str, float]
    model_path: str
    notes: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "trained_at": self.trained_at.isoformat(),
            "sample_count": self.sample_count,
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "feature_importances": self.feature_importances,
            "parameter_overrides": self.parameter_overrides,
            "model_path": self.model_path,
            "notes": self.notes,
        }
