from __future__ import annotations

import asyncio
import statistics
from typing import Any

from app.core.config import MAX_ANALYSIS_MEMORY_GB
from app.models.schemas import AgentInsight, PromotionAnalysisRequest, ScenarioResult
from app.services.agents import AGENT_REGISTRY, AgentContext
from app.services.analytics import RetailAnalyticsEngine
from app.services.capability_registry import CapabilityRegistry, infer_data_inventory
from app.services.azure_reasoning import AzureReasoningService
from app.services.foundry_iq import FoundryIQService
from app.services.memory import AnalysisMemory


def render_scenario_curve(scenarios: list[ScenarioResult]) -> str:
    """Render the discount -> profit/risk curve as a compact ASCII chart so a text model can read
    the SHAPE of the trade-off (where profit peaks, where the risk cliff starts) instead of parsing
    raw JSON dicts."""
    if not scenarios:
        return "(no scenarios)"
    ordered = sorted(scenarios, key=lambda s: s.discount)
    profits = [s.expected_profit for s in ordered]
    lo, hi = min(profits), max(profits)
    span = (hi - lo) or 1.0
    best = max(ordered, key=lambda s: s.weighted_score)
    lines = ["discount | expected profit (# = $)             | downside | risk"]
    for s in ordered:
        bars = int(round((s.expected_profit - lo) / span * 28))
        marker = "  <= best (chosen by optimizer)" if s.discount == best.discount else ""
        lines.append(f"  {s.discount:>3}%   |{'#' * max(0, bars):<28}| {s.downside_risk:>6.0%}  | {s.risk_outlook}{marker}")
    return "\n".join(lines)


def build_decision_factors(
    chosen: ScenarioResult,
    scenarios: list[ScenarioResult],
    memory: AnalysisMemory,
    verification: dict[str, Any],
    optimizer_discount: int,
) -> list[str]:
    """Produce honest, decision-specific justifications (not stray narrative log lines). Each factor
    is derived from the chosen scenario's economics and the constraints that actually bound it."""
    factors = [
        f"{chosen.discount}% has the best risk-adjusted profit (~${chosen.expected_profit:,.0f}) among policy-compliant options, "
        f"with downside risk {chosen.downside_risk:.0%}."
    ]
    deeper = sorted((s for s in scenarios if s.discount > chosen.discount), key=lambda s: s.discount)
    if deeper:
        nxt = deeper[0]
        if nxt.expected_profit < chosen.expected_profit:
            factors.append(
                f"Going deeper to {nxt.discount}% sells more units but cuts profit to ~${nxt.expected_profit:,.0f} "
                f"and raises downside risk to {nxt.downside_risk:.0%}."
            )
    f = memory.findings
    inv = f.get("inventory", {}).get("result", {})
    if inv.get("stockout_probability", 0.0) > 0.2:
        factors.append(f"Inventory limits depth: stockout probability is {inv.get('stockout_probability', 0.0):.0%} at higher discounts.")
    if inv.get("clearance_pressure", 0.0) > 0.1:
        factors.append(f"Spoilage pressure ({inv.get('clearance_pressure', 0.0):.0%} of stock at risk) favours clearing stock with a deeper cut.")
    if f.get("brand", {}).get("result", {}).get("dilution_risk", 0.0) > 0.55:
        factors.append("Premium brand image argues against repeating a deep discount.")
    if f.get("competitor", {}).get("result", {}).get("market_heat", 0.0) > 0.6:
        factors.append("Competitive pressure supports acting, but not matching the deepest price.")
    if chosen.discount != optimizer_discount:
        factors.append(f"Adjusted from the optimizer's {optimizer_discount}% to balance demand against brand and risk.")
    if not verification.get("accepted", True):
        factors.append("Flagged for human review: the leading scenario did not clear all policy gates.")
    return factors[:5]


class AgentRuntime:
    async def execute(
        self,
        request: PromotionAnalysisRequest,
        agent_keys: list[str],
        features: dict[str, Any],
    ) -> list[AgentInsight]:
        context = AgentContext(request=request, category=request.category.lower(), features=features)
        tasks = [AGENT_REGISTRY[key]().run(context) for key in agent_keys]
        return list(await asyncio.gather(*tasks))


class PlannerEngine:
    def __init__(self) -> None:
        self.reasoning = AzureReasoningService()
        self.step_cap = 2
        self.tool_budget = 4

    def plan(
        self,
        request: PromotionAnalysisRequest,
        memory: AnalysisMemory,
        available_capabilities: list[str],
    ) -> list[dict[str, str]]:
        options = [name for name in available_capabilities if name not in {item["capability"] for item in memory.plan["done"]}]
        if not options:
            return []
        return self._rule_based_plan(request, memory, options)

    def _rule_based_plan(
        self,
        request: PromotionAnalysisRequest,
        memory: AnalysisMemory,
        options: list[str],
    ) -> list[dict[str, str]]:
        picks: list[dict[str, str]] = []
        lowered_category = request.category.lower()
        open_questions = " ".join(memory.open_questions).lower()
        if "weather" in options and (lowered_category in {"beverages", "frozen_desserts"} or "weather" in open_questions):
            picks.append({"capability": "weather", "reason": "Weather-sensitive category or demand uncertainty needs forecast context."})
        if "competitor" in options and ("competitive" in open_questions or request.discount >= 15):
            picks.append({"capability": "competitor", "reason": "Competitive cross-check is relevant for the requested discount depth."})
        if "brand" in options and ("premium" in lowered_category or memory.data_inventory.get("brand_signals", {}).get("present") == "yes"):
            picks.append({"capability": "brand", "reason": "Brand signals are present and could materially affect the recommendation."})
        if "cannibalization" in options and memory.data_inventory.get("product_hierarchy", {}).get("present") == "yes":
            picks.append({"capability": "cannibalization", "reason": "Assortment data is present, so category impact should be evaluated."})
        for expert in ("luxury_strategist", "perishable_clearance_strategist", "commodity_price_fighter", "weather_driven_strategist"):
            if expert in options and len(picks) < 2:
                if expert == "luxury_strategist" and ("premium" in lowered_category or memory.data_inventory.get("brand_signals", {}).get("present") == "yes"):
                    picks.append({"capability": expert, "reason": "Premium pricing context calls for a brand-protection expert."})
                elif expert == "perishable_clearance_strategist" and "inventory" in memory.findings:
                    picks.append({"capability": expert, "reason": "Inventory and spoilage signals warrant a clearance specialist."})
                elif expert == "commodity_price_fighter" and memory.data_inventory.get("competitor_prices", {}).get("present") == "yes":
                    picks.append({"capability": expert, "reason": "Competitive pricing data is present for a price-fighter review."})
                elif expert == "weather_driven_strategist" and lowered_category in {"beverages", "frozen_desserts"}:
                    picks.append({"capability": expert, "reason": "Weather-driven demand specialist is relevant for this category."})
        return picks[:2]


class DebateEngine:
    def __init__(self) -> None:
        self.reasoning = AzureReasoningService()

    async def summarize(self, memory: AnalysisMemory, scenarios: list[ScenarioResult]) -> list[str]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"debate_summary": {"type": "array", "items": {"type": "string"}}},
            "required": ["debate_summary"],
        }
        result = await self.reasoning.json_completion(
            system_prompt=(
                "Moderate the pricing debate. Read the profit/risk curve and findings, then return 4 short "
                "bullets prefixed exactly with 'BULL:', 'BEAR:', 'TENSION:', and 'READ:'."
            ),
            user_prompt=f"Profit/risk curve:\n{render_scenario_curve(scenarios)}\n\nFindings:\n{memory.render_for_llm()}",
            schema=schema,
            temperature=0.2,
        )
        return [item.strip() for item in result["debate_summary"] if item.strip()][:4]


class CriticEngine:
    def __init__(self) -> None:
        self.reasoning = AzureReasoningService()
        self.foundry_iq = FoundryIQService()

    def _policy_query(self, request: PromotionAnalysisRequest, best: ScenarioResult, memory: AnalysisMemory) -> str:
        """Build a retrieval query so Foundry IQ returns the policy passages that
        actually bear on this decision (margin, loss, service, brand, clearance)."""
        parts = [
            f"{request.category} discount {best.discount}% margin floor probability of loss service level",
        ]
        inv = memory.findings.get("inventory", {}).get("result", {})
        if inv.get("clearance_pressure", 0.0) > 0.1 or inv.get("spoilage_loss", 0.0) > 0:
            parts.append("perishable clearance spoilage short shelf life salvage")
        if memory.findings.get("brand", {}).get("result", {}).get("dilution_risk", 0.0) > 0.4:
            parts.append("brand premium reference price discount depth dilution")
        return " ".join(parts)

    async def verify(
        self,
        request: PromotionAnalysisRequest,
        memory: AnalysisMemory,
        scenarios: list[ScenarioResult],
        optimization_summary: dict[str, Any],
        policy_issues: list[str],
    ) -> dict[str, Any]:
        best = scenarios[0]
        policy_context = await self.foundry_iq.retrieve_policy_context(
            self._policy_query(request, best, memory)
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "accepted": {"type": "boolean"},
                "status": {"type": "string"},
                "critic_summary": {"type": "string"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["accepted", "status", "critic_summary", "issues"],
        }
        result = await self.reasoning.json_completion(
            system_prompt=(
                "You are a retail pricing critic. Reject unsafe or policy-violating recommendations. "
                "Judge the recommendation against the grounded policy passages provided. "
                "In critic_summary, cite the specific policy document(s) you applied, e.g. "
                "'Per [brand_guidelines.md → Reference-price protection], ...'."
            ),
            user_prompt=(
                f"Request: {request.model_dump_json()}\n"
                f"{policy_context}\n\n"
                f"Profit/risk curve:\n{render_scenario_curve(scenarios)}\n\n"
                f"Findings:\n{memory.render_for_llm()}\n"
                f"Optimization: {optimization_summary}\n"
                f"Best scenario: {best.model_dump()}\n"
                f"Deterministic policy issues: {policy_issues}"
            ),
            schema=schema,
            temperature=0.0,
        )
        result["grounding_source"] = self.foundry_iq.source
        return result


class ArbiterEngine:
    def __init__(self) -> None:
        self.reasoning = AzureReasoningService()

    async def decide(
        self,
        request: PromotionAnalysisRequest,
        memory: AnalysisMemory,
        optimizer_summary: dict[str, Any],
        scenarios: list[ScenarioResult],
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        optimizer_discount = optimizer_summary["recommended_discount"]
        summary = dict(optimizer_summary)
        summary["optimizer_discount"] = optimizer_discount
        summary["decided_by"] = "optimizer"
        chosen = scenarios[0] if scenarios else None
        summary["decision_factors"] = (
            build_decision_factors(chosen, scenarios, memory, verification, optimizer_discount) if chosen else []
        )

        shallow_override = self._shallow_override(memory, scenarios)
        if shallow_override is not None:
            summary.update(
                {
                    "recommended_discount": shallow_override.discount,
                    "expected_profit": shallow_override.expected_profit,
                    "profit_confidence_interval": [shallow_override.profit_low, shallow_override.profit_high],
                    "downside_risk": shallow_override.downside_risk,
                    "decided_by": "arbiter",
                    "decision_factors": build_decision_factors(shallow_override, scenarios, memory, verification, optimizer_discount),
                }
            )

        if verification.get("accepted"):
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "recommended_discount": {"type": "integer"},
                    "decision_factors": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["recommended_discount", "decision_factors"],
            }
            result = await self.reasoning.json_completion(
                system_prompt=(
                    "You are the final arbiter. Read the profit/risk curve below and choose the best discount "
                    "from the rows shown. Stay within the provided scenarios and do not violate policy acceptance. "
                    "Give concrete reasons tied to the curve and findings."
                ),
                user_prompt=(
                    f"Request: {request.model_dump_json()}\n"
                    f"Profit/risk curve:\n{render_scenario_curve(scenarios)}\n\n"
                    f"Key findings:\n{memory.render_for_llm()}\n"
                    f"Optimizer summary: {optimizer_summary}\n"
                    f"Verification: {verification}"
                ),
                schema=schema,
                temperature=0.1,
            )
            allowed = {item.discount for item in scenarios}
            if result["recommended_discount"] in allowed:
                selected = next(item for item in scenarios if item.discount == result["recommended_discount"])
                llm_factors = [f.strip() for f in result.get("decision_factors", []) if f.strip()]
                # Normalize the decision owner: the arbiter "owns" the call only when it
                # moved off the optimizer's pick; otherwise it ratified the optimizer.
                decided_by = "arbiter" if selected.discount != optimizer_discount else "optimizer"
                summary.update(
                    {
                        "recommended_discount": selected.discount,
                        "expected_profit": selected.expected_profit,
                        "profit_confidence_interval": [selected.profit_low, selected.profit_high],
                        "downside_risk": selected.downside_risk,
                        "decided_by": decided_by,
                        "decision_factors": llm_factors or build_decision_factors(selected, scenarios, memory, verification, optimizer_discount),
                    }
                )

        return summary

    def _shallow_override(self, memory: AnalysisMemory, scenarios: list[ScenarioResult]) -> ScenarioResult | None:
        if not scenarios:
            return None
        best = scenarios[0]
        competitor_heat = memory.findings.get("competitor", {}).get("result", {}).get("market_heat", 0.0)
        weather_index = memory.findings.get("weather", {}).get("result", {}).get("weather_index", 0.0)
        if best.discount != 0 or competitor_heat < 0.45 or weather_index < 0.35:
            return None
        candidates = [item for item in scenarios if 0 < item.discount <= 15]
        for candidate in candidates:
            if candidate.expected_profit >= best.expected_profit * 0.96 and candidate.downside_risk <= 0.12:
                return candidate
        return None


class ExplanationEngine:
    def __init__(self) -> None:
        self.reasoning = AzureReasoningService()

    async def explain(
        self,
        request: PromotionAnalysisRequest,
        memory: AnalysisMemory,
        optimization_summary: dict[str, Any],
        verification: dict[str, Any],
    ) -> str:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"recommendation": {"type": "string"}},
            "required": ["recommendation"],
        }
        result = await self.reasoning.json_completion(
            system_prompt="Write one concise recommendation paragraph for a category manager using only supplied memory and decision data.",
            user_prompt=(
                f"Request: {request.model_dump_json()}\n"
                f"Narrative: {memory.narrative}\n"
                f"Decision: {optimization_summary}\n"
                f"Verification: {verification}"
            ),
            schema=schema,
            temperature=0.15,
        )
        return result["recommendation"]


class LangGraphSwarmWorkflow:
    def __init__(self) -> None:
        self.registry = CapabilityRegistry()
        self.runtime = AgentRuntime()
        self.analytics = RetailAnalyticsEngine()
        self.planner_engine = PlannerEngine()
        self.debate_engine = DebateEngine()
        self.critic_engine = CriticEngine()
        self.arbiter_engine = ArbiterEngine()
        self.explanation_engine = ExplanationEngine()

    def describe(self) -> dict[str, Any]:
        nodes = [
            "ingest_and_featurize",
            "plan_core",
            "run_core_capabilities",
            "plan_experts",
            "run_expert_capabilities",
            "optimize",
            "debate",
            "critic_verify",
            "arbiter_finalize",
            "explain",
        ]
        return {"nodes": nodes, "registry": [cap.__dict__ for cap in self.registry.all()]}

    async def invoke(self, request: PromotionAnalysisRequest) -> dict[str, Any]:
        memory = AnalysisMemory(
            request=request,
            data_inventory=infer_data_inventory(request),
        )
        available = self.registry.available_for(request, memory.data_inventory)
        available_names = [item.name for item in available]

        memory.narrative.append(f"Analysis started with {len(available_names)} available capabilities and a memory budget of {MAX_ANALYSIS_MEMORY_GB} GB.")

        features = await self._run_core(memory, available_names)
        selected_capabilities = ["demand", "profit", "inventory", "timing", "optimizer"]
        expert_features = await self._run_planner_rounds(memory, available_names, features)
        features.update(expert_features)

        agent_insights = await self._build_agent_insights(request, features)
        scenarios, optimization_summary, policy_issues = self._run_optimizer(request, features)
        debate_summary = await self.debate_engine.summarize(memory, scenarios)
        verification = await self.critic_engine.verify(request, memory, scenarios, optimization_summary, policy_issues)

        if not verification["accepted"]:
            compliant = [item for item in scenarios if self._is_policy_compliant(item, request, features)]
            if compliant:
                scenarios = compliant
                optimization_summary = dict(optimization_summary)
                optimization_summary.update(
                    {
                        "recommended_discount": scenarios[0].discount,
                        "expected_profit": scenarios[0].expected_profit,
                        "profit_confidence_interval": [scenarios[0].profit_low, scenarios[0].profit_high],
                        "downside_risk": scenarios[0].downside_risk,
                        "rationale": "Planner re-ran the decision through the policy filter and kept only compliant scenarios.",
                    }
                )
                verification = {
                    "accepted": True,
                    "status": "accepted_after_retry",
                    "critic_summary": "The first candidate failed policy, so the optimizer was constrained to policy-compliant scenarios.",
                    "issues": [],
                    "grounding_source": verification.get("grounding_source", "Foundry IQ"),
                }

        optimization_summary = await self.arbiter_engine.decide(request, memory, optimization_summary, scenarios, verification)
        recommendation = await self.explanation_engine.explain(request, memory, optimization_summary, verification)
        confidence = self._decision_confidence(scenarios, optimization_summary, verification)
        selected_capabilities.extend([item["capability"] for item in memory.plan["done"] if item["capability"] not in selected_capabilities])

        memory.decision = {
            "recommended_discount": optimization_summary["recommended_discount"],
            "decided_by": optimization_summary["decided_by"],
            "reasoning": optimization_summary["decision_factors"],
        }

        return {
            "selected_agents": selected_capabilities,
            "agent_insights": agent_insights,
            "debate_summary": debate_summary,
            "confidence": confidence,
            "scenarios": scenarios,
            "recommendation": recommendation,
            "verification": verification,
            "optimization_summary": optimization_summary,
            "memory": memory,
        }

    async def _run_core(self, memory: AnalysisMemory, available_names: list[str]) -> dict[str, Any]:
        request = memory.request
        features: dict[str, Any] = {}
        demand = self.analytics.demand_model(request)
        features["demand"] = demand.__dict__
        memory.record_finding(
            "demand",
            result=demand.__dict__,
            confidence=demand.confidence,
            summary="Controlled demand estimator completed.",
            flags_for_downstream=["core"],
            narrative_line=f"Demand model estimated {demand.projected_units:.0f} campaign units at {request.discount}% discount.",
            open_questions=["Cross-check with competitor pressure." if demand.confidence < 0.7 else ""],
        )
        memory.mark_done("demand", "Mandatory core capability.")

        profit = self.analytics.profit_model(request, demand.projected_units)
        features["profit"] = profit.__dict__
        memory.record_finding(
            "profit",
            result=profit.__dict__,
            confidence=0.82 if profit.min_margin_ok else 0.58,
            summary="Profit model completed.",
            flags_for_downstream=["core"],
            narrative_line=f"Profit model estimated {profit.expected_profit:.2f} expected profit before expert adjustments.",
        )
        memory.mark_done("profit", "Mandatory core capability.")

        inventory = self.analytics.inventory_model(request, demand.projected_units)
        features["inventory"] = inventory.__dict__
        extra_questions = []
        if inventory.stockout_probability > 0.2:
            extra_questions.append("Demand is strong relative to supply; should a clearance or weather specialist weigh in?")
        memory.record_finding(
            "inventory",
            result=inventory.__dict__,
            confidence=0.84,
            summary="Inventory model completed.",
            flags_for_downstream=["core"],
            narrative_line=f"Inventory model sees service level {inventory.service_level:.2f} and stockout probability {inventory.stockout_probability:.2f}.",
            open_questions=extra_questions,
        )
        memory.mark_done("inventory", "Mandatory core capability.")
        timing = self.analytics.timing_model(request)
        features["timing"] = timing.__dict__
        memory.record_finding(
            "timing",
            result=timing.__dict__,
            confidence=0.75,
            summary="Timing model completed.",
            flags_for_downstream=["calendar"],
            narrative_line=f"Timing model estimated event multiplier {timing.event_multiplier:.2f}.",
        )
        memory.mark_done("timing", "Calendar context is foundational when event data is present.")
        return features

    async def _run_planner_rounds(
        self,
        memory: AnalysisMemory,
        available_names: list[str],
        features: dict[str, Any],
    ) -> dict[str, Any]:
        request = memory.request
        produced: dict[str, Any] = {}
        core_and_control = {"demand", "profit", "inventory", "timing", "optimizer", "debate", "critic", "arbiter"}

        # Cheap math capabilities are nearly free and only add signal, so skipping them never
        # saves cost. They must NOT be gated by the LLM planner (which could drop an obviously
        # relevant one, e.g. competitor intelligence during a price war). Auto-run every cheap
        # math capability whose data is present; the data-gate already excluded missing feeds.
        auto_math = [
            name
            for name in available_names
            if name not in core_and_control and self.registry.get(name).kind == "math"
        ]
        for name in auto_math:
            result = await self._run_capability(name, request, features, memory)
            if result is not None:
                produced[name] = result
                memory.mark_done(name, "Cheap math capability auto-run because its data is present.")

        # The LLM planner only chooses among the EXPENSIVE expert capabilities, where cost and
        # relevance actually trade off.
        expert_candidates = [
            name for name in available_names if name not in core_and_control and name not in auto_math
        ]
        used_budget = 0
        for round_index in range(self.planner_engine.step_cap):
            candidates = [name for name in expert_candidates if name not in produced]
            if not candidates:
                break
            next_steps = self.planner_engine.plan(request, memory, candidates)
            if not next_steps:
                break
            for step in next_steps:
                if used_budget >= self.planner_engine.tool_budget:
                    break
                capability = step["capability"]
                if capability in produced:
                    continue
                result = await self._run_capability(capability, request, features, memory)
                if result is None:
                    continue
                produced[capability] = result
                memory.mark_done(capability, step["reason"])
                used_budget += 1
            if used_budget >= self.planner_engine.tool_budget or not memory.open_questions:
                break
        return produced

    async def _run_capability(
        self,
        capability: str,
        request: PromotionAnalysisRequest,
        features: dict[str, Any],
        memory: AnalysisMemory,
    ) -> dict[str, Any] | None:
        if capability == "timing":
            result = self.analytics.timing_model(request).__dict__
            memory.record_finding("timing", result=result, confidence=0.75, summary="Timing model completed.", narrative_line=f"Timing multiplier is {result['event_multiplier']:.2f}.")
            return result
        if capability == "weather":
            result = self.analytics.weather_model(request).__dict__
            memory.record_finding("weather", result=result, confidence=0.76, summary="Weather model completed.", narrative_line=f"Weather index is {result['weather_index']:.2f}.")
            return result
        if capability == "competitor":
            result = self.analytics.competitor_model(request).__dict__
            memory.record_finding("competitor", result=result, confidence=0.72, summary="Competitor model completed.", narrative_line=f"Competitor market heat is {result['market_heat']:.2f}.")
            return result
        if capability == "cannibalization":
            demand_units = features["demand"]["projected_units"]
            result = self.analytics.cannibalization_model(request, demand_units).__dict__
            memory.record_finding("cannibalization", result=result, confidence=result["confidence"], summary="Cannibalization model completed.", narrative_line=f"Substitution risk is {result['substitution_rate']:.2f}%.")
            return result
        if capability == "brand":
            result = self.analytics.brand_model(request).__dict__
            memory.record_finding("brand", result=result, confidence=0.74, summary="Brand model completed.", narrative_line=f"Brand dilution risk is {result['dilution_risk']:.2f}.")
            return result
        if capability in {"luxury_strategist", "perishable_clearance_strategist", "commodity_price_fighter", "weather_driven_strategist"}:
            result = await self._run_strategy_expert(capability, request, memory)
            memory.record_finding(
                capability,
                result=result,
                confidence=result["confidence"],
                summary=result["summary"],
                narrative_line=result["narrative_line"],
                open_questions=result.get("open_questions", []),
            )
            return result
        return None

    async def _run_strategy_expert(self, capability: str, request: PromotionAnalysisRequest, memory: AnalysisMemory) -> dict[str, Any]:
        prompts = {
            "luxury_strategist": "You are a luxury / premium brand strategist. Protect price image while acknowledging hard inventory and demand facts.",
            "perishable_clearance_strategist": "You are a perishable / clearance strategist. Prioritize spoilage avoidance and realistic sell-through.",
            "commodity_price_fighter": "You are a commodity price-fighter strategist. Think in elasticity and competitive defense.",
            "weather_driven_strategist": "You are a weather-driven category strategist. Read forecast, timing, and short-window demand amplification.",
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "confidence": {"type": "number"},
                "stance": {"type": "string"},
                "narrative_line": {"type": "string"},
                "open_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "confidence", "stance", "narrative_line", "open_questions"],
        }
        return await self.planner_engine.reasoning.json_completion(
            system_prompt=prompts[capability],
            user_prompt=f"Request: {request.model_dump_json()}\nMemory findings:\n{memory.render_for_llm()}\nNarrative: {memory.narrative}",
            schema=schema,
            temperature=0.15,
        )

    def _run_optimizer(
        self,
        request: PromotionAnalysisRequest,
        features: dict[str, Any],
    ) -> tuple[list[ScenarioResult], dict[str, Any], list[str]]:
        candidate_discounts = list(range(request.discount_bounds[0], request.discount_bounds[1] + 1, 5))
        monte_carlo = self.analytics.monte_carlo(request, candidate_discounts)
        scenarios = [
            ScenarioResult(
                discount=item.discount,
                expected_units=item.expected_units,
                expected_revenue=item.expected_revenue,
                expected_profit=item.expected_profit,
                profit_low=item.profit_low,
                profit_high=item.profit_high,
                downside_risk=item.probability_of_loss,
                risk_outlook="high" if item.probability_of_loss >= 0.35 else "medium" if item.probability_of_loss >= 0.15 else "low",
                weighted_score=item.weighted_score,
            )
            for item in monte_carlo
        ]
        best = monte_carlo[0]
        summary = {
            "requested_discount": request.discount,
            "recommended_discount": best.discount,
            "expected_profit": best.expected_profit,
            "profit_confidence_interval": [best.profit_low, best.profit_high],
            "downside_risk": best.probability_of_loss,
            "cvar_10": best.cvar_10,
            "rationale": "Planner-controller ran the deterministic core, then optimized across policy-aware scenarios.",
            "optimizer_discount": best.discount,
            "decided_by": "optimizer",
            "decision_factors": [],
        }
        return scenarios, summary, best.policy_issues

    async def _build_agent_insights(self, request: PromotionAnalysisRequest, features: dict[str, Any]) -> list[AgentInsight]:
        agent_keys = []
        if "demand" in features:
            agent_keys.append("demand")
        if "profit" in features:
            agent_keys.append("profit")
        if "cannibalization" in features:
            agent_keys.append("cannibalization")
        if "timing" in features:
            agent_keys.append("timing")
        if "inventory" in features:
            agent_keys.append("inventory")
        if "competitor" in features:
            agent_keys.append("competitor")
        if "weather" in features:
            agent_keys.append("weather")
        if "brand" in features:
            agent_keys.append("brand_dilution")
        if "cannibalization" in features:
            agent_keys.append("basket_affinity")
        return await self.runtime.execute(request, agent_keys, features)

    def _is_policy_compliant(self, scenario: ScenarioResult, request: PromotionAnalysisRequest, features: dict[str, Any]) -> bool:
        candidate_request = PromotionAnalysisRequest(**{**request.model_dump(), "discount": scenario.discount})
        profit = self.analytics.profit_model(candidate_request, scenario.expected_units)
        inventory = self.analytics.inventory_model(candidate_request, scenario.expected_units)
        issues = self.analytics.evaluate_policy(candidate_request, profit, inventory, scenario.downside_risk, scenario.expected_profit)
        return not issues

    def _decision_confidence(
        self,
        scenarios: list[ScenarioResult],
        optimization_summary: dict[str, Any],
        verification: dict[str, Any],
    ) -> float:
        """Calibrated confidence in the recommended decision, derived from how the choice
        actually performs — not an average of static per-agent values. It combines:
          - decisiveness: how far the winning scenario's risk-adjusted score stands above
            the field (a clear peak -> high confidence);
          - downside safety: a lower probability of loss -> higher confidence;
          - profitability: a non-positive expected profit caps confidence;
          - policy clearance: passing the critic on the first try beats a constrained
            retry or a human-review flag.
        """
        if not scenarios:
            return 0.5

        def clamp01(x: float) -> float:
            return max(0.0, min(1.0, x))

        rec = optimization_summary.get("recommended_discount")
        chosen = next(
            (s for s in scenarios if s.discount == rec),
            max(scenarios, key=lambda s: s.weighted_score),
        )

        scores = [s.weighted_score for s in scenarios]
        best = max(scores)
        spread = (best - statistics.fmean(scores)) / (abs(best) or 1.0)
        decisiveness = clamp01(spread * 6.0)

        downside_safety = clamp01(1.0 - chosen.downside_risk)
        profit_ok = 1.0 if chosen.expected_profit > 0 else 0.35

        status = verification.get("status", "accepted")
        policy = 1.0 if status == "accepted" else 0.92 if status == "accepted_after_retry" else 0.55

        raw = 0.25 * decisiveness + 0.50 * downside_safety + 0.25 * profit_ok
        return round(max(0.05, min(0.97, raw * policy)), 2)
