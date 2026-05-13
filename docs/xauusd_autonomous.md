# Autonomous XAUUSD Ecosysteem

Deze module voegt een aparte `XAUUSD` / forex stack toe bovenop de bestaande repo.

## Lagen

- `autonomous_xauusd/data_layer.py`
  Verzorgt marktdata, MT5-executie, paper trading en fail-safe sluiting van posities.
- `autonomous_xauusd/memory_layer.py`
  Slaat trades, runtime-state en ML model snapshots op in PostgreSQL via SQLAlchemy.
- `autonomous_xauusd/brain_layer.py`
  Berekent EMA/RSI/ATR/volatiliteit, maakt signalen en traint de feedback-loop met Scikit-Learn.
- `autonomous_xauusd/communication_layer.py`
  Verzorgt Telegram push/pull commando's zoals `/status`, `/stop` en `/train`.
- `autonomous_xauusd/dashboard_layer.py`
  Toont trade geschiedenis, kapitaalcurve en ML leercurve in Streamlit/Plotly.

## Starten

1. Vul `.env` aan op basis van `.env.example`.
2. Zorg dat `POSTGRES_URL`, `SUPABASE_DB_URL` of `SUPABASE_POOLER_URL` wijst naar een bereikbare PostgreSQL of Supabase Postgres database.
3. Test eerst de connectie:

```powershell
python -m autonomous_xauusd.init_db --check-only
```

4. Maak daarna de autonomous tabellen aan via SQLAlchemy:

```powershell
python -m autonomous_xauusd.init_db
```

5. Als directe connectie nog niet lukt, probeer dan de Supabase pooler-URL uit het dashboard. Als SQLAlchemy nog steeds niet kan verbinden, kun je dezelfde tabellen alvast handmatig aanmaken via:

```text
webapp/supabase/autonomous_schema.sql
```

6. Start de engine:

```powershell
python -m autonomous_xauusd.main
```

7. Start het dashboard:

```powershell
python -m streamlit run autonomous_xauusd/dashboard_layer.py
```

## Veiligheidsdefaults

- De nieuwe stack draait standaard in `paper` mode.
- Bij te veel opeenvolgende fouten zet de engine zichzelf stop.
- API keys en MT5 credentials blijven volledig in `.env`.
- `autonomous_xauusd.main` roept automatisch `memory.initialize()` aan, dus bij een werkende `POSTGRES_URL` worden ontbrekende tabellen vanzelf aangemaakt.
