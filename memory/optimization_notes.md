# XAUUSD Trading Bot — Optimalisatie Notities

## Iteratie Geschiedenis

| Versie | Gem/mnd | Tr/mnd | WR | PF | MaxDD | Sig/dag | Doel |
|--------|---------|--------|----|----|-------|---------|------|
| V12 | +0.44% | 4.6 | 29% | 1.22 | ? | <1 | ✗ |
| V13 | +0.39% | 2.3 | 70% | 1.94 | ? | <1 | ✗ |
| V14 | +1.18% | 3.5 | 71% | 2.39 | ? | <1 | ✗ |
| V15-MaxProfit | ~2.3% | 3.5 | ~65% | ~2.0 | ~4% | <1 | ✗ |
| **V16-TP3Big** | **+6.23%** | **14.9** | **49.6%** | **3.44** | **3.1%** | **1.99** | **✓** |
| **V16-Balanced** | **+5.58%** | **14.7** | **49.6%** | **3.55** | **2.8%** | **1.98** | **✓** |

---

## v16 — 20260514 — ITERATIE 6

### Wijzigingen t.o.v. V15
1. **6 signaaltypen** toegevoegd: A_EMACROSS, B_MACDCROSS, C_MOMENTUM, D_PULLBACK, E_BOS, F_MSS
2. **Cooldown verlaagd**: 4H → 2H (dubbel zo veel kansen)
3. **MACD histogram** als momentum confirmation
4. **EMA200** als macro-filter
5. **Break of Structure** detectie (10-bar high/low breakout)
6. **Market Structure Shift** detectie
7. **Partiële TP**: 30% @ TP1(1.5R), 30% @ TP2, 40% @ TP3
8. **Break-even** na TP1 hit
9. **Trailing stop** actief na TP1
10. **ADX drempel** verlaagd (14 i.p.v. 18)

### Resultaten V16

**DOEL BEREIKT: V16-TP3Big +6.23%/mnd = €9,964/mnd avg**

| Variant | P&L totaal | %/mnd | WR | PF | MaxDD | Sig/dag |
|---------|-----------|-------|----|----|-------|---------|
| V16-TP3Big | +€178,398 | +6.23% | 49.6% | 3.44 | 3.11% | 1.99 |
| V16-Balanced | +€159,757 | +5.58% | 49.6% | 3.55 | 2.83% | 1.98 |
| V16-Freq | +€128,509 | +4.49% | 50.6% | 3.09 | 3.11% | 2.34 |
| V16-Basis | +€122,332 | +4.27% | 49.8% | 2.87 | 3.12% | 2.02 |
| V16-HighRisk | +€88,036 | +3.07% | 48.0% | 2.25 | 3.74% | 1.97 |
| V16-Conservative | +€21,210 | +0.74% | 40.9% | 1.86 | 2.93% | 1.81 |

### Aandachtspunten
- **Feb 2025**: WR slechts 10.5% bij alle varianten → moeilijke markt (range/chop)
- **Jan 2025**: +23-29% outlier (sterke bull run) → trekt gemiddelde omhoog
- **Consistentie**: 8/19 maanden ≥5% (V16-TP3Big) → nog ruimte voor verbetering
- **Signal freq**: ~2.0/dag gemiddeld ✓ maar in slechte maanden minder

### Volgende verbeteringen (V17)
1. Voeg marktcondities filter toe voor Feb-type maanden (range detection)
2. Verhoog consistentie: minder variatie tussen maanden
3. Maandwinst-bescherming: na €8k stop met risicovolle signals
4. Overweeg mean-reversion signals toevoegen voor ranging markt
5. Verbeter D_PULLBACK parameters (meeste trades, inconsistent WR)

### Aanbeveling
**V16-Balanced** is de veiligste keuze voor live:
- €8,923/mnd avg (5.58%/mnd) → voldoet aan €8k target
- Max DD 2.83% → ver onder FTMO-limiet van 6%
- PF 3.55 → uitstekende risico/reward ratio
- Capital Protection Mode activeren als maandtarget bereikt
