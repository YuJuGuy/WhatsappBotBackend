from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum


class NodeType(str, Enum):
    START = "start"
    END = "end"
    MESSAGE = "message"
    CONDITION = "condition"
    OPTIONS = "options"
    ACTION_TICKET = "action_ticket"
    WAIT_MESSAGE = "wait_message"
    ACTION_XLSX_SEARCH = "action_xlsx_search"


class FlowRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class EdgeType(str, Enum):
    DEFAULT = "default"
    TRUE = "true"
    FALSE = "false"

class FlowPhoneLink(SQLModel, table=True):
    flow_id: int = Field(foreign_key="flow.id", primary_key=True, ondelete="CASCADE")
    phone_id: int = Field(foreign_key="phone.id", primary_key=True, ondelete="CASCADE")

class Flow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str
    is_active: bool = Field(default=False)
    priority: int = Field(default=50)
    message_priority: int = Field(default=50)
    priority_over_autoreply: bool = Field(default=True)
    timeout_minutes: Optional[int] = Field(default=1440)
    share_code: Optional[str] = Field(default=None, max_length=12, index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now, index=True)


from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB

class FlowNode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    flow_id: int = Field(index=True)
    client_node_id: str = Field(index=True)  # Mapped to node_id from frontend (e.g. "node-1")
    node_type: NodeType
    node_data: dict = Field(default_factory=dict, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now, index=True)


class FlowEdge(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    flow_id: int = Field(index=True)
    
    client_edge_id: str = Field(index=True)  # Mapped to edge_id from frontend

    from_node_id: int = Field(index=True, foreign_key="flownode.id")
    to_node_id: int = Field(index=True, foreign_key="flownode.id")
    
    edge_type: EdgeType
    edge_data: dict = Field(default_factory=dict, sa_column=Column(JSONB))
    
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now, index=True)

class FlowRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    flow_id: int = Field(index=True)
    session_id: str = Field(index=True)
    contact_id: str = Field(index=True)
    current_node_id: Optional[int] = Field(default=None, index=True)
    status: FlowRunStatus
    
    session_metadata: dict = Field(default_factory=dict, sa_column=Column(JSONB))
    
    expires_at: Optional[datetime] = Field(default=None, index=True)
    last_processed_message_id: Optional[str] = Field(default=None)
    
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now, index=True)
    