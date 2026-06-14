# MarginIQ — Pricing Risk Policy (Synthetic)

Document ID: pricing_policy
Owner: Revenue Management Office
Status: Approved · Synthetic data for demonstration only

## Purpose

This policy defines the hard financial gates that every promotion recommendation
must clear before it can be approved for execution. The critic agent applies these
gates to each candidate discount.

## Gate 1 — Probability of loss

A promotion is rejected if its modeled probability of loss exceeds the configured
risk ceiling. The default ceiling is **10% (max_probability_of_loss = 0.10)**.

- Promotions at or below 10% probability of loss: eligible.
- Promotions above 10%: rejected and returned for a shallower discount.

Rationale: a promotion is a deliberate margin investment. A more than one-in-ten
chance of an outright loss is outside the approved appetite for routine campaigns.

## Gate 2 — Margin floor

A promotion is rejected if the post-discount unit margin falls below the product's
minimum margin rate. The default floor is **22% (min_margin_pct = 0.22)** of the
discounted price, computed on the fully loaded unit cost (COGS + freight + cold
storage + spoilage reserve).

- Discounts that keep margin at or above the floor: eligible.
- Discounts that breach the floor: rejected.

## Gate 3 — Service level

A promotion is rejected if projected service level falls below the minimum. The
default minimum is **92% (min_service_level = 0.92)**.

A discount that drives demand above what inventory can serve creates stockouts,
lost trips, and customer dissatisfaction that outweigh the incremental volume.

## Gate 4 — Non-positive expected profit

Any scenario whose expected profit is zero or negative after all penalties
(stockout, spoilage, carrying cost, brand drag, cannibalization) is rejected
outright, regardless of the other gates.

## Application order

All four gates are evaluated together. A scenario must pass **all** of them to be
marked policy-compliant. The arbiter may only select a final discount from the set
of policy-compliant scenarios.
