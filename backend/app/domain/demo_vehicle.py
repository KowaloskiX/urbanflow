from pydantic import Field

from app.domain.common import ApiModel


class CreateDemoVehicleRequest(ApiModel):
    route_id: str
    direction_id: int | None = Field(default=None, ge=0, le=1)
    capacity: int = Field(default=202, gt=0)
    simulation_speed: int = Field(default=5, gt=0, le=100)
