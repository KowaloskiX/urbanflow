from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_store
from app.domain.common import ApiModel
from app.domain.vehicle import VehicleState
from app.services.live_updates import live_updates
from app.services.state_store import StateStore

router = APIRouter(prefix="/demo/overload", tags=["demo overload"])


class StartOverloadRequest(ApiModel):
    vehicle_id: str | None = None


@router.get("", response_model=list[str])
def list_overloaded(store: StateStore = Depends(get_store)) -> list[str]:
    """Vehicles whose occupancy is staged, so the dashboard can label it as such."""
    return list(store.demo_overloads)


@router.post("", response_model=VehicleState, status_code=status.HTTP_201_CREATED)
async def start_overload(
    body: StartOverloadRequest, store: StateStore = Depends(get_store)
) -> VehicleState:
    try:
        vehicle = store.start_demo_overload(body.vehicle_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await live_updates.publish(
        "vehicle.updated", vehicle.model_dump(mode="json", by_alias=True)
    )
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def stop_overload(vehicle_id: str, store: StateStore = Depends(get_store)) -> None:
    if not store.stop_demo_overload(vehicle_id):
        raise HTTPException(status_code=404, detail="Vehicle is not overloaded")
