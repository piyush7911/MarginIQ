"""The six demo scenarios. Each is a deterministic transform of the seed product into
a situation with a KNOWN correct direction, so anyone can run MarginIQ and verify it
reasons correctly. Shared by the API (/api/v1/scenarios) and the accuracy harness."""
from __future__ import annotations

import copy
import json
from typing import Callable

from app.core.config import BASE_DIR
from app.models.schemas import PromotionAnalysisRequest

_SEED = json.loads((BASE_DIR / "seed_data.json").read_text())


def build_request_from_seed(seed: dict) -> PromotionAnalysisRequest:
    """Single source of truth for turning a seed-shaped dict into a request."""
    req = seed.get("promotion_request", {})
    inv = seed.get("inventory", [])
    inventory_units = sum(i.get("on_hand_units", 0) + i.get("inbound_po_units", 0) for i in inv)
    return PromotionAnalysisRequest(
        sku=req.get("sku"),
        product=req.get("product"),
        category=req.get("category", "general"),
        discount=int(req.get("candidate_discount_pct", 0)),
        discount_bounds=req.get("discount_search_bounds_pct", [0, 45]),
        timing=req.get("timing", "next_week"),
        base_price=float(req.get("base_price", 10.0)),
        unit_cost=float(req.get("unit_cost", 6.0)),
        inventory_units=int(inventory_units),
        seasonal_context=req.get("seasonal_context", "standard"),
        risk_policy=req.get("risk_policy", {}),
        context_data={
            "promotion_request": req,
            "product_master": seed.get("product_master", {}),
            "product_hierarchy": seed.get("product_hierarchy", {}),
            "cost_structure": seed.get("cost_structure", {}),
            "inventory": seed.get("inventory", []),
            "historical_sales": seed.get("historical_sales", {}),
            "promotion_history": seed.get("promotion_history", []),
            "transaction_baskets": seed.get("transaction_baskets", []),
            "competitor_prices": seed.get("competitor_prices", []),
            "calendar_events": seed.get("calendar_events", []),
            "weather_forecast": seed.get("weather_forecast", []),
            "brand_signals": seed.get("brand_signals", {}),
            "customer_segments": seed.get("customer_segments", []),
        },
    )


# ----------------------------- scenario transforms -----------------------------

def _s1_baseline(seed: dict) -> dict:
    return seed


def _s2_clearance_overstock(seed: dict) -> dict:
    for store in seed["inventory"]:
        store["on_hand_units"] = store["on_hand_units"] * 5
        store["inbound_po_units"] = 0
    seed["cost_structure"]["markdown_salvage_value_per_unit"] = 0.30
    seed["cost_structure"]["spoilage_risk_per_unit_per_week"] = 0.45
    seed["product_master"]["shelf_life_days"] = 14
    seed["product_master"]["promo_freshness_window_days"] = 10
    return seed


def _s3_severe_shortage(seed: dict) -> dict:
    for store in seed["inventory"]:
        store["on_hand_units"] = 40
        store["inbound_po_units"] = 0
    return seed


def _s4_competitor_pricewar(seed: dict) -> dict:
    for c in seed["competitor_prices"]:
        c["price"] = 3.99
        c["on_promo"] = True
        c["promo_depth_pct"] = 42
    return seed


def _s5_cold_offseason(seed: dict) -> dict:
    for store in seed["historical_sales"].values():
        if not isinstance(store, list):
            continue
        for row in store:
            row["temp_high_f"] = 52
    for f in seed["weather_forecast"]:
        f["temp_high_f"] = 50
    for e in seed["calendar_events"]:
        e["demand_index"] = 1.0
    seed["promotion_request"]["timing"] = "cold_offseason"
    return seed


def _s6_margin_floor(seed: dict) -> dict:
    seed["cost_structure"]["unit_cogs"] = 5.40
    seed["promotion_request"]["unit_cost"] = 5.40
    seed["cost_structure"]["min_margin_pct"] = 0.22
    return seed


class Scenario:
    def __init__(self, key: str, title: str, summary: str, expectation: str, transform: Callable[[dict], dict]) -> None:
        self.key = key
        self.title = title
        self.summary = summary
        self.expectation = expectation
        self.transform = transform

    def build_request(self) -> PromotionAnalysisRequest:
        return build_request_from_seed(self.transform(copy.deepcopy(_SEED)))

    def meta(self) -> dict:
        return {"key": self.key, "title": self.title, "summary": self.summary, "expectation": self.expectation}


SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in [
        Scenario(
            "s1", "Baseline — heatwave, premium, tight stock",
            "The product as shipped: premium gelato, pre-July-4 heatwave demand, limited cold-chain stock.",
            "Non-zero shallow discount (5–15%) — demand responds but stock is tight.",
            _s1_baseline,
        ),
        Scenario(
            "s2", "Clearance — 5× overstock, perishable",
            "Five times the stock, near-zero salvage, short freshness window. Spoilage is the binding force.",
            "Deep discount (≥25%) to clear stock before it spoils.",
            _s2_clearance_overstock,
        ),
        Scenario(
            "s3", "Severe shortage in a heatwave",
            "Only 40 units per store against strong heatwave demand. Supply is the binding constraint.",
            "Shallow discount (≤10%) and inventory risk flagged HIGH.",
            _s3_severe_shortage,
        ),
        Scenario(
            "s4", "Competitor price war",
            "Every competitor cuts to $3.99 (−42%) and goes on promo.",
            "Competitor market-heat detected HIGH (≥0.7).",
            _s4_competitor_pricewar,
        ),
        Scenario(
            "s5", "Cold off-season",
            "Cool weather (~50°F) and no holiday demand lift.",
            "Off-season correctly detected — weather index ~0 and timing low.",
            _s5_cold_offseason,
        ),
        Scenario(
            "s6", "Margin floor binding",
            "Unit cost raised to $5.40 against a 22% margin floor.",
            "Shallow discount (≤10%) — deeper cuts would breach the margin floor.",
            _s6_margin_floor,
        ),
    ]
}


def list_scenarios() -> list[dict]:
    return [s.meta() for s in SCENARIOS.values()]


def get_scenario(key: str) -> Scenario | None:
    return SCENARIOS.get(key)
