from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.models.schemas import AgentInsight, PromotionAnalysisRequest


@dataclass
class AgentContext:
    request: PromotionAnalysisRequest
    category: str
    features: dict


class BaseAgent:
    name = "BaseAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        raise NotImplementedError

    async def _sleep(self) -> None:
        await asyncio.sleep(0)

    def _clamp_confidence(self, value: float) -> float:
        return round(max(0.05, min(0.98, value)), 2)

    def _clamp_score(self, value: float) -> float:
        return round(max(-1.0, min(1.0, value)), 3)


class DemandAgent(BaseAgent):
    name = "DemandAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        demand = context.features["demand"]
        score = self._clamp_score((float(demand["projected_lift_pct"]) - 20.0) / 70.0)
        return AgentInsight(
            agent=self.name,
            summary="Demand is estimated from historical sales, observed promo uplift, holiday timing, and weather sensitivity.",
            confidence=self._clamp_confidence(float(demand["confidence"])),
            score=score,
            metrics=demand,
        )


class ProfitabilityAgent(BaseAgent):
    name = "ProfitabilityAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        profit = context.features["profit"]
        inventory = context.features["inventory"]
        # Brand only runs when brand_signals are present, so read it defensively.
        brand = context.features.get("brand", {})
        adjusted_profit = (
            float(profit["expected_profit"])
            - float(inventory["markdown_risk_cost"])
            - float(inventory.get("spoilage_loss", 0.0))
            - float(brand.get("long_run_margin_drag", 0.0)) * 10.0
        )
        score = self._clamp_score(adjusted_profit / 1500.0)
        return AgentInsight(
            agent=self.name,
            summary="Profitability nets retained margin against inventory penalties, spoilage/clearance loss, and long-run brand drag.",
            confidence=self._clamp_confidence(0.82 if profit["min_margin_ok"] else 0.6),
            score=score,
            metrics={**profit, "risk_adjusted_profit": round(adjusted_profit, 2)},
        )


class CannibalizationAgent(BaseAgent):
    name = "CannibalizationAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        cannibalization = context.features["cannibalization"]
        score = self._clamp_score(0.65 - float(cannibalization["substitution_rate"]) / 40.0)
        return AgentInsight(
            agent=self.name,
            summary="Cannibalization uses substitute strength, basket overlap, and complement upside to estimate net category impact.",
            confidence=self._clamp_confidence(float(cannibalization["confidence"])),
            score=score,
            metrics=cannibalization,
        )


class TimingAgent(BaseAgent):
    name = "TimingAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        timing = context.features["timing"]
        return AgentInsight(
            agent=self.name,
            summary=timing["explanation"],
            confidence=self._clamp_confidence(0.82),
            score=self._clamp_score((float(timing["timing_score"]) - 0.5) * 1.7),
            metrics=timing,
        )


class InventoryRiskAgent(BaseAgent):
    name = "InventoryRiskAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        inventory = context.features["inventory"]
        score = self._clamp_score(0.8 - float(inventory["stockout_probability"]) * 1.8)
        return AgentInsight(
            agent=self.name,
            summary="Inventory risk follows service-level math using expected demand, inbound stock, cold-chain capacity, and stockout penalties.",
            confidence=self._clamp_confidence(0.86),
            score=score,
            metrics=inventory,
        )


class CompetitorIntelligenceAgent(BaseAgent):
    name = "CompetitorIntelligenceAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        competitor = context.features["competitor"]
        score = self._clamp_score((float(competitor["market_heat"]) - 0.45) * 2.0)
        return AgentInsight(
            agent=self.name,
            summary=competitor["recommended_stance"],
            confidence=self._clamp_confidence(0.78),
            score=score,
            metrics=competitor,
        )


class BasketAffinityAgent(BaseAgent):
    name = "BasketAffinityAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        cannibalization = context.features["cannibalization"]
        affinity = float(cannibalization["complement_uplift_rate"]) / 100.0
        return AgentInsight(
            agent=self.name,
            summary="Observed baskets show complementary attachments that can lift the overall trip, not just the featured SKU.",
            confidence=self._clamp_confidence(0.7),
            score=self._clamp_score((affinity - 0.03) * 6.0),
            metrics={"basket_affinity": round(affinity, 3)},
        )


class WeatherImpactAgent(BaseAgent):
    name = "WeatherImpactAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        weather = context.features["weather"]
        return AgentInsight(
            agent=self.name,
            summary="Forecast heat materially amplifies expected frozen-dessert demand during the promo window.",
            confidence=self._clamp_confidence(0.8),
            score=self._clamp_score((float(weather["weather_index"]) - 0.35) * 1.2),
            metrics=weather,
        )


class BrandDilutionAgent(BaseAgent):
    name = "BrandDilutionAgent"

    async def run(self, context: AgentContext) -> AgentInsight:
        await self._sleep()
        brand = context.features["brand"]
        score = self._clamp_score(0.62 - float(brand["dilution_risk"]))
        return AgentInsight(
            agent=self.name,
            summary="Brand risk is estimated from reference-price gap, promotion frequency, and premium price-image sensitivity.",
            confidence=self._clamp_confidence(0.76),
            score=score,
            metrics=brand,
        )


AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "demand": DemandAgent,
    "profit": ProfitabilityAgent,
    "cannibalization": CannibalizationAgent,
    "timing": TimingAgent,
    "inventory": InventoryRiskAgent,
    "competitor": CompetitorIntelligenceAgent,
    "basket_affinity": BasketAffinityAgent,
    "weather": WeatherImpactAgent,
    "brand_dilution": BrandDilutionAgent,
}
