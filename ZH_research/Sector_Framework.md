# Sector Framework — PSX Quantitative Research Platform

> **Purpose:** Defines how sector data is structured on this platform, what sectors exist, and how sector conditions are used in research.  
> **Related:** [Factor_Catalog.md](Factor_Catalog.md) · [Market_Regime_Framework.md](Market_Regime_Framework.md) · [Factor_Taxonomy.md](Factor_Taxonomy.md)

---

## Sector Data Source

All sector data comes from the `sector_signals` table.

| Column | Description |
|---|---|
| `date` | Trading date |
| `sector` | Sector name (text label) |
| `rs_score_20` | Sector RS score vs KSE-100 (20d) |
| `rs_rank` | Sector RS rank (1 = best sector) |
| `breadth_score` | % of stocks in sector above 20d EMA |
| `adv_dec_ratio` | Advancing / Declining stock count ratio |
| `vol_ratio` | Sector volume vs sector 20d average |
| `composite_score` | Weighted combination of rs, breadth, vol |
| `sector_stage` | Weinstein stage: 1 / 2 / 3 / 4 |
| `sector_above_ema` | 1 if sector price index > EMA50 |
| `sector_ema_slope` | 5-bar change in sector EMA50 |
| `rs_inflection` | 1 if sector improving in RS rank and RS > 0 |
| `sector_rs_new_high` | 1 if sector RS at 20d high |
| `sector_pivot_dist_pct` | Distance from sector index 20d pivot high |

---

## PSX Sector List

The exact sectors defined in this platform should be confirmed from the `sector_signals` table. The approximate PSX sector list includes:

| Sector Group | Example Sub-sectors |
|---|---|
| Financials | Banking, Insurance, Leasing, Investment Banks |
| Industrials | Cement, Engineering, Chemicals, Fertiliser |
| Consumer | Consumer Goods, Textile, Food & Personal Care |
| Energy | Oil & Gas, Power Generation, Alternative Energy |
| Technology | Technology & Communication |
| Real Estate | Real Estate Investment Trusts |
| Materials | Steel, Paper, Glass |

> **Note:** The exact sector labels used in the database determine how joins are performed. Always verify actual sector names from `sector_signals` before writing study methodology.

---

## Composite Score Formula

The sector composite score aggregates three signals using a weighted average of min-max normalised values computed within each date:

```
composite_score = 0.5 × rs_norm + 0.3 × breadth_norm + 0.2 × vol_norm
```

Where each `_norm` is `(value − min) / (max − min)` across all sectors on that date.

**Implication for research:** The score is date-relative, not absolute. A `composite_score` of 0.8 means a sector was in the top 20% of sectors *on that date*, not that it achieved an 80% absolute reading.

---

## Weinstein Stage Classification (Sector)

Sector stages parallel the stock-level Weinstein methodology:

| Stage | Conditions | Trading Implication |
|---|---|---|
| Stage 1 | Basing — sector EMA50 flat, price choppy | Avoid; accumulation phase |
| Stage 2 | Advancing — sector above rising EMA50 | Favour; trend phase |
| Stage 3 | Topping — sector EMA50 flattening, price declining | Reduce; distribution phase |
| Stage 4 | Declining — sector below falling EMA50 | Avoid; decline phase |

The exact computational rules (slope thresholds, EMA period) are in the pipeline code. Confirm from source before quoting in publications.

---

## Research Usage Rules

### Rule 1 — Sector as a Moderating Variable

Sector conditions moderate the relationship between stock signals and outcomes. The same RS rank (F-03) on a stock may predict different outcomes depending on whether its sector is in Stage 2 or Stage 4.

### Rule 2 — Joining Sector to Stock Signals

To add sector conditions to a `setup_log` study:
```
join sector_signals
  on setup_log.setup_date = sector_signals.date
  and setup_log.sector = sector_signals.sector
```
The `sector` column in `setup_log` must match the `sector` label in `sector_signals` exactly.

### Rule 3 — Sector Sample Sizes

Sector-stratified studies will have lower N per cell than market-level studies. With ~15–20 PSX sectors and 205,821 rows in `setup_log`, average per-sector N is approximately 10,000–15,000. However, sector N varies greatly — financial stocks dominate; technology and real estate have far fewer entries.

### Rule 4 — Hot Sector Caution

The pre-breakout gate logic excludes setups in "hot sectors" (sector RS rank ≤ 6 at time of study). When studying pre-breakout setups, the sector condition at time of signal is already part of the selection filter. This must be accounted for in study design to avoid conditioning on the selection variable.

---

## Known Limitations

- The sector assignment of a stock is static in the database — stocks are not moved between sectors even if their business evolves. This introduces noise in sector analysis near sector reclassification events.
- Small sectors (< 5 stocks) produce unstable breadth scores (one stock = 20% breadth change). Be cautious interpreting `breadth_score` for very small sectors.
- Smart money flow factors (F-33 to F-36) may not be populated for all sectors or all dates. Check for NULLs before including in studies.

---

## Future Research

- [ ] Sector size characterisation: how many stocks per sector over the study period?
- [ ] Stage 2 sector hit rate: do setups in Stage 2 sectors outperform Stage 1/3/4 sectors?
- [ ] Sector leadership rotation: what is the average duration of a sector's Stage 2 advance?
