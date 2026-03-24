from pydantic import BaseModel, Field as PydanticField
from typing import Optional, List, Dict, Any, Union, Literal, Annotated
from datetime import datetime
from app.models.flow import NodeType, FlowStatus, FlowRunStatus, EdgeType


class FlowBase(BaseModel):
    name: str
    status: FlowStatus
    priority: int = PydanticField(default=50)
    message_priority: int = PydanticField(default=50)
    priority_over_autoreply: bool = PydanticField(default=True)
    timeout_minutes: Optional[int] = PydanticField(default=1440)
    phone_ids: List[int] = PydanticField(default_factory=list)


# --- Node Data Schemas ---
class FlowNodeDataBase(BaseModel):
    model_config = {"extra": "allow"}

class StartNodeData(FlowNodeDataBase):
    trigger_type: str  # e.g., "any", "equals"
    value: Optional[str] = None

class ConditionNodeData(FlowNodeDataBase):
    operator: str # e.g., "equals", "greater_than"
    value: str

class MessageSchedule(BaseModel):
    type: str # e.g., "immediate", "delay"
    delay_seconds: Optional[int] = None

class MessageNodeData(FlowNodeDataBase):
    message_type: str # e.g., "static"
    text: str
    schedule: MessageSchedule

class EndNodeData(FlowNodeDataBase):
    pass


# --- Discriminated Union for Nodes ---
# This ensures Pydantic automatically validates the correct data layout based on node_type!

class FlowNodeStart(BaseModel):
    node_id: str
    node_type: Literal[NodeType.START]
    node_data: StartNodeData

class FlowNodeCondition(BaseModel):
    node_id: str
    node_type: Literal[NodeType.CONDITION]
    node_data: ConditionNodeData

class FlowNodeMessage(BaseModel):
    node_id: str
    node_type: Literal[NodeType.MESSAGE]
    node_data: MessageNodeData

class FlowNodeEnd(BaseModel):
    node_id: str
    node_type: Literal[NodeType.END]
    node_data: Optional[Dict[str, Any]] = PydanticField(default_factory=dict)

# Annotated Union uses the 'node_type' field exactly like a switch statement
FlowNodeBase = Annotated[
    Union[FlowNodeStart, FlowNodeCondition, FlowNodeMessage, FlowNodeEnd],
    PydanticField(discriminator="node_type")
]


# --- Edges & Wrapping Schemas ---

class FlowEdgeBase(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: EdgeType
    edge_data: Optional[Dict[str, Any]] = PydanticField(default_factory=dict)


class FlowCreate(FlowBase):
    nodes: List[FlowNodeBase]
    edges: List[FlowEdgeBase]

class FlowUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[FlowStatus] = None
    priority: Optional[int] = None
    message_priority: Optional[int] = None
    priority_over_autoreply: Optional[bool] = None
    timeout_minutes: Optional[int] = None
    phone_ids: Optional[List[int]] = None
    nodes: Optional[List[FlowNodeBase]] = None
    edges: Optional[List[FlowEdgeBase]] = None

class FlowListRead(FlowBase):
    id: int
    created_at: datetime
    updated_at: datetime

class FlowRead(FlowListRead):
    nodes: List[FlowNodeBase]
    edges: List[FlowEdgeBase]

