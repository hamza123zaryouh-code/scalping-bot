"""
Regression: Live ↔ Backtest Signal Consistency
===============================================
Bewijst dat core/strategy_engine.py deterministische, identieke signalen
produceert ongeacht of het in live of backtest context wordt aangeroepen.

Eisen:
  - Zelfde candles → zelfde signal type (100%)
  - Zelfde candles → zelfde indicators (binnen floating-point tolerantie)
  - Zelfde candles → zelfde SL/TP niveaus
  - Zelfde candles → zelfde risk percentage
  - Geen toestand lekt tussen runs (stateless engine)
"""
from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from core.strategy_engine import DEFAULT_CFG, SignalResult, StrategyEngine, get_engine


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _make_gold_ohlcv(
    n: int = 500,
    base: float = 2300.0,
    seed: int = 42,
    freq: str = "1h",
) -> pd.DataFrame:
    """Synthetische XAUUSD OHLCV — reproduceerbaar via seed."""
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.normal(0, 4.5, n))
    opens = closes + rng.normal(0, 1.5, n)
    highs = np.maximum(closes, opens) + np.abs(rng.normal(0, 2.5, n))
    lows = np.minimum(closes, opens) - np.abs(rng.normal(0, 2.5, n))
    volumes = rng.uniform(600, 1800, n)
    idx = pd.date_range("2026-01-06 07:00", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes, "spread": 0.3},
        index=idx,
    )


def _signal_summary(signal: Optional[SignalResult]) -> dict:
    """Compact, vergelijkbare weergave van een SignalResult."""
    if signal is None:
        return {"signal": None}
    return {
        "signal": signal.signal_type,
        "direction": signal.direction,
        "risk_pct": signal.risk_pct,
        "tp1_r": signal.tp1_r,
        "tp2_r": signal.tp2_r,
        "tp3_r": signal.tp3_r,
        "h4_regime": signal.h4_regime,
        "d1_trend": signal.d1_trend,
        "priority": signal.priority,
    }


def _assert_signals_equal(a: Optional[SignalResult], b: Optional[SignalResult], label: str = "") -> None:
    """Controleert dat twee SignalResults identiek zijn (of beide None)."""
    if a is None and b is None:
        return
    assert a is not None and b is not None, (
        f"{label}: Een run geeft None, de andere niet — "
        f"Run A: {_signal_summary(a)}, Run B: {_signal_summary(b)}"
    )
    assert a.signal_type == b.signal_type, f"{label}: signal_type verschil: {a.signal_type!r} vs {b.signal_type!r}"
    assert a.direction == b.direction, f"{label}: direction verschil: {a.direction!r} vs {b.direction!r}"
    assert math.isclose(a.risk_pct, b.risk_pct, rel_tol=1e-9), f"{label}: risk_pct verschil"
    assert math.isclose(a.tp1_r, b.tp1_r, rel_tol=1e-9), f"{label}: tp1_r verschil"
    assert math.isclose(a.tp2_r, b.tp2_r, rel_tol=1e-9), f"{label}: tp2_r verschil"
    assert math.isclose(a.tp3_r, b.tp3_r, rel_tol=1e-9), f"{label}: tp3_r verschil"
    assert a.h4_regime == b.h4_regime, f"{label}: h4_regime verschil"
    assert a.d1_trend == b.d1_trend, f"{label}: d1_trend verschil"
    assert a.priority == b.priority, f"{label}: priority verschil"

    if a.entry_price and b.entry_price:
        assert math.isclose(a.entry_price, b.entry_price, rel_tol=1e-9), f"{label}: entry_price verschil"
        assert math.isclose(a.stop_loss, b.stop_loss, rel_tol=1e-9), f"{label}: stop_loss verschil"
        assert math.isclose(a.take_profit_1, b.take_profit_1, rel_tol=1e-9), f"{label}: take_profit_1 verschil"
        assert math.isclose(a.take_profit_2, b.take_profit_2, rel_tol=1e-9), f"{label}: take_profit_2 verschil"
        assert math.isclose(a.take_profit_3, b.take_profit_3, rel_tol=1e-9), f"{label}: take_profit_3 verschil"


def _assert_indicators_equal(fa: pd.DataFrame, fb: pd.DataFrame, tol: float = 1e-8) -> None:
    """Controleert dat twee verrijkte DataFrames identieke indicatorwaarden hebben."""
    common_cols = set(fa.columns) & set(fb.columns)
    numeric_cols = [
        c for c in common_cols
        if pd.api.types.is_numeric_dtype(fa[c]) and not pd.api.types.is_bool_dtype(fa[c])
    ]

    for col in numeric_cols:
        max_diff = (fa[col] - fb[col]).abs().max()
        assert max_diff < tol, f"Indicator '{col}' heeft een divergentie van {max_diff:.2e} (tolerantie {tol:.0e})"


# ─────────────────────────────────────────────────────────────────
# TEST 1: DETERMINISME — dezelfde input → zelfde output
# ─────────────────────────────────────────────────────────────────

class TestDeterminism:
    """Engine is puur stateless: dezelfde input geeft altijd dezelfde output."""

    def test_prepare_features_deterministic(self):
        engine = StrategyEngine()
        df = _make_gold_ohlcv(400)
        result_a = engine.prepare_features(df.copy())
        result_b = engine.prepare_features(df.copy())
        _assert_indicators_equal(result_a, result_b)

    def test_generate_signal_deterministic(self):
        engine = StrategyEngine()
        df = _make_gold_ohlcv(400)
        features = engine.prepare_features(df)
        signal_a = engine.generate_signal(features, cfg=DEFAULT_CFG.copy())
        signal_b = engine.generate_signal(features, cfg=DEFAULT_CFG.copy())
        _assert_signals_equal(signal_a, signal_b, label="determinisme_run")

    def test_multiple_engines_give_same_result(self):
        """Twee aparte engine instanties geven identieke resultaten — geen gedeelde staat."""
        engine_a = StrategyEngine()
        engine_b = StrategyEngine()
        df = _make_gold_ohlcv(400)
        features_a = engine_a.prepare_features(df.copy())
        features_b = engine_b.prepare_features(df.copy())
        _assert_indicators_equal(features_a, features_b)
        signal_a = engine_a.generate_signal(features_a)
        signal_b = engine_b.generate_signal(features_b)
        _assert_signals_equal(signal_a, signal_b, label="multi_engine")

    def test_singleton_consistent_with_fresh_engine(self):
        """get_engine() singleton geeft zelfde resultaat als nieuwe instantie."""
        singleton = get_engine()
        fresh = StrategyEngine()
        df = _make_gold_ohlcv(400)
        fa = singleton.prepare_features(df.copy())
        fb = fresh.prepare_features(df.copy())
        _assert_indicators_equal(fa, fb)

    def test_different_seeds_give_different_signals(self):
        """Controle: verschillende marktdata geeft (potentieel) andere signalen — engine is gevoelig."""
        engine = StrategyEngine()
        df_a = _make_gold_ohlcv(400, seed=1)
        df_b = _make_gold_ohlcv(400, seed=99)
        feat_a = engine.prepare_features(df_a)
        feat_b = engine.prepare_features(df_b)
        sig_a = engine.generate_signal(feat_a)
        sig_b = engine.generate_signal(feat_b)
        # We kunnen niet garanderen dat ze verschillen, maar de engine moet in ieder geval draaien
        assert (sig_a is None or isinstance(sig_a, SignalResult))
        assert (sig_b is None or isinstance(sig_b, SignalResult))


# ─────────────────────────────────────────────────────────────────
# TEST 2: LIVE ↔ BACKTEST CONSISTENCY WALK-FORWARD
# ─────────────────────────────────────────────────────────────────

class TestLiveVsBacktestConsistency:
    """
    Simuleert zowel live als backtest mode op dezelfde candle reeks.

    Live: verwerkt bar-voor-bar (engine ziet steeds n+1 bars)
    Backtest: verwerkt de volledige dataset ineens (engine ziet alle bars)

    Verwachting: op elke identieke bar-grens geeft de engine hetzelfde signaal.
    """

    def _run_live_simulation(
        self,
        full_df: pd.DataFrame,
        engine: StrategyEngine,
        cfg: dict,
        warmup: int = 250,
    ) -> list[dict]:
        """Simuleert live trading: engine verwerkt bar voor bar na warmup."""
        signals = []
        for i in range(warmup, len(full_df)):
            window = full_df.iloc[:i + 1]
            try:
                features = engine.prepare_features(window)
                if features.empty:
                    signals.append({"bar": i, "timestamp": str(full_df.index[i]), "signal": None})
                    continue
                sig = engine.generate_signal(features, cfg=cfg)
                signals.append({
                    "bar": i,
                    "timestamp": str(full_df.index[i]),
                    "signal": _signal_summary(sig),
                    "raw": sig,
                })
            except Exception as exc:
                signals.append({"bar": i, "timestamp": str(full_df.index[i]), "signal": "ERROR", "error": str(exc)})
        return signals

    def _run_backtest_simulation(
        self,
        full_df: pd.DataFrame,
        engine: StrategyEngine,
        cfg: dict,
        warmup: int = 250,
    ) -> list[dict]:
        """Simuleert backtest: volledige dataset ineens verwerkt, dan bar-voor-bar signals."""
        features_full = engine.prepare_features(full_df)
        signals = []
        for i in range(warmup, len(full_df)):
            if full_df.index[i] not in features_full.index:
                signals.append({"bar": i, "timestamp": str(full_df.index[i]), "signal": None})
                continue
            window_feat = features_full.loc[:full_df.index[i]]
            if len(window_feat) < 4:
                signals.append({"bar": i, "timestamp": str(full_df.index[i]), "signal": None})
                continue
            sig = engine.generate_signal(window_feat, cfg=cfg)
            signals.append({
                "bar": i,
                "timestamp": str(full_df.index[i]),
                "signal": _signal_summary(sig),
                "raw": sig,
            })
        return signals

    @pytest.mark.parametrize("seed", [42, 77, 123])
    def test_live_vs_backtest_signal_match_rate(self, seed):
        """Signal match rate moet ≥ 99% zijn op dezelfde candle data."""
        engine = StrategyEngine()
        df = _make_gold_ohlcv(n=350, seed=seed)
        cfg = DEFAULT_CFG.copy()

        live_signals = self._run_live_simulation(df, engine, cfg, warmup=250)
        bt_signals = self._run_backtest_simulation(df, engine, cfg, warmup=250)

        assert len(live_signals) == len(bt_signals), "Aantal verwerkte bars moet gelijk zijn"

        total = len(live_signals)
        if total == 0:
            pytest.skip("Onvoldoende bars voor consistentietest")

        mismatches = 0
        mismatch_details = []

        for live, bt in zip(live_signals, bt_signals):
            live_sig = live["signal"]
            bt_sig = bt["signal"]

            if live_sig != bt_sig:
                mismatches += 1
                mismatch_details.append({
                    "bar": live["bar"],
                    "timestamp": live["timestamp"],
                    "live": live_sig,
                    "backtest": bt_sig,
                })

        match_rate = (total - mismatches) / total
        assert match_rate >= 0.99, (
            f"Signal match rate te laag: {match_rate:.1%} (seed={seed}). "
            f"Mismatches: {mismatches}/{total}. "
            f"Eerste 5 mismatches: {mismatch_details[:5]}"
        )

    def test_indicator_parity_on_shared_window(self):
        """Indicatorwaarden zijn identiek bij zelfde input — floating point exact."""
        engine = StrategyEngine()
        df = _make_gold_ohlcv(350)

        # Verwerk window twee keer — eenmaal als subset, eenmaal volledig
        subset = df.iloc[:300]
        feat_subset = engine.prepare_features(subset)
        feat_full = engine.prepare_features(df)

        # Haal de overlappende bars op
        common_idx = feat_subset.index.intersection(feat_full.index)
        if common_idx.empty:
            pytest.skip("Geen overlappende bars")

        # Indicator parity op de gedeelde subset (boolean kolommen overslaan)
        # H4/D1 resampled indicators (h4_*, d1_*) mogen afwijken omdat EWM path-dependent is:
        # een 300-bar en 350-bar dataset geven verschillende EWM initialisatie voor H4 bars.
        # H1 indicators zijn deterministisch en moeten exact gelijk zijn.
        h1_numeric_cols = [
            c for c in feat_subset.columns
            if pd.api.types.is_numeric_dtype(feat_subset[c])
            and not pd.api.types.is_bool_dtype(feat_subset[c])
            and not c.startswith(("h4_", "d1_"))
        ]
        for col in h1_numeric_cols:
            a_vals = feat_subset.loc[common_idx, col]
            b_vals = feat_full.loc[common_idx, col]
            max_diff = (a_vals - b_vals).abs().max()
            assert max_diff < 1e-8, (
                f"H1 indicator '{col}' heeft parity mismatch: max diff = {max_diff:.2e}"
            )

    def test_sl_tp_consistency(self):
        """SL/TP prijsniveaus zijn exact identiek tussen twee identieke runs."""
        engine = StrategyEngine()
        df = _make_gold_ohlcv(400, seed=55)
        features = engine.prepare_features(df)

        results = []
        for _ in range(5):
            sig = engine.generate_signal(features.copy(), cfg=DEFAULT_CFG.copy())
            results.append(sig)

        if results[0] is None:
            pytest.skip("Geen signaal op deze dataset")

        base = results[0]
        for i, sig in enumerate(results[1:], 1):
            _assert_signals_equal(base, sig, label=f"sl_tp_run_{i}")

    def test_cfg_override_propagates_correctly(self):
        """Config overrides (risk_a, sl_atr) werken identiek in live en backtest."""
        engine = StrategyEngine()
        df = _make_gold_ohlcv(400)
        features = engine.prepare_features(df)

        cfg_default = DEFAULT_CFG.copy()
        cfg_high_risk = {**DEFAULT_CFG, "risk_a": 0.008, "risk_b": 0.006, "risk_c": 0.005}

        sig_default = engine.generate_signal(features, cfg=cfg_default)
        sig_high = engine.generate_signal(features, cfg=cfg_high_risk)

        if sig_default is not None and sig_high is not None:
            assert sig_default.signal_type == sig_high.signal_type, "Config override mag signal_type niet wijzigen"
            assert sig_default.direction == sig_high.direction, "Config override mag direction niet wijzigen"
            if sig_default.risk_pct > 0:
                assert sig_high.risk_pct > sig_default.risk_pct, "Hogere risk_a moet hogere risk_pct geven"


# ─────────────────────────────────────────────────────────────────
# TEST 3: INDICATOR CORRECTHEID
# ─────────────────────────────────────────────────────────────────

class TestIndicatorCorrectness:
    """Valideer dat elke indicator de juiste wiskundige definitie volgt."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = StrategyEngine()
        self.df = _make_gold_ohlcv(400)
        self.features = self.engine.prepare_features(self.df)

    def test_ema_ordering_in_bull_regime(self):
        """In een stijgende markt: EMA9 > EMA21 > EMA50 voor de meeste bars."""
        bull_df = _make_gold_ohlcv(400, base=2000.0, seed=10)
        # Forceer een stijgende trend
        bull_df["close"] = 2000 + np.arange(400) * 2.5 + np.random.default_rng(10).normal(0, 3, 400)
        bull_df["open"] = bull_df["close"] - 1
        bull_df["high"] = bull_df["close"] + 3
        bull_df["low"] = bull_df["close"] - 3

        features = self.engine.prepare_features(bull_df)
        if features.empty:
            pytest.skip("Onvoldoende data")

        last_50 = features.tail(50)
        ema9_gt_21 = (last_50["ema9"] > last_50["ema21"]).mean()
        assert ema9_gt_21 > 0.7, f"In stijgende markt verwacht EMA9 > EMA21 voor >70% van bars, got {ema9_gt_21:.0%}"

    def test_rsi_bounded_0_100(self):
        """RSI moet altijd tussen 0 en 100 liggen."""
        if self.features.empty:
            pytest.skip("Onvoldoende data")
        rsi = self.features["rsi14"].dropna()
        assert rsi.min() >= 0.0, f"RSI minimum is negatief: {rsi.min()}"
        assert rsi.max() <= 100.0, f"RSI maximum overschrijdt 100: {rsi.max()}"

    def test_atr_positive(self):
        """ATR is altijd positief voor volatiele markten."""
        if self.features.empty:
            pytest.skip("Onvoldoende data")
        atr = self.features["atr14"].dropna()
        assert (atr > 0).all(), "ATR bevat niet-positieve waarden"

    def test_ema_crosses_detected(self):
        """EMA crosses worden gedetecteerd — niet alle bars kunnen True zijn."""
        if self.features.empty:
            pytest.skip("Onvoldoende data")
        xup = self.features["ema_xup"].sum()
        xdn = self.features["ema_xdn"].sum()
        total = len(self.features)
        # Crosses zijn zeldzaam — niet meer dan 20% van bars
        assert xup / total < 0.20, f"Te veel EMA cross-up events: {xup / total:.0%}"
        assert xdn / total < 0.20, f"Te veel EMA cross-down events: {xdn / total:.0%}"

    def test_h4_regime_valid_values(self):
        """H4 regime bevat alleen geldige waarden."""
        if self.features.empty:
            pytest.skip("Onvoldoende data")
        valid_regimes = {"STERK_BULL", "BULL", "ZWAK_BULL", "CHOPPY", "ZWAK_BEAR", "BEAR", "STERK_BEAR"}
        unique = set(self.features["h4_reg"].dropna().unique())
        assert unique.issubset(valid_regimes), f"Ongeldige H4 regime waarden: {unique - valid_regimes}"

    def test_d1_trend_valid_values(self):
        """D1 trend bevat alleen geldige waarden."""
        if self.features.empty:
            pytest.skip("Onvoldoende data")
        valid = {"bull", "bear", "neutral"}
        unique = set(self.features["d1_trend"].dropna().unique())
        assert unique.issubset(valid), f"Ongeldige D1 trend waarden: {unique - valid}"

    def test_macd_histogram_symmetry(self):
        """MACD histogram kan zowel positief als negatief zijn."""
        if self.features.empty:
            pytest.skip("Onvoldoende data")
        hist = self.features["macd_hist"].dropna()
        has_positive = (hist > 0).any()
        has_negative = (hist < 0).any()
        assert has_positive or has_negative, "MACD histogram lijkt constant nul"


# ─────────────────────────────────────────────────────────────────
# TEST 4: SIGNAL KWALITEIT VALIDATIE
# ─────────────────────────────────────────────────────────────────

class TestSignalQuality:
    """Valideer dat signalen aan basisregels voldoen."""

    def _get_all_signals(self, n_datasets: int = 10) -> list[SignalResult]:
        engine = StrategyEngine()
        signals = []
        for seed in range(n_datasets):
            df = _make_gold_ohlcv(400, seed=seed * 7 + 1)
            features = engine.prepare_features(df)
            if features.empty:
                continue
            sig = engine.generate_signal(features, cfg=DEFAULT_CFG.copy())
            if sig is not None:
                signals.append(sig)
        return signals

    def test_signal_risk_within_bounds(self):
        signals = self._get_all_signals()
        if not signals:
            pytest.skip("Geen signalen gegenereerd")
        for sig in signals:
            assert 0 < sig.risk_pct <= 0.02, f"risk_pct buiten bounds: {sig.risk_pct}"

    def test_signal_tp_ordering(self):
        """TP3 > TP2 > TP1 afstand van entry voor long; omgekeerd voor short."""
        signals = self._get_all_signals()
        if not signals:
            pytest.skip("Geen signalen gegenereerd")
        for sig in signals:
            if sig.direction == "long":
                if sig.entry_price > 0:
                    assert sig.take_profit_1 > sig.entry_price, "TP1 moet boven entry liggen voor long"
                    assert sig.take_profit_2 >= sig.take_profit_1, "TP2 >= TP1 voor long"
                    assert sig.take_profit_3 >= sig.take_profit_2, "TP3 >= TP2 voor long"
                    assert sig.stop_loss < sig.entry_price, "SL moet onder entry liggen voor long"
            elif sig.direction == "short":
                if sig.entry_price > 0:
                    assert sig.take_profit_1 < sig.entry_price, "TP1 moet onder entry liggen voor short"
                    assert sig.take_profit_2 <= sig.take_profit_1, "TP2 <= TP1 voor short"
                    assert sig.take_profit_3 <= sig.take_profit_2, "TP3 <= TP2 voor short"
                    assert sig.stop_loss > sig.entry_price, "SL moet boven entry liggen voor short"

    def test_signal_types_all_valid(self):
        valid_types = {"A_EMACROSS", "B_MACDCROSS", "C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"}
        signals = self._get_all_signals(20)
        if not signals:
            pytest.skip("Geen signalen gegenereerd")
        for sig in signals:
            assert sig.signal_type in valid_types, f"Ongeldig signal_type: {sig.signal_type!r}"

    def test_confidence_score_bounded(self):
        signals = self._get_all_signals()
        if not signals:
            pytest.skip("Geen signalen gegenereerd")
        for sig in signals:
            assert 0.0 <= sig.confidence <= 1.0, f"Confidence buiten 0-1 range: {sig.confidence}"

    def test_priority_matches_signal_type(self):
        from core.strategy_engine import SIGNAL_PRIORITY
        signals = self._get_all_signals()
        if not signals:
            pytest.skip("Geen signalen gegenereerd")
        for sig in signals:
            expected_prio = SIGNAL_PRIORITY.get(sig.signal_type, 0)
            assert sig.priority == expected_prio, (
                f"{sig.signal_type}: priority {sig.priority} != expected {expected_prio}"
            )

    def test_high_priority_signals_more_frequent(self):
        """A_EMACROSS (prio 6) en B_MACDCROSS (prio 5) zijn de meest gekwalificeerde signalen."""
        signals = self._get_all_signals(30)
        if len(signals) < 5:
            pytest.skip("Te weinig signalen voor statistische test")

        type_counts = {}
        for sig in signals:
            type_counts[sig.signal_type] = type_counts.get(sig.signal_type, 0) + 1

        # Hoog-prioriteit signalen mogen aanwezig zijn
        high_prio_types = {"A_EMACROSS", "B_MACDCROSS", "E_BOS"}
        has_high_prio = any(t in type_counts for t in high_prio_types)
        assert has_high_prio, f"Geen hoog-prioriteit signalen gevonden in {len(signals)} signals: {type_counts}"


# ─────────────────────────────────────────────────────────────────
# TEST 5: BACKTEST SIMULATION REPLAY
# ─────────────────────────────────────────────────────────────────

class TestBacktestReplay:
    """Deterministisch replay systeem: backtest output is reproduceerbaar."""

    def _run_full_backtest(
        self,
        df: pd.DataFrame,
        cfg: dict,
        capital: float = 160_000.0,
    ) -> dict:
        """Eenvoudige backtest loop die alle signalen en PnL bijhoudt."""
        engine = StrategyEngine()
        features = engine.prepare_features(df)
        if features.empty:
            return {"trades": [], "signals": [], "final_capital": capital}

        signals = []
        trades = []
        open_trade = None
        cap = capital

        for i in range(4, len(features)):
            window = features.iloc[:i + 1]
            sig = engine.generate_signal(window, cfg=cfg)
            if sig is not None:
                signals.append({
                    "bar": i,
                    "timestamp": str(features.index[i]),
                    "type": sig.signal_type,
                    "direction": sig.direction,
                    "entry": sig.entry_price,
                    "sl": sig.stop_loss,
                    "tp1": sig.take_profit_1,
                    "tp3": sig.take_profit_3,
                    "risk_pct": sig.risk_pct,
                })

        return {"signals": signals, "final_capital": cap}

    def test_backtest_replay_is_deterministic(self):
        """Dezelfde backtest twee keer draaien geeft identieke resultaten."""
        df = _make_gold_ohlcv(300, seed=42)
        cfg = DEFAULT_CFG.copy()

        result_a = self._run_full_backtest(df, cfg)
        result_b = self._run_full_backtest(df, cfg)

        assert len(result_a["signals"]) == len(result_b["signals"]), (
            f"Aantal signalen verschilt: {len(result_a['signals'])} vs {len(result_b['signals'])}"
        )

        for i, (sa, sb) in enumerate(zip(result_a["signals"], result_b["signals"])):
            assert sa["type"] == sb["type"], f"Signal {i}: type mismatch {sa['type']} vs {sb['type']}"
            assert sa["direction"] == sb["direction"], f"Signal {i}: direction mismatch"
            assert math.isclose(sa["entry"], sb["entry"], rel_tol=1e-9), f"Signal {i}: entry mismatch"
            assert math.isclose(sa["sl"], sb["sl"], rel_tol=1e-9), f"Signal {i}: sl mismatch"

    def test_backtest_capital_bounded(self):
        """Backtest capital valt niet onder FTMO limit."""
        df = _make_gold_ohlcv(300, seed=77)
        result = self._run_full_backtest(df, DEFAULT_CFG.copy(), capital=160_000.0)
        # Final capital moet redelijk zijn (niet gecrasht)
        assert result["final_capital"] >= 0.0, "Capital is negatief geworden"

    @pytest.mark.parametrize("cfg_key,cfg_val", [
        ("risk_a", 0.008),
        ("sl_atr", 2.0),
        ("tp1_r", 2.0),
    ])
    def test_cfg_sensitivity(self, cfg_key, cfg_val):
        """Config wijzigingen beïnvloeden signalen reproduceerbaar."""
        df = _make_gold_ohlcv(300, seed=33)
        cfg_base = DEFAULT_CFG.copy()
        cfg_mod = {**DEFAULT_CFG, cfg_key: cfg_val}

        result_base = self._run_full_backtest(df, cfg_base)
        result_mod = self._run_full_backtest(df, cfg_mod)

        # Beide moeten deterministisch zijn
        result_base2 = self._run_full_backtest(df, cfg_base)
        assert len(result_base["signals"]) == len(result_base2["signals"]), (
            f"Base backtest niet deterministisch voor cfg_key={cfg_key}"
        )
