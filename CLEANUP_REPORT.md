# Cleanup Report — XAUUSD Trading Platform
**Datum:** 2026-05-14  
**Uitgevoerd door:** Claude Code (senior cleanup engineer)

---

## Samenvatting

| Categorie | Actie | Ruimte bespaard |
|-----------|-------|-----------------|
| Cache artifacts | 16× `__pycache__` + `.pytest_cache` + `.ruff_cache` | ~373 KB |
| Test artifacts | `coverage.xml` + `.coverage` | ~371 KB |
| Build output | `webapp/.next` | ~205 KB |
| Dev-logs | `.codex-logs/` | ~0 KB |
| Dead code | `telegram_alerts.py` | ~0.5 KB |
| **Totaal verwijderd** | | **~950 KB** |

---

## 1. Verwijderde Bestanden & Mappen

### Cache Directories (automatisch regenereerbaar)
| Pad | Reden |
|-----|-------|
| `__pycache__/` (16×) | Python bytecode cache — regenereert bij import |
| `.pytest_cache/` | Pytest cache — regenereert bij `pytest` |
| `.ruff_cache/` | Ruff linter cache — regenereert bij `ruff` |
| `.codex-logs/` | CI/CD framework logs — niet nodig in repo |

### Test Artifacts
| Bestand | Reden |
|---------|-------|
| `coverage.xml` (303 KB) | Gegenereerd door pytest-cov — run `pytest` om te regenereren |
| `.coverage` (68 KB) | Coverage database — idem |

### Build Output
| Bestand | Reden |
|---------|-------|
| `webapp/.next/` | Next.js build output — regenereert met `npm run build` |

### Dead Code
| Bestand | Reden |
|---------|-------|
| `telegram_alerts.py` | Importeert `ftmo_report_pipeline` dat nergens bestaat. Nergens geïmporteerd in het project. Volledig dode module. |

---

## 2. Code Fixes

### `backend/main.py`
- **Probleem:** `import json` stond dubbel — eenmaal globaal (`from json import JSONDecodeError`) én nogmaals inline in `_parse_client_message()`
- **Fix:** Inline `import json` verwijderd, `import json` toegevoegd aan top-level imports

### `backend/api/routes/dashboard.py`
- **Probleem:** `import pandas as pd` en `import numpy as np` stonden als lazy imports binnenin 3 functies (`equity_curve`, `monthly_pnl`, `drawdown_curve`)
- **Fix:** Naar top-level imports verplaatst — betere performance (module wordt eenmalig geladen), betere leesbaarheid, consistent met Python-standaarden

### `pyproject.toml`
Zie sectie 3.

---

## 3. Dependency Cleanup (`pyproject.toml`)

### Verwijderde dependencies
| Package | Reden |
|---------|-------|
| `reportlab>=4.2` | Nergens geïmporteerd in de codebase — nooit in gebruik genomen |
| `fpdf2>=2.7` | Nergens geïmporteerd in de codebase — nooit in gebruik genomen |

### Verwijderde script entry points
| Entry | Reden |
|-------|-------|
| `xauusd-dash = "frontend.app:run"` | `frontend/` map was al verwijderd uit git — broken script |

### Verwijderd uit `packages.find`
| Entry | Reden |
|-------|-------|
| `"frontend*"` | `frontend/` map bestaat niet meer |

---

## 4. .gitignore Verbeteringen

- Dubbele `__pycache__/` en `*.pyc` entries geconsolideerd
- Aparte sectie voor coverage & build artifacts toegevoegd
- `coverage.xml`, `.coverage`, `htmlcov/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` expliciet gedocumenteerd

---

## 5. Wat NIET verwijderd is (en waarom)

| Item | Grootte | Reden bewaard |
|------|---------|---------------|
| `strategy_v7.py` t/m `strategy_v16.py` | ~200 KB | Versiegeschiedenis van strategie-evolutie — referentiemateriaal |
| `strategy_backtest.py` | ~30 KB | Legacy v6 backtest — standalone script, niet geïmporteerd maar historisch |
| `exports/` | 93.77 MB | Backtest-archieven — waardevolle historische data |
| `results/` | 7.79 MB | Optimizer resultaten — actief gebruikt |
| `logs/` | 1.29 MB | Runtime logs — nuttig voor debugging |
| `webapp/node_modules/` | 554 MB | npm dependencies — vereist voor webapp |

---

## 6. Risico's Gevonden

### LAAG RISICO
- `ccxt` is optioneel geïmporteerd in `autonomous_xauusd/data_layer.py` met fallback naar `None` — safe
- `streamlit` wordt gebruikt in `autonomous_xauusd/dashboard_layer.py` — dependency correct bewaard

### GEEN BEVEILIGINGSRISICO's
- `.env` staat correct in `.gitignore` — niet gecommit
- Geen hardcoded credentials gevonden in tracked bestanden
- Path traversal beveiliging aanwezig in `reports.py` (line 54)
- CORS is configureerbaar via settings (niet wildcard hardcoded)

---

## 7. Aanbevelingen voor V17 Development

1. **`strategy_backtest.py`** — Overweeg te verwijderen of te verplaatsen naar `archive/` als het definitief vervangen is door de versioned scripts
2. **`exports/` cleanup** — De 2 backtest runs van 2026-05-11 zijn samen ~94 MB. Overweeg archiveren naar externe opslag na V17
3. **`streamlit` dependency** — Indien `autonomous_xauusd/dashboard_layer.py` ook gemigreerd wordt naar de Next.js webapp, kan streamlit uit de dependencies
4. **`fpdf2`/`reportlab`** waren verwijderd — als PDF-export nodig is voor V17, voeg ze dan terug toe wanneer het daadwerkelijk geïmplementeerd wordt
