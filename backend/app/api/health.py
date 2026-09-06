from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.dependencies import get_store
from app.domain.common import ApiModel
from app.services.state_store import StateStore

router = APIRouter(tags=["health"])


class HealthResponse(ApiModel):
    status: str
    mode: str
    sources: dict[str, str]
    last_realtime_update: datetime


@router.get("/health", response_model=HealthResponse)
def health(store: StateStore = Depends(get_store)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        mode=store.settings.app_mode,
        sources=store.source_health,
        last_realtime_update=store.last_realtime_update,
    )
