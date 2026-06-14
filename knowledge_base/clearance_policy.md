# MarginIQ — Perishable Clearance Policy (Synthetic)

Document ID: clearance_policy
Owner: Supply Chain & Margin Recovery
Status: Approved · Synthetic data for demonstration only

## Purpose

This policy authorizes deeper-than-normal discounts when perishable stock is at
risk of spoiling. It overrides the brand depth guidelines because preventing total
loss takes priority over reference-price protection. The perishable clearance
strategist cites this policy; the critic applies it.

## When clearance applies

Clearance is triggered when **both** conditions hold:

1. The product has a short freshness window (perishable / short shelf life).
2. On-hand stock cannot be sold through during the promo window and absorbed by
   baseline demand before the freshness window expires — i.e. there is genuine
   spoilage exposure.

## Spoilage pressure threshold

When the inventory model reports **clearance pressure above 10%** (more than 10% of
available stock at risk of spoiling), a clearance discount is justified even if it
exceeds the normal brand depth limit.

The deeper the clearance pressure, the deeper the authorized discount, up to the
configured search bound. The goal is to maximize recovered value: unsold perishable
stock is charged at (unit cost − salvage value), so clearing it at a discount is
almost always better than letting it spoil.

## Economics

- Salvage value is the residual value of spoiled/marked-down stock (often near zero
  for perishables).
- Loss per spoiled unit = unit cost − salvage value.
- A clearance discount is approved when the margin given up by discounting is less
  than the spoilage loss it prevents.

## Interaction with other gates

The probability-of-loss and non-positive-profit gates from the pricing policy still
apply. Clearance authorizes exceeding the **brand depth** limit; it does not
authorize an expected loss. The recommended clearance discount is the one that
minimizes total expected loss (spoilage + margin), not simply the deepest.

## Premium perishables

For premium perishable items (e.g. premium gelato), clearance overrides the brand
reference-price guideline only for the at-risk stock. Once spoilage exposure is
cleared, depth should return to the premium guideline for any remaining inventory.
