from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import statsmodels.api as sm

from app.models.schemas import PromotionAnalysisRequest


def _mean(values: list[float], default: float = 0.0) -> float:
    return statistics.fmean(values) if values else default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _context(request: PromotionAnalysisRequest, key: str, default: Any) -> Any:
    return request.context_data.get(key, default)


@dataclass
class ElasticityEstimate:
    naive_elasticity: float
    controlled_elasticity: float
    controlled_std_error: float
    controlled_ci: tuple[float, float]
    confidence: float


@dataclass
class DemandModelResult:
    baseline_units: float
    elasticity: float
    weather_coefficient: float
    promo_uplift: float
    projected_units: float
    projected_lift_pct: float
    confidence_interval: tuple[float, float]
    confidence: float
    per_store_day_baseline_units: float
    promo_days: int
    store_count: int
    base_reference_price: float
    elasticity_ci_low: float
    elasticity_ci_high: float


@dataclass
class ProfitModelResult:
    unit_price: float
    unit_margin: float
    expected_revenue: float
    expected_profit: float
    min_margin_ok: bool
    margin_rate: float


@dataclass
class CannibalizationResult:
    substitution_rate: float
    complement_uplift_rate: float
    net_category_units: float
    confidence: float


@dataclass
class InventoryRiskResult:
    service_level: float
    stockout_probability: float
    expected_lost_units: float
    expected_leftover_units: float
    carrying_cost: float
    markdown_risk_cost: float
    max_store_stockout_probability: float
    available_units: float
    post_promo_capacity: float
    spoiled_units: float
    spoilage_loss: float
    loss_per_spoiled_unit: float
    clearance_pressure: float


@dataclass
class TimingResult:
    timing_score: float
    event_multiplier: float
    explanation: str


@dataclass
class CompetitorResult:
    market_heat: float
    average_gap_pct: float
    pressure_label: str
    recommended_stance: str


@dataclass
class WeatherResult:
    avg_forecast_temp: float
    weather_index: float
    uplift_pct: float


@dataclass
class BrandResult:
    dilution_risk: float
    reference_price_gap_pct: float
    long_run_margin_drag: float


@dataclass
class MonteCarloScenario:
    discount: int
    expected_units: float
    expected_revenue: float
    expected_profit: float
    profit_low: float
    profit_high: float
    probability_of_loss: float
    cvar_10: float
    weighted_score: float
    policy_compliant: bool
    policy_issues: list[str]


class RetailAnalyticsEngine:
    def historical_rows(self, request: PromotionAnalysisRequest) -> list[dict[str, Any]]:
        history = _context(request, "historical_sales", {})
        rows: list[dict[str, Any]] = []
        if isinstance(history, dict):
            for store, items in history.items():
                if not isinstance(items, list):
                    continue
                for row in items:
                    if isinstance(row, dict):
                        enriched = dict(row)
                        enriched["store"] = store
                        rows.append(enriched)
        elif isinstance(history, list):
            rows = [dict(row) for row in history if isinstance(row, dict)]
        return rows

    def demand_model(
        self,
        request: PromotionAnalysisRequest,
        discount_pct: int | None = None,
        estimate: ElasticityEstimate | None = None,
    ) -> DemandModelResult:
        rows = self.historical_rows(request)
        inventory = _context(request, "inventory", [])
        applied_discount = discount_pct if discount_pct is not None else request.discount
        applied_price = request.base_price * (1 - applied_discount / 100.0)

        units = [float(row.get("units", 0.0)) for row in rows]
        promos = [1.0 if row.get("on_promo") else 0.0 for row in rows]
        prices = [float(row.get("price", request.base_price)) for row in rows]

        per_store_day_baseline_units = _mean([u for u, p in zip(units, promos) if p == 0.0], default=_mean(units, max(1.0, request.inventory_units / 30.0)))
        store_count = max(1, len(inventory) or len({row.get("store") for row in rows if row.get("store")}))
        promo_days = self._promo_days(request)
        baseline_units = per_store_day_baseline_units * store_count * promo_days

        nonpromo_prices = [p for p, promo in zip(prices, promos) if promo == 0.0]
        base_reference_price = _mean(nonpromo_prices, request.base_price)
        # Elasticity depends only on the history, not on the candidate discount, so it can be
        # estimated once and reused across the discount sweep.
        if estimate is None:
            estimate = self.estimate_elasticity(request)
        elasticity = estimate.controlled_elasticity

        price_ratio = max(applied_price / max(base_reference_price, 0.01), 0.1)
        base_demand_units = baseline_units * (price_ratio ** (-elasticity))

        weather = self.weather_model(request)
        timing = self.timing_model(request)
        weather_multiplier = 1 + (weather.uplift_pct / 100.0)
        event_multiplier = timing.event_multiplier

        promo_history = _context(request, "promotion_history", [])
        history_uplift = _mean([float(item.get("observed_lift_pct", 0.0)) for item in promo_history], default=35.0) / 100.0
        execution_multiplier = self._promo_execution_multiplier(request, applied_discount, baseline_units, history_uplift)
        projected_units = base_demand_units * weather_multiplier * event_multiplier * execution_multiplier
        projected_lift_pct = ((projected_units / max(baseline_units, 1.0)) - 1.0) * 100.0

        elasticity_span = max(0.05, estimate.controlled_ci[1] - estimate.controlled_ci[0])
        ci_half = max(15.0, projected_units * (elasticity_span * 0.09))
        confidence = estimate.confidence

        return DemandModelResult(
            baseline_units=round(baseline_units, 2),
            elasticity=round(elasticity, 3),
            weather_coefficient=round(weather.weather_index, 3),
            promo_uplift=round((execution_multiplier - 1.0) * 100.0, 2),
            projected_units=round(projected_units, 2),
            projected_lift_pct=round(projected_lift_pct, 2),
            confidence_interval=(round(projected_units - ci_half, 2), round(projected_units + ci_half, 2)),
            confidence=round(confidence, 2),
            per_store_day_baseline_units=round(per_store_day_baseline_units, 2),
            promo_days=promo_days,
            store_count=store_count,
            base_reference_price=round(base_reference_price, 2),
            elasticity_ci_low=round(estimate.controlled_ci[0], 3),
            elasticity_ci_high=round(estimate.controlled_ci[1], 3),
        )

    def estimate_elasticity(self, request: PromotionAnalysisRequest) -> ElasticityEstimate:
        rows = self.historical_rows(request)
        if len(rows) < 6:
            return ElasticityEstimate(1.4, 1.4, 0.25, (0.91, 1.89), 0.45)

        holiday_dates = {item.get("date") for item in _context(request, "calendar_events", []) if item.get("date")}
        y = np.array([math.log(max(float(row.get("units", 1.0)), 1.0)) for row in rows])
        log_price = np.array([math.log(max(float(row.get("price", request.base_price)), 0.01)) for row in rows])
        temp = np.array([float(row.get("temp_high_f", 80.0)) for row in rows])
        promo = np.array([1.0 if row.get("on_promo") else 0.0 for row in rows])
        holiday = np.array([1.0 if row.get("date") in holiday_dates else 0.0 for row in rows])

        naive_X = sm.add_constant(log_price)
        naive_model = sm.OLS(y, naive_X).fit()
        naive_elasticity = _clamp(-float(naive_model.params[1]), 0.4, 4.0)

        # Controlled regression: the price coefficient is the partial effect holding the confounders
        # (temperature, holiday, promo) constant. This is backdoor adjustment and gives standard errors.
        controlled_X = sm.add_constant(np.column_stack([log_price, temp, holiday, promo]))
        controlled_model = sm.OLS(y, controlled_X).fit()
        raw_controlled = -float(controlled_model.params[1])
        controlled_stderr = abs(float(controlled_model.bse[1]))

        # Identifiability guard. If price is nearly collinear with the confounders (no overlap:
        # price always moves together with promo/heat/holiday), the controlled coefficient is not
        # identified and collapses toward the clamp floor. We measure the share of price variation
        # left AFTER removing the confounders and trust the controlled estimate only in proportion
        # to it, blending toward the naive estimate otherwise. With real overlap the adjusted
        # estimate is kept; on thin or confounded data it stays robust.
        price_on_confounders = sm.OLS(log_price, sm.add_constant(np.column_stack([temp, holiday, promo]))).fit()
        overlap = max(0.0, 1.0 - float(price_on_confounders.rsquared))
        # A wrong-signed or implausibly large controlled coefficient is a definitive sign that the
        # price effect is not identified (collinearity), so it earns no trust regardless of overlap.
        sign_plausible = 0.3 < raw_controlled < 4.5
        reliability = _clamp(overlap / 0.45, 0.0, 1.0) if sign_plausible else 0.0
        controlled_elasticity = _clamp(reliability * raw_controlled + (1 - reliability) * naive_elasticity, 0.4, 4.0)

        half = 1.96 * max(controlled_stderr, 0.05)
        controlled_ci = (_clamp(controlled_elasticity - half, 0.2, 5.0), _clamp(controlled_elasticity + half, 0.2, 5.0))

        confidence = _clamp(
            0.45 + min(0.15, len(rows) / 160.0) + min(0.15, controlled_model.rsquared * 0.2) + 0.12 * reliability,
            0.45, 0.92,
        )
        return ElasticityEstimate(
            naive_elasticity=round(naive_elasticity, 3),
            controlled_elasticity=round(controlled_elasticity, 3),
            controlled_std_error=round(controlled_stderr, 4),
            controlled_ci=(round(controlled_ci[0], 3), round(controlled_ci[1], 3)),
            confidence=round(confidence, 2),
        )

    def profit_model(self, request: PromotionAnalysisRequest, expected_units: float, discount_pct: int | None = None) -> ProfitModelResult:
        discount = discount_pct if discount_pct is not None else request.discount
        cost = _context(request, "cost_structure", {})
        unit_price = request.base_price * (1 - discount / 100.0)
        full_unit_cost = (
            float(cost.get("unit_cogs", request.unit_cost))
            + float(cost.get("inbound_freight_per_unit", 0.0))
            + float(cost.get("cold_storage_cost_per_unit_per_week", 0.0))
            + float(cost.get("spoilage_risk_per_unit_per_week", 0.0))
        )
        unit_margin = unit_price - full_unit_cost
        expected_revenue = unit_price * expected_units
        expected_profit = unit_margin * expected_units
        margin_rate = unit_margin / max(unit_price, 0.01)
        min_margin_ok = margin_rate >= float(cost.get("min_margin_pct", 0.2))
        return ProfitModelResult(round(unit_price, 2), round(unit_margin, 2), round(expected_revenue, 2), round(expected_profit, 2), min_margin_ok, round(margin_rate, 3))

    def cannibalization_model(self, request: PromotionAnalysisRequest, expected_units: float) -> CannibalizationResult:
        hierarchy = _context(request, "product_hierarchy", {})
        substitutes = hierarchy.get("substitutes", [])
        complements = hierarchy.get("complements", [])
        substitution_rate = _mean([float(item.get("substitution_strength", 0.0)) for item in substitutes], 0.35) * 0.28
        complement_uplift_rate = _mean([float(item.get("complement_strength", 0.0)) for item in complements], 0.2) * 0.18
        baskets = _context(request, "transaction_baskets", [])

        basket_overlap = 0.0
        if baskets:
            with_target = 0
            with_substitute = 0
            substitute_skus = {item.get("sku") for item in substitutes}
            for basket in baskets:
                items = set(basket.get("items", []))
                if request.sku and request.sku in items:
                    with_target += 1
                    if items & substitute_skus:
                        with_substitute += 1
            if with_target:
                basket_overlap = with_substitute / with_target

        substitution_rate = _clamp(substitution_rate + (basket_overlap * 0.12), 0.03, 0.42)
        complement_uplift_rate = _clamp(complement_uplift_rate, 0.01, 0.18)
        net_category_units = expected_units * (1 - substitution_rate + complement_uplift_rate)
        confidence = _clamp(0.42 + len(baskets) / 40.0, 0.4, 0.86)
        return CannibalizationResult(round(substitution_rate * 100.0, 2), round(complement_uplift_rate * 100.0, 2), round(net_category_units, 2), round(confidence, 2))

    def inventory_model(self, request: PromotionAnalysisRequest, expected_units: float) -> InventoryRiskResult:
        inventory = _context(request, "inventory", [])
        cost = _context(request, "cost_structure", {})
        if not inventory:
            inventory = [{"on_hand_units": request.inventory_units, "inbound_po_units": 0, "weekly_baseline_velocity": request.inventory_units / 4.0, "safety_stock": request.inventory_units * 0.15}]

        available_units = sum(int(item.get("on_hand_units", 0)) + int(item.get("inbound_po_units", 0)) for item in inventory)
        total_baseline_velocity = sum(float(item.get("weekly_baseline_velocity", 0.0)) for item in inventory)
        safety_stock = sum(float(item.get("safety_stock", 0.0)) for item in inventory)
        strategic_buffer = max(safety_stock, total_baseline_velocity * 0.35)
        overstock_ratio = max(0.0, (available_units / max(expected_units, 1.0)) - 1.0)
        service_level = _clamp(available_units / max(expected_units, 1.0), 0.0, 1.25)
        stockout_probability = self._stockout_probability(service_level)

        store_count = len(inventory)
        per_store_demand = expected_units / max(store_count, 1)
        per_store_risks = []
        for item in inventory:
            store_supply = float(item.get("on_hand_units", 0)) + float(item.get("inbound_po_units", 0))
            store_service = _clamp(store_supply / max(per_store_demand, 1.0), 0.0, 1.25)
            per_store_risks.append(self._stockout_probability(store_service))

        expected_lost_units = max(0.0, expected_units - available_units) + (expected_units * stockout_probability * 0.08)
        expected_leftover_units = max(0.0, available_units - expected_units - strategic_buffer)
        carrying_cost = expected_leftover_units * float(cost.get("cold_storage_cost_per_unit_per_week", 0.0))
        markdown_risk_cost = expected_leftover_units * max(0.0, float(cost.get("unit_cogs", request.unit_cost)) - float(cost.get("markdown_salvage_value_per_unit", 0.0))) * 0.18

        product_master = _context(request, "product_master", {})
        shelf_life_days = float(product_master.get("promo_freshness_window_days", product_master.get("shelf_life_days", 365)))
        promo_days = self._promo_days(request)
        post_promo_weeks = max(0.0, (shelf_life_days - promo_days) / 7.0)
        post_promo_capacity = total_baseline_velocity * post_promo_weeks
        loss_per_spoiled_unit = max(0.0, float(cost.get("unit_cogs", request.unit_cost)) - float(cost.get("markdown_salvage_value_per_unit", 0.0)))
        spoiled_units = max(0.0, available_units - expected_units - post_promo_capacity)
        spoilage_loss = spoiled_units * loss_per_spoiled_unit
        perishability_index = _clamp((21.0 - min(shelf_life_days, 21.0)) / 21.0, 0.0, 1.0)
        baseline_absorption_capacity = total_baseline_velocity * max(post_promo_weeks, 1.0)
        overhang_ratio = max(0.0, available_units - baseline_absorption_capacity) / max(available_units, 1.0)
        clearance_pressure = _clamp(
            max(
                spoiled_units / max(available_units, 1.0),
                overstock_ratio * perishability_index * 0.18,
                overhang_ratio * perishability_index * 0.8,
            ),
            0.0,
            1.0,
        )

        return InventoryRiskResult(
            round(min(service_level, 1.0), 3),
            round(stockout_probability, 3),
            round(expected_lost_units, 2),
            round(expected_leftover_units, 2),
            round(carrying_cost, 2),
            round(markdown_risk_cost, 2),
            round(max(per_store_risks) if per_store_risks else stockout_probability, 3),
            round(available_units, 2),
            round(post_promo_capacity, 2),
            round(spoiled_units, 2),
            round(spoilage_loss, 2),
            round(loss_per_spoiled_unit, 2),
            round(clearance_pressure, 3),
        )

    def timing_model(self, request: PromotionAnalysisRequest) -> TimingResult:
        events = _context(request, "calendar_events", [])
        multiplier = _clamp(_mean([float(item.get("demand_index", 1.0)) for item in events], 1.0), 0.8, 2.1)
        score = _clamp((multiplier - 1.0) / 0.7, 0.2, 0.98)
        return TimingResult(round(score, 2), round(multiplier, 3), "Timing score is derived from supplied event, payday, and holiday demand indices.")

    def competitor_model(self, request: PromotionAnalysisRequest) -> CompetitorResult:
        competitors = _context(request, "competitor_prices", [])
        target_price = request.base_price * (1 - request.discount / 100.0)
        prices = [float(item.get("price", target_price)) for item in competitors]
        promo_depths = [float(item.get("promo_depth_pct", 0.0)) for item in competitors]
        avg_comp_price = _mean(prices, target_price)
        average_gap_pct = ((target_price - avg_comp_price) / max(avg_comp_price, 0.01)) * 100.0
        price_war_signal = max(0.0, _mean(promo_depths, 0.0) / 35.0)
        market_heat = _clamp(0.35 + price_war_signal * 0.35 + (0.08 if average_gap_pct > 0 else 0.0), 0.2, 0.92)
        if market_heat >= 0.7:
            label = "high"
            stance = "Competitive pressure is high; defend traffic without triggering a destructive price war."
        elif market_heat >= 0.5:
            label = "moderate"
            stance = "A disciplined promotion is justified, but economics should still dominate."
        else:
            label = "contained"
            stance = "Competitor pressure looks limited relative to internal economics."
        return CompetitorResult(round(market_heat, 2), round(average_gap_pct, 2), label, stance)

    def weather_model(self, request: PromotionAnalysisRequest) -> WeatherResult:
        hist_avg = _mean([float(row.get("temp_high_f", 80.0)) for row in self.historical_rows(request)], 80.0)
        forecast = _context(request, "weather_forecast", [])
        forecast_avg = _mean([float(item.get("temp_high_f", hist_avg)) for item in forecast], hist_avg)
        weather_index = _clamp((forecast_avg - hist_avg) / 18.0, 0.0, 1.5)
        uplift_pct = max(0.0, weather_index * 22.0)
        return WeatherResult(round(forecast_avg, 2), round(weather_index, 3), round(uplift_pct, 2))

    def brand_model(self, request: PromotionAnalysisRequest) -> BrandResult:
        brand = _context(request, "brand_signals", {})
        reference_price = float(brand.get("reference_price_estimate", request.base_price))
        discounted_price = request.base_price * (1 - request.discount / 100.0)
        reference_gap_pct = ((reference_price - discounted_price) / max(reference_price, 0.01)) * 100.0
        promo_frequency = float(brand.get("promo_frequency_last_12mo", 0.0))
        avg_depth = float(brand.get("avg_discount_depth_last_12mo_pct", 0.0))
        sensitivity = 1.15 if str(brand.get("price_image_sensitivity", "")).lower() == "high" else 0.85
        dilution_risk = _clamp(((reference_gap_pct / 35.0) + (promo_frequency / 12.0) + (avg_depth / 40.0)) * 0.32 * sensitivity, 0.03, 0.95)
        long_run_margin_drag = dilution_risk * request.base_price * 0.12
        return BrandResult(round(dilution_risk, 3), round(reference_gap_pct, 2), round(long_run_margin_drag, 2))

    def monte_carlo(self, request: PromotionAnalysisRequest, candidate_discounts: list[int]) -> list[MonteCarloScenario]:
        seed_basis = sum(ord(ch) for ch in request.product) + request.discount + int(request.base_price * 100)
        rng = random.Random(seed_basis)
        scenarios: list[MonteCarloScenario] = []
        max_loss_prob = float((request.risk_policy or {}).get("max_probability_of_loss", 0.1))

        # Elasticity depends only on the history, so estimate it once and reuse it across the
        # whole discount sweep instead of refitting the regression for every candidate.
        estimate = self.estimate_elasticity(request)

        for discount in sorted(set(candidate_discounts)):
            sampled_request = self._request_with_discount(request, discount)
            demand = self.demand_model(sampled_request, estimate=estimate)
            profit = self.profit_model(sampled_request, demand.projected_units)
            inventory = self.inventory_model(sampled_request, demand.projected_units)
            brand = self.brand_model(sampled_request)
            cannibalization = self.cannibalization_model(sampled_request, demand.projected_units)
            stockout_penalty = float(_context(sampled_request, "cost_structure", {}).get("stockout_penalty_per_unit", 0.0))

            profits: list[float] = []
            for _ in range(300):
                sampled_units = max(1.0, rng.gauss(demand.projected_units, max(18.0, (demand.confidence_interval[1] - demand.confidence_interval[0]) / 3.0)))
                sampled_units *= rng.uniform(0.95, 1.06)
                sampled_units *= 1 - (inventory.stockout_probability * rng.uniform(0.02, 0.12))
                sellable_units = min(sampled_units, inventory.available_units)
                sampled_spoiled = max(0.0, inventory.available_units - sellable_units - inventory.post_promo_capacity)
                sampled_profit = (
                    sellable_units * profit.unit_margin
                    - inventory.expected_lost_units * stockout_penalty
                    - sampled_spoiled * inventory.loss_per_spoiled_unit
                    - inventory.carrying_cost * rng.uniform(0.3, 0.7)
                    - brand.long_run_margin_drag * sampled_units * 0.02
                    - (cannibalization.substitution_rate / 100.0) * sampled_units * 0.05
                )
                profits.append(sampled_profit)

            profits.sort()
            expected_profit = _mean(profits, profit.expected_profit)
            low_idx = max(0, int(len(profits) * 0.1) - 1)
            high_idx = min(len(profits) - 1, int(len(profits) * 0.9))
            probability_of_loss = sum(1 for value in profits if value < 0) / len(profits)
            tail = profits[: max(1, len(profits) // 10)]
            cvar_10 = _mean(tail, profits[0])
            policy_issues = self.evaluate_policy(sampled_request, profit, inventory, probability_of_loss, expected_profit)
            policy_compliant = not policy_issues
            weighted_score = (
                (expected_profit / max(request.base_price * 500.0, 1.0)) * 0.55
                + max(0.0, 1 - probability_of_loss / max(max_loss_prob, 0.01)) * 0.2
                + max(0.0, 1 - brand.dilution_risk) * 0.1
                + max(0.0, 1 - inventory.stockout_probability) * 0.1
                + (0.05 if policy_compliant else -0.2)
            )
            scenarios.append(
                MonteCarloScenario(
                    discount=discount,
                    expected_units=round(demand.projected_units, 2),
                    expected_revenue=round(profit.expected_revenue, 2),
                    expected_profit=round(expected_profit, 2),
                    profit_low=round(profits[low_idx], 2),
                    profit_high=round(profits[high_idx], 2),
                    probability_of_loss=round(probability_of_loss, 3),
                    cvar_10=round(cvar_10, 2),
                    weighted_score=round(weighted_score, 3),
                    policy_compliant=policy_compliant,
                    policy_issues=policy_issues,
                )
            )
        scenarios.sort(key=lambda item: (item.policy_compliant, item.weighted_score), reverse=True)
        return scenarios

    def evaluate_policy(
        self,
        request: PromotionAnalysisRequest,
        profit: ProfitModelResult,
        inventory: InventoryRiskResult,
        probability_of_loss: float,
        expected_profit: float,
    ) -> list[str]:
        issues = []
        risk_policy = request.risk_policy or {}
        if probability_of_loss > float(risk_policy.get("max_probability_of_loss", 0.1)):
            issues.append("Probability of loss exceeds the current risk policy.")
        if not profit.min_margin_ok:
            issues.append("Margin floor is violated.")
        if inventory.service_level < float(risk_policy.get("min_service_level", 0.9)):
            issues.append("Inventory service level is below policy.")
        if expected_profit <= 0:
            issues.append("Expected profit is non-positive after penalties.")
        return issues

    def _promo_execution_multiplier(
        self,
        request: PromotionAnalysisRequest,
        applied_discount: int,
        baseline_units: float,
        history_uplift: float,
    ) -> float:
        if applied_discount <= 0:
            return 1.0
        inventory = _context(request, "inventory", [])
        available_units = sum(int(item.get("on_hand_units", 0)) + int(item.get("inbound_po_units", 0)) for item in inventory) or request.inventory_units
        product_master = _context(request, "product_master", {})
        freshness_window = float(product_master.get("promo_freshness_window_days", product_master.get("shelf_life_days", 365)))
        overstock_ratio = max(0.0, (available_units / max(baseline_units, 1.0)) - 1.0)
        perishability_index = _clamp((28.0 - min(freshness_window, 28.0)) / 28.0, 0.0, 1.0)
        history_bonus = min(0.45, history_uplift * min(applied_discount / 25.0, 1.0) * 0.35)
        clearance_bonus = min(1.15, (applied_discount / 100.0) * overstock_ratio * perishability_index * 1.8)
        return 1.0 + history_bonus + clearance_bonus

    def _request_with_discount(self, request: PromotionAnalysisRequest, discount: int) -> PromotionAnalysisRequest:
        payload = request.model_dump()
        payload["discount"] = discount
        return PromotionAnalysisRequest(**payload)

    def _promo_days(self, request: PromotionAnalysisRequest) -> int:
        promotion_request = _context(request, "promotion_request", {})
        window = promotion_request.get("promo_window", {})
        start_raw = window.get("start")
        end_raw = window.get("end")
        if not start_raw or not end_raw:
            return 7
        try:
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
        except ValueError:
            return 7
        return max(1, (end - start).days + 1)

    def _stockout_probability(self, service_level: float) -> float:
        shortfall = max(0.0, 1.0 - service_level)
        return _clamp(shortfall * 1.35 + 0.02, 0.01, 0.98)
