# Historical Similarity Design — PSX Quantitative Research Platform

> **Purpose:** Specification for the Historical Similarity feature — a lookup that finds past setups in `setup_log` that most closely match the current factor profile of a live signal. An optional extension of the conviction engine.  
> **Related:** [Conviction_Engine_Specification.md](Conviction_Engine_Specification.md) · [Factor_Catalog.md](Factor_Catalog.md) · [Outcome_Definitions.md](Outcome_Definitions.md)

---

## Concept

The conviction engine assigns a score based on factor weights derived from population-level studies. Historical Similarity is a complementary approach that answers a more intuitive question:

> "Show me the 10 most similar past setups and what happened to them."

This gives the trader concrete examples of historical analogues alongside the abstract score. It does not replace the score — it contextualises it.

---

## Design Principles

1. **Transparency:** Show the actual historical setups, not just a summary. The trader can look up LUCK on 2023-04-15 and see whether it followed through.
2. **Non-parametric:** No assumptions about how factors combine. Similarity is measured empirically.
3. **Honest about limitations:** A historical analogue that returned +20% is not a guarantee. Show the distribution of similar-case outcomes, not just the best ones.
4. **Phase 5+ feature:** This is a display feature, not a research feature. It depends on Phase 4 (engine construction) being complete first.

---

## Similarity Metric Design

### Approach — Weighted Euclidean Distance

For each live signal, compute the distance to every historical setup in `setup_log`:

```
distance(signal, historical) = sqrt(
  Σ_i  weight_i × (factor_i(signal) − factor_i(historical))²
)
```

Where:
- `factor_i` values are min-max normalised across all of `setup_log` (same scale for all factors)
- `weight_i` is proportional to the factor's validated predictive value (same weights as the conviction engine)
- The sum is over the factors included in the conviction engine at the current version

The N historical setups with the lowest distance scores are the "most similar."

### Handling Categorical Factors

For categorical factors (Market Regime F-37, Sector Stage F-28):
- Match required: only historical setups with the same categorical value are eligible
- Alternatively, convert to indicator variables (one-hot) and treat as binary

### Handling Missing Factors

If a live signal is missing a factor value (NULL), exclude that factor from the distance calculation and adjust the denominator accordingly.

---

## Output Specification

For each live signal, the Historical Similarity display shows:

| Field | Description |
|---|---|
| Rank | 1 = most similar |
| Symbol | Historical stock symbol |
| Setup date | Date of the historical signal |
| Setup type | BREAKOUT / PRE_BREAKOUT / etc. |
| Distance score | How similar (lower = more similar) |
| Outcome label | WINNER / LOSER |
| fwd_return_10d | Actual 10-day forward return |
| fwd_return_20d | Actual 20-day forward return |
| Key factor values | The top 3–5 factor values for comparison |

Additionally, show a summary table:

| Metric | Value |
|---|---|
| N similar setups shown | 10 (configurable) |
| % WINNER | e.g., 7/10 = 70% |
| Average 10d return | e.g., +4.2% |
| Median 10d return | e.g., +2.8% |
| Min 10d return | e.g., −6.1% |
| Max 10d return | e.g., +18.4% |

---

## Implementation Requirements

- Requires `setup_log` to be queryable at dashboard runtime (available)
- Factor values must be precomputed and normalised (requires a normalisation reference table)
- Distance computation for 205K rows is potentially slow — may require precomputed nearest-neighbour index or batch preprocessing
- This is a read-only operation: no database writes

---

## Research Validation Requirements Before Implementation

The Historical Similarity feature requires at minimum:

1. A validated factor set (output of Phase 3) with confirmed weights
2. Evidence that the similarity metric produces coherent groupings (setups near each other actually have similar outcomes)
3. A check that the feature does not show future data to the user (all historical setups must have occurred before the live signal date)

---

## Status

| Field | Value |
|---|---|
| Status | Design specification only |
| Phase | Phase 5+ |
| Dependencies | Conviction Engine V1 complete and validated |
| Estimated complexity | Medium (mainly the distance computation and display layer) |
