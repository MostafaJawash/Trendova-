from math import ceil
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', from_attributes=True)

class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[Any] = Field(default_factory=list)

class ErrorResponse(BaseModel):
    error: ErrorBody

ERROR_RESPONSES = {code: {'model': ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 429, 503)}

def paginate(items, total, page, limit):
    return {'items': items, 'total': total, 'page': page, 'limit': limit, 'pages': ceil(total/limit) if total else 0}
