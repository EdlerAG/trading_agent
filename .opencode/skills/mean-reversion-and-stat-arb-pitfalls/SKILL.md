---
name: mean-reversion-and-stat-arb-pitfalls
description: 'Use this skill when building, reviewing, or validating a mean-reversion, pairs-trading, or statistical arbitrage strategy specifically, in addition to the general checks in overfitting-and-robustness-checks. Also use it when a user describes a strategy trading a spread, a pairs relationship, or a reversion-to-a-reference-level signal. This skill exists because this category''s central risk, a temporary dislocation turning out to be a permanent structural break, doesn''t show up as an obvious modeling error; it shows up as a strategy that worked reliably for a long time and then failed in a way that looks, in hindsight, like it should have been foreseeable.'
---

# Mean-Reversion and Stat-Arb Pitfalls

## Why this matters

Mean-reversion and statistical arbitrage strategies bet that a specific relationship (a price relative to its own recent average, a spread between two related instruments, a basket relative to its components) will revert toward some reference level after diverging from it. Per [edge-taxonomy-and-strategy-classification](../edge-taxonomy-and-strategy-classification/SKILL.md), this category's central risk is the reference relationship itself breaking down structurally rather than temporarily, which is the "catching a falling knife" or "the spread never comes back" failure mode, and it's specifically dangerous because it doesn't look different from a normal, temporary divergence until well after the strategy has already kept adding to a losing position on the assumption that reversion is still coming.

## Do this

### Explicitly test cointegration/relationship stability for pairs or spread trades, not just historical correlation

A pairs or spread trade needs the actual relationship between the instruments to be statistically stable (cointegrated, in the formal sense, not just historically correlated) for mean reversion to be a meaningful concept at all; correlation alone doesn't establish that a spread has a genuine tendency to revert to a stable level. Run an actual cointegration test (not just a correlation coefficient) before treating a pairs relationship as mean-reverting, and re-test periodically, since a relationship that was cointegrated historically can stop being so.

### Estimate the actual half-life of reversion, and use it to inform holding-period expectations and position limits

A mean-reversion signal that implies a specific expected half-life (the time it typically takes for a divergence to revert halfway back to its reference level) gives a concrete, checkable expectation for how long a position should reasonably be held before the reversion thesis for that specific trade should be reconsidered. A position held dramatically longer than the estimated half-life without reverting is itself a signal worth acting on (reducing size, reassessing the relationship), not something to simply wait out indefinitely on the assumption that reversion is merely delayed.

### Build an explicit limit on how much a strategy will add to a losing mean-reversion position as the divergence grows

A common, costly mean-reversion failure pattern is scaling into a growing divergence (adding size as the price moves further from the reference level, on the reasoning that a bigger divergence means a bigger expected reversion), which is exactly the pattern that turns a normal temporary divergence into a catastrophic loss if the divergence turns out to be the start of a genuine structural break rather than a temporary one. Set an explicit, predetermined maximum position size and a point past which the strategy stops adding and instead treats continued divergence as evidence the mean-reversion assumption may be wrong for this specific instance, rather than as an increasingly attractive entry.

### Distinguish a temporary liquidity/order-flow-driven divergence from a fundamental relationship change, using external context, not just price action alone

Price action alone often can't distinguish "temporary order-flow-driven dislocation, will revert" from "the fundamental relationship between these instruments has actually changed" (a merger arbitrage spread that widens because the deal is now genuinely at risk, not because of a temporary liquidity imbalance). Where feasible, incorporate external context relevant to the specific relationship being traded (news, corporate actions, fundamental changes) rather than relying purely on the price/spread time series to judge whether a divergence is the normal kind the strategy is designed for.

### Treat rare, historically-unprecedented divergence magnitudes with more caution than the historical distribution alone would suggest

Consistent with [synthetic-data-and-adversarial-stress-testing](../synthetic-data-and-adversarial-stress-testing/SKILL.md), a divergence larger than anything in the strategy's validation history is exactly the situation where historical validation provides the least guidance, and it's also disproportionately likely to be the "this time it's a real structural break, not a normal reversion" case rather than simply an unusually large normal divergence. Treat historically-unprecedented divergence magnitudes as a trigger for reduced sizing or human review, not as an even-more-attractive version of the strategy's normal signal.

## Never do this

- Never treat a pairs or spread relationship as mean-reverting based on historical correlation alone without an actual cointegration or equivalent stability test, and never assume that test result is permanent without periodic re-testing.
- Never hold a mean-reversion position indefinitely past its estimated reversion half-life without treating the extended non-reversion as new evidence worth acting on.
- Never scale into a growing divergence without an explicit, predetermined maximum position size and a point past which continued divergence is treated as a warning sign rather than a better entry.
- Never rely purely on price/spread time series to judge whether a divergence is a normal temporary dislocation versus a fundamental relationship change, when external context relevant to the specific relationship is available.
- Never treat a historically-unprecedented divergence magnitude as simply a larger version of the normal signal; treat it as a specific trigger for reduced sizing or human review.

## Verification checklist

- [ ] Pairs/spread relationships are validated with an actual cointegration or equivalent stability test, not correlation alone, and re-tested periodically
- [ ] An estimated half-life of reversion informs explicit holding-period expectations, and extended non-reversion past that half-life triggers reassessment rather than indefinite waiting
- [ ] An explicit, predetermined maximum position size and stop-adding threshold exists for scaling into a growing divergence
- [ ] External context relevant to the specific relationship being traded is incorporated where feasible, rather than relying purely on price/spread time series to judge the nature of a divergence
- [ ] Historically-unprecedented divergence magnitudes trigger reduced sizing or human review, rather than being treated as a stronger version of the normal signal
