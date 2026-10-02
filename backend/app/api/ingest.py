"""Ingest for door counters.

Counters are not browsers: they authenticate with `Authorization: Bearer <key>`, one key
per vehicle (see app/services/devices.py). Every response says how much of the batch was
new, so a counter can tell a redelivery from a loss.

After each write the dashboard gets a `vehicle.updated` over the WebSocket — the same
event the simulation loop already publishes, so the frontend needs no change to show it.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_store
from app.domain.occupancy import AnchorIn, IngestResult, PassageBatchIn
from app.domain.recommendation import Recommendation
from app.domain.vehicle import MobilityAids, VehicleState
from app.services.devices import Device
from app.services.live_updates import live_updates
from app.services.occupancy_tracker import IngestOutcome
from app.services.state_store import StateStore, occupancy_status

router = APIRouter(prefix="/ingest", tags=["ingest"])

# `auto_error=False`, so a missing header gets the same 401 as a wrong key instead of
# FastAPI's 403 with a different body.
_bearer = HTTPBearer(auto_error=False)


def get_device(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    store: StateStore = Depends(get_store),
) -> Device:
    device = store.devices.resolve(credentials.credentials) if credentials else None
    if device is None:
        # One message for both cases: a probe with a stolen key must not learn whether
        # it was ever valid.
        raise HTTPException(status_code=401, detail="Unknown or missing device key")
    return device


async def _publish(
    vehicle: VehicleState | None, recommendation: Recommendation | None
) -> None:
    if vehicle is not None:
        await live_updates.publish(
            "vehicle.updated", vehicle.model_dump(mode="json", by_alias=True)
        )
    if recommendation is not None:
        await live_updates.publish(
            "recommendation.created",
            recommendation.model_dump(mode="json", by_alias=True),
        )


def _result(device: Device, outcome: IngestOutcome) -> IngestResult:
    return IngestResult(
        vehicle_id=device.vehicle_id,
        accepted=outcome.accepted,
        duplicates=outcome.duplicates,
        occupancy=outcome.passenger_count,
        level=occupancy_status(outcome.passenger_count / outcome.capacity),
    )


@router.post("/passages", response_model=IngestResult)
async def record_passages(
    body: PassageBatchIn,
    device: Device = Depends(get_device),
    store: StateStore = Depends(get_store),
) -> IngestResult:
    """People crossing the doorway. Deltas, idempotent by `eventId`."""
    outcome = store.occupancy.record_passages(
        device.vehicle_id, device.capacity, body.events
    )
    if outcome.accepted:
        await _publish(*store.apply_counter_update(device.vehicle_id))
    return _result(device, outcome)


@router.post("/anchor", response_model=IngestResult)
async def record_anchor(
    body: AnchorIn,
    device: Device = Depends(get_device),
    store: StateStore = Depends(get_store),
) -> IngestResult:
    """An absolute count — sent at a terminus, where the truth is zero."""
    outcome = store.occupancy.record_anchor(
        device.vehicle_id,
        device.capacity,
        body.occupancy,
        body.observed_at,
        MobilityAids(**body.mobility_aids.model_dump()) if body.mobility_aids else None,
    )
    await _publish(*store.apply_counter_update(device.vehicle_id))
    return _result(device, outcome)
