from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_store
from app.domain.dispatch import CreateDispatchRequest, Dispatch, ResetResponse
from app.services.live_updates import live_updates
from app.services.state_store import StateStore

router = APIRouter(prefix="/mock-dispatch", tags=["mock dispatch"])


@router.post(
    "/extra-trams", response_model=Dispatch, status_code=status.HTTP_201_CREATED
)
async def create_extra_tram(
    body: CreateDispatchRequest,
    store: StateStore = Depends(get_store),
) -> Dispatch:
    try:
        dispatch = store.create_dispatch(body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await live_updates.publish(
        "dispatch.status_changed", dispatch.model_dump(mode="json", by_alias=True)
    )
    simulated_vehicle = store.vehicles.get(dispatch.vehicle_id)
    if simulated_vehicle:
        await live_updates.publish(
            "vehicle.updated", simulated_vehicle.model_dump(mode="json", by_alias=True)
        )
    return dispatch


@router.get("/extra-trams", response_model=list[Dispatch])
def list_extra_trams(store: StateStore = Depends(get_store)) -> list[Dispatch]:
    store.refresh_simulations()
    return list(store.dispatches.values())


@router.post("/extra-trams/{dispatch_id}/cancel", response_model=Dispatch)
async def cancel_extra_tram(
    dispatch_id: str,
    store: StateStore = Depends(get_store),
) -> Dispatch:
    try:
        dispatch = store.cancel_dispatch(dispatch_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if dispatch is None:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    await live_updates.publish(
        "dispatch.status_changed", dispatch.model_dump(mode="json", by_alias=True)
    )
    return dispatch


@router.post("/reset", response_model=ResetResponse)
def reset_demo(store: StateStore = Depends(get_store)) -> ResetResponse:
    if store.settings.app_mode != "DEMO":
        raise HTTPException(
            status_code=403, detail="Reset is available only in DEMO mode"
        )
    store.reset_demo()
    return ResetResponse()
