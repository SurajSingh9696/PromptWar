from pydantic import BaseModel, Field, field_validator
from typing import Optional, List

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    context: Optional[dict] = Field(default_factory=dict)

class ChatResponse(BaseModel):
    reply: str
    suggested_followups: List[str] = Field(default_factory=list)
    source: Optional[str] = "ai"  # 'local' or 'ai'

class EligibilityRequest(BaseModel):
    age: int = Field(..., ge=0, le=150)
    citizen: bool
    state: str = Field(..., min_length=2, max_length=2)

    @field_validator("state")
    def state_must_be_uppercase(cls, v: str) -> str:
        return v.upper()

class EligibilityResponse(BaseModel):
    eligible: bool
    reasons: List[str]
    next_steps: List[str]
