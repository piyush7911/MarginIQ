from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.schemas import PromotionAnalysisRequest


@dataclass(frozen=True)
class Capability:
    name: str
    kind: str
    requires: tuple[str, ...]
    applies_when: tuple[str, ...]
    produces: tuple[str, ...]
    cost: str
    categories: tuple[str, ...]
    mandatory: bool = False

    def applies_to(self, request: PromotionAnalysisRequest) -> bool:
        return "*" in self.categories or request.category.lower() in self.categories


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._register_defaults()

    def register(self, capability: Capability) -> None:
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability:
        return self._capabilities[name]

    def all(self) -> list[Capability]:
        return list(self._capabilities.values())

    def available_for(self, request: PromotionAnalysisRequest, data_inventory: dict[str, dict[str, str]]) -> list[Capability]:
        available: list[Capability] = []
        for capability in self._capabilities.values():
            if not capability.applies_to(request):
                continue
            if all(data_inventory.get(feed, {}).get("present") == "yes" for feed in capability.requires):
                available.append(capability)
        return available

    def _register_defaults(self) -> None:
        defaults = [
            Capability("demand", "math", ("historical_sales",), ("core",), ("demand",), "cheap", ("*",), True),
            Capability("profit", "math", ("cost_structure",), ("core",), ("profit",), "cheap", ("*",), True),
            Capability("inventory", "math", ("inventory",), ("core",), ("inventory",), "cheap", ("*",), True),
            Capability("optimizer", "math", ("historical_sales", "inventory", "cost_structure"), ("core",), ("optimization",), "expensive", ("*",), True),
            Capability("timing", "math", ("calendar_events",), ("calendar",), ("timing",), "cheap", ("*",)),
            Capability("weather", "math", ("weather_forecast", "historical_sales"), ("weather_sensitive",), ("weather",), "cheap", ("beverages", "frozen_desserts")),
            Capability("competitor", "math", ("competitor_prices",), ("competitive",), ("competitor",), "cheap", ("*",)),
            Capability("cannibalization", "math", ("product_hierarchy",), ("assortment",), ("cannibalization",), "cheap", ("*",)),
            Capability("brand", "math", ("brand_signals",), ("premium",), ("brand",), "cheap", ("*",)),
            Capability("luxury_strategist", "llm_expert", ("brand_signals",), ("premium",), ("luxury_strategy",), "expensive", ("luxury", "premium_gelato", "frozen_desserts")),
            Capability("perishable_clearance_strategist", "llm_expert", ("inventory", "cost_structure"), ("clearance",), ("clearance_strategy",), "expensive", ("*",)),
            Capability("commodity_price_fighter", "llm_expert", ("competitor_prices", "historical_sales"), ("competitive",), ("commodity_strategy",), "expensive", ("grocery", "general", "beverages")),
            Capability("weather_driven_strategist", "llm_expert", ("weather_forecast", "calendar_events"), ("weather_sensitive",), ("weather_strategy",), "expensive", ("beverages", "frozen_desserts")),
            Capability("debate", "llm_control", tuple(), ("control",), ("debate",), "expensive", ("*",)),
            Capability("critic", "llm_control", tuple(), ("control",), ("verification",), "expensive", ("*",), True),
            Capability("arbiter", "llm_control", tuple(), ("control",), ("decision",), "expensive", ("*",), True),
        ]
        for capability in defaults:
            self.register(capability)


def infer_data_inventory(request: PromotionAnalysisRequest) -> dict[str, dict[str, str]]:
    feeds = [
        "historical_sales",
        "promotion_history",
        "inventory",
        "cost_structure",
        "competitor_prices",
        "product_hierarchy",
        "transaction_baskets",
        "calendar_events",
        "weather_forecast",
        "brand_signals",
        "customer_segments",
    ]
    inventory: dict[str, dict[str, str]] = {}
    for feed in feeds:
        value: Any = request.context_data.get(feed)
        present = "yes" if value not in (None, {}, [], "") else "no"
        quality = "available" if present == "yes" else "missing"
        inventory[feed] = {"present": present, "quality": quality}
    return inventory
