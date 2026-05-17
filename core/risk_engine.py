"""
XAUUSD V17 Risk Engine — Autonoom Circuit Breaker Systeem
=========================================================
Beschermt het account zonder handmatige interventie.

Circuit breakers:
  1. Drawdown circuit breaker     — trading pauze bij te hoog verlies
  2. Volatility shutdown          — safe mode bij abnormale volatiliteit
  3. Spread protection            — geen trades bij te hoge spread
  4. Loss streak protection       — cooldown na opeenvolgende verliezen
  5. Session anomaly detection    — detecteert abnormale price action
  6. Daily loss limit             — FTMO dag-limiet bescherming
  7. Total drawdown limit         — FTMO totaal drawdown bescherming

Elke check is autonoom en herstart vanzelf na recovery.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────

FTMO_STARTING_CAPITAL = 160_000.0
FTMO_DAILY_LOSS_LIMIT = 6_000.0       # Interne daglimiet €6k per dag
FTMO_TOTAL_LOSS_LIMIT = 16_000.0      # €16k totaal (10%)
FTMO_DAILY_LOSS_PCT = FTMO_DAILY_LOSS_LIMIT / FTMO_STARTING_CAPITAL
FTMO_TOTAL_LOSS_PCT = 0.10            # 10% totaal

# Interne limieten (conservatiever dan FTMO)
INTERNAL_DAILY_LOSS_PCT = 0.65        # 65% van FTMO dag-limiet
INTERNAL_DRAWDOWN_PAUSE_PCT = 0.04    # 4% → risk halvering
INTERNAL_DRAWDOWN_STOP_PCT = 0.055    # 5.5% → trading stop
LOSS_STREAK_COOLDOWN = 3              # 3 verliezen op rij → cooldown
VOLATILITY_MULTIPLIER_THRESHOLD = 3.0 # 3x normaal ATR → safe mode
MAX_SPREAD_POINTS = 350               # Max toegestane spread in points

# Graduated capital protection thresholds (% van FTMO dag-limiet gebruikt)
GRAD_STAGE1_PCT = 0.50   # 50% dagverlies → alleen signaaltype C/F/D (laagste risico)
GRAD_STAGE2_PCT = 0.75   # 75% dagverlies → stop (vóór FTMO breuk)


class CircuitBreakerReason(str, Enum):
    NONE = "none"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    TOTAL_DRAWDOWN = "total_drawdown"
    LOSS_STREAK = "loss_streak"
    HIGH_SPREAD = "high_spread"
    HIGH_VOLATILITY = "high_volatility"
    SESSION_ANOMALY = "session_anomaly"
    MANUAL_STOP = "manual_stop"
    FTMO_RISK = "ftmo_risk_protection"


@dataclass
class RiskState:
    """Volledige risicostate van het systeem."""
    can_trade: bool = True
    circuit_breaker_active: bool = False
    circuit_breaker_reason: str = CircuitBreakerReason.NONE
    circuit_breaker_since: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None

    # Account state
    starting_capital: float = FTMO_STARTING_CAPITAL
    current_balance: float = FTMO_STARTING_CAPITAL
    peak_balance: float = FTMO_STARTING_CAPITAL
    day_start_balance: float = FTMO_STARTING_CAPITAL

    # Daily tracking
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_losses: int = 0
    trading_date: date = field(default_factory=date.today)

    # Streak tracking
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    recent_results: list = field(default_factory=list)

    # Risk scaling
    risk_multiplier: float = 1.0    # 1.0 = normaal, 0.5 = half, 0.25 = kwart

    # Graduated capital protection
    graduated_stage: int = 0         # 0=normaal, 1=beperkte signalen, 2=dag-stop
    allowed_signal_types: list = field(default_factory=list)  # leeg = alle

    # FTMO compliance
    ftmo_daily_loss_used: float = 0.0
    ftmo_total_loss_used: float = 0.0
    ftmo_daily_loss_pct: float = 0.0
    ftmo_total_loss_pct: float = 0.0
    ftmo_compliant: bool = True

    # Conditions
    current_spread: float = 0.0
    current_atr: float = 0.0
    baseline_atr: float = 0.0
    volatility_ratio: float = 1.0
    spread_ok: bool = True
    volatility_ok: bool = True

    def to_dict(self) -> dict:
        return {
            "can_trade": self.can_trade,
            "circuit_breaker_active": self.circuit_breaker_active,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "circuit_breaker_since": self.circuit_breaker_since.isoformat() if self.circuit_breaker_since else None,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "balance": round(self.current_balance, 2),
            "peak_balance": round(self.peak_balance, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "daily_losses": self.daily_losses,
            "consecutive_losses": self.consecutive_losses,
            "risk_multiplier": round(self.risk_multiplier, 2),
            "drawdown_pct": round(self._drawdown_pct * 100, 2),
            "daily_loss_pct": round(self._daily_loss_pct * 100, 2),
            "ftmo_daily_pct": round(self.ftmo_daily_loss_pct * 100, 2),
            "ftmo_total_pct": round(self.ftmo_total_loss_pct * 100, 2),
            "ftmo_compliant": self.ftmo_compliant,
            "spread_ok": self.spread_ok,
            "volatility_ok": self.volatility_ok,
            "volatility_ratio": round(self.volatility_ratio, 2),
            "graduated_stage": self.graduated_stage,
            "allowed_signal_types": self.allowed_signal_types,
        }

    @property
    def _drawdown_pct(self) -> float:
        if self.peak_balance <= 0:
            return 0.0
        return max(0.0, (self.peak_balance - self.current_balance) / self.peak_balance)

    @property
    def _daily_loss_pct(self) -> float:
        if self.day_start_balance <= 0:
            return 0.0
        loss = self.day_start_balance - self.current_balance
        return max(0.0, loss / self.day_start_balance)


class CircuitBreaker:
    """
    Autonoom circuit breaker systeem.
    Bewaakt alle risicofactoren en stopt/herstart trading automatisch.

    Gebruik:
        cb = CircuitBreaker()
        cb.update_balance(balance=161000, peak=161000)
        cb.record_trade_result(pnl=-500)
        cb.update_market_conditions(spread=180, atr=8.5, baseline_atr=7.2)

        if cb.can_trade():
            risk_pct = cb.get_risk_multiplier() * base_risk
    """

    def __init__(
        self,
        starting_capital: float = FTMO_STARTING_CAPITAL,
        daily_loss_limit: float = FTMO_DAILY_LOSS_LIMIT,
        total_loss_limit: float = FTMO_TOTAL_LOSS_LIMIT,
        max_spread: float = MAX_SPREAD_POINTS,
        loss_streak_limit: int = LOSS_STREAK_COOLDOWN,
    ):
        self._starting = starting_capital
        self._daily_limit = daily_loss_limit
        self._total_limit = total_loss_limit
        self._max_spread = max_spread
        self._loss_streak_limit = loss_streak_limit
        self._state = RiskState(
            starting_capital=starting_capital,
            current_balance=starting_capital,
            peak_balance=starting_capital,
            day_start_balance=starting_capital,
        )
        self._manual_stop = False

    @property
    def state(self) -> RiskState:
        return self._state

    def update_balance(self, balance: float, equity: Optional[float] = None) -> None:
        """Update het saldo na trade of periodiek."""
        s = self._state
        today = date.today()

        # Dag reset
        if today != s.trading_date:
            s.day_start_balance = s.current_balance
            s.daily_pnl = 0.0
            s.daily_trades = 0
            s.daily_losses = 0
            s.trading_date = today
            logger.info("Nieuwe handelsdag: dagelijkse limieten gereset")

        s.current_balance = balance
        s.peak_balance = max(s.peak_balance, balance)
        s.daily_pnl = balance - s.day_start_balance

        # FTMO compliance update
        daily_loss = max(0.0, s.day_start_balance - balance)
        total_loss = max(0.0, s.starting_capital - balance)
        s.ftmo_daily_loss_used = daily_loss
        s.ftmo_total_loss_used = total_loss
        s.ftmo_daily_loss_pct = daily_loss / s.day_start_balance if s.day_start_balance > 0 else 0.0
        s.ftmo_total_loss_pct = total_loss / s.starting_capital if s.starting_capital > 0 else 0.0
        s.ftmo_compliant = (
            daily_loss < self._daily_limit and
            total_loss < self._total_limit
        )

        self._evaluate()

    def record_trade_result(self, pnl: float) -> None:
        """Registreer het resultaat van een afgesloten trade."""
        s = self._state
        s.daily_trades += 1

        if pnl < 0:
            s.consecutive_losses += 1
            s.consecutive_wins = 0
            s.daily_losses += 1
        else:
            s.consecutive_losses = 0
            s.consecutive_wins += 1

        # Houdt de laatste 10 resultaten bij
        s.recent_results.append("W" if pnl >= 0 else "L")
        s.recent_results = s.recent_results[-10:]

        self._evaluate()

        if pnl < 0:
            logger.warning(
                "Verlies geregistreerd: €%.2f | Streak: %d | Dag verliezen: %d",
                pnl, s.consecutive_losses, s.daily_losses,
            )

    def update_market_conditions(
        self,
        spread: float,
        atr: Optional[float] = None,
        baseline_atr: Optional[float] = None,
    ) -> None:
        """Update marktcondities (spread, volatiliteit)."""
        s = self._state
        s.current_spread = spread
        s.spread_ok = spread <= self._max_spread

        if atr is not None and atr > 0:
            s.current_atr = atr
            if baseline_atr and baseline_atr > 0:
                s.baseline_atr = baseline_atr
                s.volatility_ratio = atr / baseline_atr
                s.volatility_ok = s.volatility_ratio <= VOLATILITY_MULTIPLIER_THRESHOLD
            else:
                s.volatility_ok = True

        self._evaluate()

    def manual_stop(self, reason: str = "Handmatig gestopt") -> None:
        """Handmatige stop via Telegram of dashboard."""
        self._manual_stop = True
        s = self._state
        s.circuit_breaker_active = True
        s.circuit_breaker_reason = CircuitBreakerReason.MANUAL_STOP
        s.circuit_breaker_since = datetime.now(timezone.utc)
        s.can_trade = False
        logger.warning("MANUAL STOP geactiveerd: %s", reason)

    def manual_resume(self) -> None:
        """Herstart trading na handmatige stop."""
        self._manual_stop = False
        self._evaluate()
        logger.info("Handmatige stop opgeheven — circuit breaker herwaardeerd")

    def can_trade(self) -> bool:
        """Retourneert True als trading is toegestaan."""
        self._evaluate()
        return self._state.can_trade

    def is_signal_allowed(self, signal_type: str) -> bool:
        """
        Controleert of een signaaltype is toegestaan onder graduated protection.
        Stage 0: alle signalen toegestaan.
        Stage 1: alleen laag-risico typen (C_MOMENTUM, F_MSS, D_PULLBACK).
        Stage 2: geen signalen — trading gestopt.
        """
        self._evaluate()
        if not self._state.can_trade:
            return False
        allowed = self._state.allowed_signal_types
        if not allowed:  # leeg = alles toegestaan
            return True
        return signal_type in allowed

    def get_graduated_stage(self) -> int:
        """Geeft de huidige graduated protection fase (0/1/2)."""
        return self._state.graduated_stage

    def get_risk_multiplier(self) -> float:
        """Geeft de risicomultiplier terug (0.25, 0.40, 0.60, 0.80, 1.0)."""
        return self._state.risk_multiplier

    def get_status_summary(self) -> dict:
        """Volledig statusoverzicht voor dashboard/Telegram."""
        s = self._state
        return {
            **s.to_dict(),
            "circuit_description": self._get_circuit_description(),
            "risk_level": self._get_risk_level(),
        }

    # ─────────────────────────────────────────────────────────────
    # INTERNE EVALUATIE
    # ─────────────────────────────────────────────────────────────

    def _evaluate(self) -> None:
        """Herwaardeer alle circuit breakers en update de state."""
        s = self._state

        if self._manual_stop:
            s.can_trade = False
            s.circuit_breaker_active = True
            s.circuit_breaker_reason = CircuitBreakerReason.MANUAL_STOP
            return

        # Cooldown periode check
        if s.cooldown_until and datetime.now(timezone.utc) < s.cooldown_until:
            s.can_trade = False
            return
        elif s.cooldown_until and datetime.now(timezone.utc) >= s.cooldown_until:
            s.cooldown_until = None
            logger.info("Cooldown periode afgelopen — trading hervat")

        reasons: list[str] = []
        block_trading = False

        # 1. FTMO totaal drawdown limit
        if s.ftmo_total_loss_pct >= FTMO_TOTAL_LOSS_PCT:
            reasons.append(CircuitBreakerReason.TOTAL_DRAWDOWN)
            block_trading = True
            logger.critical(
                "FTMO TOTAAL DRAWDOWN BEREIKT: %.1f%% — ALLE TRADING GESTOPT",
                s.ftmo_total_loss_pct * 100,
            )

        # 2. FTMO dag limiet
        elif s.ftmo_daily_loss_pct >= FTMO_DAILY_LOSS_PCT:
            reasons.append(CircuitBreakerReason.DAILY_LOSS_LIMIT)
            block_trading = True
            logger.warning(
                "FTMO DAG LIMIET BEREIKT: €%.0f — dag gestopt",
                s.ftmo_daily_loss_used,
            )

        # 3. Interne dag limiet (conservatiever)
        elif s.daily_pnl < 0 and abs(s.daily_pnl) > self._daily_limit * INTERNAL_DAILY_LOSS_PCT:
            reasons.append(CircuitBreakerReason.DAILY_LOSS_LIMIT)
            block_trading = True
            logger.warning("Interne dag limiet bereikt: €%.0f", s.daily_pnl)

        # 4. Interne drawdown stop
        elif s._drawdown_pct >= INTERNAL_DRAWDOWN_STOP_PCT:
            reasons.append(CircuitBreakerReason.TOTAL_DRAWDOWN)
            block_trading = True
            logger.warning("Interne drawdown stop: %.1f%%", s._drawdown_pct * 100)

        # 5. Loss streak → cooldown
        if s.consecutive_losses >= self._loss_streak_limit and not block_trading:
            cooldown_minutes = 60 * s.consecutive_losses  # langer bij meer verliezen
            s.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)
            reasons.append(CircuitBreakerReason.LOSS_STREAK)
            block_trading = True
            logger.warning(
                "LOSS STREAK: %d verliezen op rij → %d min cooldown",
                s.consecutive_losses, cooldown_minutes,
            )

        # 6. Spread te hoog
        if not s.spread_ok:
            reasons.append(CircuitBreakerReason.HIGH_SPREAD)
            block_trading = True

        # 7. Volatiliteit abnormaal
        if not s.volatility_ok:
            reasons.append(CircuitBreakerReason.HIGH_VOLATILITY)
            block_trading = True
            logger.warning(
                "HOGE VOLATILITEIT: %.1fx normaal — safe mode",
                s.volatility_ratio,
            )

        # 8. Graduated capital protection
        # Berekend als fractie van de FTMO dag-limiet die al gebruikt is.
        daily_used_pct = s.ftmo_daily_loss_pct / FTMO_DAILY_LOSS_PCT if FTMO_DAILY_LOSS_PCT > 0 else 0.0
        if daily_used_pct >= GRAD_STAGE2_PCT:
            s.graduated_stage = 2
            s.allowed_signal_types = []
            if not block_trading:
                block_trading = True
                reasons.append(CircuitBreakerReason.DAILY_LOSS_LIMIT)
            logger.warning(
                "GRADUATED STAGE 2: %.0f%% dagverlies — dag gestopt voor FTMO breuk",
                daily_used_pct * 100,
            )
        elif daily_used_pct >= GRAD_STAGE1_PCT:
            s.graduated_stage = 1
            s.allowed_signal_types = ["C_MOMENTUM", "F_MSS", "D_PULLBACK"]
            logger.info(
                "GRADUATED STAGE 1: %.0f%% dagverlies — alleen laagrisico signalen (C/F/D)",
                daily_used_pct * 100,
            )
        else:
            s.graduated_stage = 0
            s.allowed_signal_types = []

        # State updaten
        if block_trading:
            s.can_trade = False
            s.circuit_breaker_active = True
            s.circuit_breaker_reason = reasons[0] if reasons else CircuitBreakerReason.NONE
            if s.circuit_breaker_since is None:
                s.circuit_breaker_since = datetime.now(timezone.utc)
        else:
            s.can_trade = True
            s.circuit_breaker_active = False
            s.circuit_breaker_reason = CircuitBreakerReason.NONE
            s.circuit_breaker_since = None

        # Risk multiplier op basis van drawdown
        dd = s._drawdown_pct
        if dd >= INTERNAL_DRAWDOWN_STOP_PCT:
            s.risk_multiplier = 0.0
        elif dd >= INTERNAL_DRAWDOWN_PAUSE_PCT:
            s.risk_multiplier = 0.40
        elif dd >= 0.03:
            s.risk_multiplier = 0.60
        elif dd >= 0.01:
            s.risk_multiplier = 0.80
        elif s.consecutive_losses >= 2:
            s.risk_multiplier = 0.75
        else:
            s.risk_multiplier = 1.0

        # Extra loss streak scaling
        if s.consecutive_losses >= 3:
            s.risk_multiplier *= 0.50

    def _get_circuit_description(self) -> str:
        reason = self._state.circuit_breaker_reason
        descriptions = {
            CircuitBreakerReason.NONE: "Alle systemen operationeel",
            CircuitBreakerReason.DAILY_LOSS_LIMIT: "Dagelijkse verliesgrens bereikt — wacht op nieuwe dag",
            CircuitBreakerReason.TOTAL_DRAWDOWN: "Totale drawdown grens bereikt — account beschermd",
            CircuitBreakerReason.LOSS_STREAK: f"Verlies reeks gedetecteerd — {self._state.cooldown_until} cooldown",
            CircuitBreakerReason.HIGH_SPREAD: f"Spread te hoog ({self._state.current_spread:.0f} pts > {self._max_spread})",
            CircuitBreakerReason.HIGH_VOLATILITY: f"Abnormale volatiliteit ({self._state.volatility_ratio:.1f}x normaal)",
            CircuitBreakerReason.SESSION_ANOMALY: "Sessie anomalie gedetecteerd — veiligheid prioriteit",
            CircuitBreakerReason.MANUAL_STOP: "Handmatig gestopt via commando",
            CircuitBreakerReason.FTMO_RISK: "FTMO bescherming actief",
        }
        return descriptions.get(reason, "Onbekende circuit breaker")

    def _get_risk_level(self) -> str:
        dd = self._state._drawdown_pct
        if dd >= 0.055:     return "KRITIEK"
        elif dd >= 0.04:    return "HOOG"
        elif dd >= 0.025:   return "GEMIDDELD"
        elif dd >= 0.01:    return "LAAG"
        return "NORMAAL"


# ─────────────────────────────────────────────────────────────────
# FTMO COMPLIANCE CHECKER
# ─────────────────────────────────────────────────────────────────

class FTMOCompliance:
    """
    Volledige FTMO compliance checker.
    Bewaakt alle FTMO regels en geeft waarschuwingen voor mogelijke violations.
    """

    def __init__(
        self,
        starting_capital: float = FTMO_STARTING_CAPITAL,
        daily_loss_limit: float = FTMO_DAILY_LOSS_LIMIT,
        total_loss_limit: float = FTMO_TOTAL_LOSS_LIMIT,
    ):
        self._start = starting_capital
        self._daily_limit = daily_loss_limit
        self._total_limit = total_loss_limit

    def check(self, balance: float, day_start: float) -> dict:
        daily_loss = max(0.0, day_start - balance)
        total_loss = max(0.0, self._start - balance)

        daily_remaining = self._daily_limit - daily_loss
        total_remaining = self._total_limit - total_loss

        status = "PASS"
        warnings = []

        if daily_loss >= self._daily_limit:
            status = "FAIL_DAILY"
            warnings.append(f"Dag limiet overschreden: €{daily_loss:,.0f} / €{self._daily_limit:,.0f}")
        elif daily_loss >= self._daily_limit * 0.80:
            warnings.append(f"Dag limiet kritiek: €{daily_remaining:,.0f} resterend")

        if total_loss >= self._total_limit:
            status = "FAIL_TOTAL"
            warnings.append(f"Totaal drawdown overschreden: €{total_loss:,.0f} / €{self._total_limit:,.0f}")
        elif total_loss >= self._total_limit * 0.80:
            warnings.append(f"Totaal drawdown kritiek: €{total_remaining:,.0f} resterend")

        return {
            "status": status,
            "daily_loss": round(daily_loss, 2),
            "daily_limit": self._daily_limit,
            "daily_remaining": round(daily_remaining, 2),
            "daily_pct": round(daily_loss / self._daily_limit * 100, 1),
            "total_loss": round(total_loss, 2),
            "total_limit": self._total_limit,
            "total_remaining": round(total_remaining, 2),
            "total_pct": round(total_loss / self._total_limit * 100, 1),
            "warnings": warnings,
            "can_trade": status == "PASS",
        }
