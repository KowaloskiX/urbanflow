import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    demo_vehicles,
    dispatch,
    health,
    live,
    recommendations,
    routes,
    scenarios,
    vehicles,
)
from app.config import get_settings
from app.integrations.realtime_provider import KrakowRealtimeProvider
from app.services.live_updates import live_updates
from app.services.state_store import StateStore


async def simulation_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(1)
        store: StateStore = app.state.store
        store.refresh_simulations()
        for vehicle in store.vehicles.values():
            if vehicle.is_simulation:
                await live_updates.publish(
                    "vehicle.updated",
                    vehicle.model_dump(mode="json", by_alias=True),
                )


async def realtime_loop(app: FastAPI) -> None:
    settings = get_settings()
    provider = KrakowRealtimeProvider(
        settings.ztp_base_url,
        settings.live_max_age_seconds,
        settings.stale_max_age_seconds,
    )
    app.state.realtime_provider = provider
    try:
        await provider.initialize()
        while True:
            try:
                snapshot = await provider.get_snapshot()
                store: StateStore = app.state.store
                store.apply_realtime_snapshot(snapshot)
                await live_updates.publish(
                    "vehicles.snapshot",
                    {
                        "generatedAt": store.last_realtime_update.isoformat(),
                        "vehicles": [
                            vehicle.model_dump(mode="json", by_alias=True)
                            for vehicle in snapshot.vehicles
                        ],
                    },
                )
            except Exception:
                app.state.store.mark_realtime_failure()
            await asyncio.sleep(settings.realtime_poll_seconds)
    finally:
        await provider.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.store = StateStore(settings)
    tasks = [asyncio.create_task(simulation_loop(app))]
    if settings.realtime_enabled:
        tasks.append(asyncio.create_task(realtime_loop(app)))
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="UrbanFlow API",
    version="0.1.0",
    description="API wspomagania dyspozytora komunikacji miejskiej.",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = "/api/v1"
app.include_router(health.router, prefix=api_prefix)
app.include_router(vehicles.router, prefix=api_prefix)
app.include_router(routes.router, prefix=api_prefix)
app.include_router(recommendations.router, prefix=api_prefix)
app.include_router(dispatch.router, prefix=api_prefix)
app.include_router(scenarios.router, prefix=api_prefix)
app.include_router(demo_vehicles.router, prefix=api_prefix)
app.include_router(live.router, prefix=api_prefix)
