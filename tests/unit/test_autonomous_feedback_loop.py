from __future__ import annotations

import pandas as pd

from autonomous_xauusd.brain_layer import derive_parameter_overrides
from autonomous_xauusd.models import StrategyParameters


def test_feedback_loop_tightens_parameters_from_winners():
    parameters = StrategyParameters(
        take_profit_atr=2.6,
        risk_per_trade=0.005,
        risk_strong_regime=0.015,
        risk_weak_regime=0.008,
    )
    trades = pd.DataFrame(
        [
            {"side": "buy", "label": 1, "rsi_fast": 31.0, "reward_risk_ratio": 2.2},
            {"side": "buy", "label": 1, "rsi_fast": 33.0, "reward_risk_ratio": 2.4},
            {"side": "sell", "label": 1, "rsi_fast": 68.0, "reward_risk_ratio": 2.1},
            {"side": "sell", "label": 0, "rsi_fast": 52.0, "reward_risk_ratio": 0.7},
        ]
    )
    importances = {"rsi_fast": 0.22}

    overrides = derive_parameter_overrides(trades, parameters, importances, accuracy=0.62)

    assert overrides["rsi_pullback_strong"] >= 25.0
    assert overrides["rsi_pullback_weak"] >= overrides["rsi_pullback_strong"]
    assert overrides["take_profit_atr"] > parameters.take_profit_atr
    assert overrides["risk_strong_regime"] >= parameters.risk_strong_regime


def test_feedback_loop_reduces_risk_when_accuracy_is_low():
    parameters = StrategyParameters(risk_strong_regime=0.015, risk_weak_regime=0.008)
    trades = pd.DataFrame([{"side": "buy", "label": 0, "rsi_fast": 49.0, "reward_risk_ratio": 0.8}])

    overrides = derive_parameter_overrides(trades, parameters, {"rsi_fast": 0.01}, accuracy=0.4)

    assert overrides["risk_strong_regime"] < parameters.risk_strong_regime
    assert overrides["risk_weak_regime"] < parameters.risk_weak_regime
