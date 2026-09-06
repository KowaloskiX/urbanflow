from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_store
from app.domain.scenario import Scenario, ScenarioActivationResponse
from app.services.live_updates import live_updates
from app.services.state_store import StateStore

router = APIRouter(prefix="/demo/scenarios", tags=["demo scenarios"])


@router.get("", response_model=list[Scenario])
def list_scenarios(store: StateStore = Depends(get_store)) -> list[Scenario]:
    return store.scenarios()


@router.post("/{scenario_id}/activate", response_model=ScenarioActivationResponse)
async def activate_scenario(
    scenario_id: str,
    store: StateStore = Depends(get_store),
) -> ScenarioActivationResponse:
    if store.settings.app_mode != "DEMO":
        raise HTTPException(
            status_code=403, detail="Scenarios are available only in DEMO mode"
        )
    result = store.activate_scenario(scenario_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Scenario not found")

    vehicle = store.get_vehicle(result.target_vehicle_id or "")
    if vehicle:
        await live_updates.publish(
            "vehicle.updated", vehicle.model_dump(mode="json", by_alias=True)
        )
    if result.recommendation_id:
        recommendation = store.recommendations[result.recommendation_id]
        await live_updates.publish(
            "recommendation.created",
            recommendation.model_dump(mode="json", by_alias=True),
        )
    return result
