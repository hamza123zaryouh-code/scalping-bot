"""
XAUUSD Backtest — Moving Average Crossover
==========================================
Vereisten:  pip install yfinance pandas matplotlib

Hoe gebruiken:
  python xauusd_backtest.py

De bot downloadt automatisch historische XAUUSD data via Yahoo Finance
en simuleert alle trades. Aan het einde zie je:
  - Totaal rendement
  - Aantal trades (wins / losses)
  - Win rate
  - Max drawdown
  - Equity curve grafiek
"""

import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# ─── INSTELLINGEN ─────────────────────────────────────────────
SYMBOL          = "GC=F"          # XAUUSD ticker op Yahoo Finance
START_DATUM     = "2022-01-01"    # Startdatum backtest
EIND_DATUM      = "2024-12-31"    # Einddatum backtest
INTERVAL        = "1d"            # Tijdsframe: 1d, 1h, 15m (max 60 dagen voor 15m)

FAST_MA         = 20              # Snelle moving average
SLOW_MA         = 50              # Trage moving average

STARTKAPITAAL   = 10_000          # Startkapitaal in dollars
LOT_WAARDE      = 100             # Dollar-waarde per 1 punt beweging (0.01 lot XAUUSD ≈ $1/punt)
STOP_LOSS_USD   = 50              # Max verlies per trade in dollars
TAKE_PROFIT_USD = 100             # Max winst per trade in dollars
MAX_TRADES      = 1               # Max gelijktijdige open posities
COMMISSIE       = 3.50            # Commissie per trade in dollars (round trip)
# ──────────────────────────────────────────────────────────────


def haal_data(symbol, start, eind, interval):
    print(f"📥 Data downloaden: {symbol} ({start} → {eind}, {interval})...")
    df = yf.download(symbol, start=start, end=eind, interval=interval, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError("Geen data ontvangen. Controleer symbool en datum.")
    # Nieuwere yfinance versies geven MultiIndex kolommen terug — flatten naar strings
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    print(f"✅ {len(df)} kaarsen geladen\n")
    return df


def bereken_indicatoren(df, fast, slow):
    df = df.copy()
    df['ma_fast'] = df['close'].rolling(window=fast).mean()
    df['ma_slow'] = df['close'].rolling(window=slow).mean()
    df['signaal'] = 0
    # Crossover detectie
    df['cross_up']   = (df['ma_fast'] > df['ma_slow']) & (df['ma_fast'].shift(1) <= df['ma_slow'].shift(1))
    df['cross_down'] = (df['ma_fast'] < df['ma_slow']) & (df['ma_fast'].shift(1) >= df['ma_slow'].shift(1))
    return df.dropna()


def run_backtest(df):
    kapitaal    = STARTKAPITAAL
    equity_curve = []
    trades      = []
    open_positie = None  # {'richting': 'KOOP'/'VERKOOP', 'prijs': float, 'datum': date}

    for datum, rij in df.iterrows():
        prijs = float(rij['close'])

        # ── Sluit open positie als SL/TP geraakt ──
        if open_positie:
            verschil = prijs - open_positie['prijs']
            if open_positie['richting'] == 'VERKOOP':
                verschil = -verschil

            pnl_dollar = verschil * LOT_WAARDE

            sluit = False
            reden = ''
            if pnl_dollar <= -STOP_LOSS_USD:
                pnl_dollar = -STOP_LOSS_USD
                sluit = True; reden = 'SL'
            elif pnl_dollar >= TAKE_PROFIT_USD:
                pnl_dollar = TAKE_PROFIT_USD
                sluit = True; reden = 'TP'

            # Signaal in tegenrichting sluit ook
            if rij['cross_up'] and open_positie['richting'] == 'VERKOOP':
                sluit = True; reden = 'Omgekeerd signaal'
            if rij['cross_down'] and open_positie['richting'] == 'KOOP':
                sluit = True; reden = 'Omgekeerd signaal'

            if sluit:
                netto = pnl_dollar - COMMISSIE
                kapitaal += netto
                trades.append({
                    'open_datum':  open_positie['datum'],
                    'sluit_datum': datum,
                    'richting':    open_positie['richting'],
                    'open_prijs':  open_positie['prijs'],
                    'sluit_prijs': prijs,
                    'pnl':         round(netto, 2),
                    'reden':       reden,
                    'win':         netto > 0
                })
                open_positie = None

        # ── Open nieuwe positie op crossover ──
        if open_positie is None:
            if rij['cross_up']:
                open_positie = {'richting': 'KOOP', 'prijs': prijs, 'datum': datum}
            elif rij['cross_down']:
                open_positie = {'richting': 'VERKOOP', 'prijs': prijs, 'datum': datum}

        equity_curve.append({'datum': datum, 'kapitaal': round(kapitaal, 2)})

    return pd.DataFrame(trades), pd.DataFrame(equity_curve).set_index('datum')


def bereken_statistieken(trades_df, equity_df):
    if trades_df.empty:
        print("⚠️  Geen trades gevonden in deze periode.")
        return

    totaal      = len(trades_df)
    wins        = trades_df['win'].sum()
    losses      = totaal - wins
    win_rate    = wins / totaal * 100
    totaal_pnl  = trades_df['pnl'].sum()
    gem_win     = trades_df.loc[trades_df['win'], 'pnl'].mean() if wins > 0 else 0
    gem_loss    = trades_df.loc[~trades_df['win'], 'pnl'].mean() if losses > 0 else 0
    eind_kap    = equity_df['kapitaal'].iloc[-1]
    rendement   = (eind_kap - STARTKAPITAAL) / STARTKAPITAAL * 100

    # Max drawdown berekenen
    rolling_max = equity_df['kapitaal'].cummax()
    drawdown    = (equity_df['kapitaal'] - rolling_max) / rolling_max * 100
    max_dd      = drawdown.min()

    print("=" * 50)
    print("   BACKTEST RESULTATEN — XAUUSD MA Crossover")
    print("=" * 50)
    print(f"  Periode:         {equity_df.index[0].date()} → {equity_df.index[-1].date()}")
    print(f"  Startkapitaal:   ${STARTKAPITAAL:,.2f}")
    print(f"  Eindkapitaal:    ${eind_kap:,.2f}")
    print(f"  Totaal rendement:{rendement:+.1f}%")
    print(f"  Totaal P&L:      ${totaal_pnl:+,.2f}")
    print("-" * 50)
    print(f"  Aantal trades:   {totaal}")
    print(f"  Wins:            {wins}  ({win_rate:.1f}%)")
    print(f"  Losses:          {losses}")
    print(f"  Gemiddelde win:  ${gem_win:+.2f}")
    print(f"  Gemiddelde loss: ${gem_loss:+.2f}")
    print(f"  Max drawdown:    {max_dd:.1f}%")
    print("=" * 50)

    return {
        'totaal': totaal, 'wins': wins, 'losses': losses,
        'win_rate': win_rate, 'rendement': rendement,
        'eind_kap': eind_kap, 'max_dd': max_dd
    }


def maak_grafiek(df, trades_df, equity_df):
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), facecolor='#0D0D0D')
    fig.suptitle('XAUUSD Backtest — MA Crossover', color='#D4A843', fontsize=14, fontweight='bold', y=0.98)

    for ax in axes:
        ax.set_facecolor('#141414')
        ax.tick_params(colors='#666666', labelsize=8)
        ax.spines[:].set_color('#222222')

    # ── Grafiek 1: Prijs + MA's + signalen ──
    ax1 = axes[0]
    ax1.plot(df.index, df['close'],   color='#D4A843', linewidth=1,   label='XAUUSD', alpha=0.9)
    ax1.plot(df.index, df['ma_fast'], color='#378ADD', linewidth=1.5, label=f'MA {FAST_MA}', alpha=0.8)
    ax1.plot(df.index, df['ma_slow'], color='#D85A30', linewidth=1.5, label=f'MA {SLOW_MA}', alpha=0.8)

    if not trades_df.empty:
        for _, t in trades_df.iterrows():
            kleur = '#1D9E75' if t['richting'] == 'KOOP' else '#D85A30'
            marker = '^' if t['richting'] == 'KOOP' else 'v'
            ax1.scatter(t['open_datum'], t['open_prijs'], color=kleur, marker=marker, s=60, zorder=5)

    ax1.set_ylabel('Prijs (USD)', color='#888888', fontsize=9)
    ax1.legend(fontsize=8, facecolor='#1A1A1A', edgecolor='#333333',
               labelcolor='white', loc='upper left')
    ax1.grid(color='#1E1E1E', linewidth=0.5)

    # ── Grafiek 2: P&L per trade ──
    ax2 = axes[1]
    if not trades_df.empty:
        kleuren = ['#1D9E75' if p > 0 else '#D85A30' for p in trades_df['pnl']]
        ax2.bar(range(len(trades_df)), trades_df['pnl'], color=kleuren, alpha=0.8, width=0.7)
        ax2.axhline(0, color='#444444', linewidth=0.8, linestyle='--')
    ax2.set_ylabel('P&L per trade ($)', color='#888888', fontsize=9)
    ax2.set_xlabel('Trade #', color='#888888', fontsize=9)
    ax2.grid(color='#1E1E1E', linewidth=0.5, axis='y')

    # ── Grafiek 3: Equity curve ──
    ax3 = axes[2]
    ax3.plot(equity_df.index, equity_df['kapitaal'], color='#D4A843', linewidth=1.5)
    ax3.axhline(STARTKAPITAAL, color='#444444', linewidth=0.8, linestyle='--', label='Startkapitaal')
    ax3.fill_between(equity_df.index, STARTKAPITAAL, equity_df['kapitaal'],
                     where=equity_df['kapitaal'] >= STARTKAPITAAL,
                     color='#1D9E75', alpha=0.15)
    ax3.fill_between(equity_df.index, STARTKAPITAAL, equity_df['kapitaal'],
                     where=equity_df['kapitaal'] < STARTKAPITAAL,
                     color='#D85A30', alpha=0.15)
    ax3.set_ylabel('Kapitaal ($)', color='#888888', fontsize=9)
    ax3.legend(fontsize=8, facecolor='#1A1A1A', edgecolor='#333333', labelcolor='white')
    ax3.grid(color='#1E1E1E', linewidth=0.5)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=30, ha='right')

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    bestand = 'xauusd_backtest_resultaat.png'
    plt.savefig(bestand, dpi=150, bbox_inches='tight', facecolor='#0D0D0D')
    print(f"\n📊 Grafiek opgeslagen als: {bestand}")
    plt.show()


def main():
    df = haal_data(SYMBOL, START_DATUM, EIND_DATUM, INTERVAL)
    df = bereken_indicatoren(df, FAST_MA, SLOW_MA)
    trades_df, equity_df = run_backtest(df)
    bereken_statistieken(trades_df, equity_df)
    maak_grafiek(df, trades_df, equity_df)

    # Sla trades op als CSV
    if not trades_df.empty:
        trades_df.to_csv('xauusd_trades.csv', index=False)
        print(f"📄 Alle trades opgeslagen in: xauusd_trades.csv")


if __name__ == "__main__":
    main()