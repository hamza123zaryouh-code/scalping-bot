# =============================================================================
# XAUUSD Trading Bot — Hoofd bestand
# Strategie: Moving Average Crossover (MA20 / MA50) op M15 tijdsframe
# =============================================================================

import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime

# --- Verbindingsinstellingen (later verplaatst naar config.py) ---
MT5_LOGIN    = 12345678      # Jouw MT5 account nummer
MT5_PASSWORD = "jouw_wachtwoord"
MT5_SERVER   = "jouw_broker_server"

# --- Handelsinstellingen ---
SYMBOL     = "XAUUSD"
TIMEFRAME  = mt5.TIMEFRAME_M15
LOT_SIZE   = 0.01
MA_SNEL    = 20              # Snelle Moving Average periode
MA_TRAAG   = 50              # Trage Moving Average periode
STOP_LOSS  = 50              # Stop loss in pips
TAKE_PROFIT = 100            # Take profit in pips


def verbind_mt5():
    """Verbindt met MetaTrader 5 platform."""
    if not mt5.initialize():
        print(f"MT5 initialisatie mislukt: {mt5.last_error()}")
        return False

    if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print(f"MT5 login mislukt: {mt5.last_error()}")
        mt5.shutdown()
        return False

    print(f"Verbonden met MT5 — Account: {MT5_LOGIN}")
    return True


def haal_data_op(symbol, timeframe, aantal_bars=100):
    """Haalt historische OHLCV data op van MT5."""
    try:
        bars = mt5.copy_rates_from_pos(symbol, timeframe, 0, aantal_bars)
        if bars is None:
            print(f"Geen data ontvangen: {mt5.last_error()}")
            return None
        df = pd.DataFrame(bars)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df
    except Exception as e:
        print(f"Fout bij ophalen data: {e}")
        return None


def bereken_ma(prijzen, periode):
    """Berekent een Simple Moving Average."""
    return prijzen.rolling(window=periode).mean()


def controleer_signaal(df):
    """
    Controleert of er een koop- of verkoopsignaal is.
    Geeft 'KOOP', 'VERKOOP' of None terug.
    """
    df['ma_snel'] = bereken_ma(df['close'], MA_SNEL)
    df['ma_traag'] = bereken_ma(df['close'], MA_TRAAG)

    # Huidige en vorige waarden
    ma_snel_nu    = df['ma_snel'].iloc[-1]
    ma_snel_vorig = df['ma_snel'].iloc[-2]
    ma_traag_nu   = df['ma_traag'].iloc[-1]
    ma_traag_vorig = df['ma_traag'].iloc[-2]

    # Gouden kruis: snelle MA kruist boven trage MA → KOOP
    if ma_snel_vorig <= ma_traag_vorig and ma_snel_nu > ma_traag_nu:
        return 'KOOP'

    # Dood kruis: snelle MA kruist onder trage MA → VERKOOP
    if ma_snel_vorig >= ma_traag_vorig and ma_snel_nu < ma_traag_nu:
        return 'VERKOOP'

    return None


def plaats_order(symbol, richting, lot_size, stop_loss_pips, take_profit_pips):
    """Plaatst een marktorder met stop loss en take profit."""
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            print(f"Kan tickdata niet ophalen voor {symbol}")
            return False

        symbol_info = mt5.symbol_info(symbol)
        pip_waarde  = symbol_info.point * 10  # 1 pip = 10 points voor XAUUSD

        if richting == 'KOOP':
            prijs      = tick.ask
            sl         = prijs - (stop_loss_pips * pip_waarde)
            tp         = prijs + (take_profit_pips * pip_waarde)
            order_type = mt5.ORDER_TYPE_BUY
        else:
            prijs      = tick.bid
            sl         = prijs + (stop_loss_pips * pip_waarde)
            tp         = prijs - (take_profit_pips * pip_waarde)
            order_type = mt5.ORDER_TYPE_SELL

        verzoek = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    lot_size,
            "type":      order_type,
            "price":     prijs,
            "sl":        sl,
            "tp":        tp,
            "deviation": 20,
            "magic":     20240101,
            "comment":   "XAUUSD Bot",
            "type_time": mt5.ORDER_TIME_GTC,
        }

        resultaat = mt5.order_send(verzoek)
        if resultaat.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Order mislukt: {resultaat.comment}")
            return False

        print(f"Order geplaatst: {richting} {lot_size} lot @ {prijs:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        return True

    except Exception as e:
        print(f"Fout bij plaatsen order: {e}")
        return False


def run_bot():
    """Hoofdlus van de trading bot."""
    print(f"XAUUSD Bot gestart — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not verbind_mt5():
        return

    try:
        while True:
            df = haal_data_op(SYMBOL, TIMEFRAME)
            if df is not None:
                signaal = controleer_signaal(df)
                if signaal:
                    print(f"Signaal gevonden: {signaal}")
                    plaats_order(SYMBOL, signaal, LOT_SIZE, STOP_LOSS, TAKE_PROFIT)
                else:
                    print(f"Geen signaal — {datetime.now().strftime('%H:%M:%S')}")

            time.sleep(60)  # Wacht 1 minuut voor volgende check

    except KeyboardInterrupt:
        print("Bot gestopt door gebruiker.")
    finally:
        mt5.shutdown()
        print("MT5 verbinding gesloten.")


if __name__ == "__main__":
    run_bot()
