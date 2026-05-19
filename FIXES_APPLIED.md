# FIXES APPLIED
**Datum:** 2026-05-19  
**Versie:** Post-audit patch

---

## FIX 1 — Settings mode leest nu van .env [KRITIEK]

**Bestand:** `autonomous_xauusd/settings.py:136`

**Voor:**
```python
mode = os.getenv("AUTONOMOUS_MODE", "").strip().lower() or "paper"
```

**Na:**
```python
mode = _read("AUTONOMOUS_MODE", "paper").strip().lower() or "paper"
```

**Impact:** Mode (`paper`/`demo`/`live`) wordt nu consistent gelezen uit `.env` als het niet
als process-environment variabele is ingesteld. Voorheen startte de bot in `paper` mode als je 
`autonomous_xauusd.settings` direct importeerde zonder `load_dotenv()` te callen.

---

## FIX 2 — 2-uurs Telegram rapporten toegevoegd [KRITIEK]

**Bestand:** `autonomous_xauusd/main.py`

**Nieuwe methoden:**
- `_maybe_send_2h_report()` — controleert interval, stuurt rapport, logt status
- `_build_2h_report()` — bouwt gedetailleerd statusrapport

**Inhoud van elk 2-uurs rapport:**
```
📊 2-UURS RAPPORT — 19 May 10:00 UTC
━━━━━━━━━━━━━━━━━━━━━━━━
Status: 🟢 actief
Modus: DEMO | XAUUSD

ACCOUNT
  Equity:  €160,000.38
  Balance: €160,000.38
  Open:    0 positie(s)

VANDAAG (19 May)
  Trades: 0  (✅0W / ❌0L)
  PnL:    €0.00
  FTMO ruimte: €6,000 resterend

SIGNALEN
  Laatste signaal: 2026-05-12T15:15:00
  Sessie: LONDON — VALID
  Sentiment: neutral (+0.00)
  Nieuws lock: nee

SYSTEEM
  Circuit breaker: 🟢 OK
  FTMO bescherming: ✅ OK
  Signals enabled: ja
  Laatste bar: 2026-05-19T09:00:00
━━━━━━━━━━━━━━━━━━━━━━━━
```

**Logging toegevoegd:**
```
[REPORT_JOB_STARTED] 2-uurs Telegram rapport genereren
[REPORT_GENERATED] 2-uurs rapport gegenereerd (N chars)
[REPORT_SENT_SUCCESS] 2-uurs rapport verstuurd naar Telegram
[REPORT_SEND_FAILED] Telegram kon rapport niet versturen
[NEXT_REPORT_TIME] Volgend rapport om HH:MM UTC
```

---

## FIX 3 — WAIT: Signal rejection logging [HOOG]

**Bestand:** `autonomous_xauusd/main.py`

Elke reden waarom GEEN trade geopend wordt, wordt nu gelogd:

```
[WAIT: session_blocked]         — buiten trading sessie
[WAIT: circuit_breaker]         — circuit breaker actief
[WAIT: ftmo_blocked]            — FTMO bescherming actief
[WAIT: news_lock]               — nieuws lock actief
[WAIT: max_concurrent_positions] — max posities bereikt
[WAIT: position_open]           — positie al open voor dit paar
[WAIT: signals_disabled]        — signalen uitgeschakeld
[WAIT: no_signal]               — strategie geeft geen signaal + REDEN
[WAIT: circuit_breaker_signal]  — signaaltype geblokkeerd
[WAIT: pattern_memory_blocked]  — verlieshistorie blokkeert signaaltype
[WAIT: risk_gate]               — pre-trade risk gate gefailed
[WAIT: insufficient_bars]       — te weinig bars voor indicatoren
```

**Voorbeeld log output:**
```
[WAIT: no_signal] XAUUSD — H4 regime = CHOPPY (geen directional bias)
[WAIT: no_signal] XAUUSD — H4 ADX 8.3 < min 10.0
[WAIT: risk_gate] cooldown actief: 32/60 min — buy F_MSS XAUUSD
[WAIT: session_blocked] Aziatische sessie — laag volume, geen trading
```

**Voordeel:** Je weet altijd WAAROM er geen trades zijn. Nooit meer "geen trades" zonder uitleg.

---

## FIX 4 — Control flow refactor in _run_symbol_cycle [MEDIUM]

**Bestand:** `autonomous_xauusd/main.py`

De `signals_enabled` check is verplaatst naar vóór `generate_signal()` call (was inconsistent).  
Nu wordt een duidelijke log geschreven als signalen uitgeschakeld zijn.

---

## NIET GEFIXED — Watchdog configuratie (handmatige actie vereist)

Het watchdog-script (`scripts/watchdog.ps1`) moet geïnstalleerd worden als Windows-taak.  
Het huidige script heeft een verkeerd pad (`C:\TradingBot\XAUUSD_VPS\`).

**Actie:** Pas het pad aan in `scripts/watchdog.ps1`:
```powershell
$BotDir = "C:\Users\hamza\Downloads\XAUUSD"
```

Dan installeren:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_watchdog.ps1
```

---

## HOE DE BOT NU STARTEN

```bat
scripts\run_bot_demo.bat
```

Of direct:
```powershell
cd C:\Users\hamza\Downloads\XAUUSD
python scripts/run_live_bot.py --mode demo --log-level INFO
```

**Vereisten:**
- MT5 Terminal moet draaien met FTMO-Demo ingelogd
- `.env` moet aanwezig zijn (aanwezig ✅)
- Python environment met dependencies (controleer via `pip list`)
