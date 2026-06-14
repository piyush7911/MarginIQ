# MarginIQ — Results & Accuracy Report

This report documents how MarginIQ performs on a controlled evaluation where the
**correct answer is known in advance**. Every result below was produced by the full
production pipeline running live on **Azure AI Foundry (gpt-4o)** with policy grounding
from **Foundry IQ** — no mocks, no shortcuts.

> Reproduce: `python tests/scenario_accuracy.py` → writes [results/scenario_results.json](results/scenario_results.json).

---

## 1. Headline

| | |
|---|---|
| Scenarios evaluated | **6** |
| Matched expectation | **6 / 6** |
| Policy grounding | **Foundry IQ on every scenario** |
| Estimator (elasticity) recovery | true 1.85 recovered within confidence interval |
| Pipeline | Azure AI Foundry gpt-4o + Foundry IQ, end to end |

MarginIQ recommended the directionally correct discount in **all six** situations, and
in each case the recommendation was checked against policy retrieved and cited from the
Foundry IQ knowledge base.

---

## 2. Why this is a real accuracy test

Most "demos" can't prove correctness because no one knows the right answer. We solve
this by **authoring the ground truth**: each scenario is a deterministic transform of
one seed product into a situation where economic theory dictates the correct *direction*
of the decision. If MarginIQ reasons well, it must land on that direction for the right
reason — not by luck.

- **The seed** is a premium gelato with full data feeds (sales history, inventory, cost
  structure, competitor prices, calendar, weather, brand signals).
- **Each scenario** changes exactly the variables needed to force a known outcome
  (e.g. multiply stock 5× to force a clearance decision), leaving everything else fixed.
- **The check** is an objective, pre-registered predicate per scenario (e.g. "recommended
  discount ≥ 25% **and** spoilage pressure detected"), not a subjective read.

This isolates cause and effect: a pass means the system responded to the *right signal*.

---

## 3. Results at a glance

| # | Scenario | What we changed | Expected direction | MarginIQ result | Conf. | Verdict |
|---|---|---|---|---|---|---|
| S1 | Baseline | nothing (product as shipped) | shallow 5–15% | **5%**, 0% downside | 73% | ✅ |
| S2 | Clearance overstock | 5× stock, near-zero salvage, short shelf life | deep ≥ 25% to clear | **30%**, spoilage pressure 0.38 | 49% | ✅ |
| S3 | Severe shortage | 40 units/store vs heatwave demand | shallow ≤ 10%, inventory risk HIGH | **0%**, inventory risk **high** | 19% | ✅ |
| S4 | Competitor price war | all rivals −42% on promo | competitor heat HIGH (≥0.7) | heat **0.85**, holds disciplined 5% | 73% | ✅ |
| S5 | Cold off-season | ~50°F, no holiday lift | off-season detected | **10%**, weather/timing low | 75% | ✅ |
| S6 | Margin floor binding | unit cost → $5.40 vs 22% floor | shallow ≤ 10%, margin protected | **0%**, deeper cuts breach floor | 55% | ✅ |

Every row was grounded by Foundry IQ. Detailed per-run metrics (profit, downside, CVaR,
confidence, decision factors, recommendation text) are in
[results/scenario_results.json](results/scenario_results.json).

### Confidence is calibrated, not cosmetic

The **Conf.** column is a real signal, not a constant. It is derived from how the
recommended decision actually performs — the separation of the winning scenario from the
field, the chosen scenario's probability of loss, whether expected profit is positive,
and whether the critic cleared it on the first pass. It moves sensibly with the
situation: a clean, low-risk call lands high (**S1/S4/S5 ≈ 73–75%**), a genuinely risky
deep clearance is lower (**S2 = 49%**), and a forced-loss shortage where every option
loses money is honestly low (**S3 = 19%**). A flat confidence across opposite situations
would be a red flag; this varies because it measures the decision, not the agents.

---

## 4. Scenario deep-dives

### S1 — Baseline (heatwave, premium, tight stock)
The product as shipped. Demand is responsive but cold-chain stock is limited, so the
optimizer settles on a **shallow 5%** with zero modelled downside. This is the control:
it proves the system does **not** over-discount a healthy, well-stocked promotion.

### S2 — Clearance overstock → the system flips deep on purpose
With 5× stock, near-zero salvage, and a short freshness window, the time-bounded
**spoilage model** turns shallow discounts into losses: unsold perishable stock is
charged at (cost − salvage). MarginIQ recommends **30%** — the depth that clears stock
before it spoils — and the inventory agent reports **spoilage pressure 0.38** (38% of
stock at risk). This is the hardest scenario and the clearest proof the economics drive
the call: the profit curve *inverts* versus S1, and the system inverts with it.

### S3 — Severe shortage → refuse to discount
Only 40 units per store against strong heatwave demand. Discounting scarce stock just
gives away margin on units that would sell anyway. MarginIQ recommends **0%** and flags
**inventory risk: high** — correctly treating supply, not price, as the binding constraint.

### S4 — Competitor price war → detect, don't capitulate
Every competitor cuts to $3.99 (−42%). The competitor agent registers market **heat 0.85**
(well above the 0.7 bar), so the system *sees* the pressure — but on a premium brand with
healthy margins it holds a disciplined **5%** rather than racing to the bottom. Detection
and judgment are both correct.

### S5 — Cold off-season → read the weather and the calendar
At ~50°F with no holiday lift, the weather and timing signals collapse. The system
recognizes the off-season and keeps the discount modest (**10%**), rather than assuming
summer-level demand response.

### S6 — Margin floor binding → protect the floor
With unit cost raised to $5.40 against a 22% margin floor, deeper discounts breach the
floor. MarginIQ recommends **0%**, and the critic — grounded in the pricing policy
retrieved from Foundry IQ — confirms the margin gate. No recommendation is allowed to
violate policy.

---

## 5. What the results demonstrate

**The three-layer separation works.** The deterministic math core produces the number,
the LLM layer applies judgment, and across six very different regimes the two agree on
the correct direction every time. S2 (clear deep) and S3 (refuse to discount) are
near-opposite responses produced by the *same* system — evidence it reasons from the
situation, not from a fixed bias.

**Grounding is real and auditable.** Every scenario's policy check was answered by
Foundry IQ retrieving and citing the relevant policy document. The decision is never a
black box: each ships with `decision_factors` tied to the chosen scenario's economics.

**Safety holds under pressure.** In the two scenarios designed to tempt a bad call —
the price war (S4) and the margin-floor squeeze (S6) — the system detected the pressure
yet stayed policy-compliant.

**The estimator is calibrated, not just plausible.** On a synthetic dataset with a known
true elasticity of 1.85, the controlled regression recovers the truth within its
confidence interval while the naive estimate is measurably biased — so the demand curve
underpinning every recommendation is grounded in a verified estimator
(`pytest tests/test_elasticity_recovery.py`).

---

## 6. Reproducibility

```bash
# Full live accuracy run (6 scenarios on Azure gpt-4o + Foundry IQ)
python tests/scenario_accuracy.py        # writes results/scenario_results.json

# Elasticity recovery against known ground truth
pytest tests/test_elasticity_recovery.py

# One scenario end to end over HTTP
curl -X POST http://127.0.0.1:8000/api/v1/scenarios/s2/analyze
```

Or open the web app at `/` and click any of the six scenario buttons to run and verify
live.
