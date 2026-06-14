from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR


@dataclass
class SeedContext:
    meta: dict[str, Any]
    promotion_request: dict[str, Any]
    product_master: dict[str, Any]
    product_hierarchy: dict[str, Any]
    cost_structure: dict[str, Any]
    inventory: list[dict[str, Any]]
    historical_sales: dict[str, list[dict[str, Any]]]
    promotion_history: list[dict[str, Any]]
    transaction_baskets: list[dict[str, Any]]
    competitor_prices: list[dict[str, Any]]
    calendar_events: list[dict[str, Any]]
    weather_forecast: list[dict[str, Any]]
    brand_signals: dict[str, Any]
    customer_segments: list[dict[str, Any]]


class SeedRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (BASE_DIR / "seed_data.json")
        self._cache: SeedContext | None = None

    def load(self) -> SeedContext:
        if self._cache is not None:
            return self._cache
        with self.path.open() as infile:
            payload = json.load(infile)
        self._cache = SeedContext(
            meta=payload.get("_meta", {}),
            promotion_request=payload.get("promotion_request", {}),
            product_master=payload.get("product_master", {}),
            product_hierarchy=payload.get("product_hierarchy", {}),
            cost_structure=payload.get("cost_structure", {}),
            inventory=payload.get("inventory", []),
            historical_sales=payload.get("historical_sales", {}),
            promotion_history=payload.get("promotion_history", []),
            transaction_baskets=payload.get("transaction_baskets", []),
            competitor_prices=payload.get("competitor_prices", []),
            calendar_events=payload.get("calendar_events", []),
            weather_forecast=payload.get("weather_forecast", []),
            brand_signals=payload.get("brand_signals", {}),
            customer_segments=payload.get("customer_segments", []),
        )
        return self._cache
