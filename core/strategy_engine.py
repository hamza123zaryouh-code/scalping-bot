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

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────
# DEFAULT PARAMETERS (V17-Basis — FTMO safe, €16k/77d target)
# ─────────────────────────────────────────────────────────────────

DEFAULT_CFG: dict = {
    "risk_a": 0.0120,  # EMA cross — sterkste signaal
    "risk_b": 0.0090,  # MACD cross / BOS / Momentum
    "risk_c": 0.0075,  # Pullback / MSS
    "adx_min": 10,  # Minimale ADX H1
    "h4adx_min": 14,  # Minimale ADX H4
    "vol_mult": 1.00,  # Volume multiplier filter
    "tp1_r": 1.5,  # TP1 reward ratio
    "tp2_r": 3.0,  # TP2 reward ratio
    "tp3_r": 5.0,  # TP3 reward ratio
    "tp1_pct": 0.30,  # Fractie positie bij TP1
    "tp2_pct": 0.30,  # Fractie positie bij TP2
    "sl_atr": 1.5,  # SL ATR multiplier
    "sl_max": 2.0,  # Max SL ATR multiplier
    "max_dag": 10,  # Max trades per dag
    "sl_dag_max": 3,  # Max SL's per dag
    "cooldown_h": 1,  # Cooldown uren tussen trades
    "trailing": True,  # Trailing stop na TP1
    "breakeven_r": 0.8,  # Breakeven stop na 0.8R winst
    "kz_mult": 1.25,  # Risico multiplier tijdens kill zones
    "pullback_dist_long_min": -0.15,
    "pullback_dist_long_max": 0.35,
    "pullback_dist_short_min": -0.35,
    "pullback_dist_short_max": 0.15,
    "pullback_rsi_long_min": 52,
    "pullback_rsi_long_max": 60,
    "pullback_rsi_short_min": 40,
    "pullback_rsi_short_max": 50,
    "pullback_min_adx": 18,
    "pullback_min_h4_slope": 0.45,
    "pullback_vol_ratio_min": 0.85,
    "pullback_risk_scale": 1.0,
    "ema_cross_risk_scale": 1.0,
    "ema_cross_min_adx": 16,
    "ema_cross_min_h4_slope": 0.25,
    "ema_cross_vol_ratio_min": 0.85,
    "ema_cross_rsi_long_min": 49,
    "ema_cross_rsi_long_max": 68,
    "ema_cross_rsi_short_min": 32,
    "ema_cross_rsi_short_max": 51,
    "ema_cross_require_strong_regime": False,
    "bos_min_adx": 24,
    "bos_min_h4_slope": 0.45,
}

# ─────────────────────────────────────────────────────────────────
# V18 PARAMETERS (Sprint Config — doel: €30k in 60 dagen)
# FTMO-veilig: verwachte max DD ~2.5-3.2% (limiet 6%)
# Compound groeit automatisch: risk_usd = risk_pct × huidige equity
# ─────────────────────────────────────────────────────────────────

V18_CFG: dict = {
    # ── Risico per signaaltype (FTMO-safe op €160k) ────────────────
    "risk_a": 0.0150,  # EMA cross — 1.5% | KZ: 1.875% met kz_mult
    "risk_b": 0.0120,  # MACD/BOS/Momentum — 1.2%
    "risk_c": 0.0100,  # Pullback/MSS — 1.0%
    # ── Signaalfilters ─────────────────────────────────────────────
    "adx_min": 9,  # Minimale ADX H1
    "h4adx_min": 12,  # Minimale ADX H4
    "vol_mult": 1.00,  # Volume filter
    # ── Take profit niveaus ────────────────────────────────────────
    "tp1_r": 1.5,  # TP1 reward ratio
    "tp2_r": 3.5,  # TP2 reward ratio
    "tp3_r": 6.5,  # TP3 reward ratio (grote runners)
    "tp1_pct": 0.25,  # 25% uitstappen bij TP1
    "tp2_pct": 0.30,  # 30% bij TP2
    # ── Stop loss ─────────────────────────────────────────────────
    "sl_atr": 1.5,  # SL ATR multiplier
    "sl_max": 2.0,  # Max SL ATR multiplier
    # ── Trade frequentie ──────────────────────────────────────────
    "max_dag": 10,  # Max trades per dag
    "sl_dag_max": 3,  # Max SL's per dag
    "cooldown_h": 0.5,  # Cooldown 30 min
    # ── Trailing / breakeven ──────────────────────────────────────
    "trailing": True,  # Trailing stop actief
    "breakeven_r": 0.7,  # Breakeven na 0.7R winst
    # ── Kill zone boost ────────────────────────────────────────────
    "kz_mult": 1.25,  # Kill zone boost +25% — London/NY open premium
    # ── Compound systeem ──────────────────────────────────────────
    "weekly_compound": True,  # Wekelijkse compound herberekening
    "compound_boost": 1.08,  # +8% risico-budget na elke winstgevende week
    # ── FTMO limieten ─────────────────────────────────────────────
    "max_lot_size": 4.0,  # Harde lot cap
    "max_daily_loss_eur": 6_000.0,  # Dagelijkse verliesgrens €6k
}

# ─────────────────────────────────────────────────────────────────
# V19 PARAMETERS (Verbeterd — betere verliesweek-bescherming)
# Fixes: tighter filters, conservative compound, weekly loss protection
# ─────────────────────────────────────────────────────────────────

V19_CFG: dict = {
    **V18_CFG,
    "risk_a": 0.0110,
    # ── Betere risk/reward (grotere winnaars, sneller breakeven) ──
    "tp3_r": 7.0,  # grotere runners lopen langer
    "tp1_pct": 0.20,  # minder sluiten bij TP1, meer laten lopen
    "breakeven_r": 0.65,  # sneller breakeven na 0.65R winst
    "compound_decay": 0.85,  # compound verlagen na verliesweek
    # ── Verliesweek-bescherming ────────────────────────────────────
    "weekly_loss_threshold": 0.015,  # -1.5% deze week → risico verlagen
    "weekly_loss_risk_scale": 0.55,  # risico → 55% bij verliesweek
    "loss_day_filter": True,  # na 2 verlies-dagen: alleen A/B/F signalen
    "soft_weekly_loss_threshold": 0.0075,
    "soft_weekly_loss_risk_scale": 0.75,
    "weekly_loss_block_signals": ("D_PULLBACK", "E_BOS"),
    "recent_sl_block_threshold": 2,
    "recent_sl_lookback": 4,
    "recent_sl_block_signals": ("D_PULLBACK", "E_BOS"),
    "pullback_dist_long_min": -0.12,
    "pullback_dist_long_max": 0.32,
    "pullback_dist_short_min": -0.32,
    "pullback_dist_short_max": 0.12,
    "pullback_rsi_long_min": 52,
    "pullback_rsi_long_max": 60,
    "pullback_rsi_short_min": 40,
    "pullback_rsi_short_max": 50,
    "pullback_min_adx": 19,
    "pullback_min_h4_slope": 0.45,
    "pullback_vol_ratio_min": 0.90,
    "pullback_risk_scale": 0.75,
    "ema_cross_risk_scale": 0.75,
    "ema_cross_min_adx": 19,
    "ema_cross_min_h4_slope": 0.45,
    "ema_cross_vol_ratio_min": 0.95,
    "ema_cross_rsi_long_min": 51,
    "ema_cross_rsi_long_max": 63,
    "ema_cross_rsi_short_min": 37,
    "ema_cross_rsi_short_max": 49,
    "ema_cross_require_strong_regime": True,
    "bos_min_adx": 26,
    "bos_min_h4_slope": 0.55,
}

# ─────────────────────────────────────────────────────────────────
# V20 PARAMETERS (Stabiel — FTMO-safe, reset elke 3 weken)
# ─────────────────────────────────────────────────────────────────

V20_CFG: dict = {
    **V19_CFG,
    "risk_a": 0.0100,
    # ── Maandelijks winstdoel ──────────────────────────────────────
    "monthly_profit_target": 40_000.0,
    "monthly_min_target": 20_000.0,
    # ── 3-weken reset systeem ─────────────────────────────────────
    "reset_weeks": 3,
    "reset_capital": 160_000.0,
    "soft_weekly_loss_threshold": 0.0065,
    "soft_weekly_loss_risk_scale": 0.65,
    "weekly_loss_threshold": 0.012,
    "weekly_loss_risk_scale": 0.40,
}

# ─────────────────────────────────────────────────────────────────
# V21 PARAMETERS — Doel: €20-40k/maand | Geen verlies weken
# Hogere risk voor rendement + harde weekly stop + dagwinst-lock
# ─────────────────────────────────────────────────────────────────

V21_CFG: dict = {
    **V20_CFG,
    # ── Risico omhoog voor 20-40k/maand doel ──────────────────────
    "risk_a": 0.0140,  # EMA cross — 1.4% (was 1.0% in V20)
    "risk_b": 0.0110,  # MACD/BOS/Momentum — 1.1%
    "risk_c": 0.0085,  # Pullback/MSS — 0.85%
    # ── Harde weekly stop: geen nieuwe entries als week > -2% ──────
    "weekly_stop_threshold": 0.020,
    # ── Soft drempel eerder: -0.5% → 70% risk ─────────────────────
    "soft_weekly_loss_threshold": 0.005,
    "soft_weekly_loss_risk_scale": 0.70,
    # ── Hard drempel scherper: -1.0% → 35% risk + block C/D/E/F ──
    "weekly_loss_threshold": 0.010,
    "weekly_loss_risk_scale": 0.35,
    "weekly_loss_block_signals": ("C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"),
    # ── Dagelijkse winst-lock: na +2.5% dag → 50% risk rest dag ──
    "daily_profit_lock_pct": 0.025,
    "daily_profit_lock_scale": 0.50,
    # ── Tighter dagverlies ─────────────────────────────────────────
    "max_daily_loss_eur": 5_000.0,
    # ── Snellere breakeven om dag-winst te beschermen ──────────────
    "breakeven_r": 0.55,
    # ── Maanddoel behouden ────────────────────────────────────────
    "monthly_profit_target": 40_000.0,
    "monthly_min_target": 20_000.0,
}

# ─────────────────────────────────────────────────────────────────
# V22 PARAMETERS — Multi-paar | Min 2 trades/dag | €16k+/maand
# XAUUSD + EURUSD + GBPUSD, gedeeld kapitaal, iets lagere ADX drempels
# ─────────────────────────────────────────────────────────────────

V22_CFG: dict = {
    **V21_CFG,
    # ── Risico per signaaltype (3 paren = meer kansen, iets lager per trade) ──
    "risk_a": 0.0120,
    "risk_b": 0.0095,
    "risk_c": 0.0075,
    # ── ADX drempels — gefilterd op echte trendkracht ────────────
    "adx_min": 18,
    "h4adx_min": 18,
    # ── EMA cross ─────────────────────────────────────────────────
    "ema_cross_min_adx": 18,
    "ema_cross_min_h4_slope": 0.20,
    "ema_cross_vol_ratio_min": 0.80,
    "ema_cross_require_strong_regime": False,
    # ── Pullback ──────────────────────────────────────────────────
    "pullback_min_adx": 18,
    "pullback_min_h4_slope": 0.20,
    "pullback_vol_ratio_min": 0.80,
    # ── BOS ───────────────────────────────────────────────────────
    "bos_min_adx": 20,
    "bos_min_h4_slope": 0.25,
    # ── Breakeven pas na 1R winst ─────────────────────────────────
    "breakeven_r": 1.0,
    # ── Max gelijktijdige posities ────────────────────────────────
    "max_concurrent_positions": 2,
    # ── Per-paar daglimieten ──────────────────────────────────────
    "max_dag": 5,
    "sl_dag_max": 3,
    # ── Compound (iets agressiever bij winstgevende week) ─────────
    "compound_boost": 1.10,
}

# ─────────────────────────────────────────────────────────────────
# V23 PARAMETERS — Doel: €5k-10k/week | Max heat ≤ 4.8%
# Hoge risk per trade + lagere ADX/slope drempels = meer signalen
# Portfolio heat ≤ 4.8%: 2 × risk_a = 4.6% (binnen limiet)
# ─────────────────────────────────────────────────────────────────

V23_CFG: dict = {
    **V22_CFG,
    # ── Risico — 2× hoger dan V22, 2 concurrent trades past binnen 4.8% heat ──
    "risk_a": 0.0230,   # EMA cross / MACD cross — 2.3% | 2×2.3=4.6% < 4.8%
    "risk_b": 0.0180,   # BOS / Momentum — 1.8%
    "risk_c": 0.0140,   # Pullback / MSS — 1.4%
    # ── ADX drempels — lager voor meer geldig trends (was 18/18) ────
    "adx_min": 13,
    "h4adx_min": 13,
    # ── EMA cross — lagere drempels voor meer entries ────────────
    "ema_cross_min_adx": 13,
    "ema_cross_min_h4_slope": 0.12,
    "ema_cross_vol_ratio_min": 0.70,
    "ema_cross_rsi_long_min": 47,
    "ema_cross_rsi_long_max": 70,
    "ema_cross_rsi_short_min": 30,
    "ema_cross_rsi_short_max": 53,
    "ema_cross_require_strong_regime": False,
    # ── Pullback — ruimere RSI/dist vensters ─────────────────────
    "pullback_min_adx": 13,
    "pullback_min_h4_slope": 0.12,
    "pullback_vol_ratio_min": 0.70,
    "pullback_dist_long_min": -0.20,
    "pullback_dist_long_max": 0.45,
    "pullback_dist_short_min": -0.45,
    "pullback_dist_short_max": 0.20,
    "pullback_rsi_long_min": 48,
    "pullback_rsi_long_max": 64,
    "pullback_rsi_short_min": 36,
    "pullback_rsi_short_max": 52,
    # ── BOS / MSS — lagere ADX drempel ───────────────────────────
    "bos_min_adx": 15,
    "bos_min_h4_slope": 0.15,
    # ── TP niveaus — zelfde als V22 maar TP3 groter ──────────────
    "tp3_r": 8.0,
    "tp1_pct": 0.20,    # minder vroeg sluiten → meer runners
    "breakeven_r": 0.75,
    # ── Kill zone boost — extra beloning voor premium sessies ─────
    "kz_mult": 1.40,
    # ── Trade frequentie ─────────────────────────────────────────
    "max_dag": 7,
    "sl_dag_max": 4,
    "cooldown_h": 0.25,  # 15 min cooldown (was 30 min in V22)
    "max_concurrent_positions": 2,
    # ── Compound boost — sneller groeien na winstweek ─────────────
    "compound_boost": 1.12,  # +12%/week na winstweek (was 10%)
    "compound_decay": 0.82,  # compound verlagen na verliesweek
    # ── Verliesweek-bescherming — iets soepeler voor meer kansen ──
    "weekly_loss_threshold": 0.020,
    "weekly_loss_risk_scale": 0.45,
    "soft_weekly_loss_threshold": 0.008,
    "soft_weekly_loss_risk_scale": 0.75,
    "weekly_loss_block_signals": ("D_PULLBACK",),  # alleen D blokkeren
    # ── Maanddoel behouden ────────────────────────────────────────
    "monthly_profit_target": 40_000.0,
    "monthly_min_target": 20_000.0,
    "max_daily_loss_eur": 6_000.0,
}

# ─────────────────────────────────────────────────────────────────
# V24 PARAMETERS — Doel: minder verliesweken | €5k-10k/week
# Fixes t.o.v. V23:
#   1. A_EMACROSS geblokkeerd in niet-sterke regimes (50% WR → verliesmaker)
#   2. E_BOS hogere kwaliteitsdrempel (67% WR maar gemiddeld +€38/trade)
#   3. Post-winstweek bescherming: na >2% week → 65% risk volgende week
#   4. Snellere breakeven (0.45R i.p.v. 0.75R) om verliezers te beperken
#   5. Na 2 opeenvolgende SLs: blokkeer A/D/E signalen
# ─────────────────────────────────────────────────────────────────

V24_CFG: dict = {
    **V23_CFG,
    # ── A_EMACROSS: alleen in STERK regime met hoge ADX ────────────
    # V23 resultaat: 50% WR, -€2,266 totaal — kost meer dan het oplevert
    "ema_cross_require_strong_regime": True,   # alleen STERK_BULL/STERK_BEAR
    "ema_cross_min_adx": 26,                   # zeer hoge ADX eis (was 13)
    "ema_cross_min_h4_slope": 0.30,            # sterke H4 slope vereist
    # ── E_BOS: hogere kwaliteitsdrempel ───────────────────────────
    # V23 resultaat: 15 trades voor +€570 totaal (+€38/trade) — niet efficiënt
    "bos_min_adx": 22,                         # was 15 — hogere trendkracht
    "bos_min_h4_slope": 0.22,                  # was 0.15 — sterkere structuur
    # ── Snellere breakeven ─────────────────────────────────────────
    # Verliesweken komen deels door trades die omslaan na een mooie start
    "breakeven_r": 0.45,                       # was 0.75 — protect na 0.45R
    # ── Na 2 opeenvolgende SLs: blokkeer zwakste signalen ──────────
    "recent_sl_block_threshold": 2,
    "recent_sl_lookback": 6,
    "recent_sl_block_signals": ("A_EMACROSS", "D_PULLBACK", "E_BOS"),
    # ── Post-winstweek bescherming ─────────────────────────────────
    # 4 van de 9 verliesweken zijn ná een winstweek door markt-exhaustion
    "post_win_week_threshold": 0.020,          # winstweek > +2% → volgende week beschermd
    "post_win_week_risk_scale": 0.65,          # 65% risico de week erna
    # ── H4 ADX licht verhoogd voor meer trendkwaliteit ─────────────
    "h4adx_min": 15,                           # was 13
    # ── TP1 kleiner sluit minder vroeg → meer runners naar TP2/TP3 ─
    "tp1_pct": 0.15,                           # was 0.20 — minder sluiten bij TP1
    # ── SL iets wijder om minder vroegtijdige stops te hebben ──────
    "sl_atr": 1.7,                             # was 1.5
    "sl_max": 2.3,
}

# ─────────────────────────────────────────────────────────────────
# V25 PARAMETERS — Doel: meer winst + zo min mogelijk verliesweken
# Fixes t.o.v. V24:
#   1. E_BOS volledig uitgeschakeld (66.7% WR maar avg -€247/trade: verliezen > winsten)
#   2. B_MACDCROSS meer risico (avg +€2,685/trade — beste signaal)
#   3. C_MOMENTUM licht verhoogd (68.8% WR — betrouwbaarst)
#   4. Post-verliesweek bescherming: na verliesweek → 65% risico
#   5. Wekelijkse circuit breaker op -1.5% (was -2%)
#   6. Strakkere SL (1.5 ATR) → kleinere individuele verliezen
#   7. Snellere breakeven (0.35R) → meer bescherming van open winst
#   8. Hogere TP2/TP3 targets → grotere winsten op sterke moves
#   9. Na 1 SL al blokkeer zwakste signals (was 2)
#  10. Hogere compound boost (+15%/week na winstweek)
# ─────────────────────────────────────────────────────────────────

V25_CFG: dict = {
    **V24_CFG,
    # ── Gerichte fixes op basis van V24 analyse ───────────────────────────────
    #
    # V24 verliesanalyse:
    #   E_BOS:  9 trades, 66.7% WR maar avg -€247/trade (verliezen > winsten)
    #           → mrt-23 week: 2 E_BOS trades met 0% WR = -€4,165
    #   F_MSS:  9 trades, 66.7% WR, avg +€273/trade → OK, laten staan
    #   B_MACD: 14 trades, 64.3% WR, avg +€2,685 → ster-signaal, meer risico
    #   C_MOM:  16 trades, 68.8% WR, avg +€230 → betrouwbaar, licht verhoogd
    #
    # Principe: minimale wijzigingen — alleen fixen wat aantoonbaar slecht is

    # ── Gerichte fixes op basis van V24 analyse ───────────────────────────────
    #
    # V24 verliesanalyse:
    #   E_BOS:  9 trades, 66.7% WR maar avg -€247/trade — verliezen > winsten
    #           In V24 verantwoordelijk voor mrt-23 week (-€4,165, 0% WR)
    #   Probleem: E_BOS volledig uitschakelen (999) veroorzaakte side-effect:
    #             C_MOMENTUM en F_MSS namen de vrijgekomen cooldown-slots over,
    #             waardoor dec-01 week 3 trades had (was 1) met 33% WR = -€2,554
    #
    # Oplossing: E_BOS behouden maar alleen in ZEER sterke trends (ADX>=30)
    # Dit geeft 1-3 E_BOS trades (was 9) in ideale condities, behoud cooldown-gedrag

    # ── V25: multi-engine fixes — alle beschermingen nu ook in single-symbol engine ─
    #
    # Nieuw in V25 (nu werkend in beide engines):
    #   1. B_MACDCROSS: 2.0% risico (was 1.8%) → ster-signaal 64% WR avg +€2,685/trade
    #   2. Post-verliesweek: na verliesweek > -1.5% → 72% risico volgende week
    #   3. Post-winstweek: na winstweek > +2% → 65% risico (al in V24, nu ook single-engine)
    #   4. Vroege breakeven: SL naar entry bij 0.45R vóór TP1 (nu ook single-engine)
    #   5. Wekelijkse verliesbeperking: bij -1.0% wekelijks → 30% risico (was 2.0% → 45%)
    #   6. Zachte wekelijkse beperking: bij -0.5% → 65% risico (was 0.8% → 75%)
    #   7. Configureerbare SL-blokkering: na 2 SLs blokkeer A/D/E (nu ook single-engine)

    # ── 1. B_MACDCROSS licht meer risico ──────────────────────────────────────
    "risk_b": 0.0200,                          # was 0.018 → 2.0%

    # ── 2+3. Post-win/verliesweek bescherming ─────────────────────────────────
    "post_loss_week_threshold": -0.015,        # verliesweek > -1.5% → protect
    "post_loss_week_risk_scale": 0.72,         # 72% risico de week erna
    "post_win_week_threshold": 0.020,          # winstweek > +2% → protect (ongewijzigd)
    "post_win_week_risk_scale": 0.65,          # 65% risico (ongewijzigd)

    # ── Wekelijkse scaling ONGEWIJZIGD t.o.v. V24 ────────────────────────────
    # Tighter scaling schaalt ook winnende trades neer → behoud V24 waarden
    # bos_min_adx=22, bos_min_h4_slope=0.22, breakeven_r=0.45, sl_atr=1.7
    # tp1_pct=0.15, tp2_r=3.5, tp3_r=8.0, compound_boost=1.12, compound_decay=0.82
    # weekly_loss_threshold=0.020, weekly_loss_risk_scale=0.45 (V23 inherited, ongewijzigd)
    # recent_sl_block_threshold=2, recent_sl_block_signals=(A/D/E)
}

# ─────────────────────────────────────────────────────────────────
# V26 PARAMETERS — Doel: consistente €1-4k/week | bugfix + echte R:R
# Fixes t.o.v. V25:
#   1. Alleen C_MOMENTUM + B_MACDCROSS (E_BOS/F_MSS/A/D uitgeschakeld)
#   2. tp1_pct=0.45 zodat TP1-hit wins > losses worden
#   3. breakeven_r=1.5 — meer ruimte voor trade vóór breakeven
#   4. TP2=2.5R (was 3.5R) — haalbaarder target
#   5. B_MACDCROSS: H4-slope + ADX filter toegevoegd
#   6. P&L bug gefixed: orig_sl_dist in backtest_service
# ─────────────────────────────────────────────────────────────────

V26_CFG: dict = {
    **V25_CFG,
    # ── Alleen C_MOMENTUM (enige consistent winstgevende signaal) ──
    # C_MOMENTUM: 72% WR, +492/trade — enige signal dat werkt
    # B_MACDCROSS: 55% WR, -664/trade → uitgeschakeld
    # E_BOS/F_MSS/A/D: al eerder bewezen verliezend
    "disabled_signals": ["A_EMACROSS", "B_MACDCROSS", "D_PULLBACK", "E_BOS", "F_MSS"],
    # ── C_MOMENTUM: alleen STERK_BULL/BEAR (BULL geeft te veel slechte trades) ─
    "c_momentum_allow_bull": False,
    "c_momentum_min_adx": 20,
    # ── ADX filters ────────────────────────────────────────────────
    "adx_min": 18,
    "h4adx_min": 18,
    # ── TP structuur: grotere wins zodat win/loss ratio > 0.5 ──────
    "tp1_pct": 0.45,    # 45% bij TP1 — zelfde als eerste succesvolle V26 run
    "tp2_pct": 0.35,    # 35% bij TP2, 20% runner
    "tp1_r": 1.5,
    "tp2_r": 2.5,       # haalbaarder dan 3.5R
    "tp3_r": 5.0,       # haalbaarder dan 8.0R
    # ── Breakeven na 1.5R — zelfde als eerste succesvolle V26 run ──
    "breakeven_r": 1.5,
    # ── Risk: 1.8% per trade ──────────────────────────────────────
    "risk_b": 0.0180,   # C_MOMENTUM — 1.8% per trade
    # ── Verliesweek bescherming ────────────────────────────────────
    "weekly_loss_threshold": 0.012,
    "weekly_loss_risk_scale": 0.40,
    "soft_weekly_loss_threshold": 0.006,
    "soft_weekly_loss_risk_scale": 0.70,
    "weekly_loss_block_signals": (),
    "sl_dag_max": 2,
    # ── Compound: gematigd ────────────────────────────────────────
    "compound_boost": 1.08,
    "compound_decay": 0.92,
}

# ─────────────────────────────────────────────────────────────────
# V27 PARAMETERS — Doel: €10-20k/maand | Weinig verliesweken
# Basis: V26 (alleen C_MOMENTUM, bewezen 72% WR)
# Wijzigingen t.o.v. V26:
#   1. max_dag: 6 → 8 (meer kansen per dag)
#   2. cooldown_h: 2 → 1 (sneller opnieuw instappen)
#   3. risk_b: 1.8% → 2.0% (iets hoger per trade)
#   4. max_concurrent_positions: 1 → 2 (2 posities tegelijk)
#   5. breakeven_r: 1.5 → 1.2 (winsten sneller beschermen)
#   6. monthly_profit_target: 8k → 15k
# ─────────────────────────────────────────────────────────────────

V27_CFG: dict = {
    **V26_CFG,
    # ── Meer trades per dag ────────────────────────────────────────
    "max_dag": 8,
    "sl_dag_max": 3,
    "cooldown_h": 1,
    # ── Iets hogere risk voor €10-20k/maand doel ──────────────────
    "risk_b": 0.0200,
    # ── 2 posities tegelijk ────────────────────────────────────────
    "max_concurrent_positions": 2,
    # ── Snellere breakeven — winsten beter beschermen ──────────────
    "breakeven_r": 1.2,
    # ── C_MOMENTUM: ook BULL regime toestaan, maar strikter ADX ───
    # V26: alleen STERK_BULL = 19 trades/6mnd — te weinig
    # V27: ook BULL, maar min_adx 20→22 om kwaliteit te bewaren
    "c_momentum_allow_bull": True,
    "c_momentum_min_adx": 22,
    # ── Maanddoel ─────────────────────────────────────────────────
    "monthly_profit_target": 15_000.0,
    "monthly_min_target": 8_000.0,
    # ── Verliesweek bescherming: ongewijzigd sterk ─────────────────
    "soft_weekly_loss_threshold": 0.006,   # -0.6% → 70% risk
    "soft_weekly_loss_risk_scale": 0.70,
    "weekly_loss_threshold": 0.012,        # -1.2% → 40% risk
    "weekly_loss_risk_scale": 0.40,
    "weekly_stop_threshold": 0.018,        # -1.8% → volledig stoppen
}

# ─────────────────────────────────────────────────────────────────
# EXPERT_CFG — Trend-following intraday | kwaliteit boven frequentie
# Basis: V27, maar zonder scalp-logica en met strengere kwaliteitsfilters
# Doel: robuuste live-handel met harde risico- en verliesweekbescherming
# ─────────────────────────────────────────────────────────────────

EXPERT_CFG: dict = {
    **V27_CFG,
    "disabled_signals": ["E_BOS"],
    "risk_a": 0.0150,
    "risk_b": 0.0130,
    "risk_c": 0.0090,
    "adx_min": 17,
    "h4adx_min": 18,
    "b_macd_min_adx": 20,
    "b_macd_min_h4_slope": 0.22,
    "b_macd_require_strong": True,
    "ema_cross_risk_scale": 0.85,
    "ema_cross_min_adx": 20,
    "ema_cross_min_h4_slope": 0.30,
    "ema_cross_vol_ratio_min": 0.95,
    "ema_cross_require_strong_regime": True,
    "pullback_min_adx": 20,
    "pullback_min_h4_slope": 0.40,
    "pullback_vol_ratio_min": 0.95,
    "pullback_risk_scale": 0.80,
    "c_momentum_allow_bull": True,
    "c_momentum_min_adx": 24,
    "tp1_r": 1.5,
    "tp2_r": 3.0,
    "tp3_r": 6.0,
    "tp1_pct": 0.25,
    "tp2_pct": 0.35,
    "sl_atr": 1.6,
    "sl_max": 2.2,
    "max_dag": 6,
    "sl_dag_max": 2,
    "cooldown_h": 1.5,
    "breakeven_r": 0.9,
    "kz_mult": 1.20,
    "compound_boost": 1.06,
    "compound_decay": 0.88,
    "max_concurrent_positions": 2,
    "soft_weekly_loss_threshold": 0.005,
    "soft_weekly_loss_risk_scale": 0.65,
    "weekly_loss_threshold": 0.010,
    "weekly_loss_risk_scale": 0.35,
    "weekly_stop_threshold": 0.015,
    "daily_profit_lock_pct": 0.020,
    "daily_profit_lock_scale": 0.45,
    "max_daily_loss_eur": 4_000.0,
    "monthly_profit_target": 20_000.0,
    "monthly_stretch_target": 30_000.0,
    "monthly_min_target": 12_000.0,
}

# ─────────────────────────────────────────────────────────────────
# SCALP_CFG — Hogere frequentie op M15 | meerdere signalen per dag
# Gebruikt dezelfde A-F signalen, maar met soepelere filters en kleinere risk
# per trade zodat de strategie meer kansen pakt zonder blind agressief te zijn.
# ─────────────────────────────────────────────────────────────────

SCALP_CFG: dict = {
    **V27_CFG,
    # Winnende scalp-variant op MT5 M15 backtest:
    # focus op B_MACDCROSS + D_PULLBACK, de rest uitgezet.
    "disabled_signals": ["A_EMACROSS", "C_MOMENTUM", "E_BOS", "F_MSS"],
    "risk_a": 0.0045,
    "risk_b": 0.0045,
    "risk_c": 0.0040,
    "adx_min": 11,
    "h4adx_min": 10,
    "b_macd_min_adx": 13,
    "b_macd_min_h4_slope": 0.05,
    "b_macd_require_strong": False,
    "ema_cross_risk_scale": 1.0,
    "ema_cross_min_adx": 12,
    "ema_cross_min_h4_slope": 0.08,
    "ema_cross_vol_ratio_min": 0.70,
    "ema_cross_rsi_long_min": 46,
    "ema_cross_rsi_long_max": 72,
    "ema_cross_rsi_short_min": 28,
    "ema_cross_rsi_short_max": 54,
    "ema_cross_require_strong_regime": False,
    "pullback_dist_long_min": -0.25,
    "pullback_dist_long_max": 0.45,
    "pullback_dist_short_min": -0.45,
    "pullback_dist_short_max": 0.25,
    "pullback_rsi_long_min": 47,
    "pullback_rsi_long_max": 64,
    "pullback_rsi_short_min": 36,
    "pullback_rsi_short_max": 53,
    "pullback_min_adx": 12,
    "pullback_min_h4_slope": 0.06,
    "pullback_vol_ratio_min": 0.65,
    "pullback_risk_scale": 0.95,
    "c_momentum_allow_bull": True,
    "c_momentum_min_adx": 16,
    "bos_min_adx": 13,
    "bos_min_h4_slope": 0.08,
    "tp1_r": 1.0,
    "tp2_r": 2.0,
    "tp3_r": 3.0,
    "tp1_pct": 0.55,
    "tp2_pct": 0.25,
    "sl_atr": 0.85,
    "sl_max": 1.20,
    "max_dag": 24,
    "sl_dag_max": 5,
    "cooldown_h": 0.05,
    "breakeven_r": 0.30,
    "kz_mult": 1.15,
    "compound_boost": 1.03,
    "compound_decay": 0.94,
    "max_concurrent_positions": 3,
    "soft_weekly_loss_threshold": 0.0035,
    "soft_weekly_loss_risk_scale": 0.55,
    "weekly_loss_threshold": 0.0075,
    "weekly_loss_risk_scale": 0.30,
    "weekly_stop_threshold": 0.012,
    "daily_profit_lock_pct": 0.015,
    "daily_profit_lock_scale": 0.40,
    "max_daily_loss_eur": 2_500.0,
    "monthly_profit_target": 12_000.0,
    "monthly_stretch_target": 20_000.0,
    "monthly_min_target": 6_000.0,
}

# ─────────────────────────────────────────────────────────────────
# AGGRESSIVE_FTMO_CFG — High-activity scalp mode
# Meer trades en meer risico per dag. Bedoeld als experimentele modus
# voor hogere output, maar aantoonbaar minder robuust dan SCALP_CFG.
# ─────────────────────────────────────────────────────────────────

AGGRESSIVE_FTMO_CFG: dict = {
    **SCALP_CFG,
    "b_macd_min_adx": 11,
    "b_macd_min_h4_slope": 0.03,
    "pullback_min_adx": 10,
    "pullback_min_h4_slope": 0.05,
    "pullback_vol_ratio_min": 0.60,
    "risk_a": 0.0050,
    "risk_b": 0.0055,
    "risk_c": 0.0050,
    "tp2_r": 1.8,
    "tp3_r": 2.8,
    "tp1_pct": 0.60,
    "sl_atr": 0.85,
    "sl_max": 1.20,
    "breakeven_r": 0.25,
    "max_dag": 30,
    "sl_dag_max": 8,
    "cooldown_h": 0.10,
    "max_daily_loss_eur": 3_500.0,
    "monthly_profit_target": 20_000.0,
    "monthly_stretch_target": 30_000.0,
    "monthly_min_target": 10_000.0,
}

# ─────────────────────────────────────────────────────────────────
# MULTI-PAAR CONTRACT SPECS (gedeeld door backtest + live bot)
# lot_factor: P&L per lot per 1 prijseenheid (USD)
# price_ref: referentieprijs voor H4-slope normalisatie t.o.v. XAUUSD
# ─────────────────────────────────────────────────────────────────

SYMBOL_SPECS: dict[str, dict] = {
    "XAUUSD": {"yf_ticker": "GC=F",      "lot_factor": 100,     "max_lot": 4.0,  "price_ref": 2800.0},
    "EURUSD": {"yf_ticker": "EURUSD=X",  "lot_factor": 100_000, "max_lot": 20.0, "price_ref": 1.10},
    "GBPUSD": {"yf_ticker": "GBPUSD=X",  "lot_factor": 100_000, "max_lot": 20.0, "price_ref": 1.30},
}


def get_symbol_cfg(base_cfg: dict, symbol: str) -> dict:
    """
    Schaalt H4-slope drempels naar de prijsschaal van het symbool.
    XAUUSD: ongewijzigd. Forex-paren: slope × (prijs / 2800).
    """
    spec = SYMBOL_SPECS.get(symbol)
    if spec is None or symbol == "XAUUSD":
        return base_cfg
    scale = spec["price_ref"] / SYMBOL_SPECS["XAUUSD"]["price_ref"]
    cfg = dict(base_cfg)
    for key in ("ema_cross_min_h4_slope", "pullback_min_h4_slope", "bos_min_h4_slope"):
        if key in cfg:
            cfg[key] = cfg[key] * scale
    return cfg


# Signal prioriteit
SIGNAL_PRIORITY: dict[str, int] = {
    "B_MACDCROSS": 6,
    "A_EMACROSS": 5,
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
    direction: str  # "long" | "short"
    signal_type: str  # A_EMACROSS | B_MACDCROSS | C_MOMENTUM | D_PULLBACK | E_BOS | F_MSS
    risk_pct: float  # Risicopercentage van kapitaal
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
    timestamp: datetime | None = None
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
    losses = (-d).clip(lower=0).ewm(com=p - 1, adjust=False).mean()
    return 100 - 100 / (1 + g / losses.replace(0, 1e-10))


def _atr(hi: pd.Series, lo: pd.Series, cl: pd.Series, p: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            hi - lo,
            (hi - cl.shift(1)).abs(),
            (lo - cl.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
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
            (d["rsi14"] > d["rsi14"].shift(1)) & (d["rsi14"].shift(1) < d["rsi14"].shift(2)) & (d["rsi14"] > 48)
        )

        # ── H4 regime ───────────────────────────────────────────
        h4 = (
            d.resample("4h")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        h4["e21"] = _ema(h4["close"], 21)
        h4["e50"] = _ema(h4["close"], 50)
        h4["e200"] = _ema(h4["close"], 200)
        h4["adx"] = _adx(h4["high"], h4["low"], h4["close"], 14)
        h4["atr"] = _atr(h4["high"], h4["low"], h4["close"], 14)
        h4["rsi"] = _rsi(h4["close"], 14)
        h4["sl21"] = h4["e21"] - h4["e21"].shift(3)
        h4["regime"] = h4.apply(self._h4_regime, axis=1)

        for col, src in [
            ("h4_reg", "regime"),
            ("h4_atr", "atr"),
            ("h4_adx", "adx"),
            ("h4_sl", "sl21"),
            ("h4_rsi", "rsi"),
            ("h4_e21", "e21"),
            ("h4_e50", "e50"),
        ]:
            d[col] = h4[src].reindex(d.index, method="ffill")
        d["h4_reg"] = d["h4_reg"].fillna("CHOPPY")
        d["h4_adx"] = d["h4_adx"].fillna(0)
        d["h4_sl"] = d["h4_sl"].fillna(0)
        d["h4_rsi"] = d["h4_rsi"].fillna(50)

        # ── D1 trend ────────────────────────────────────────────
        d1 = (
            d.resample("1D")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        if len(d1) >= 3:
            d1["e50"] = _ema(d1["close"], 50)
            d1["e200"] = _ema(d1["close"], 200)
            d1["sl50"] = d1["e50"] - d1["e50"].shift(5)
            d1["trend"] = np.where(
                (d1["close"] > d1["e50"]) & (d1["sl50"] > 0),
                "bull",
                np.where(
                    (d1["close"] < d1["e50"]) & (d1["sl50"] < 0),
                    "bear",
                    "neutral",
                ),
            )
        else:
            d1["trend"] = "neutral"
        d["d1_trend"] = d1["trend"].reindex(d.index, method="ffill").fillna("neutral")

        # ── Structure patterns ──────────────────────────────────
        d["bos_bull"] = d["close"] > d["hh10"]
        d["bos_bear"] = d["close"] < d["ll10"]
        d["mss_bull"] = (d["ema9"] > d["ema21"]) & (d["ema9"].shift(3) < d["ema21"].shift(3)) & (d["rsi14"] > 52)
        d["mss_bear"] = (d["ema9"] < d["ema21"]) & (d["ema9"].shift(3) > d["ema21"].shift(3)) & (d["rsi14"] < 48)

        # ── Fair Value Gaps (3-candle imbalance) ────────────────
        # Bullish FVG: huidige low > 2 bars geleden high (opwaartse gap, onvervuld)
        fvg_bull_raw = d["low"] > d["high"].shift(2)
        # Bearish FVG: huidige high < 2 bars geleden low (neerwaartse gap, onvervuld)
        fvg_bear_raw = d["high"] < d["low"].shift(2)
        # Detecteer recente FVG (binnen de laatste 6 bars) als potentieel entry-gebied
        d["fvg_bull"] = fvg_bull_raw.rolling(6, min_periods=1).max().fillna(0).astype(bool)
        d["fvg_bear"] = fvg_bear_raw.rolling(6, min_periods=1).max().fillna(0).astype(bool)

        # ── Liquidity Sweeps (stop hunt detectie) ───────────────
        # Bullish sweep: huidige bar liep onder ll10 maar sloot erboven (stop hunt op retail shorts)
        d["liq_sweep_bull"] = (d["low"] < d["ll10"]) & (d["close"] > d["ll10"])
        # Bearish sweep: huidige bar liep boven hh10 maar sloot eronder (stop hunt op retail longs)
        d["liq_sweep_bear"] = (d["high"] > d["hh10"]) & (d["close"] < d["hh10"])
        # Recente sweep (binnen 3 bars) is relevanter voor entry-kwaliteit
        d["liq_sweep_bull_recent"] = d["liq_sweep_bull"].rolling(3, min_periods=1).max().fillna(0).astype(bool)
        d["liq_sweep_bear_recent"] = d["liq_sweep_bear"].rolling(3, min_periods=1).max().fillna(0).astype(bool)

        return d.dropna(subset=["ema9", "ema21", "ema50", "ema200", "rsi14", "atr14", "h4_atr"])

    @staticmethod
    def _h4_regime(r) -> str:
        bull = r["e21"] > r["e50"]
        bear = r["e21"] < r["e50"]
        a200 = r["e50"] > r["e200"]
        b200 = r["e50"] < r["e200"]
        adx = r["adx"]
        sl = r["sl21"]
        if bull and adx >= 20 and sl > 0 and a200:
            return "STERK_BULL"
        if bull and adx >= 14:
            return "BULL"
        if bull:
            return "ZWAK_BULL"
        if bear and adx >= 20 and sl < 0 and b200:
            return "STERK_BEAR"
        if bear and adx >= 14:
            return "BEAR"
        if bear:
            return "ZWAK_BEAR"
        return "CHOPPY"

    def generate_signal(
        self,
        df: pd.DataFrame,
        cfg: dict | None = None,
        sentiment_score: float = 0.0,
        sentiment_label: str = "neutral",
        ml_confidence: float = 0.5,
        is_killzone: bool = False,
    ) -> SignalResult | None:
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
        fvg_bull = bool(bar.get("fvg_bull", False))
        fvg_bear = bool(bar.get("fvg_bear", False))
        liq_sweep_bull = bool(bar.get("liq_sweep_bull_recent", False))
        liq_sweep_bear = bool(bar.get("liq_sweep_bear_recent", False))

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
        pullback_dist_long_min = _safe(params.get("pullback_dist_long_min", -0.15), -0.15)
        pullback_dist_long_max = _safe(params.get("pullback_dist_long_max", 0.35), 0.35)
        pullback_dist_short_min = _safe(params.get("pullback_dist_short_min", -0.35), -0.35)
        pullback_dist_short_max = _safe(params.get("pullback_dist_short_max", 0.15), 0.15)
        pullback_rsi_long_min = _safe(params.get("pullback_rsi_long_min", 52), 52)
        pullback_rsi_long_max = _safe(params.get("pullback_rsi_long_max", 60), 60)
        pullback_rsi_short_min = _safe(params.get("pullback_rsi_short_min", 40), 40)
        pullback_rsi_short_max = _safe(params.get("pullback_rsi_short_max", 50), 50)
        pullback_min_adx = _safe(params.get("pullback_min_adx", max(adx_min + 4, 18)), max(adx_min + 4, 18))
        pullback_min_h4_slope = _safe(params.get("pullback_min_h4_slope", 0.45), 0.45)
        pullback_vol_ratio_min = _safe(params.get("pullback_vol_ratio_min", 0.85), 0.85)
        pullback_risk_scale = _safe(params.get("pullback_risk_scale", 1.0), 1.0)
        ema_cross_risk_scale = _safe(params.get("ema_cross_risk_scale", 1.0), 1.0)
        ema_cross_min_adx = _safe(params.get("ema_cross_min_adx", max(adx_min + 2, 16)), max(adx_min + 2, 16))
        ema_cross_min_h4_slope = _safe(params.get("ema_cross_min_h4_slope", 0.25), 0.25)
        ema_cross_vol_ratio_min = _safe(params.get("ema_cross_vol_ratio_min", 0.85), 0.85)
        ema_cross_rsi_long_min = _safe(params.get("ema_cross_rsi_long_min", 49), 49)
        ema_cross_rsi_long_max = _safe(params.get("ema_cross_rsi_long_max", 68), 68)
        ema_cross_rsi_short_min = _safe(params.get("ema_cross_rsi_short_min", 32), 32)
        ema_cross_rsi_short_max = _safe(params.get("ema_cross_rsi_short_max", 51), 51)
        ema_cross_require_strong_regime = bool(params.get("ema_cross_require_strong_regime", False))
        bos_min_adx = _safe(params.get("bos_min_adx", 24), 24)
        bos_min_h4_slope = _safe(params.get("bos_min_h4_slope", 0.45), 0.45)
        disabled_signals: set[str] = set(params.get("disabled_signals", []))
        b_macd_min_adx = _safe(params.get("b_macd_min_adx", adx_min), adx_min)
        b_macd_min_h4_slope = _safe(params.get("b_macd_min_h4_slope", 0.0), 0.0)
        b_macd_require_strong = bool(params.get("b_macd_require_strong", False))

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
        _mom_allow_bull = bool(params.get("c_momentum_allow_bull", False))
        _mom_min_adx = _safe(params.get("c_momentum_min_adx", 20), 20)

        # ── LONG signalen ────────────────────────────────────────
        bull_ok = (
            not block_long
            and h4reg in ("STERK_BULL", "BULL", "ZWAK_BULL")
            and d1t in ("bull", "neutral")
            and cl > e50
            and cl > e200 * 0.998
        )

        if bull_ok:
            rsi_lo, rsi_hi = 47, 72

            if "A_EMACROSS" not in disabled_signals and (
                ema_xup
                and macdh > -0.5
                and ema_cross_rsi_long_min <= rsi14 <= ema_cross_rsi_long_max
                and adx >= ema_cross_min_adx
                and h4sl >= ema_cross_min_h4_slope
                and (not ema_cross_require_strong_regime or h4reg == "STERK_BULL")
                and (vol_ma <= 100 or vol >= vol_ma * ema_cross_vol_ratio_min)
                and e9 > e50
            ):
                sigs.append(("long", "A_EMACROSS", risk_a * ema_cross_risk_scale * sent_mult_long, tp1r, tp2r, tp3r))

            if "B_MACDCROSS" not in disabled_signals and (
                macd_xu and e9 > e21
                and rsi_lo <= rsi14 <= rsi_hi - 3
                and h4sl >= b_macd_min_h4_slope
                and adx >= b_macd_min_adx
                and (not b_macd_require_strong or h4reg in ("STERK_BULL",))
            ):
                sigs.append(("long", "B_MACDCROSS", risk_b * sent_mult_long, tp1r, tp2r, tp3r))

            # C_MOMENTUM: STERK_BULL (+ optioneel BULL) + hogere ADX + sterkere momentum
            _mom_regimes = ("STERK_BULL", "BULL") if _mom_allow_bull else ("STERK_BULL",)
            if "C_MOMENTUM" not in disabled_signals and (
                e9 > e21 > e50
                and 50 <= rsi14 <= 65
                and macdh > 0.5
                and h4sl > 0.3
                and rsi_rec
                and h4reg in _mom_regimes
                and adx > _mom_min_adx
            ):
                sigs.append(("long", "C_MOMENTUM", risk_b * sent_mult_long, tp1r, tp2r, tp3r))

            # D_PULLBACK: schonere pullback range (dichter bij EMA21)
            if "D_PULLBACK" not in disabled_signals and (
                h4reg == "STERK_BULL"
                and pullback_dist_long_min <= dist21 <= pullback_dist_long_max
                and cl > e21
                and e21 > e50
                and pullback_rsi_long_min <= rsi14 <= pullback_rsi_long_max
                and e9 > e21
                and macdh > -0.5
                and adx >= pullback_min_adx
                and h4sl >= pullback_min_h4_slope
                and (vol_ma <= 100 or vol >= vol_ma * pullback_vol_ratio_min)
            ):
                sigs.append(("long", "D_PULLBACK", risk_c * pullback_risk_scale * sent_mult_long, tp1r, tp2r, tp3r))

            # E_BOS: risk_c (was risk_b) + strengere ADX-filter
            if "E_BOS" not in disabled_signals and (
                bos_b
                and cl > e21
                and 53 <= rsi14 <= 68
                and adx >= bos_min_adx
                and h4sl >= bos_min_h4_slope
                and h4reg in ("STERK_BULL", "BULL")
            ):
                sigs.append(("long", "E_BOS", risk_c * sent_mult_long, tp1r * 0.9, tp2r, tp3r * 0.9))

            if "F_MSS" not in disabled_signals and mss_b and 50 <= rsi14 <= 65 and cl > e21 and h4reg in ("STERK_BULL", "BULL") and h4sl > 0:
                sigs.append(("long", "F_MSS", risk_c * sent_mult_long, tp1r, tp2r, tp3r))

        # ── SHORT signalen ───────────────────────────────────────
        bear_ok = (
            not block_short
            and h4reg in ("STERK_BEAR", "BEAR", "ZWAK_BEAR")
            and d1t in ("bear", "neutral")
            and cl < e50
            and cl < e200 * 1.002
        )

        if bear_ok:
            rsi_lo, rsi_hi = 28, 53

            if "A_EMACROSS" not in disabled_signals and (
                ema_xdn
                and macdh < 0.5
                and ema_cross_rsi_short_min <= rsi14 <= ema_cross_rsi_short_max
                and adx >= ema_cross_min_adx
                and h4sl <= -ema_cross_min_h4_slope
                and (not ema_cross_require_strong_regime or h4reg == "STERK_BEAR")
                and (vol_ma <= 100 or vol >= vol_ma * ema_cross_vol_ratio_min)
                and e9 < e50
            ):
                sigs.append(("short", "A_EMACROSS", risk_a * ema_cross_risk_scale * sent_mult_short, tp1r, tp2r, tp3r))

            if "B_MACDCROSS" not in disabled_signals and (
                macd_xd and e9 < e21
                and rsi_lo + 3 <= rsi14 <= rsi_hi
                and h4sl <= -b_macd_min_h4_slope
                and adx >= b_macd_min_adx
                and (not b_macd_require_strong or h4reg in ("STERK_BEAR",))
            ):
                sigs.append(("short", "B_MACDCROSS", risk_b * sent_mult_short, tp1r, tp2r, tp3r))

            # C_MOMENTUM: STERK_BEAR (+ optioneel BEAR) + hogere ADX + sterkere neerwaartse momentum
            _mom_regimes_s = ("STERK_BEAR", "BEAR") if _mom_allow_bull else ("STERK_BEAR",)
            if "C_MOMENTUM" not in disabled_signals and (
                e9 < e21 < e50
                and 35 <= rsi14 <= rsi_hi
                and macdh < -0.5
                and h4sl < -0.3
                and h4reg in _mom_regimes_s
                and adx > _mom_min_adx
            ):
                sigs.append(("short", "C_MOMENTUM", risk_b * sent_mult_short, tp1r, tp2r, tp3r))

            # D_PULLBACK: schonere pullback range (dichter bij EMA21)
            if "D_PULLBACK" not in disabled_signals and (
                h4reg == "STERK_BEAR"
                and pullback_dist_short_min <= dist21 <= pullback_dist_short_max
                and cl < e21
                and e21 < e50
                and pullback_rsi_short_min <= rsi14 <= pullback_rsi_short_max
                and e9 < e21
                and macdh < 0.5
                and adx >= pullback_min_adx
                and h4sl <= -pullback_min_h4_slope
                and (vol_ma <= 100 or vol >= vol_ma * pullback_vol_ratio_min)
            ):
                sigs.append(("short", "D_PULLBACK", risk_c * pullback_risk_scale * sent_mult_short, tp1r, tp2r, tp3r))

            # E_BOS: risk_c (was risk_b) + strengere ADX-filter
            if "E_BOS" not in disabled_signals and (
                bos_be
                and cl < e21
                and rsi_lo <= rsi14 <= rsi_hi - 2
                and adx >= bos_min_adx
                and h4sl <= -bos_min_h4_slope
                and h4reg in ("STERK_BEAR", "BEAR")
            ):
                sigs.append(("short", "E_BOS", risk_c * sent_mult_short, tp1r * 0.9, tp2r, tp3r * 0.9))

            if "F_MSS" not in disabled_signals and mss_be and 35 <= rsi14 <= rsi_hi and cl < e21 and h4reg in ("STERK_BEAR", "BEAR") and h4sl < 0:
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

        # Confidence: combinatie van signal prioriteit + ML + sentiment + FVG/Sweep
        prio_conf = priority / 6.0
        sent_conf = abs(sentiment_score) * 0.3 if sentiment_score != 0 else 0.0
        # FVG bevestigt entry-richting: institutionele imbalance in ons voordeel
        fvg_confirms = (direction == "long" and fvg_bull) or (direction == "short" and fvg_bear)
        # Liquiditeitssweep bevestigt setup: retail stops gejaagd vóór onze entry
        sweep_confirms = (direction == "long" and liq_sweep_bull) or (direction == "short" and liq_sweep_bear)
        fvg_boost = 0.05 if fvg_confirms else 0.0
        sweep_boost = 0.06 if sweep_confirms else 0.0
        confidence = round(min(0.95, prio_conf * 0.5 + ml_confidence * 0.35 + sent_conf * 0.15 + fvg_boost + sweep_boost), 3)

        # Liquiditeitssweep boost voor BOS/MSS signalen: sweep + BOS = confirmed institutional entry
        if sweep_confirms and sig_type in ("E_BOS", "F_MSS"):
            risk_pct = round(risk_pct * 1.10, 5)  # +10% risk bij bevestigde sweep+BOS combo

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
                "rsi14": rsi14,
                "adx14": adx,
                "macd_hist": macdh,
                "h4_adx": h4adx,
                "h4_reg": h4reg,
                "d1_trend": d1t,
                "ema_xup": ema_xup,
                "ema_xdn": ema_xdn,
                "macd_xup": macd_xu,
                "macd_xdn": macd_xd,
                "bos_bull": bos_b,
                "bos_bear": bos_be,
                "mss_bull": mss_b,
                "mss_bear": mss_be,
                "dist21": dist21,
                "h4_sl": h4sl,
                "atr14": atr14,
                "sentiment": sentiment_score,
                "breakeven_r": breakeven_r,
                "is_killzone": is_killzone,
                "kz_mult": kz_mult,
                "fvg_confirms": fvg_confirms,
                "sweep_confirms": sweep_confirms,
                "fvg_bull": fvg_bull,
                "fvg_bear": fvg_bear,
                "liq_sweep_bull": liq_sweep_bull,
                "liq_sweep_bear": liq_sweep_bear,
            },
        )

    def get_session(self, dt: datetime) -> str:
        """Geeft sessie terug op basis van UTC uur (compatibel met V16)."""
        uur = dt.hour
        dow = dt.weekday()
        if dow >= 5:
            return "blocked"
        if dow == 0 and uur < 7:
            return "blocked"
        if dow == 4 and uur >= 17:
            return "blocked"
        if 7 <= uur < 12:
            return "premium"
        if 13 <= uur <= 17:
            return "premium"
        if uur == 12:
            return "standard"
        return "blocked"


# ─────────────────────────────────────────────────────────────────
# SINGLETON INSTANCE
# ─────────────────────────────────────────────────────────────────

_engine_instance: StrategyEngine | None = None
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
