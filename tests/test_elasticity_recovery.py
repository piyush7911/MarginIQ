"""Estimator proof: on a synthetic dataset with a KNOWN true elasticity (1.85), the
controlled regression recovers the truth within its confidence interval while the naive
estimate is measurably biased. Pure math — no Azure required."""
from app.models.schemas import PromotionAnalysisRequest
from app.services.analytics import RetailAnalyticsEngine
from app.services.synthetic_generator import generate_synthetic_dataset


def test_parameter_recovery() -> None:
    dataset = generate_synthetic_dataset()
    request = PromotionAnalysisRequest(
        sku="SYN-1",
        product="Synthetic Gelato",
        category="frozen_desserts",
        discount=20,
        discount_bounds=[0, 40],
        timing="synthetic",
        base_price=7.0,
        unit_cost=2.8,
        inventory_units=2400,
        seasonal_context="summer",
        risk_policy={"max_probability_of_loss": 0.15, "min_service_level": 0.85},
        context_data=dataset.request_context,
    )
    analytics = RetailAnalyticsEngine()
    estimate = analytics.estimate_elasticity(request)

    # Naive estimate is biased away from the truth.
    assert abs(estimate.naive_elasticity - dataset.true_elasticity) > 0.05
    # Controlled estimate recovers the truth within its confidence interval.
    assert estimate.controlled_ci[0] <= dataset.true_elasticity <= estimate.controlled_ci[1]
    assert abs(estimate.controlled_elasticity - dataset.true_elasticity) < 0.35
