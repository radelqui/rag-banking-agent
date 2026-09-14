from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    pregunta: str = Field(min_length=1, max_length=4000)


class HealthResponse(BaseModel):
    status: str
