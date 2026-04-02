from pydantic import BaseModel, Field as PydanticField
from typing import Optional, List, Dict, Any, Union, Literal, Annotated
from datetime import datetime
from app.models.flow import NodeType, FlowRunStatus, EdgeType


class FlowBase(BaseModel):
    name: str
    is_active: bool = PydanticField(default=False)
    priority: int = PydanticField(default=50)
    message_priority: int = PydanticField(default=50)
    priority_over_autoreply: bool = PydanticField(default=True)
    timeout_minutes: Optional[int] = PydanticField(default=1440)
    phone_ids: List[int] = PydanticField(default_factory=list)


# --- Node Data Schemas ---
class FlowNodeDataBase(BaseModel):
    model_config = {"extra": "allow"}

class StartNodeData(FlowNodeDataBase):
    trigger_type: Literal["any", "equals", "contains", "contains_any"]
    value: Optional[str] = None

class ConditionNodeData(FlowNodeDataBase):
    operator: Literal["equals", "contains", "contains_any"]
    value: str

class FlowOptionCondition(BaseModel):
    id: str
    operator: Literal["equals", "contains", "contains_any"]
    value: str

class OptionsNodeData(FlowNodeDataBase):
    options: List[FlowOptionCondition] = PydanticField(default_factory=list)

class MessageSchedule(BaseModel):
    type: Literal["immediate", "delay"]
    delay_seconds: Optional[int] = None

class MessageNodeData(FlowNodeDataBase):
    message_type: Literal["static"]
    text: str
    schedule: MessageSchedule

class EndNodeData(FlowNodeDataBase):
    pass

class ActionTicketNodeData(FlowNodeDataBase):
    category_id: int
    assignee_id: Optional[int] = None

class WaitMessageNodeData(FlowNodeDataBase):
    pass

class ActionXlsxSearchData(FlowNodeDataBase):
    file_id: Optional[int] = None
    search_column: str
    search_value: Optional[str] = None
    result_column: str
    variable_name: str


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

class FlowNodeOptions(BaseModel):
    node_id: str
    node_type: Literal[NodeType.OPTIONS]
    node_data: OptionsNodeData

class FlowNodeMessage(BaseModel):
    node_id: str
    node_type: Literal[NodeType.MESSAGE]
    node_data: MessageNodeData

class FlowNodeActionTicket(BaseModel):
    node_id: str
    node_type: Literal[NodeType.ACTION_TICKET]
    node_data: ActionTicketNodeData

class FlowNodeWaitMessage(BaseModel):
    node_id: str
    node_type: Literal[NodeType.WAIT_MESSAGE]
    node_data: Optional[Dict[str, Any]] = PydanticField(default_factory=dict)

class FlowNodeEnd(BaseModel):
    node_id: str
    node_type: Literal[NodeType.END]
    node_data: Optional[Dict[str, Any]] = PydanticField(default_factory=dict)

class FlowNodeActionXlsxSearch(BaseModel):
    node_id: str
    node_type: Literal[NodeType.ACTION_XLSX_SEARCH]
    node_data: ActionXlsxSearchData


# Annotated Union uses the 'node_type' field exactly like a switch statement
FlowNodeBase = Annotated[
    Union[
        FlowNodeStart, 
        FlowNodeCondition, 
        FlowNodeOptions, 
        FlowNodeMessage, 
        FlowNodeActionTicket, 
        FlowNodeWaitMessage, 
        FlowNodeActionXlsxSearch,
        FlowNodeEnd
    ],
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
    is_active: Optional[bool] = None
    priority: Optional[int] = None
    message_priority: Optional[int] = None
    priority_over_autoreply: Optional[bool] = None
    timeout_minutes: Optional[int] = None
    phone_ids: Optional[List[int]] = None
    nodes: Optional[List[FlowNodeBase]] = None
    edges: Optional[List[FlowEdgeBase]] = None

class FlowListRead(FlowBase):
    id: int
    share_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class FlowRead(FlowListRead):
    nodes: List[FlowNodeBase]
    edges: List[FlowEdgeBase]

