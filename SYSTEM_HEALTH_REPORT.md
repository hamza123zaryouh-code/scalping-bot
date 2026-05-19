# SYSTEM HEALTH REPORT
**Datum:** 2026-05-19  
**Audit type:** Full production system audit

---

## OVERALL STATUS: 🔴 KRITIEK — BOT NIET ACTIEF

Het systeem is operationeel qua infrastructuur maar het bot-process draait niet.

---

## COMPONENT STATUS

| Component | Status | Detail |
|-----------|--------|--------|
| MT5 Terminal | ✅ OK | Account 1513372223, Balance €160,000.38 |
| MT5 Verbinding | ✅ OK | FTMO-Demo verbonden |
| Telegram Bot | ✅ OK | Token geldig, chat_id correct |
| Strategy Engine | ✅ OK | F_MSS short signaal op live markt (09:00 UTC) |
| Signal Engine | ✅ OK | H4=STERK_BEAR, ADX=42.2, signaal aanwezig |
| Database | ✅ OK | SQLite lokaal (Supabase portgeblokkeerd) |
| .env configuratie | ✅ OK | Alle vereiste variabelen aanwezig |
| Session Engine | ✅ OK | Trading window 07:00-17:00 UTC |
| Bot Process | 🔴 DOWN | Gestopt op 2026-05-17 18:44 UTC |
| Watchdog | 🔴 DOWN | Niet geïnstalleerd als Windows-taak |
| 2-uurs rapporten | 🔴 MISSING | Nu geïmplementeerd (na fix) |
| Signal logging | 🟡 VERBETERD | WAIT: logging toegevoegd (na fix) |

---

## MARKT STATE OP AUDIT MOMENT (2026-05-19 10:00 UTC)

```
Symbool:     XAUUSD
Prijs:       $4,547.92
H4 regime:   STERK_BEAR
H1 ADX:      19.0  (min: 7 → OK)
H4 ADX:      42.2  (min: 10 → STERK OK)
H4 slope:    -12.39 (negatief = bearish OK)
RSI H1:      47.1  (neutraal-bearish)
MACD hist:   -0.873 (negatief = bearish)
D1 trend:    bear
EMA xup:     False
EMA xdn:     False
BOS:         False/False

SIGNAAL:     F_MSS SHORT ✅
```

**Conclusie:** Als de bot nu draaide, zou hij een F_MSS short signaal verwerken.

---

## ACCOUNT STATUS

| Item | Waarde |
|------|--------|
| Account | 1513372223 (FTMO-Demo) |
| Balance | €160,000.38 |
| Equity | €160,000.38 |
| Open posities | 0 |
| Dagverlies | €0.00 |
| FTMO dagruimte | €6,000.00 |
| FTMO totaal ruimte | €16,000.00 |
| Laatste trade | 2026-05-12 (7 dagen geleden) |

---

## SCHEDULER STATUS

| Scheduler | Status | Detail |
|-----------|--------|--------|
| Main trading loop | 🔴 DOWN | Bot niet actief |
| 2-uurs rapport | 🔴 DOWN (was MISSING) | Nu geïmplementeerd — bot starten vereist |
| Dagrapport (19:00 UTC) | 🔴 DOWN | Bot niet actief |
| ML training | 🔴 DOWN | Bot niet actief |
| Health monitor | 🔴 DOWN | Bot niet actief |
| Heartbeat writer | 🔴 DOWN | Bot niet actief |
| Watchdog | 🔴 NOT INSTALLED | Handmatige actie vereist |

---

## LOG ANALYSE

### bot_stdout.log
- Meeste entries zijn DRY-RUN runs (2026-05-15) die direct exiten
- Laatste echte run: geen entry (LiveRuntime logt naar runtime.log)

### runtime.log  
- 2 entries: `runtime_start` (17:16) + `boot_complete` (17:16) op 2026-05-17
- Geen `crash` of `shutdown` event → extern beëindigd

### xauusd_live_bot.log
- Oudere bot gestopt op 2026-05-15 13:16
- 100+ "No new qualified signal" entries (trading window + markt choppy)
- 2x "2-uurs rapport" verzonden (08:36 en 11:54 op 2026-05-15)

### heartbeat.json
- `status: running` (STALE — bot is down)
- `last_cycle_at: 2026-05-17T18:44:48`
- `mt5_connected: true` (was true bij afsluiten)
- `uptime_seconds: 5288` (1h 28m)

### api.log
- MT5 IPC timeout errors op 2026-05-18 13:27 (API service ook gestopt)

---

## RISICO ANALYSE

| Risico | Ernst | Mitigatie |
|--------|-------|-----------|
| Bot niet actief, mist F_MSS short | HOOG | Direct starten |
| Watchdog niet geïnstalleerd | HOOG | Installeer Windows Task |
| PC reboot = bot herstart niet | HOOG | Watchdog + auto-start |
| Geen 2-uurs status | MEDIUM | ✅ Gefixed |
| Silent signal rejection | MEDIUM | ✅ Gefixed |
| FTMO ruimte volledig beschikbaar | LAAG | Geen actie nodig |

---

## AANBEVELINGEN

### Direct uitvoeren (nu)
1. **Start de bot:** `python scripts/run_live_bot.py --mode demo`
2. **Verifieer:** Telegram moet binnen 2 uur een rapport sturen

### Korte termijn (deze week)
3. **Pas watchdog pad aan** in `scripts/watchdog.ps1` (`$BotDir`)
4. **Installeer watchdog** als Windows-taak via `install_watchdog.ps1`
5. **Overweeg VPS** voor 24/7 uptime zonder afhankelijkheid van lokale PC

### Middellange termijn
6. **Supabase verbinding** via VPN of VPS (poort 5432 geblokkeerd op residential ISP)
7. **Monitoring dashboard** altijd open houden voor visueel toezicht

---

## GEZONDHEIDSCHECK COMMANDO'S

Na het starten van de bot, controleer:

```powershell
# Heartbeat status
Get-Content live_logs\heartbeat.json

# Runtime log (nieuwe entries)
Get-Content live_logs\runtime.log

# Bot output
Get-Content live_logs\bot_stdout.log -Tail 20

# WAIT: logging check
Select-String "\[WAIT:" live_logs\bot_stdout.log | Select -Last 20
```
