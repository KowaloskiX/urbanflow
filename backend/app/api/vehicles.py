from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_store
from app.domain.common import SourceStatus, utc_now
from app.domain.vehicle import (
    Freshness,
    OccupancyStatus,
    VehicleDetails,
    VehicleHistoryPoint,
    VehicleListResponse,
)
from app.services.state_store import StateStore

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    try:
        values = tuple(float(value) for value in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="bbox must contain four numbers"
        ) from exc
    if len(values) != 4:
        raise HTTPException(
            status_code=400, detail="bbox must use minLon,minLat,maxLon,maxLat"
        )
    min_lon, min_lat, max_lon, max_lat = values
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status_code=400, detail="bbox minimums must be smaller than maximums"
        )
    return min_lon, min_lat, max_lon, max_lat


@router.get("", response_model=VehicleListResponse)
def list_vehicles(
    route_id: str | None = Query(default=None, alias="routeId"),
    occupancy_status: OccupancyStatus | None = Query(
        default=None, alias="occupancyStatus"
    ),
    freshness: Freshness | None = None,
    include_simulation: bool = Query(default=True, alias="includeSimulation"),
    bbox: str | None = None,
    store: StateStore = Depends(get_store),
) -> VehicleListResponse:
    bounds = parse_bbox(bbox)
    vehicles = store.list_vehicles()
    if route_id:
        vehicles = [vehicle for vehicle in vehicles if vehicle.route_id == route_id]
    if occupancy_status:
        vehicles = [
            vehicle
            for vehicle in vehicles
            if vehicle.occupancy_status == occupancy_status
        ]
    if freshness:
        vehicles = [vehicle for vehicle in vehicles if vehicle.freshness == freshness]
    if not include_simulation:
        vehicles = [vehicle for vehicle in vehicles if not vehicle.is_simulation]
    if bounds:
        min_lon, min_lat, max_lon, max_lat = bounds
        vehicles = [
            vehicle
            for vehicle in vehicles
            if min_lon <= vehicle.longitude <= max_lon
            and min_lat <= vehicle.latitude <= max_lat
        ]
    occupancy_source_status = {
        "ok": SourceStatus.LIVE,
        "stale": SourceStatus.STALE,
        "offline": SourceStatus.OFFLINE,
    }.get(store.source_health["occupancy"], SourceStatus.OFFLINE)
    return VehicleListResponse(
        generated_at=utc_now(),
        vehicles=vehicles,
        source_health={
            "gtfsRealtime": SourceStatus.LIVE,
            "occupancy": occupancy_source_status,
        },
    )


@router.get("/{vehicle_id}", response_model=VehicleDetails)
def get_vehicle(
    vehicle_id: str, store: StateStore = Depends(get_store)
) -> VehicleDetails:
    vehicle = store.get_vehicle(vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    shape = store.route_shape(vehicle.route_id, vehicle.direction_id)
    return VehicleDetails(
        vehicle=vehicle,
        history=store.vehicle_history(vehicle_id, 30),
        route=shape.model_dump(by_alias=True) if shape else {},
    )


@router.get("/{vehicle_id}/history", response_model=list[VehicleHistoryPoint])
def get_vehicle_history(
    vehicle_id: str,
    minutes: int = Query(default=30, ge=1, le=60),
    store: StateStore = Depends(get_store),
) -> list[VehicleHistoryPoint]:
    if store.get_vehicle(vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return store.vehicle_history(vehicle_id, minutes)
