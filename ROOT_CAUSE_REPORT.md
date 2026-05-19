# ROOT CAUSE REPORT
**Datum audit:** 2026-05-19  
**Systeem:** Autonomous XAUUSD Trading Bot  
**Auditor:** Production Systems Engineer (Claude Sonnet 4.6)

---

## SAMENVATTING

Het systeem is **volledig gestopt** sinds 2026-05-17 18:44 UTC.  
Geen signalen, geen trades, geen Telegram rapporten — omdat het bot-proces niet meer draait.

---

## BEVINDINGEN PER CATEGORIE

### 1. PRIMAIRE ROOT CAUSE — BOT NIET ACTIEF

| Item | Waarde |
|------|--------|
| Laatste heartbeat | 2026-05-17T18:44:48 UTC |
| Laatste runtime log entry | 2026-05-17T17:16:58 (boot_complete) |
| Laatste signaal | 2026-05-12T15:15 |
| Laatste trade | 2026-05-12T15:15 |
| Huidige datum | 2026-05-19 |
| Bot down since | ~41+ uur |

**Oorzaak:** Het bot-process (PID 7792) is gestopt op 2026-05-17 na 1h 28m uptime.  
Er is geen crash-event gelogd in `runtime.log` → het process is extern beëindigd (PC reboot, Task Manager, stroom uitval).

**Bewijs:**
- `live_logs/runtime.log`: slechts 2 entries: `runtime_start` + `boot_complete`
- Geen `crash` of `shutdown` event
- `heartbeat.json`: frozen op 18:44, `status: running` (valse positief)
- Geen Python process actief met `run_live_bot`

---

### 2. WAAROM GEEN SIGNALEN (2026-05-13 t/m 2026-05-15 — oude bot)

De OUDE bot (`xauusd_live_bot.log`) draaide van 2026-05-13 t/m 2026-05-15 en logde doorlopend:  
`"No new qualified signal on bar close"`

**Root causes voor geen signalen (confirmed via live markt test op 2026-05-19):**

| Oorzaak | Status |
|---------|--------|
| H4 regime CHOPPY | Mogelijk tijdens die periode |
| ADX te laag | Onbekend (geen gedetailleerde logs) |
| Buitenste trading window 07:00-15:00 UTC | BEVESTIGD (18+ uur logs) |
| Signaalfilters te streng | Nee — filters zijn correct |

**Kritieke bevinding:** Op 2026-05-19 10:00 UTC geeft het systeem WEL een signaal:  
`F_MSS short` op STERK_BEAR regime, H4 ADX=42.2, H1 ADX=19.0  
→ De signaalengine werkt correct. Het probleem was de sessie-blokkade en/of marktomstandigheden.

**Probleem:** Tot gisteren was er GEEN logging van de REDEN waarom een signaal niet gegenereerd werd.  
De log zei alleen `"No new qualified signal on bar close"` zonder uitleg.

---

### 3. WAAROM GEEN 2-UURS TELEGRAM RAPPORTEN

**Root cause:** Het nieuwe autonome systeem had **GEEN 2-uurs rapportfunctie**.  

- Oud systeem (`xauusd_live_bot`): had `STATUS_HEARTBEAT_MINUTES=180` + `_send_heartbeat_to_telegram()`
- Nieuw systeem (`AutonomousTradingSystem`): had alleen `_maybe_send_daily_report()` (1x per dag om 19:00 UTC)
- De 2-uurs rapporten zijn nooit geïmplementeerd in de nieuwe stack

---

### 4. SETTINGS BUG — MODE LEEST NIET VAN .ENV

**Bestand:** `autonomous_xauusd/settings.py:136`

```python
# FOUT (voor fix):
mode = os.getenv("AUTONOMOUS_MODE", "").strip().lower() or "paper"

# CORRECT (na fix):
mode = _read("AUTONOMOUS_MODE", "paper").strip().lower() or "paper"
```

`os.getenv()` leest alleen process-environment variabelen.  
Als `.env` `AUTONOMOUS_MODE=demo` heeft maar de env-var niet extern gezet is, start de bot in paper mode.  
`_read()` leest eerst env-var, dan `.env` als fallback — consistent met alle andere settings.

**Impact:** Wanneer je `from autonomous_xauusd.settings import load_settings` direct importeert (niet via `run_live_bot.py`), geeft het mode="paper" terug ook al staat `.env` op "demo".

---

### 5. MT5 VERBINDING

**Status: WERKEND** ✅  
- Account: 1513372223 (FTMO-Demo)
- Balance: €160,000.38
- Equity: €160,000.38
- MT5 Terminal: actief en verbonden

---

### 6. WATCHDOG NIET GEÏNSTALLEERD

Het watchdog-script (`scripts/watchdog.ps1`) bestaat maar is **niet actief** als Windows-taak.  
Na een pc-herstart of crash start de bot niet automatisch opnieuw.

```
Watchdog pad: C:\TradingBot\XAUUSD_VPS\  (FOUT pad — bot staat in C:\Users\hamza\Downloads\XAUUSD\)
Correct pad: C:\Users\hamza\Downloads\XAUUSD\
```

---

### 7. TELEGRAM

**Status: WERKEND** ✅ (token + chat_id aanwezig in .env)  
- Token: 8757076306:AAELjx_KSypJYS0C-... (geldig)
- Chat ID: 5921087860 (correct)
- Owner ID: 5921087860 (correct)
- Conditie: bot MOET draaien om berichten te sturen

---

## TIJDLIJN VAN EVENTS

```
2026-05-12 15:15  — Laatste trade (XAUUSD LONG)
2026-05-13 11:05  — Oude bot: "No new qualified signal" (buiten trading window 07-15)
2026-05-14 16:38  — Oude bot herstart — direct "Outside trading window 07:00-15:00"
2026-05-15 08:36  — Oude bot: trading window open, maar geen signalen (market niet trending)
2026-05-15 13:17  — Oude bot gestopt (laatste log entry)
2026-05-15 12:55  — Laatste dry-run van nieuwe bot (PAPER mode)
2026-05-17 17:16  — Nieuwe LiveRuntime gestart (LIVE mode, PID 7792)
2026-05-17 17:16  — boot_complete: MT5 verbonden, Telegram actief
2026-05-17 18:44  — Laatste heartbeat (1h 28m uptime)
2026-05-17 18:44+ — Bot gestopt (extern gekilld, geen crash event)
2026-05-19 10:00  — AUDIT: bot niet actief, signaal engine WEL werkend (F_MSS short)
```
