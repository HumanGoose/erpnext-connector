from typing import Any

from pydantic import BaseModel, Field


class ThrottleStatus(BaseModel):
    maximum_available: float = Field(alias="maximumAvailable")
    currently_available: float = Field(alias="currentlyAvailable")
    restore_rate: float = Field(alias="restoreRate")


class QueryCost(BaseModel):
    requested_query_cost: float = Field(alias="requestedQueryCost")
    actual_query_cost: float | None = Field(default=None, alias="actualQueryCost")
    throttle_status: ThrottleStatus = Field(alias="throttleStatus")


class GraphQLExtensions(BaseModel):
    cost: QueryCost


class GraphQLError(BaseModel):
    message: str
    extensions: dict[str, Any] | None = None


class GraphQLResponse(BaseModel):
    data: dict[str, Any] | None = None
    errors: list[GraphQLError] | None = None
    extensions: GraphQLExtensions | None = None


class WebhookHttpEndpoint(BaseModel):
    callback_url: str | None = Field(default=None, alias="callbackUrl")


class WebhookSubscriptionNode(BaseModel):
    id: str
    topic: str
    endpoint: WebhookHttpEndpoint | None = None


class UserError(BaseModel):
    field: list[str] | None = None
    message: str
