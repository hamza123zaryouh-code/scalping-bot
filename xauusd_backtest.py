"""
XAUUSD Backtest — Verbeterde MA Crossover Strategie (2024–Mei 2026)
====================================================================
6 verbeteringen ten opzichte van de originele versie:
  1. Alleen LONG trades   → volgt de structurele bull trend van goud
  2. RSI filter           → voorkomt kopen bij overbought condities
  3. MA optimalisatie     → vindt automatisch de beste MA combinatie
  4. ATR stop loss        → dynamische SL/TP aangepast aan marktvolatiliteit
  5. Sessie filter        → handelt alleen tijdens actieve markturen (07-21 UTC)
  6. Uitgebreide stats    → Sharpe ratio, profit factor, maandanalyse, vergelijking

Gebruik:
  pip install yfinance pandas matplotlib numpy
  python xauusd_backtest.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
from datetime import datetime
import os
import warnings

warnings.filterwarnings('ignore')


def safe_float(value, default=0.0):
    """Best-effort float conversion used by the live bot feature pipeline."""
    try:
        if value is None:
            return float(default)
        if pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def add_indicators(df):
    """Compatibility wrapper expected by indicators.py for M1 feature prep."""
    data = df.copy()

    if 'volume' not in data.columns:
        data['volume'] = 0.0
    if 'spread' not in data.columns:
        data['spread'] = 0.0

    data['ema8'] = _ema(data['close'], 8)
    data['ema21'] = _ema(data['close'], 21)
    data['ema50'] = _ema(data['close'], 50)
    data['rsi14'] = bereken_rsi(data['close'], 14)
    data['atr14'] = bereken_atr(data['high'], data['low'], data['close'], 14)
    data['adx14'] = bereken_adx(data['high'], data['low'], data['close'], 14)
    data['volume_ma20'] = data['volume'].rolling(20).mean()
    data['cross_up'] = (data['ema8'] > data['ema21']) & (data['ema8'].shift(1) <= data['ema21'].shift(1))
    data['cross_down'] = (data['ema8'] < data['ema21']) & (data['ema8'].shift(1) >= data['ema21'].shift(1))

    return data


def make_m5_bars(df):
    """Resample M1 candles to M5 for directional bias."""
    data = df.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        if 'time' in data.columns:
            data['time'] = pd.to_datetime(data['time'])
            data = data.set_index('time')
        else:
            raise ValueError("Expected DatetimeIndex or 'time' column in market data")

    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'spread': 'mean',
    }
    available_agg = {k: v for k, v in agg.items() if k in data.columns}
    m5 = data.resample('5min').agg(available_agg).dropna(subset=['open', 'high', 'low', 'close'])

    m5['ema50'] = _ema(m5['close'], 50)
    m5['m5_bias'] = np.where(m5['close'] >= m5['ema50'], 'bull', 'bear')
    return m5


def apply_m5_bias(m1, m5):
    """Project latest M5 bias onto each M1 bar using backward asof join."""
    left = m1.sort_index().copy()
    right = m5[['m5_bias']].sort_index().copy()

    merged = pd.merge_asof(
        left,
        right,
        left_index=True,
        right_index=True,
        direction='backward',
    )
    merged['m5_bias'] = merged['m5_bias'].fillna('neutral')
    return merged


def simulate_trades(
    enriched,
    starting_capital=160000.0,
    risk_per_trade=0.0025,
    sl_atr_multiplier=1.5,
    tp_atr_multiplier=3.0,
    max_daily_loss=8000.0,
    max_total_loss=16000.0,
    min_volume_multiplier=1.10,
    adx_min_strength=22.0,
    commission=0.35,
):
    """Run a lightweight replay of the live XAUUSD signal logic on enriched bars."""
    if enriched is None or len(enriched) < 5:
        return pd.DataFrame(), pd.DataFrame(columns=["timestamp", "equity"]).set_index("timestamp")

    capital = float(starting_capital)
    day_start_equity = float(starting_capital)
    current_day = pd.Timestamp(enriched.index[0]).date()
    min_allowed_equity = float(starting_capital - max_total_loss)
    position = None
    trades = []
    equity_points = []

    for idx in range(2, len(enriched)):
        bar_time = pd.Timestamp(enriched.index[idx])
        row = enriched.iloc[idx]
        previous = enriched.iloc[idx - 1]

        if bar_time.date() != current_day:
            current_day = bar_time.date()
            day_start_equity = capital

        if position is not None:
            side_mult = 1.0 if position["side"] == "long" else -1.0
            exit_price = None
            exit_reason = None

            if position["side"] == "long":
                if safe_float(row.get("low", row["close"])) <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "SL"
                elif safe_float(row.get("high", row["close"])) >= position["take_profit"]:
                    exit_price = position["take_profit"]
                    exit_reason = "TP"
                elif bool(row.get("cross_down", False)):
                    exit_price = safe_float(row["close"])
                    exit_reason = "SignalFlip"
            else:
                if safe_float(row.get("high", row["close"])) >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    exit_reason = "SL"
                elif safe_float(row.get("low", row["close"])) <= position["take_profit"]:
                    exit_price = position["take_profit"]
                    exit_reason = "TP"
                elif bool(row.get("cross_up", False)):
                    exit_price = safe_float(row["close"])
                    exit_reason = "SignalFlip"

            if exit_price is not None:
                gross_pnl = (exit_price - position["entry_price"]) * side_mult * position["size"]
                pnl = gross_pnl - commission
                capital += pnl
                trades.append(
                    {
                        "side": position["side"],
                        "entry_time": position["entry_time"],
                        "exit_time": bar_time,
                        "entry_price": position["entry_price"],
                        "exit_price": exit_price,
                        "stop_loss": position["stop_loss"],
                        "take_profit": position["take_profit"],
                        "size": position["size"],
                        "pnl": pnl,
                        "cumulative_equity": capital,
                        "exit_reason": exit_reason,
                    }
                )
                position = None

        equity_points.append({"timestamp": bar_time, "equity": capital})

        if position is not None:
            continue

        atr = safe_float(previous.get("atr14", 0.0))
        if atr <= 0:
            continue

        estimated_trade_risk = capital * risk_per_trade
        daily_remaining = capital - (day_start_equity - max_daily_loss)
        total_remaining = capital - min_allowed_equity
        if daily_remaining <= estimated_trade_risk or total_remaining <= estimated_trade_risk:
            continue

        rsi = safe_float(previous.get("rsi14", 0.0))
        adx = safe_float(previous.get("adx14", 0.0))
        volume = safe_float(previous.get("volume", 0.0))
        volume_ma = safe_float(previous.get("volume_ma20", 0.0))
        close_price = safe_float(previous.get("close", 0.0))
        ema50 = safe_float(previous.get("ema50", 0.0))
        bias = str(previous.get("m5_bias", "neutral"))

        long_entry = (
            adx >= adx_min_strength
            and bool(previous.get("cross_up", False))
            and bias == "bull"
            and close_price > ema50
            and 53 <= rsi <= 67
            and volume > volume_ma * min_volume_multiplier
        )
        short_entry = (
            adx >= adx_min_strength
            and bool(previous.get("cross_down", False))
            and bias == "bear"
            and close_price < ema50
            and 33 <= rsi <= 47
            and volume > volume_ma * min_volume_multiplier
        )

        if not long_entry and not short_entry:
            continue

        stop_distance = atr * sl_atr_multiplier
        take_distance = atr * tp_atr_multiplier
        if stop_distance <= 0:
            continue

        entry_price = safe_float(row.get("open", row["close"]))
        size = estimated_trade_risk / stop_distance
        if size <= 0:
            continue

        if long_entry:
            position = {
                "side": "long",
                "entry_time": bar_time,
                "entry_price": entry_price,
                "stop_loss": entry_price - stop_distance,
                "take_profit": entry_price + take_distance,
                "size": size,
            }
        elif short_entry:
            position = {
                "side": "short",
                "entry_time": bar_time,
                "entry_price": entry_price,
                "stop_loss": entry_price + stop_distance,
                "take_profit": entry_price - take_distance,
                "size": size,
            }

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_points)
    if not equity_df.empty:
        equity_df = equity_df.set_index("timestamp")
    return trades_df, equity_df

# ─── MAPPEN AANMAKEN ALS ZE NOG NIET BESTAAN ─────────────────
os.makedirs('results', exist_ok=True)
os.makedirs('logs', exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# INSTELLINGEN — alle parameters op één plek
# ═══════════════════════════════════════════════════════════════
SYMBOL      = "GC=F"        # XAUUSD futures ticker op Yahoo Finance
START_DATUM = "2024-01-01"  # Backtest startdatum
EIND_DATUM  = "2026-05-11"  # Backtest einddatum (mei 2026)
INTERVAL    = "1d"          # Dagelijkse kaarsen (beste dekking voor deze periode)

# Verbetering 1: Geen short trades — goud heeft een structurele opwaartse trend
ALLEEN_LONG = True

# MA startwaarden (worden automatisch overschreven door optimalisatie)
FAST_MA = 20
SLOW_MA = 50

# Verbetering 2: RSI filter — koopt niet in extreme zones
RSI_PERIODE = 14
RSI_MIN     = 40   # Onder 40 = te zwak / dalende markt
RSI_MAX     = 65   # Boven 65 = overbought, te laat instappen

# Verbetering 4: ATR multipliers voor dynamische SL en TP
ATR_PERIODE       = 14
ATR_SL_MULTIPLIER = 1.5   # SL = entry_prijs - 1.5 × ATR
ATR_TP_MULTIPLIER = 2.5   # TP = entry_prijs + 2.5 × ATR  (risk/reward 1:1.67)

# Verbetering 5: Handelssessie filter (UTC)
SESSIE_START = 7   # London sessie open
SESSIE_EIND  = 21  # New York sessie sluit

# Kapitaal en handelskosten
STARTKAPITAAL = 10_000  # Startkapitaal in dollars
LOT_WAARDE    = 100     # $100 per punt beweging (0.01 lot XAUUSD ≈ $1/punt)
COMMISSIE     = 3.50    # Commissie per trade round-trip in dollars
# ═══════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────
# DATA & INDICATOREN
# ─────────────────────────────────────────────────────────────

def haal_data(symbol, start, eind, interval):
    """Download historische OHLCV data via Yahoo Finance."""
    print(f"  Data downloaden: {symbol} ({start} tot {eind}, {interval})...")
    df = yf.download(symbol, start=start, end=eind, interval=interval,
                     progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"Geen data ontvangen voor {symbol}. Controleer symbool en datum.")

    # Flatten MultiIndex kolommen (nieuwere yfinance versies)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower()
                      for c in df.columns]

    print(f"  {len(df)} kaarsen geladen "
          f"({df.index[0].date()} tot {df.index[-1].date()})\n")
    return df


def bereken_rsi(close, periode=14):
    """RSI via Wilder's exponential smoothing methode."""
    delta       = close.diff()
    winst       = delta.clip(lower=0)
    verlies     = (-delta).clip(lower=0)
    gem_winst   = winst.ewm(com=periode - 1, adjust=False).mean()
    gem_verlies = verlies.ewm(com=periode - 1, adjust=False).mean()
    rs = gem_winst / gem_verlies.replace(0, 1e-10)  # Vermijd deling door nul
    return 100 - (100 / (1 + rs))


def bereken_atr(high, low, close, periode=14):
    """ATR meet de gemiddelde dagelijkse prijsbeweging (volatiliteit maatstaf)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=periode - 1, adjust=False).mean()


def bereken_adx(high, low, close, periode=14):
    """ADX meet trendsterkte: >22 = trending, <20 = zijwaarts."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    atr = bereken_atr(high, low, close, periode)
    atr_safe = atr.replace(0, float('nan'))
    plus_di = 100 * plus_dm.ewm(com=periode - 1, adjust=False).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(com=periode - 1, adjust=False).mean() / atr_safe
    di_sum = (plus_di + minus_di).replace(0, float('nan'))
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(com=periode - 1, adjust=False).mean()
    return adx.fillna(0.0)


def check_sessie(datum):
    """
    Geeft True terug als de candle binnen handelssessietijden valt.
    Voor dagelijkse data (hour == 0) is de sessie filter niet toepasbaar.
    """
    if hasattr(datum, 'hour') and datum.hour != 0:
        return SESSIE_START <= datum.hour < SESSIE_EIND
    return True  # Dagelijkse candles: geen uurinfo, altijd doorgaan


def bereken_indicatoren(df, fast, slow):
    """Voegt MA's, RSI, ATR en crossover-signalen toe aan de dataframe."""
    df = df.copy()
    df['ma_fast'] = df['close'].rolling(window=fast).mean()
    df['ma_slow'] = df['close'].rolling(window=slow).mean()
    df['rsi']     = bereken_rsi(df['close'], RSI_PERIODE)
    df['atr']     = bereken_atr(df['high'], df['low'], df['close'], ATR_PERIODE)

    # Golden cross: snelle MA kruist boven trage MA → koopsignaal
    df['cross_up'] = (
        (df['ma_fast'] > df['ma_slow']) &
        (df['ma_fast'].shift(1) <= df['ma_slow'].shift(1))
    )
    # Death cross: snelle MA kruist onder trage MA → sluitingssignaal
    df['cross_down'] = (
        (df['ma_fast'] < df['ma_slow']) &
        (df['ma_fast'].shift(1) >= df['ma_slow'].shift(1))
    )
    return df.dropna()


# ─────────────────────────────────────────────────────────────
# VERBETERING 1 + 2 + 4 + 5: Verbeterde backtest (alleen LONG)
# ─────────────────────────────────────────────────────────────

def run_verbeterde_backtest(df):
    """
    Verbeterde backtest met 4 actieve filters:
    - Alleen LONG posities (geen shorts)
    - RSI filter bij entry (40–65)
    - ATR-gebaseerde SL en TP
    - Sessie filter (07–21 UTC, alleen relevant bij intraday data)
    """
    kapitaal     = STARTKAPITAAL
    equity_curve = []
    trades       = []
    open_pos     = None
    rsi_gefilterd    = 0
    sessie_gefilterd = 0

    for datum, rij in df.iterrows():
        prijs = float(rij['close'])
        atr   = float(rij['atr'])

        # ── Beheer open LONG positie ──────────────────────────
        if open_pos is not None:
            verschil   = (prijs - open_pos['prijs']) * LOT_WAARDE
            sl_drempel = open_pos['sl_dollar']
            tp_drempel = open_pos['tp_dollar']

            sluit = False
            reden = ''

            if verschil <= -sl_drempel:
                verschil = -sl_drempel
                sluit = True
                reden = 'Stop Loss'
            elif verschil >= tp_drempel:
                verschil = tp_drempel
                sluit = True
                reden = 'Take Profit'
            elif rij['cross_down']:
                # Death cross sluit de LONG — maar opent GEEN short positie
                sluit = True
                reden = 'Death Cross'

            if sluit:
                netto = round(verschil - COMMISSIE, 2)
                kapitaal += netto
                trades.append({
                    'open_datum':  open_pos['datum'],
                    'sluit_datum': datum,
                    'richting':    'KOOP',
                    'open_prijs':  open_pos['prijs'],
                    'sluit_prijs': prijs,
                    'pnl':         netto,
                    'reden':       reden,
                    'win':         netto > 0,
                    'duur_dagen':  (datum - open_pos['datum']).days,
                    'atr_entry':   round(open_pos['atr'], 2),
                    'sl_niveau':   round(open_pos['prijs'] - open_pos['atr'] * ATR_SL_MULTIPLIER, 2),
                    'tp_niveau':   round(open_pos['prijs'] + open_pos['atr'] * ATR_TP_MULTIPLIER, 2),
                })
                open_pos = None

        # ── Zoek nieuwe LONG entry op golden cross ───────────
        if open_pos is None and rij['cross_up']:

            # Verbetering 5: Sessie check (actief bij intraday data)
            if not check_sessie(datum):
                sessie_gefilterd += 1
                equity_curve.append({'datum': datum, 'kapitaal': round(kapitaal, 2)})
                continue

            # Verbetering 2: RSI filter — blokkeer overbought en te zwakke entries
            rsi_waarde = float(rij['rsi'])
            if not (RSI_MIN <= rsi_waarde <= RSI_MAX):
                rsi_gefilterd += 1
                equity_curve.append({'datum': datum, 'kapitaal': round(kapitaal, 2)})
                continue

            # Verbetering 4: Bereken dynamische SL en TP op basis van ATR
            sl_dollar = ATR_SL_MULTIPLIER * atr * LOT_WAARDE
            tp_dollar = ATR_TP_MULTIPLIER * atr * LOT_WAARDE

            open_pos = {
                'richting':  'KOOP',
                'prijs':     prijs,
                'datum':     datum,
                'atr':       atr,
                'sl_dollar': sl_dollar,
                'tp_dollar': tp_dollar,
            }

        equity_curve.append({'datum': datum, 'kapitaal': round(kapitaal, 2)})

    filter_stats = {
        'rsi_gefilterd':    rsi_gefilterd,
        'sessie_gefilterd': sessie_gefilterd,
    }
    equity_df = pd.DataFrame(equity_curve).set_index('datum')
    return pd.DataFrame(trades), equity_df, filter_stats


# ─────────────────────────────────────────────────────────────
# ORIGINELE BACKTEST — baseline voor vergelijking
# ─────────────────────────────────────────────────────────────

def run_originele_backtest(df):
    """
    Simuleert de originele strategie: MA 20/50, long én short trades,
    vaste $50 SL en $100 TP. Dient als vergelijkingsbasis.
    """
    ORIG_SL = 50
    ORIG_TP = 100

    df_o = df.copy()
    df_o['ma_fast'] = df_o['close'].rolling(window=20).mean()
    df_o['ma_slow'] = df_o['close'].rolling(window=50).mean()
    df_o['rsi']     = bereken_rsi(df_o['close'], RSI_PERIODE)
    df_o['atr']     = bereken_atr(df_o['high'], df_o['low'], df_o['close'], ATR_PERIODE)
    df_o['cross_up'] = (
        (df_o['ma_fast'] > df_o['ma_slow']) &
        (df_o['ma_fast'].shift(1) <= df_o['ma_slow'].shift(1))
    )
    df_o['cross_down'] = (
        (df_o['ma_fast'] < df_o['ma_slow']) &
        (df_o['ma_fast'].shift(1) >= df_o['ma_slow'].shift(1))
    )
    df_o = df_o.dropna()

    kapitaal     = STARTKAPITAAL
    equity_curve = []
    trades       = []
    open_pos     = None

    for datum, rij in df_o.iterrows():
        prijs = float(rij['close'])

        if open_pos is not None:
            verschil = prijs - open_pos['prijs']
            if open_pos['richting'] == 'VERKOOP':
                verschil = -verschil
            pnl = verschil * LOT_WAARDE

            sluit = False
            reden = ''
            if pnl <= -ORIG_SL:
                pnl = -ORIG_SL; sluit = True; reden = 'SL'
            elif pnl >= ORIG_TP:
                pnl = ORIG_TP;  sluit = True; reden = 'TP'
            elif rij['cross_up']   and open_pos['richting'] == 'VERKOOP':
                sluit = True; reden = 'Omgekeerd signaal'
            elif rij['cross_down'] and open_pos['richting'] == 'KOOP':
                sluit = True; reden = 'Omgekeerd signaal'

            if sluit:
                netto = round(pnl - COMMISSIE, 2)
                kapitaal += netto
                trades.append({
                    'open_datum':  open_pos['datum'],
                    'sluit_datum': datum,
                    'richting':    open_pos['richting'],
                    'open_prijs':  open_pos['prijs'],
                    'sluit_prijs': prijs,
                    'pnl':         netto,
                    'reden':       reden,
                    'win':         netto > 0,
                    'duur_dagen':  (datum - open_pos['datum']).days,
                })
                open_pos = None

        if open_pos is None:
            if rij['cross_up']:
                open_pos = {'richting': 'KOOP',    'prijs': prijs, 'datum': datum}
            elif rij['cross_down']:
                open_pos = {'richting': 'VERKOOP', 'prijs': prijs, 'datum': datum}

        equity_curve.append({'datum': datum, 'kapitaal': round(kapitaal, 2)})

    equity_df = pd.DataFrame(equity_curve).set_index('datum')
    return pd.DataFrame(trades), equity_df


# ─────────────────────────────────────────────────────────────
# VERBETERING 3: Automatische MA parameter optimalisatie
# ─────────────────────────────────────────────────────────────

def optimaliseer_ma(df):
    """
    Test automatisch alle MA combinaties (fast 10–50 stap 5, slow 30–200 stap 10)
    en kiest de beste op basis van totaal rendement.
    Sla alle resultaten op in results/optimalisatie_DATUM.csv.
    """
    print("  MA parameters optimaliseren (alle combinaties worden getest)...")

    # Pre-bereken RSI en ATR eenmalig — zijn onafhankelijk van MA periode
    df_base = df.copy()
    df_base['rsi'] = bereken_rsi(df_base['close'], RSI_PERIODE)
    df_base['atr'] = bereken_atr(df_base['high'], df_base['low'],
                                  df_base['close'], ATR_PERIODE)

    fast_reeks = range(10, 51, 5)    # 10, 15, 20, 25, 30, 35, 40, 45, 50
    slow_reeks = range(30, 201, 10)  # 30, 40, 50, ..., 200
    combinaties = [(f, s) for f in fast_reeks for s in slow_reeks if f < s]
    print(f"  Totaal: {len(combinaties)} combinaties...\n")

    resultaten = []

    for i, (fast, slow) in enumerate(combinaties):
        if i % 25 == 0:
            print(f"    Voortgang: {i}/{len(combinaties)} ({i*100//len(combinaties)}%)")

        df_t = df_base.copy()
        df_t['ma_fast'] = df_t['close'].rolling(fast).mean()
        df_t['ma_slow'] = df_t['close'].rolling(slow).mean()
        df_t['cross_up'] = (
            (df_t['ma_fast'] > df_t['ma_slow']) &
            (df_t['ma_fast'].shift(1) <= df_t['ma_slow'].shift(1))
        )
        df_t['cross_down'] = (
            (df_t['ma_fast'] < df_t['ma_slow']) &
            (df_t['ma_fast'].shift(1) >= df_t['ma_slow'].shift(1))
        )
        df_t = df_t.dropna()

        if df_t.empty:
            continue

        trades_t, equity_t, _ = run_verbeterde_backtest(df_t)

        if len(trades_t) < 2:
            continue

        eind_kap  = equity_t['kapitaal'].iloc[-1]
        rendement = (eind_kap - STARTKAPITAAL) / STARTKAPITAAL * 100
        wins      = int(trades_t['win'].sum())
        win_rate  = wins / len(trades_t) * 100
        roll_max  = equity_t['kapitaal'].cummax()
        max_dd    = ((equity_t['kapitaal'] - roll_max) / roll_max * 100).min()

        dagret = equity_t['kapitaal'].pct_change().dropna()
        sharpe = (dagret.mean() / dagret.std() * np.sqrt(252)
                  if dagret.std() > 0 else 0)

        resultaten.append({
            'fast_ma':     fast,
            'slow_ma':     slow,
            'rendement':   round(rendement, 2),
            'trades':      len(trades_t),
            'win_rate':    round(win_rate, 1),
            'max_dd':      round(max_dd, 1),
            'sharpe':      round(sharpe, 2),
            'eindkapitaal': round(eind_kap, 2),
        })

    if not resultaten:
        print("  Geen bruikbare combinaties gevonden — standaard MA 20/50 wordt gebruikt.")
        return FAST_MA, SLOW_MA

    res_df = pd.DataFrame(resultaten).sort_values('rendement', ascending=False)

    # Sla alle resultaten op als CSV
    datum_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_pad   = f'results/optimalisatie_{datum_str}.csv'
    res_df.to_csv(csv_pad, index=False)
    print(f"\n  Optimalisatieresultaten opgeslagen: {csv_pad}")

    # Top 5 tabel printen
    print("\n  TOP 5 BESTE MA COMBINATIES:")
    print(f"  {'#':<3} {'Fast':>5} {'Slow':>5} {'Rendement':>11} "
          f"{'Trades':>7} {'Win%':>6} {'Max DD':>8} {'Sharpe':>7}")
    print(f"  {'---':<3} {'-----':>5} {'-----':>5} {'-----------':>11} "
          f"{'-------':>7} {'------':>6} {'--------':>8} {'-------':>7}")

    for rank, (_, r) in enumerate(res_df.head(5).iterrows(), 1):
        print(f"  {rank:<3} {int(r['fast_ma']):>5} {int(r['slow_ma']):>5} "
              f"{r['rendement']:>+9.1f}%  {int(r['trades']):>7} "
              f"{r['win_rate']:>5.1f}%  {r['max_dd']:>7.1f}%  {r['sharpe']:>7.2f}")

    beste = res_df.iloc[0]
    print(f"\n  Beste combinatie gekozen: MA {int(beste['fast_ma'])} / "
          f"MA {int(beste['slow_ma'])} -> {beste['rendement']:+.1f}% rendement\n")

    return int(beste['fast_ma']), int(beste['slow_ma'])


# ─────────────────────────────────────────────────────────────
# VERBETERING 6: Uitgebreide statistieken
# ─────────────────────────────────────────────────────────────

def bereken_statistieken(trades_df, equity_df, filter_stats, fast_ma, slow_ma,
                          label="STRATEGIE"):
    """
    Berekent en print uitgebreide statistieken:
    Sharpe ratio, profit factor, maandanalyse, gefilterde signalen.
    """
    if trades_df.empty:
        print(f"  [{label}] Geen trades gevonden in deze periode.")
        return {}

    totaal     = len(trades_df)
    wins       = int(trades_df['win'].sum())
    losses     = totaal - wins
    win_rate   = wins / totaal * 100
    totaal_pnl = trades_df['pnl'].sum()
    gem_win    = trades_df.loc[ trades_df['win'],  'pnl'].mean() if wins    > 0 else 0
    gem_loss   = trades_df.loc[~trades_df['win'], 'pnl'].mean() if losses > 0 else 0
    eind_kap   = equity_df['kapitaal'].iloc[-1]
    rendement  = (eind_kap - STARTKAPITAAL) / STARTKAPITAAL * 100

    # Max drawdown
    roll_max = equity_df['kapitaal'].cummax()
    max_dd   = ((equity_df['kapitaal'] - roll_max) / roll_max * 100).min()

    # Sharpe ratio (geannualiseerd, risk-free rate = 0)
    dagret = equity_df['kapitaal'].pct_change().dropna()
    sharpe = (dagret.mean() / dagret.std() * np.sqrt(252)
              if dagret.std() > 0 else 0)

    # Profit factor = totale winst / totaal verlies
    totale_winst   = trades_df.loc[ trades_df['win'],  'pnl'].sum() if wins    > 0 else 0
    totale_verlies = trades_df.loc[~trades_df['win'], 'pnl'].abs().sum() if losses > 0 else 0
    profit_factor  = (totale_winst / totale_verlies) if totale_verlies > 0 else float('inf')

    # Gemiddelde trade duur
    gem_duur = trades_df['duur_dagen'].mean() if 'duur_dagen' in trades_df.columns else 0

    # Beste en slechtste maand
    td = trades_df.copy()
    td['maand'] = pd.to_datetime(td['sluit_datum']).dt.to_period('M')
    maand_pnl   = td.groupby('maand')['pnl'].sum()

    if not maand_pnl.empty:
        beste_maand      = str(maand_pnl.idxmax())
        slechtste_maand  = str(maand_pnl.idxmin())
        beste_waarde     = maand_pnl.max()
        slechtste_waarde = maand_pnl.min()
    else:
        beste_maand = slechtste_maand = "N/B"
        beste_waarde = slechtste_waarde = 0

    print("\n" + "=" * 62)
    print(f"  BACKTEST [{label}]  |  MA {fast_ma}/{slow_ma}")
    print("=" * 62)
    print(f"  Periode:            {equity_df.index[0].date()} t/m "
          f"{equity_df.index[-1].date()}")
    print(f"  Startkapitaal:      ${STARTKAPITAAL:>10,.2f}")
    print(f"  Eindkapitaal:       ${eind_kap:>10,.2f}")
    print(f"  Totaal rendement:   {rendement:>+10.1f}%")
    print(f"  Totaal P&L:         ${totaal_pnl:>+10,.2f}")
    print("-" * 62)
    print(f"  Trades:             {totaal:>10}")
    print(f"  Wins:               {wins:>10}  ({win_rate:.1f}%)")
    print(f"  Losses:             {losses:>10}")
    print(f"  Gem. winst:         ${gem_win:>+10.2f}")
    print(f"  Gem. verlies:       ${gem_loss:>+10.2f}")
    print(f"  Gem. trade duur:    {gem_duur:>10.1f} dagen")
    print("-" * 62)
    print(f"  Max drawdown:       {max_dd:>10.1f}%")

    sharpe_label = "  Goed (>1.0)" if sharpe > 1.0 else "  Let op (<1.0)"
    pf_label     = "  Goed (>1.5)" if profit_factor > 1.5 else "  Let op (<1.5)"
    print(f"  Sharpe ratio:       {sharpe:>10.2f}{sharpe_label}")
    print(f"  Profit factor:      {profit_factor:>10.2f}{pf_label}")
    print("-" * 62)
    print(f"  Beste maand:        {beste_maand:>10}  (${beste_waarde:+.2f})")
    print(f"  Slechtste maand:    {slechtste_maand:>10}  (${slechtste_waarde:+.2f})")

    rsi_blok  = filter_stats.get('rsi_gefilterd', 0)
    sess_blok = filter_stats.get('sessie_gefilterd', 0)
    if rsi_blok > 0 or sess_blok > 0:
        print("-" * 62)
        print(f"  RSI geblokkeerd:    {rsi_blok:>10} signalen")
        print(f"  Sessie geblokkeerd: {sess_blok:>10} signalen")

    print("=" * 62)

    return {
        'label': label, 'fast_ma': fast_ma, 'slow_ma': slow_ma,
        'totaal': totaal, 'wins': wins, 'losses': losses,
        'win_rate': win_rate, 'rendement': rendement,
        'eind_kap': eind_kap, 'max_dd': max_dd,
        'sharpe': sharpe, 'profit_factor': profit_factor,
        'gem_duur': gem_duur,
    }


def druk_vergelijkingstabel(stats_orig, stats_verb):
    """Verbetering 6: Vergelijkingstabel originele strategie vs verbeterde strategie."""
    print("\n" + "=" * 68)
    print("  VERGELIJKING: ORIGINEEL vs VERBETERD")
    print("=" * 68)
    print(f"  {'Metriek':<24} {'Origineel':>17} {'Verbeterd':>17}  Resultaat")
    print(f"  {'-'*24} {'-'*17} {'-'*17}  ---------")

    metrics = [
        ('Eindkapitaal ($)',   'eind_kap',       '${:,.0f}',  True),
        ('Rendement',          'rendement',      '{:+.1f}%',  True),
        ('Aantal trades',      'totaal',         '{:.0f}',    None),
        ('Win rate',           'win_rate',       '{:.1f}%',   True),
        ('Max drawdown',       'max_dd',         '{:.1f}%',   True),
        ('Sharpe ratio',       'sharpe',         '{:.2f}',    True),
        ('Profit factor',      'profit_factor',  '{:.2f}',    True),
        ('Gem. trade duur',    'gem_duur',       '{:.1f}d',   None),
    ]

    for naam, sleutel, fmt, hoger_beter in metrics:
        o = stats_orig.get(sleutel, 0)
        v = stats_verb.get(sleutel, 0)
        try:
            o_str = fmt.format(o)
            v_str = fmt.format(v)
        except Exception:
            o_str, v_str = str(o), str(v)

        if hoger_beter is True:
            status = "Beter   +" if v > o else ("Gelijk" if abs(v - o) < 0.01 else "Slechter")
        else:
            status = ""

        print(f"  {naam:<24} {o_str:>17} {v_str:>17}  {status}")

    print("=" * 68)
    verschil = stats_verb.get('rendement', 0) - stats_orig.get('rendement', 0)
    print(f"\n  Totale rendementsverandering: {verschil:+.1f}% t.o.v. origineel")
    print("=" * 68 + "\n")


# ─────────────────────────────────────────────────────────────
# VERBETERING 6: Uitgebreide grafiek (6 panelen)
# ─────────────────────────────────────────────────────────────

def maak_grafiek(df, verb_trades, verb_equity, orig_equity, fast_ma, slow_ma):
    """
    6-panelen grafiek:
    (1) Prijsgrafiek met MA's en trade-signalen
    (2) P&L per trade + cumulatieve lijn
    (3) Equity curve: verbeterd vs origineel
    (4) Maandelijks resultaat
    (5) Drawdown curve
    (6) Samenvatting statistieken
    """
    fig = plt.figure(figsize=(16, 12), facecolor='#0D0D0D')
    gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.32)

    fig.suptitle(
        f'XAUUSD Verbeterde Backtest  |  MA {fast_ma}/{slow_ma}  |  2024–Mei 2026',
        color='#D4A843', fontsize=13, fontweight='bold', y=0.99,
    )

    ax_prijs  = fig.add_subplot(gs[0, :])   # Hele bovenste rij
    ax_pnl    = fig.add_subplot(gs[1, 0])
    ax_equity = fig.add_subplot(gs[1, 1])
    ax_maand  = fig.add_subplot(gs[2, 0])
    ax_dd     = fig.add_subplot(gs[2, 1])

    for ax in [ax_prijs, ax_pnl, ax_equity, ax_maand, ax_dd]:
        ax.set_facecolor('#141414')
        ax.tick_params(colors='#666666', labelsize=7)
        ax.spines[:].set_color('#222222')

    # ── Paneel 1: Prijs + MA's + trade entries/exits ─────────
    ax_prijs.plot(df.index, df['close'],   color='#D4A843', lw=0.8,
                  label='XAUUSD', alpha=0.9)
    ax_prijs.plot(df.index, df['ma_fast'], color='#378ADD', lw=1.2,
                  label=f'MA {fast_ma} (snel)', alpha=0.85)
    ax_prijs.plot(df.index, df['ma_slow'], color='#D85A30', lw=1.2,
                  label=f'MA {slow_ma} (traag)', alpha=0.85)

    if not verb_trades.empty:
        for _, t in verb_trades.iterrows():
            kleur_exit = '#1D9E75' if t['win'] else '#D85A30'
            ax_prijs.scatter(t['open_datum'],  t['open_prijs'],
                             color='#1D9E75', marker='^', s=45, zorder=5)
            ax_prijs.scatter(t['sluit_datum'], t['sluit_prijs'],
                             color=kleur_exit, marker='x', s=30, zorder=5, alpha=0.7)

    ax_prijs.set_ylabel('Prijs (USD)', color='#888888', fontsize=8)
    ax_prijs.set_title('XAUUSD Prijs + MA Signalen  (▲ = entry  ✕ = exit)',
                       color='#CCCCCC', fontsize=9)
    ax_prijs.legend(fontsize=7.5, facecolor='#1A1A1A', edgecolor='#333333',
                    labelcolor='white', loc='upper left')
    ax_prijs.grid(color='#1E1E1E', lw=0.4)
    ax_prijs.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax_prijs.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=7)

    # ── Paneel 2: P&L per trade + cumulatieve lijn ───────────
    if not verb_trades.empty:
        kleuren = ['#1D9E75' if p > 0 else '#D85A30' for p in verb_trades['pnl']]
        ax_pnl.bar(range(len(verb_trades)), verb_trades['pnl'],
                   color=kleuren, alpha=0.8, width=0.7)
        ax_pnl.axhline(0, color='#444444', lw=0.8, linestyle='--')

        ax_pnl2 = ax_pnl.twinx()
        ax_pnl2.plot(range(len(verb_trades)), verb_trades['pnl'].cumsum(),
                     color='#D4A843', lw=1.4, alpha=0.8, label='Cum.')
        ax_pnl2.set_facecolor('#141414')
        ax_pnl2.tick_params(colors='#666666', labelsize=7)
        ax_pnl2.spines[:].set_color('#222222')
        ax_pnl2.set_ylabel('Cum. P&L ($)', color='#888888', fontsize=7)

    ax_pnl.set_ylabel('P&L per trade ($)', color='#888888', fontsize=8)
    ax_pnl.set_xlabel('Trade #',           color='#888888', fontsize=8)
    ax_pnl.set_title('P&L per Trade + Cumulatief', color='#CCCCCC', fontsize=9)
    ax_pnl.grid(color='#1E1E1E', lw=0.4, axis='y')

    # ── Paneel 3: Equity curve — verbeterd vs origineel ──────
    ax_equity.plot(verb_equity.index, verb_equity['kapitaal'],
                   color='#1D9E75', lw=1.5, label='Verbeterd', zorder=3)
    if orig_equity is not None and not orig_equity.empty:
        ax_equity.plot(orig_equity.index, orig_equity['kapitaal'],
                       color='#D85A30', lw=1.0, alpha=0.7, label='Origineel', zorder=2)
    ax_equity.axhline(STARTKAPITAAL, color='#555555', lw=0.8, linestyle='--',
                      label=f'Start ${STARTKAPITAAL:,}')
    ax_equity.fill_between(verb_equity.index, STARTKAPITAAL, verb_equity['kapitaal'],
                           where=verb_equity['kapitaal'] >= STARTKAPITAAL,
                           color='#1D9E75', alpha=0.12)
    ax_equity.fill_between(verb_equity.index, STARTKAPITAAL, verb_equity['kapitaal'],
                           where=verb_equity['kapitaal'] < STARTKAPITAAL,
                           color='#D85A30', alpha=0.12)
    ax_equity.set_ylabel('Kapitaal ($)', color='#888888', fontsize=8)
    ax_equity.set_title('Equity Curve (Verbeterd vs Origineel)', color='#CCCCCC', fontsize=9)
    ax_equity.legend(fontsize=7.5, facecolor='#1A1A1A', edgecolor='#333333',
                     labelcolor='white')
    ax_equity.grid(color='#1E1E1E', lw=0.4)
    ax_equity.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax_equity.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=7)

    # ── Paneel 4: Maandelijks P&L ────────────────────────────
    if not verb_trades.empty:
        td_copy = verb_trades.copy()
        td_copy['maand'] = pd.to_datetime(td_copy['sluit_datum']).dt.to_period('M')
        maand_pnl = td_copy.groupby('maand')['pnl'].sum()
        kleuren_m = ['#1D9E75' if p > 0 else '#D85A30' for p in maand_pnl.values]
        ax_maand.bar(range(len(maand_pnl)), maand_pnl.values,
                     color=kleuren_m, alpha=0.85, width=0.85)
        ax_maand.axhline(0, color='#444444', lw=0.8, linestyle='--')
        ax_maand.set_xticks(range(len(maand_pnl)))
        ax_maand.set_xticklabels(
            [str(m) for m in maand_pnl.index],
            rotation=45, ha='right', fontsize=6,
        )
    ax_maand.set_ylabel('P&L ($)', color='#888888', fontsize=8)
    ax_maand.set_title('Maandelijks Resultaat', color='#CCCCCC', fontsize=9)
    ax_maand.grid(color='#1E1E1E', lw=0.4, axis='y')

    # ── Paneel 5: Drawdown curve ─────────────────────────────
    roll_max = verb_equity['kapitaal'].cummax()
    dd_curve = (verb_equity['kapitaal'] - roll_max) / roll_max * 100
    ax_dd.fill_between(verb_equity.index, 0, dd_curve,
                       color='#D85A30', alpha=0.45, label='Drawdown')
    ax_dd.plot(verb_equity.index, dd_curve, color='#D85A30', lw=0.8)
    ax_dd.axhline(0, color='#555555', lw=0.6, linestyle='--')
    ax_dd.set_ylabel('Drawdown (%)', color='#888888', fontsize=8)
    ax_dd.set_title('Drawdown Curve', color='#CCCCCC', fontsize=9)
    ax_dd.grid(color='#1E1E1E', lw=0.4)
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax_dd.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=7)

    plt.tight_layout(rect=[0, 0, 1, 0.98])

    datum_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    bestand   = f'results/backtest_grafiek_{datum_str}.png'
    plt.savefig(bestand, dpi=150, bbox_inches='tight', facecolor='#0D0D0D')
    print(f"  Grafiek opgeslagen: {bestand}")
    plt.show()


# ─────────────────────────────────────────────────────────────
# LIVE BOT HELPER FUNCTIONS (used by indicators.py)
# ─────────────────────────────────────────────────────────────

def safe_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
        return default if (result != result) else result  # NaN check
    except (TypeError, ValueError):
        return default


def add_indicators(df: "pd.DataFrame") -> "pd.DataFrame":
    df = df.copy()
    df["ema8"]        = df["close"].ewm(span=8,  adjust=False).mean()
    df["ema21"]       = df["close"].ewm(span=21, adjust=False).mean()
    df["ema50"]       = df["close"].ewm(span=50, adjust=False).mean()
    df["rsi14"]       = bereken_rsi(df["close"], 14)
    df["atr14"]       = bereken_atr(df["high"], df["low"], df["close"], 14)
    df["adx14"]       = bereken_adx(df["high"], df["low"], df["close"], 14)
    df["volume_ma20"] = df["volume"].rolling(window=20).mean()
    df["cross_up"]    = (df["ema8"] > df["ema21"]) & (df["ema8"].shift(1) <= df["ema21"].shift(1))
    df["cross_down"]  = (df["ema8"] < df["ema21"]) & (df["ema8"].shift(1) >= df["ema21"].shift(1))
    return df.dropna()


def make_m5_bars(m1_df: "pd.DataFrame") -> "pd.DataFrame":
    m5 = m1_df.resample("5min").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    m5["ema8"]  = m5["close"].ewm(span=8,  adjust=False).mean()
    m5["ema21"] = m5["close"].ewm(span=21, adjust=False).mean()
    return m5


def apply_m5_bias(m1: "pd.DataFrame", m5: "pd.DataFrame") -> "pd.DataFrame":
    m1 = m1.copy()
    bias = m5["ema8"] > m5["ema21"]
    bias_reindexed = bias.reindex(m1.index, method="ffill")
    m1["m5_bias"] = bias_reindexed.map({True: "bull", False: "bear"}).fillna("bear")
    return m1


# ─────────────────────────────────────────────────────────────
# HOOFDFUNCTIE
# ─────────────────────────────────────────────────────────────

def main():
    """Voert de volledige verbeterde backtest uit in 4 stappen."""
    print("\n" + "=" * 62)
    print("  XAUUSD VERBETERDE BACKTEST  |  2024 - Mei 2026")
    print("=" * 62 + "\n")

    # ── Stap 1/4: Data laden ─────────────────────────────────
    print("[1/4] Data laden...")
    df_raw = haal_data(SYMBOL, START_DATUM, EIND_DATUM, INTERVAL)

    # ── Stap 2/4: Originele baseline ─────────────────────────
    print("[2/4] Originele strategie draaien (baseline voor vergelijking)...")
    orig_trades, orig_equity = run_originele_backtest(df_raw)
    orig_stats = bereken_statistieken(
        orig_trades, orig_equity,
        {'rsi_gefilterd': 0, 'sessie_gefilterd': 0},
        20, 50, "ORIGINEEL (MA 20/50 + shorts)",
    )

    # ── Stap 3/4: MA optimalisatie ───────────────────────────
    print("\n[3/4] MA parameters optimaliseren...")
    beste_fast, beste_slow = optimaliseer_ma(df_raw)

    # ── Stap 4/4: Verbeterde backtest ────────────────────────
    print(f"[4/4] Verbeterde backtest draaien (MA {beste_fast}/{beste_slow})...")
    df_verb      = bereken_indicatoren(df_raw, beste_fast, beste_slow)
    verb_trades, verb_equity, filter_stats = run_verbeterde_backtest(df_verb)
    verb_stats   = bereken_statistieken(
        verb_trades, verb_equity, filter_stats,
        beste_fast, beste_slow, "VERBETERD",
    )

    # ── Vergelijkingstabel ────────────────────────────────────
    druk_vergelijkingstabel(orig_stats, verb_stats)

    # ── Trades opslaan als CSV ────────────────────────────────
    if not verb_trades.empty:
        datum_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_pad   = f'results/backtest_{datum_str}.csv'
        verb_trades.to_csv(csv_pad, index=False)
        print(f"  Trades opgeslagen: {csv_pad}\n")

    # ── Grafieken genereren ───────────────────────────────────
    print("  Grafieken genereren...")
    df_plot = bereken_indicatoren(df_raw, beste_fast, beste_slow)
    maak_grafiek(df_plot, verb_trades, verb_equity, orig_equity, beste_fast, beste_slow)


if __name__ == "__main__":
    main()
