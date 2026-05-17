"""
XAUUSD V17 Strategy Engine — Één Bron van Waarheid
===================================================
Centrale signaallogica gebaseerd op Strategy V16.
Alle signalen (live, backtest, optimizer, AI, Telegram, dashboard)
komen uitsluitend uit deze module.

6 Signaaltypen (prioriteit A→F):
  A_EMACROSS     — EMA9 cross + MACD positief (hoogste kwaliteit)
  B_MACDCROSS    — MACD cross + EMA aligned
  E_BOS          — Break of Structure
  C_MOMENTUM     — Momentum continuation (volledige EMA stack)
  F_MSS          — Market Structure Shift
  D_PULLBACK     — Pullback naar EMA21 in sterke trend

Multi-TF: H1 indicators + H4 regime + D1 trend
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────
# DEFAULT PARAMETERS (V17-Basis — FTMO safe, €16k/77d target)
# ─────────────────────────────────────────────────────────────────

DEFAULT_CFG: dict = {
    "risk_a": 0.0120,       # EMA cross — sterkste signaal
    "risk_b": 0.0090,       # MACD cross / BOS / Momentum
    "risk_c": 0.0075,       # Pullback / MSS
    "adx_min": 10,          # Minimale ADX H1
    "h4adx_min": 14,        # Minimale ADX H4
    "vol_mult": 1.00,       # Volume multiplier filter
    "tp1_r": 1.5,           # TP1 reward ratio
    "tp2_r": 3.0,           # TP2 reward ratio
    "tp3_r": 5.0,           # TP3 reward ratio
    "tp1_pct": 0.30,        # Fractie positie bij TP1
    "tp2_pct": 0.30,        # Fractie positie bij TP2
    "sl_atr": 1.5,          # SL ATR multiplier
    "sl_max": 2.0,          # Max SL ATR multiplier
    "max_dag": 10,          # Max trades per dag
    "sl_dag_max": 3,        # Max SL's per dag
    "cooldown_h": 1,        # Cooldown uren tussen trades
    "trailing": True,       # Trailing stop na TP1
    "breakeven_r": 0.8,     # Breakeven stop na 0.8R winst
    "kz_mult": 1.25,        # Risico multiplier tijdens kill zones
}

# ─────────────────────────────────────────────────────────────────
# V18 PARAMETERS (Sprint Config — doel: €30k in 60 dagen)
# FTMO-veilig: verwachte max DD ~2.5-3.2% (limiet 6%)
# Compound groeit automatisch: risk_usd = risk_pct × huidige equity
# ─────────────────────────────────────────────────────────────────

V18_CFG: dict = {
    # ── Risico per signaaltype (FTMO-safe op €160k) ────────────────
    "risk_a": 0.0150,       # EMA cross — 1.5% | KZ: 1.875% met kz_mult
    "risk_b": 0.0120,       # MACD/BOS/Momentum — 1.2%
    "risk_c": 0.0100,       # Pullback/MSS — 1.0%
    # ── Signaalfilters ─────────────────────────────────────────────
    "adx_min": 9,           # Minimale ADX H1
    "h4adx_min": 12,        # Minimale ADX H4
    "vol_mult": 1.00,       # Volume filter
    # ── Take profit niveaus ────────────────────────────────────────
    "tp1_r": 1.5,           # TP1 reward ratio
    "tp2_r": 3.5,           # TP2 reward ratio
    "tp3_r": 6.5,           # TP3 reward ratio (grote runners)
    "tp1_pct": 0.25,        # 25% uitstappen bij TP1
    "tp2_pct": 0.30,        # 30% bij TP2
    # ── Stop loss ─────────────────────────────────────────────────
    "sl_atr": 1.5,          # SL ATR multiplier
    "sl_max": 2.0,          # Max SL ATR multiplier
    # ── Trade frequentie ──────────────────────────────────────────
    "max_dag": 10,          # Max trades per dag
    "sl_dag_max": 3,        # Max SL's per dag
    "cooldown_h": 0.5,      # Cooldown 30 min
    # ── Trailing / breakeven ──────────────────────────────────────
    "trailing": True,       # Trailing stop actief
    "breakeven_r": 0.7,     # Breakeven na 0.7R winst
    # ── Kill zone boost ────────────────────────────────────────────
    "kz_mult": 1.25,        # Kill zone boost +25% — London/NY open premium
    # ── Compound systeem ──────────────────────────────────────────
    "weekly_compound": True,    # Wekelijkse compound herberekening
    "compound_boost": 1.08,     # +8% risico-budget na elke winstgevende week
    # ── FTMO limieten ─────────────────────────────────────────────
    "max_lot_size": 4.0,            # Harde lot cap
    "max_daily_loss_eur": 6_000.0,  # Dagelijkse verliesgrens €6k
}

# ─────────────────────────────────────────────────────────────────
# V19 PARAMETERS (Verbeterd — betere verliesweek-bescherming)
# Fixes: tighter filters, conservative compound, weekly loss protection
# ─────────────────────────────────────────────────────────────────

V19_CFG: dict = {
    **V18_CFG,
    # ── Betere risk/reward (grotere winnaars, sneller breakeven) ──
    "tp3_r": 7.0,              # grotere runners lopen langer
    "tp1_pct": 0.20,           # minder sluiten bij TP1, meer laten lopen
    "breakeven_r": 0.65,       # sneller breakeven na 0.65R winst
    "compound_decay": 0.85,    # compound verlagen na verliesweek
    # ── Verliesweek-bescherming ────────────────────────────────────
    "weekly_loss_threshold": 0.015,   # -1.5% deze week → risico verlagen
    "weekly_loss_risk_scale": 0.55,   # risico → 55% bij verliesweek
    "loss_day_filter": True,          # na 2 verlies-dagen: alleen A/B/F signalen
}

# ─────────────────────────────────────────────────────────────────
# V20 PARAMETERS (Stabiel — FTMO-safe, reset elke 3 weken)
# ─────────────────────────────────────────────────────────────────

V20_CFG: dict = {
    **V19_CFG,
    # ── Maandelijks winstdoel ──────────────────────────────────────
    "monthly_profit_target": 40_000.0,
    "monthly_min_target":    20_000.0,
    # ── 3-weken reset systeem ─────────────────────────────────────
    "reset_weeks":   3,
    "reset_capital": 160_000.0,
}

# Signal prioriteit
SIGNAL_PRIORITY: dict[str, int] = {
    "A_EMACROSS": 6,
    "B_MACDCROSS": 5,
    "E_BOS": 4,
    "C_MOMENTUM": 3,
    "F_MSS": 2,
    "D_PULLBACK": 1,
}


# ─────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class SignalResult:
    direction: str          # "long" | "short"
    signal_type: str        # A_EMACROSS | B_MACDCROSS | C_MOMENTUM | D_PULLBACK | E_BOS | F_MSS
    risk_pct: float         # Risicopercentage van kapitaal
    tp1_r: float
    tp2_r: float
    tp3_r: float
    priority: int
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    take_profit_3: float = 0.0
    atr: float = 0.0
    h4_regime: str = "CHOPPY"
    d1_trend: str = "neutral"
    adx: float = 0.0
    rsi: float = 50.0
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"
    confidence: float = 0.0
    reason: str = ""
    timestamp: Optional[datetime] = None
    features: dict = field(default_factory=dict)


@dataclass
class BarFeatures:
    """Volledig verrijkte bar met alle indicatoren."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    # H1 indicators
    ema9: float = 0.0
    ema21: float = 0.0
    ema50: float = 0.0
    ema200: float = 0.0
    rsi14: float = 50.0
    atr14: float = 1.0
    adx14: float = 0.0
    macd_hist: float = 0.0
    macd_xup: bool = False
    macd_xdn: bool = False
    ema_xup: bool = False
    ema_xdn: bool = False
    vol_ma: float = 0.0
    hh5: float = 0.0
    ll5: float = 0.0
    hh10: float = 0.0
    ll10: float = 0.0
    dist21: float = 0.0
    rsi_recov: bool = False
    bos_bull: bool = False
    bos_bear: bool = False
    mss_bull: bool = False
    mss_bear: bool = False
    # H4 regime
    h4_reg: str = "CHOPPY"
    h4_atr: float = 0.0
    h4_adx: float = 0.0
    h4_sl: float = 0.0
    h4_rsi: float = 50.0
    # D1 trend
    d1_trend: str = "neutral"


# ─────────────────────────────────────────────────────────────────
# INDICATOR FUNCTIES (puur, geen side-effects)
# ─────────────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, p: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(com=p - 1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=p - 1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-10))


def _atr(hi: pd.Series, lo: pd.Series, cl: pd.Series, p: int = 14) -> pd.Series:
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=p - 1, adjust=False).mean()


def _adx(hi: pd.Series, lo: pd.Series, cl: pd.Series, p: int = 14) -> pd.Series:
    u = hi.diff()
    dw = -lo.diff()
    pm = ((u > dw) & (u > 0)) * u
    mm = ((dw > u) & (dw > 0)) * dw
    at = _atr(hi, lo, cl, p).replace(0, np.nan)
    pdi = 100 * pm.ewm(com=p - 1, adjust=False).mean() / at
    mdi = 100 * mm.ewm(com=p - 1, adjust=False).mean() / at
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(com=p - 1, adjust=False).mean().fillna(0)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    ml = _ema(close, fast) - _ema(close, slow)
    sl = _ema(ml, sig)
    return ml, sl, ml - sl


def _safe(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────
# FEATURE PREPARATION
# ─────────────────────────────────────────────────────────────────

class StrategyEngine:
    """
    Centrale strategy engine — V16 logica als productie-API.

    Gebruik:
        engine = StrategyEngine()
        df = engine.prepare_features(raw_df)          # verrijkt df
        signal = engine.generate_signal(df, cfg)       # SignalResult | None
        sl, tp1, tp2, tp3 = engine.calculate_levels(signal, entry_price, atr)
    """

    def __init__(self) -> None:
        self.cfg: dict = dict(DEFAULT_CFG)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Verrijkt een OHLCV DataFrame met alle V16 indicatoren.
        Input: DataFrame met kolommen [open, high, low, close, volume]
               Index: DatetimeTZAware (UTC)
        Output: Verrijkt DataFrame met alle indicator kolommen.
        """
        if df.empty or len(df) < 20:
            return pd.DataFrame()

        d = df.copy()
        d.columns = [c.lower() for c in d.columns]

        if not isinstance(d.index, pd.DatetimeIndex):
            d.index = pd.to_datetime(d.index, utc=True)
        elif d.index.tz is None:
            d.index = d.index.tz_localize("UTC")

        # ── H1 indicatoren ──────────────────────────────────────
        d["ema9"] = _ema(d["close"], 9)
        d["ema21"] = _ema(d["close"], 21)
        d["ema50"] = _ema(d["close"], 50)
        d["ema200"] = _ema(d["close"], 200)
        d["rsi14"] = _rsi(d["close"], 14)
        d["atr14"] = _atr(d["high"], d["low"], d["close"], 14)
        d["atr_ma"] = d["atr14"].rolling(20).mean()
        d["adx14"] = _adx(d["high"], d["low"], d["close"], 14)

        _, _, hist = _macd(d["close"])
        d["macd_hist"] = hist
        d["macd_xup"] = (hist > 0) & (hist.shift(1) <= 0)
        d["macd_xdn"] = (hist < 0) & (hist.shift(1) >= 0)
        d["ema_xup"] = (d["ema9"] > d["ema21"]) & (d["ema9"].shift(1) <= d["ema21"].shift(1))
        d["ema_xdn"] = (d["ema9"] < d["ema21"]) & (d["ema9"].shift(1) >= d["ema21"].shift(1))

        d["vol_ma"] = d["volume"].rolling(20).mean()

        # Structure levels
        d["hh5"] = d["high"].rolling(5).max().shift(1)
        d["ll5"] = d["low"].rolling(5).min().shift(1)
        d["hh10"] = d["high"].rolling(10).max().shift(1)
        d["ll10"] = d["low"].rolling(10).min().shift(1)

        d["dist21"] = (d["close"] - d["ema21"]) / d["atr14"].replace(0, np.nan)

        d["rsi_recov"] = (
            (d["rsi14"] > d["rsi14"].shift(1)) &
            (d["rsi14"].shift(1) < d["rsi14"].shift(2)) &
            (d["rsi14"] > 48)
        )

        # ── H4 regime ───────────────────────────────────────────
        h4 = d.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        h4["e21"] = _ema(h4["close"], 21)
        h4["e50"] = _ema(h4["close"], 50)
        h4["e200"] = _ema(h4["close"], 200)
        h4["adx"] = _adx(h4["high"], h4["low"], h4["close"], 14)
        h4["atr"] = _atr(h4["high"], h4["low"], h4["close"], 14)
        h4["rsi"] = _rsi(h4["close"], 14)
        h4["sl21"] = h4["e21"] - h4["e21"].shift(3)
        h4["regime"] = h4.apply(self._h4_regime, axis=1)

        for col, src in [
            ("h4_reg", "regime"), ("h4_atr", "atr"),
            ("h4_adx", "adx"), ("h4_sl", "sl21"),
            ("h4_rsi", "rsi"), ("h4_e21", "e21"),
            ("h4_e50", "e50"),
        ]:
            d[col] = h4[src].reindex(d.index, method="ffill")
        d["h4_reg"] = d["h4_reg"].fillna("CHOPPY")
        d["h4_adx"] = d["h4_adx"].fillna(0)
        d["h4_sl"] = d["h4_sl"].fillna(0)
        d["h4_rsi"] = d["h4_rsi"].fillna(50)

        # ── D1 trend ────────────────────────────────────────────
        d1 = d.resample("1D").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        if len(d1) >= 3:
            d1["e50"] = _ema(d1["close"], 50)
            d1["e200"] = _ema(d1["close"], 200)
            d1["sl50"] = d1["e50"] - d1["e50"].shift(5)
            d1["trend"] = np.where(
                (d1["close"] > d1["e50"]) & (d1["sl50"] > 0), "bull",
                np.where(
                    (d1["close"] < d1["e50"]) & (d1["sl50"] < 0), "bear",
                    "neutral",
                ),
            )
        else:
            d1["trend"] = "neutral"
        d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("neutral")

        # ── Structure patterns ──────────────────────────────────
        d["bos_bull"] = d["close"] > d["hh10"]
        d["bos_bear"] = d["close"] < d["ll10"]
        d["mss_bull"] = (
            (d["ema9"] > d["ema21"]) &
            (d["ema9"].shift(3) < d["ema21"].shift(3)) &
            (d["rsi14"] > 52)
        )
        d["mss_bear"] = (
            (d["ema9"] < d["ema21"]) &
            (d["ema9"].shift(3) > d["ema21"].shift(3)) &
            (d["rsi14"] < 48)
        )

        return d.dropna(subset=["ema9", "ema21", "ema50", "ema200", "rsi14", "atr14", "h4_atr"])

    @staticmethod
    def _h4_regime(r) -> str:
        bull = r["e21"] > r["e50"]
        bear = r["e21"] < r["e50"]
        a200 = r["e50"] > r["e200"]
        b200 = r["e50"] < r["e200"]
        adx = r["adx"]
        sl = r["sl21"]
        if bull and adx >= 20 and sl > 0 and a200:  return "STERK_BULL"
        if bull and adx >= 14:                       return "BULL"
        if bull:                                     return "ZWAK_BULL"
        if bear and adx >= 20 and sl < 0 and b200:  return "STERK_BEAR"
        if bear and adx >= 14:                       return "BEAR"
        if bear:                                     return "ZWAK_BEAR"
        return "CHOPPY"

    def generate_signal(
        self,
        df: pd.DataFrame,
        cfg: Optional[dict] = None,
        sentiment_score: float = 0.0,
        sentiment_label: str = "neutral",
        ml_confidence: float = 0.5,
        is_killzone: bool = False,
    ) -> Optional[SignalResult]:
        """
        Genereert een SignalResult op basis van de laatste volledige bar.
        Retourneert None als er geen valide signaal is.

        Args:
            df: Verrijkt DataFrame (output van prepare_features)
            cfg: Strategy configuratie (gebruikt DEFAULT_CFG als None)
            sentiment_score: Float -1.0 tot 1.0 (negatief = bearish)
            sentiment_label: sterk_bearish | bearish | neutral | bullish | sterk_bullish
            ml_confidence: ML model confidence score (0.0 - 1.0)
        """
        if len(df) < 4:
            return None

        params = {**DEFAULT_CFG, **(cfg or {})}
        bar = df.iloc[-2]  # laatste volledige bar (niet de huidige open bar)

        h4reg = str(bar.get("h4_reg", "CHOPPY"))
        d1t = str(bar.get("d1_trend", "neutral"))
        rsi14 = _safe(bar.get("rsi14", 50.0), 50.0)
        cl = _safe(bar.get("close", 0.0))
        e9 = _safe(bar.get("ema9", 0.0))
        e21 = _safe(bar.get("ema21", 0.0))
        e50 = _safe(bar.get("ema50", 0.0))
        e200 = _safe(bar.get("ema200", 0.0))
        adx = _safe(bar.get("adx14", 0.0))
        h4adx = _safe(bar.get("h4_adx", 0.0))
        h4sl = _safe(bar.get("h4_sl", 0.0))
        macdh = _safe(bar.get("macd_hist", 0.0))
        dist21 = _safe(bar.get("dist21", 0.0))
        vol = _safe(bar.get("volume", 0.0))
        vol_ma = _safe(bar.get("vol_ma", 1.0), 1.0)
        rsi_rec = bool(bar.get("rsi_recov", False))
        ema_xup = bool(bar.get("ema_xup", False))
        ema_xdn = bool(bar.get("ema_xdn", False))
        macd_xu = bool(bar.get("macd_xup", False))
        macd_xd = bool(bar.get("macd_xdn", False))
        bos_b = bool(bar.get("bos_bull", False))
        bos_be = bool(bar.get("bos_bear", False))
        mss_b = bool(bar.get("mss_bull", False))
        mss_be = bool(bar.get("mss_bear", False))
        atr14 = _safe(bar.get("atr14", 1.0), 1.0)

        kz_mult = params.get("kz_mult", 1.25) if is_killzone else 1.0
        risk_a = params["risk_a"] * kz_mult
        risk_b = params["risk_b"] * kz_mult
        risk_c = params["risk_c"] * kz_mult
        adx_min = params["adx_min"]
        h4a_min = params["h4adx_min"]
        vol_f = params["vol_mult"]
        tp1r = params["tp1_r"]
        tp2r = params["tp2_r"]
        tp3r = params["tp3_r"]

        # ── Globale filters ──────────────────────────────────────
        if h4adx < h4a_min:
            return None
        if adx < adx_min * 0.75:
            return None
        if vol_ma > 100 and vol < vol_f * vol_ma:
            return None

        # ── Sentiment blokkering ─────────────────────────────────
        # sterk_bearish blokkeert longs; sterk_bullish blokkeert shorts
        block_long = sentiment_label == "sterk_bearish"
        block_short = sentiment_label == "sterk_bullish"

        # Sentiment boost: bullish nieuws verhoogt risk voor longs
        sent_mult_long = 1.15 if sentiment_label in ("sterk_bullish", "bullish") else 1.0
        sent_mult_short = 1.15 if sentiment_label in ("sterk_bearish", "bearish") else 1.0

        sigs: list[tuple] = []

        # ── LONG signalen ────────────────────────────────────────
        bull_ok = (
            not block_long and
            h4reg in ("STERK_BULL", "BULL", "ZWAK_BULL") and
            d1t in ("bull", "neutral") and
            cl > e50 and
            cl > e200 * 0.998
        )

        if bull_ok:
            rsi_lo, rsi_hi = 47, 72

            if ema_xup and macdh > -1.0 and rsi_lo <= rsi14 <= rsi_hi and h4reg in ("STERK_BULL", "BULL"):
                sigs.append(("long", "A_EMACROSS", risk_a * sent_mult_long, tp1r, tp2r, tp3r))

            if macd_xu and e9 > e21 and rsi_lo <= rsi14 <= rsi_hi - 3 and h4sl > 0:
                sigs.append(("long", "B_MACDCROSS", risk_b * sent_mult_long, tp1r, tp2r, tp3r))

            # C_MOMENTUM: alleen STERK_BULL + hogere ADX + sterkere momentum
            if (e9 > e21 > e50 and 50 <= rsi14 <= 65 and macdh > 0.5
                    and h4sl > 0.3 and rsi_rec and h4reg == "STERK_BULL" and adx > 20):
                sigs.append(("long", "C_MOMENTUM", risk_b * sent_mult_long, tp1r, tp2r, tp3r))

            # D_PULLBACK: schonere pullback range (dichter bij EMA21)
            if (h4reg == "STERK_BULL" and -0.2 <= dist21 <= 0.6
                    and cl > e21 and 50 <= rsi14 <= 61 and e9 > e21 and macdh > -0.5):
                sigs.append(("long", "D_PULLBACK", risk_c * sent_mult_long, tp1r, tp2r, tp3r))

            # E_BOS: risk_c (was risk_b) + strengere ADX-filter
            if (bos_b and cl > e21 and 53 <= rsi14 <= 68
                    and adx > 22 and h4reg in ("STERK_BULL", "BULL")):
                sigs.append(("long", "E_BOS", risk_c * sent_mult_long, tp1r * 0.9, tp2r, tp3r * 0.9))

            if (mss_b and 50 <= rsi14 <= 65 and cl > e21
                    and h4reg in ("STERK_BULL", "BULL") and h4sl > 0):
                sigs.append(("long", "F_MSS", risk_c * sent_mult_long, tp1r, tp2r, tp3r))

        # ── SHORT signalen ───────────────────────────────────────
        bear_ok = (
            not block_short and
            h4reg in ("STERK_BEAR", "BEAR", "ZWAK_BEAR") and
            d1t in ("bear", "neutral") and
            cl < e50 and
            cl < e200 * 1.002
        )

        if bear_ok:
            rsi_lo, rsi_hi = 28, 53

            if ema_xdn and macdh < 1.0 and rsi_lo <= rsi14 <= rsi_hi and h4reg in ("STERK_BEAR", "BEAR"):
                sigs.append(("short", "A_EMACROSS", risk_a * sent_mult_short, tp1r, tp2r, tp3r))

            if macd_xd and e9 < e21 and rsi_lo + 3 <= rsi14 <= rsi_hi and h4sl < 0:
                sigs.append(("short", "B_MACDCROSS", risk_b * sent_mult_short, tp1r, tp2r, tp3r))

            # C_MOMENTUM: alleen STERK_BEAR + hogere ADX + sterkere neerwaartse momentum
            if (e9 < e21 < e50 and 35 <= rsi14 <= rsi_hi and macdh < -0.5
                    and h4sl < -0.3 and h4reg == "STERK_BEAR" and adx > 20):
                sigs.append(("short", "C_MOMENTUM", risk_b * sent_mult_short, tp1r, tp2r, tp3r))

            # D_PULLBACK: schonere pullback range (dichter bij EMA21)
            if (h4reg == "STERK_BEAR" and -0.6 <= dist21 <= 0.2
                    and cl < e21 and 39 <= rsi14 <= rsi_hi and e9 < e21 and macdh < 0.5):
                sigs.append(("short", "D_PULLBACK", risk_c * sent_mult_short, tp1r, tp2r, tp3r))

            # E_BOS: risk_c (was risk_b) + strengere ADX-filter
            if (bos_be and cl < e21 and rsi_lo <= rsi14 <= rsi_hi - 2
                    and adx > 22 and h4reg in ("STERK_BEAR", "BEAR")):
                sigs.append(("short", "E_BOS", risk_c * sent_mult_short, tp1r * 0.9, tp2r, tp3r * 0.9))

            if (mss_be and 35 <= rsi14 <= rsi_hi and cl < e21
                    and h4reg in ("STERK_BEAR", "BEAR") and h4sl < 0):
                sigs.append(("short", "F_MSS", risk_c * sent_mult_short, tp1r, tp2r, tp3r))

        if not sigs:
            return None

        # Prioriteit sortering
        sigs.sort(key=lambda x: SIGNAL_PRIORITY.get(x[1], 0), reverse=True)
        direction, sig_type, risk_pct, t1r, t2r, t3r = sigs[0]
        priority = SIGNAL_PRIORITY.get(sig_type, 0)

        # SL berekening
        h4_atr = _safe(bar.get("h4_atr", atr14 * 4), atr14 * 4)
        ll5 = _safe(bar.get("ll5", cl - 9999))
        hh5 = _safe(bar.get("hh5", cl + 9999))
        sl_atr_m = params["sl_atr"]
        sl_max_m = params["sl_max"]

        if direction == "long":
            swing_sl = ll5 - 0.15 * atr14
            atr_sl = cl - sl_atr_m * h4_atr * 0.25
            sl_raw = max(swing_sl, atr_sl)
            sl_dist = cl - sl_raw
        else:
            swing_sl = hh5 + 0.15 * atr14
            atr_sl = cl + sl_atr_m * h4_atr * 0.25
            sl_raw = min(swing_sl, atr_sl)
            sl_dist = sl_raw - cl

        min_sl = 0.5 * atr14
        max_sl = sl_max_m * atr14 * 4
        sl_dist = max(min_sl, min(max_sl, sl_dist))

        d = 1 if direction == "long" else -1
        sl = cl - d * sl_dist
        tp1 = cl + d * t1r * sl_dist
        tp2 = cl + d * t2r * sl_dist
        tp3 = cl + d * t3r * sl_dist

        # Confidence: combinatie van signal prioriteit + ML + sentiment
        prio_conf = priority / 6.0
        sent_conf = abs(sentiment_score) * 0.3 if sentiment_score != 0 else 0.0
        confidence = round(min(0.95, prio_conf * 0.5 + ml_confidence * 0.35 + sent_conf * 0.15), 3)

        breakeven_r = params.get("breakeven_r", 0.8)
        kz_tag = " KZ" if is_killzone else ""
        reason = (
            f"{sig_type}{kz_tag}: H4={h4reg} D1={d1t} RSI={rsi14:.0f} "
            f"ADX={adx:.0f} MACD_H={macdh:.1f} "
            f"Sent={sentiment_label}({sentiment_score:+.2f}) "
            f"Conf={confidence:.0%}"
        )

        ts = bar.name if hasattr(bar.name, "to_pydatetime") else datetime.now(timezone.utc)
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()

        return SignalResult(
            direction=direction,
            signal_type=sig_type,
            risk_pct=round(risk_pct, 5),
            tp1_r=t1r,
            tp2_r=t2r,
            tp3_r=t3r,
            priority=priority,
            entry_price=round(cl, 3),
            stop_loss=round(sl, 3),
            take_profit_1=round(tp1, 3),
            take_profit_2=round(tp2, 3),
            take_profit_3=round(tp3, 3),
            atr=round(atr14, 4),
            h4_regime=h4reg,
            d1_trend=d1t,
            adx=round(adx, 2),
            rsi=round(rsi14, 2),
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            confidence=confidence,
            reason=reason,
            timestamp=ts,
            features={
                "rsi14": rsi14, "adx14": adx, "macd_hist": macdh,
                "h4_adx": h4adx, "h4_reg": h4reg, "d1_trend": d1t,
                "ema_xup": ema_xup, "ema_xdn": ema_xdn,
                "macd_xup": macd_xu, "macd_xdn": macd_xd,
                "bos_bull": bos_b, "bos_bear": bos_be,
                "mss_bull": mss_b, "mss_bear": mss_be,
                "dist21": dist21, "h4_sl": h4sl, "atr14": atr14,
                "sentiment": sentiment_score,
                "breakeven_r": breakeven_r,
                "is_killzone": is_killzone,
                "kz_mult": kz_mult,
            },
        )

    def get_session(self, dt: datetime) -> str:
        """Geeft sessie terug op basis van UTC uur (compatibel met V16)."""
        uur = dt.hour
        dow = dt.weekday()
        if dow >= 5:              return "blocked"
        if dow == 0 and uur < 7:  return "blocked"
        if dow == 4 and uur >= 17: return "blocked"
        if 7 <= uur < 12:         return "premium"
        if 13 <= uur <= 17:       return "premium"
        if uur == 12:             return "standard"
        return "blocked"


# ─────────────────────────────────────────────────────────────────
# SINGLETON INSTANCE
# ─────────────────────────────────────────────────────────────────

_engine_instance: Optional[StrategyEngine] = None
_engine_lock = threading.Lock()


def get_engine(cfg_override: dict | None = None) -> StrategyEngine:
    """Geeft de singleton StrategyEngine terug. cfg_override wordt samengevouwen met DEFAULT_CFG."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = StrategyEngine()
        if cfg_override:
            _engine_instance.cfg = {**_engine_instance.cfg, **cfg_override}
        return _engine_instance
