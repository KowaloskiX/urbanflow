from fastapi import Request

from app.services.state_store import StateStore


def get_store(request: Request) -> StateStore:
    return request.app.state.store
