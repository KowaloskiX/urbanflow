from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_store
from app.domain.demo_vehicle import CreateDemoVehicleRequest
from app.domain.vehicle import VehicleState
from app.services.live_updates import live_updates
from app.services.state_store import StateStore

router = APIRouter(prefix="/demo/vehicles", tags=["demo vehicles"])


@router.get("", response_model=list[VehicleState])
def list_demo_vehicles(store: StateStore = Depends(get_store)) -> list[VehicleState]:
    return [vehicle for vehicle in store.list_vehicles() if vehicle.is_simulation]


@router.post("", response_model=VehicleState, status_code=status.HTTP_201_CREATED)
async def create_demo_vehicle(
    body: CreateDemoVehicleRequest,
    store: StateStore = Depends(get_store),
) -> VehicleState:
    try:
        vehicle = store.create_demo_vehicle(body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    await live_updates.publish(
        "vehicle.updated", vehicle.model_dump(mode="json", by_alias=True)
    )
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_demo_vehicle(
    vehicle_id: str, store: StateStore = Depends(get_store)
) -> None:
    if not store.delete_demo_vehicle(vehicle_id):
        raise HTTPException(status_code=404, detail="Demo vehicle not found")
    await live_updates.publish("vehicle.removed", {"vehicleId": vehicle_id})
