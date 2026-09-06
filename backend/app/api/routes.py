from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_store
from app.domain.route import RouteShape, RouteSummary
from app.services.state_store import StateStore

router = APIRouter(prefix="/routes", tags=["routes"])


@router.get("", response_model=list[RouteSummary])
def list_routes(store: StateStore = Depends(get_store)) -> list[RouteSummary]:
    return store.list_routes()


@router.get("/{route_id}/shape", response_model=RouteShape)
def get_route_shape(
    route_id: str,
    direction_id: int = Query(default=0, alias="directionId", ge=0, le=1),
    store: StateStore = Depends(get_store),
) -> RouteShape:
    shape = store.route_shape(route_id, direction_id)
    if shape is None:
        raise HTTPException(status_code=404, detail="Route shape not found")
    return shape
