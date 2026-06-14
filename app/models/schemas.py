from typing import Literal, Optional

from pydantic import BaseModel, Field


class PromotionAnalysisRequest(BaseModel):
    sku: Optional[str] = None
    product: str = Field(..., min_length=2)
    category: str = Field(default="general")
    discount: int = Field(..., ge=0, le=90)
    discount_bounds: list[int] = Field(default_factory=lambda: [0, 45], min_length=2, max_length=2)
    timing: str = Field(default="next_week")
    base_price: float = Field(default=10.0, gt=0)
    unit_cost: float = Field(default=6.0, ge=0)
    inventory_units: int = Field(default=1000, ge=0)
    seasonal_context: str = Field(default="standard")
    risk_policy: dict = Field(default_factory=dict)
    context_data: dict = Field(default_factory=dict)


class AgentInsight(BaseModel):
    agent: str
    summary: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    score: float = Field(..., ge=-1.0, le=1.0)
    metrics: dict = Field(default_factory=dict)


class ScenarioResult(BaseModel):
    discount: int
    expected_units: float
    expected_revenue: float
    expected_profit: float
    profit_low: float
    profit_high: float
    downside_risk: float = Field(..., ge=0.0, le=1.0)
    risk_outlook: str
    weighted_score: float


class PromotionMetrics(BaseModel):
    projected_lift: float
    incremental_profit: float
    cannibalization_risk: Literal["low", "medium", "high"]
    inventory_risk: Literal["low", "medium", "high"]
    timing_score: float


class OptimizationSummary(BaseModel):
    requested_discount: int
    recommended_discount: int
    expected_profit: float
    profit_confidence_interval: list[float]
    downside_risk: float
    cvar_10: float
    rationale: str
    decided_by: str = "optimizer"
    optimizer_discount: Optional[int] = None
    decision_factors: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    accepted: bool
    status: str = "accepted"
    critic_summary: str
    issues: list[str] = Field(default_factory=list)
    grounding_source: str = "Foundry IQ"


class PromotionAnalysisResponse(BaseModel):
    recommendation: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    metrics: PromotionMetrics
    optimization: OptimizationSummary
    verification: VerificationResult
    agent_insights: list[AgentInsight]
    scenarios: list[ScenarioResult]
    debate_summary: list[str]
    data_inventory: dict = Field(default_factory=dict)
    planning_trace: dict = Field(default_factory=dict)
    narrative: list[str] = Field(default_factory=list)
    execution_id: int
