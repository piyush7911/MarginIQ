from fastapi import APIRouter, HTTPException

from app.models.schemas import PromotionAnalysisRequest, PromotionAnalysisResponse
from app.services.promotion_manager import PromotionManager
from app.services.scenarios import get_scenario, list_scenarios


router = APIRouter()
promotion_manager = PromotionManager()


@router.post("/analyze-promotion", response_model=PromotionAnalysisResponse)
async def analyze_promotion(
    request: PromotionAnalysisRequest,
) -> PromotionAnalysisResponse:
    return await promotion_manager.analyze(request)


@router.post("/analyze-seed", response_model=PromotionAnalysisResponse)
async def analyze_seed() -> PromotionAnalysisResponse:
    request = promotion_manager.build_seed_request()
    return await promotion_manager.analyze(request)


@router.get("/scenarios")
async def scenarios() -> dict:
    """The six demo scenarios with their known-correct expected directions."""
    return {"scenarios": list_scenarios()}


@router.post("/scenarios/{key}/analyze", response_model=PromotionAnalysisResponse)
async def analyze_scenario(key: str) -> PromotionAnalysisResponse:
    """Run MarginIQ on one of the six demo scenarios (e.g. 's1' … 's6')."""
    scenario = get_scenario(key)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{key}'.")
    return await promotion_manager.analyze(scenario.build_request())


@router.get("/workflow-graph")
async def workflow_graph() -> dict:
    return promotion_manager.get_workflow_graph()
