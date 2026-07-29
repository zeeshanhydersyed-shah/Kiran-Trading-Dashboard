# Research Universe — Rules, Gaps, and Known Inconsistencies

This document records how the production research universe (`stock_metadata`,
314 symbols as of 2026-07) is actually defined today, and what was found when
that definition was audited against the raw `prices` table (2,784 distinct
symbols) during the Open price acquisition project. See
[`docs/DATA_ACQUISITION_ARCHITECTURE.md`](DATA_ACQUISITION_ARCHITECTURE.md)
for why this audit was done: any future import utility must reproduce the
existing universe exactly, not re-derive it from scratch.

---

## How the universe is actually built today

`build_stock_metadata.py` builds `stock_metadata` from the `sectors` table
(symbol → sector), applying two gates:

1. **Implicit gate — must have a `sectors` entry at all.** `sectors` is only
   populated by the *live* daily scraper (`scraper.py`), never by the
   2005–2019 historical backfill scripts (`scrape_2005_2010.py`,
   `scrape_2010_2015.py`, `scrape_historical_2015_2020.py`) or the BI
   PostgreSQL merge loader (`load_bi_history.py`). A symbol with price rows
   but no `sectors` row is silently excluded — this is a side effect of
   table structure, not a documented rule anywhere.
2. **Explicit gate — sector not in `EXCLUDED_SECTORS`** (`config.py:135`,
   mirrored inline in `build_stock_metadata.py` for self-containment): 15
   categories — mutual funds, inv. banks, leasing, leather & tanneries,
   modarabas, sugar, synthetic & rayon, textile spinning, textile weaving,
   tobacco, vanaspati, woollen, **Unknown Sector**, **FUTURE CONTRACTS**,
   **STOCK INDEX FUTURE CONTRACTS**.

Additional attributes, not filters:
- `is_active` — last trade ≥ `ACTIVE_CUTOFF = "2024-01-01"` (hardcoded).
- `in_kse100` — index-membership flag from `kse100_constituents`.
- `DFC_SYMBOLS` (`config.py`) — short/DFC-market eligibility. Orthogonal to
  research-universe membership; do not confuse the two.

**A second, redundant futures filter exists** in `step1b_universe_gap.py`: a
regex on ticker suffix, `-(JAN|FEB|MAR|...)B?$`. It is not used by
production (`build_stock_metadata.py` uses the sector-based rule only) and is
demonstrably less complete — it misses 59 symbols that the sector-based rule
correctly excludes via the `FUTURE CONTRACTS` sector. Treat this script as
diagnostic-only; it should not be treated as an alternate source of truth.

---

## Full accounting: why 2,470 symbols are missing from `stock_metadata`

(`prices` has 2,784 distinct symbols; `stock_metadata` has 314.)

| Category | Count | Status |
|---|---|---|
| Matches futures regex (`step1b` script) | 1,748 | Correctly excluded |
| Has a sector, and that sector is on `EXCLUDED_SECTORS` | 408 | Correctly excluded — verified directly, not inferred |
| No `sectors` entry at all | 315 | Dormant: 219 stopped trading before 2020; zero have traded since 2026-05-01 |
| **Unexplained** | **0** | Every excluded symbol accounted for |

The 408 breaks down as: Unknown Sector 190, FUTURE CONTRACTS (sector-caught,
missed by regex) 59, TEXTILE SPINNING 51, SUGAR & ALLIED 29, INV. BANKS 27,
MODARABAS 22, TEXTILE WEAVING 6, LEATHER & TANNERIES 6, SYNTHETIC & RAYON 6,
LEASING 3, CLOSE-END MUTUAL FUND 3, TOBACCO 3, VANASPATI 2, WOOLLEN 1.

---

## Known finding: "Unknown Sector" conflates two different things

Of the 190 `Unknown Sector` symbols, 109 are still actively trading
(last price ≥ 2026-06-01). Breaking those down by ticker pattern:

- **~56 legitimate non-equity instruments**, correctly caught here: 44
  government bond/sukuk codes (`P01GIS...`, `P03FRR...` — maturity-encoded
  tickers), 9 ETFs, 3 TFC/SC bonds.
- **~53 currently-active symbols** that don't fit that pattern — plausible
  real equity, currently and silently excluded from the research universe
  with no deliberate decision behind it.

### Confirmed case: ENGRO → ENGROH

`ENGRO` (sector: FERTILIZER) traded 2005-01-03 → 2025-01-03 (4,902 days — one
of PSX's largest blue-chips). `ENGROH` begins trading 2025-01-06 and has
traded every day since (through 2026-07-02). This is almost certainly a
ticker succession from a corporate restructuring. `ENGROH` landed in
`Unknown Sector` on the source site and is therefore excluded from
`stock_metadata` — not by any rule, just because the site's own sector index
hasn't reclassified the new ticker.

`WAVESAPP` — also currently in `Unknown Sector` and excluded — is already
treated as a real tradeable symbol elsewhere in this codebase: it's in
`config.py`'s `DFC_SYMBOLS` list. That's an internal inconsistency between
two parts of the same project.

Several `GEM*`-prefixed symbols (`GEMBCEM`, `GEMMEL`, `GEMNETS`, `GEMPACRA`)
are likely GEM-board listings (a legitimate PSX growth-market segment), also
currently excluded via the same mechanism.

### Staleness of `is_active`

`build_stock_metadata.py` has been run exactly once (single git commit,
"Phase 2 complete — data integrity layer") and has never been rerun since.
Five symbols are flagged `is_active=1` despite not having traded in over a
year: `ENGRO` (superseded, see above), `HCL`, `PHDL`, `SHEL`, `SILK` — likely
the same ticker-succession pattern, not yet investigated individually.

---

## Recommendations

1. **The Open price import utility must join against the current
   `stock_metadata` table as-is** — reproduce today's universe exactly,
   including its gaps. Do not have the import utility re-derive or "fix"
   universe membership; that's a separate decision.
2. **Separately** (not blocking Open import): refresh `build_stock_metadata.py`
   to pick up `ENGROH` via a `SECTOR_OVERRIDES` entry — `config.py` already
   has precedent for exactly this (`GAL → AUTOMOBILE ASSEMBLER`) — and
   re-evaluate `is_active` for the other 4 stale symbols.
3. **Retire or clearly label** the regex-based futures filter in
   `step1b_universe_gap.py` as diagnostic-only, since it's an incomplete
   second source of truth for a rule the sector-based method already handles
   correctly.
4. **Split "Unknown Sector" conceptually** going forward: instrument-type
   exclusion (bonds/sukuk/ETFs — legitimately excluded, keep excluding) vs.
   unclassified-equity (needs a human to assign a real sector before the
   next `build_stock_metadata.py` run) — today they're the same bucket, and
   the second case silently drops real stocks with no signal that it
   happened.

---

## Status

Comparison against the newly acquired Open price dataset (per the original
request) is **deferred until `acquire_open_prices.py` completes** — the
acquisition is still mid-run (2005→2014 as of this writing) and a meaningful
universe comparison needs the full 2005→today dataset. The staging DB already
carries `symbol` per row, so that comparison will be a straightforward join
against `stock_metadata` once the run finishes.
