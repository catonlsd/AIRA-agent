from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class AiraXStep(BaseModel):
    id: int
    title: str
    description: str
    status: str = "pending"  # pending, running, completed, failed
    assigned_agent: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None


class AiraXState(BaseModel):
    user_goal: str
    current_step: Optional[int] = None

    plan: List[AiraXStep] = Field(default_factory=list)

    messages: List[Dict[str, Any]] = Field(default_factory=list)
    tool_outputs: List[Dict[str, Any]] = Field(default_factory=list)
    execution_outputs: List[Dict[str, Any]] = Field(default_factory=list)

    memory: Dict[str, Any] = Field(default_factory=dict)

    decision: Optional[str] = None
    final_answer: Optional[str] = None

    retry_count: int = 0
    max_retries: int = 3

    status: str = "initialized"  # initialized, planning, executing, validating, completed, failed