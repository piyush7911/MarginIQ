from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class SyntheticDataset:
    true_elasticity: float
    rows: list[dict]
    request_context: dict


def generate_synthetic_dataset(seed: int = 17, stores: int = 3, days: int = 120) -> SyntheticDataset:
    rng = random.Random(seed)
    true_elasticity = 1.85
    base_price = 7.0
    baseline_units = [42, 55, 36]
    rows: dict[str, list[dict]] = {}
    weather_forecast = []
    calendar_events = []
    competitor_prices = []
    inventory = []

    for store_idx in range(stores):
        store_name = f"STORE-{store_idx+1}"
        rows[store_name] = []
        inventory.append(
            {
                "store": store_name,
                "on_hand_units": 700 + (store_idx * 60),
                "inbound_po_units": 180,
                "lead_time_days": 4,
                "reorder_point": 320,
                "safety_stock": 140,
                "weekly_baseline_velocity": 260 + (store_idx * 30),
            }
        )
        for day in range(days):
            month = 5 + ((day // 30) % 3)
            day_of_month = (day % 28) + 1
            date_str = f"2026-{month:02d}-{day_of_month:02d}"
            temp = 68 + (store_idx * 2) + (day % 10) * 2 + rng.uniform(-3, 3)
            holiday = 1 if day in {25, 26, 55, 56, 85, 86} else 0
            hot_day = 1 if temp >= 86 else 0
            promo = 1 if (holiday or hot_day) and day % 5 != 0 else 0
            if day % 19 == 0:
                promo = 1
            if day % 23 == 0:
                promo = 0
            promo_display = 1 if promo and day % 4 != 0 else 0
            # Deliberate confounding with overlap:
            # most price cuts happen on hot/holiday days, but some hot days remain full-price
            # and some cooler days still get promoted so the controlled estimator can recover truth.
            price_cut = 0.0
            if promo:
                price_cut = rng.choice([0.12, 0.16, 0.22, 0.28, 0.34])
            elif day % 17 == 0:
                price_cut = 0.05
            price = base_price * (1 - price_cut)

            log_units = (
                math.log(baseline_units[store_idx])
                + (-true_elasticity * math.log(price / base_price))
                + 0.012 * (temp - 75)
                + 0.18 * holiday
                + 0.08 * promo_display
                + rng.gauss(0, 0.08)
            )
            units = max(5, int(round(math.exp(log_units))))
            rows[store_name].append(
                {
                    "date": date_str,
                    "units": units,
                    "price": round(price, 2),
                    "on_promo": bool(promo),
                    "promo_display": promo_display,
                    "temp_high_f": round(temp, 1),
                }
            )

    for idx in range(7):
        weather_forecast.append({"store": "STORE-1", "date": f"2026-08-{idx+1:02d}", "temp_high_f": 96 + idx, "precip_prob": 0.05})
    for offset, index in enumerate([1.05, 1.18, 1.32, 1.1]):
        calendar_events.append({"date": f"2026-08-{10+offset:02d}", "demand_index": index})
    competitor_prices = [{"competitor": "Rival", "price": 6.29, "promo_depth_pct": 12}]

    request_context = {
        "promotion_request": {"promo_window": {"start": "2026-08-10", "end": "2026-08-16"}},
        "historical_sales": rows,
        "weather_forecast": weather_forecast,
        "calendar_events": calendar_events,
        "competitor_prices": competitor_prices,
        "inventory": inventory,
        "cost_structure": {
            "unit_cogs": 2.8,
            "inbound_freight_per_unit": 0.4,
            "cold_storage_cost_per_unit_per_week": 0.12,
            "spoilage_risk_per_unit_per_week": 0.05,
            "markdown_salvage_value_per_unit": 1.5,
            "stockout_penalty_per_unit": 2.4,
            "min_margin_pct": 0.22,
        },
        "promotion_history": [
            {"discount_pct": 20, "observed_lift_pct": 54, "baseline_units": 700, "observed_units": 1080, "realized_margin": 0.29},
            {"discount_pct": 30, "observed_lift_pct": 89, "baseline_units": 760, "observed_units": 1430, "realized_margin": 0.23},
        ],
        "product_hierarchy": {
            "substitutes": [{"sku": "ALT-1", "substitution_strength": 0.35}],
            "complements": [{"sku": "CMP-1", "complement_strength": 0.22}],
        },
        "transaction_baskets": [{"items": ["CMP-1"]}],
        "brand_signals": {
            "reference_price_estimate": 6.95,
            "promo_frequency_last_12mo": 3,
            "avg_discount_depth_last_12mo_pct": 18,
            "price_image_sensitivity": "medium",
        },
    }
    return SyntheticDataset(true_elasticity=true_elasticity, rows=[row for store_rows in rows.values() for row in store_rows], request_context=request_context)
