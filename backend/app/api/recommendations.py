from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_store
from app.domain.recommendation import (
    DismissRecommendationRequest,
    Recommendation,
    RecommendationStatus,
)
from app.services.live_updates import live_updates
from app.services.state_store import StateStore

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=list[Recommendation])
def list_recommendations(
    status: RecommendationStatus | None = Query(default=None),
    store: StateStore = Depends(get_store),
) -> list[Recommendation]:
    recommendations = list(store.recommendations.values())
    if status:
        recommendations = [item for item in recommendations if item.status == status]
    return recommendations


@router.get("/{recommendation_id}", response_model=Recommendation)
def get_recommendation(
    recommendation_id: str,
    store: StateStore = Depends(get_store),
) -> Recommendation:
    recommendation = store.recommendations.get(recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return recommendation


@router.post("/{recommendation_id}/dismiss", response_model=Recommendation)
async def dismiss_recommendation(
    recommendation_id: str,
    body: DismissRecommendationRequest,
    store: StateStore = Depends(get_store),
) -> Recommendation:
    recommendation = store.dismiss_recommendation(recommendation_id, body.reason)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    await live_updates.publish(
        "recommendation.updated",
        recommendation.model_dump(mode="json", by_alias=True),
    )
    return recommendation
