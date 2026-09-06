from pydantic import Field

from app.domain.common import ApiModel


class RouteSummary(ApiModel):
    route_id: str
    short_name: str
    long_name: str
    color: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    vehicle_count: int = 0


class RouteShape(ApiModel):
    type: str = "Feature"
    geometry: dict
    properties: dict
