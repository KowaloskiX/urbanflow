from app.domain.common import ApiModel


class Scenario(ApiModel):
    id: str
    name: str
    description: str
    active: bool = False


class ScenarioActivationResponse(ApiModel):
    scenario: Scenario
    target_vehicle_id: str | None = None
    recommendation_id: str | None = None
