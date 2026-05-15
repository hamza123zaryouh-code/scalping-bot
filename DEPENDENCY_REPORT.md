# Dependency Report — XAUUSD Trading Platform
**Datum:** 2026-05-14

---

## Python Dependencies (pyproject.toml)

### Actieve Dependencies

| Package | Versie | Gebruikt in | Prioriteit |
|---------|--------|-------------|-----------|
| pandas | ≥2.0 | Overal — data analyse | Kritisch |
| numpy | ≥1.26 | Indicatoren, backtests | Kritisch |
| scipy | ≥1.12 | Statistische analyse | Hoog |
| scikit-learn | ≥1.4 | brain_layer.py (ML) | Hoog |
| SQLAlchemy | ≥2.0 | memory_layer.py (ORM) | Kritisch |
| psycopg[binary] | ≥3.2 | PostgreSQL driver | Kritisch |
| yfinance | ≥0.2.36 | data_layer.py (backtest data) | Hoog |
| ccxt | ≥4.3 | data_layer.py (optioneel, fallback) | Laag |
| MetaTrader5 | ≥5.0 | data_layer.py (Windows live trading) | Kritisch (live) |
| matplotlib | ≥3.8 | Backtest charts genereren | Hoog |
| plotly | ≥5.20 | Interactieve charts | Gemiddeld |
| fastapi | ≥0.111 | backend/main.py | Kritisch |
| uvicorn[standard] | ≥0.29 | ASGI server | Kritisch |
| pydantic | ≥2.7 | Models, schemas | Kritisch |
| pydantic-settings | ≥2.3 | Config management | Kritisch |
| python-jose[cryptography] | ≥3.3 | JWT auth | Kritisch |
| passlib[bcrypt] | ≥1.7 | Password hashing | Kritisch |
| python-multipart | ≥0.0.9 | Form data (FastAPI) | Gemiddeld |
| httpx | ≥0.27 | Async HTTP client | Gemiddeld |
| anyio | ≥4.3 | Async runtime | Hoog |
| python-dotenv | ≥1.0 | .env loading | Hoog |
| pyyaml | ≥6.0 | YAML configs | Hoog |
| streamlit | ≥1.35 | autonomous_xauusd/dashboard_layer.py | Gemiddeld |
| streamlit-extras | ≥0.4 | dashboard_layer.py | Laag |
| Pillow | ≥10.3 | Image processing | Gemiddeld |
| requests | ≥2.32 | HTTP calls | Hoog |
| python-telegram-bot | ≥21.6 | communication_layer.py (Telegram bot) | Hoog |
| structlog | ≥24.1 | Gestructureerd loggen | Hoog |
| psutil | ≥5.9 | monitoring/watchdog.py | Gemiddeld |

### Dev Dependencies

| Package | Versie | Doel |
|---------|--------|------|
| pytest | ≥8.2 | Test runner |
| pytest-asyncio | ≥0.23 | Async test support |
| pytest-cov | ≥5.0 | Coverage reporting |
| pytest-mock | ≥3.14 | Mocking |
| httpx | ≥0.27 | FastAPI test client |
| ruff | ≥0.4 | Linter + formatter |
| mypy | ≥1.10 | Static type checking |
| types-requests | ≥2.32 | Type stubs |
| types-PyYAML | ≥6.0 | Type stubs |

---

## Verwijderde Dependencies (deze cleanup)

| Package | Reden |
|---------|-------|
| `reportlab>=4.2` | Nooit geïmporteerd — PDF generatie nooit geïmplementeerd |
| `fpdf2>=2.7` | Nooit geïmporteerd — duplicate PDF library, ook niet geïmplementeerd |

---

## Frontend Dependencies (webapp/package.json)

### Production

| Package | Versie | Doel |
|---------|--------|------|
| next | ^15.0.0 | React framework (App Router) |
| react | 19.2.4 | UI library |
| react-dom | 19.2.4 | DOM rendering |
| recharts | ^3.2.1 | Chart components |

### Dev

| Package | Versie | Doel |
|---------|--------|------|
| @tailwindcss/postcss | ^4 | Tailwind CSS integration |
| @types/node | ^20 | Node.js type definitions |
| @types/react | ^19 | React type definitions |
| @types/react-dom | ^19 | React DOM type definitions |
| eslint | ^9 | JavaScript linter |
| eslint-config-next | ^15.0.0 | Next.js ESLint config |
| tailwindcss | ^4 | Utility-first CSS |
| typescript | ^5 | TypeScript compiler |

**Status:** Alle frontend dependencies zijn up-to-date (React 19, Next.js 15, Tailwind 4).  
**Geen ongebruikte frontend dependencies gevonden.**

---

## Aanbevelingen

### Te overwegen voor V17

1. **`ccxt`** — Optioneel geïmporteerd, maar de gebruiker gebruikt primair XAUUSD/forex (geen crypto). Kan verwijderd worden als `data_layer.py` de ccxt-fallback niet nodig heeft.

2. **`streamlit` + `streamlit-extras`** — Alleen gebruikt in `autonomous_xauusd/dashboard_layer.py`. Als deze functionaliteit gemigreerd wordt naar de Next.js webapp, kunnen deze 2 packages verwijderd worden (~20 MB installatie).

3. **`plotly`** — Geïnstalleerd maar controleer actief gebruik vs matplotlib. Beide zware charting libraries — één kan voldoende zijn voor de backtest output.

4. **`scipy`** — Controleer of dit actief gebruikt wordt in V17's ML-laag of alleen als transitive dependency van scikit-learn.

---

## Beveiligingsstatus

- Geen bekende critical CVEs in de opgegeven versieranges (stand 2026-05-14)
- `python-jose` heeft een ouder bekende timing attack issue — optioneel upgraden naar `authlib` voor productie
- `passlib` is in maintenance mode, maar bcrypt backend is veilig
- Alle versies gebruiken `>=` floor pins — run periodiek `pip list --outdated`
