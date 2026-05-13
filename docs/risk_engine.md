# Risk Engine Documentation

## Overview

The risk engine (`risk_manager.py`) implements FTMO-compliant guardrails
that prevent trades from breaching prop-firm loss limits.

## FTMO Limits

| Limit | Default | Description |
|-------|---------|-------------|
| Daily loss | $8,000 | Max loss per calendar day (5% of $160k) |
| Total loss | $16,000 | Max drawdown from starting balance (10%) |
| Safety daily buffer | $2,000 | Extra cushion before the daily limit |
| Safety total buffer | $3,000 | Extra cushion before total limit |

## Decision Flow

```
validate_ftmo_buffers(equity, day_start_equity, limits, estimated_trade_risk)
  │
  ├── daily_floor = day_start_equity - max_daily_loss
  ├── remaining_daily = equity - daily_floor
  ├── remaining_total = equity - min_allowed_equity
  │
  ├── If remaining_daily ≤ trade_risk + safety_daily_buffer → BLOCK
  ├── If remaining_total ≤ trade_risk + safety_total_buffer → BLOCK
  └── else → ALLOW
```

## Risk Levels

| Level | Condition |
|-------|-----------|
| 🟢 green | Both buffers > 30% remaining |
| 🟡 yellow | Either buffer 0–30% remaining |
| 🔴 red | Either buffer exhausted or trade blocked |

## Position Sizing

```
risk_amount = equity × risk_per_trade
raw_volume  = risk_amount / stop_distance
volume      = normalize_volume(raw_volume, min_volume, step, max_volume)
```

The normalizer rounds to the nearest valid lot step and clamps to broker limits.

## Spread Guard

Spread in points is computed as `(ask - bid) / point`. If the spread exceeds
`MAX_SPREAD_POINTS` (default 450), the trade signal is discarded.

## Trading Window Guard

Trades are only allowed Monday–Friday between `SESSION_START_HOUR` and
`SESSION_END_HOUR` (UTC). Both limits are configurable via `.env`.
