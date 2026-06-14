import json

from app.db.sqlite import save_run
from app.models.schemas import (
    OptimizationSummary,
    PromotionAnalysisRequest,
    PromotionAnalysisResponse,
    PromotionMetrics,
    VerificationResult,
)
from app.services.scenarios import build_request_from_seed
from app.services.seed_repository import SeedRepository
from app.services.swarm import LangGraphSwarmWorkflow


class PromotionManager:
    def __init__(self) -> None:
        self.workflow = LangGraphSwarmWorkflow()
        self.seed_repository = SeedRepository()

    async def analyze(
        self,
        request: PromotionAnalysisRequest,
    ) -> PromotionAnalysisResponse:
        workflow_state = await self.workflow.invoke(request)
        selected_agents = workflow_state["selected_agents"]
        insights = workflow_state["agent_insights"]
        debate_summary = workflow_state["debate_summary"]
        confidence = workflow_state["confidence"]
        scenarios = workflow_state["scenarios"]
        recommendation = workflow_state["recommendation"]
        memory = workflow_state["memory"]

        metrics = PromotionMetrics(
            projected_lift=self._metric(insights, "DemandAgent", "projected_lift_pct"),
            incremental_profit=self._metric(insights, "ProfitabilityAgent", "expected_profit"),
            cannibalization_risk=self._risk_band(
                self._metric(insights, "CannibalizationAgent", "substitution_rate")
            ),
            inventory_risk=self._inventory_risk_band(
                self._metric(insights, "InventoryRiskAgent", "stockout_probability")
            ),
            timing_score=self._metric(insights, "TimingAgent", "timing_score"),
        )

        optimization = OptimizationSummary(**workflow_state["optimization_summary"])
        verification = VerificationResult(**workflow_state["verification"])

        payload = {
            "recommendation": recommendation,
            "confidence": confidence,
            "metrics": metrics.model_dump(),
            "optimization": optimization.model_dump(),
            "verification": verification.model_dump(),
            "agent_insights": [item.model_dump() for item in insights],
            "scenarios": [item.model_dump() for item in scenarios],
            "debate_summary": debate_summary,
            "selected_agents": selected_agents,
            "data_inventory": memory.data_inventory,
            "planning_trace": memory.plan,
            "narrative": memory.narrative,
            "decision": memory.decision,
        }

        execution_id = save_run(
            product=request.product,
            category=request.category,
            discount=request.discount,
            timing=request.timing,
            recommendation=recommendation,
            confidence=confidence,
            payload=payload,
        )

        return PromotionAnalysisResponse(
            recommendation=recommendation,
            confidence=confidence,
            metrics=metrics,
            optimization=optimization,
            verification=verification,
            agent_insights=insights,
            scenarios=scenarios,
            debate_summary=debate_summary,
            data_inventory=memory.data_inventory,
            planning_trace=memory.plan,
            narrative=memory.narrative,
            execution_id=execution_id,
        )

    def get_workflow_graph(self) -> dict:
        return self.workflow.describe()

    def build_seed_request(self) -> PromotionAnalysisRequest:
        # The baseline product (the seed as shipped) is scenario s1, so reuse the single
        # shared builder rather than reconstructing the request here.
        with self.seed_repository.path.open() as infile:
            return build_request_from_seed(json.load(infile))

    def _metric(self, insights: list, agent_name: str, key: str) -> float:
        for insight in insights:
            if insight.agent == agent_name:
                return float(insight.metrics.get(key, 0.0))
        return 0.0

    def _risk_band(self, value: float) -> str:
        if value >= 12:
            return "high"
        if value >= 6:
            return "medium"
        return "low"

    def _inventory_risk_band(self, value: float) -> str:
        if value >= 0.30:
            return "high"
        if value >= 0.15:
            return "medium"
        return "low"
