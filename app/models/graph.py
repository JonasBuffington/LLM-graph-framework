# app/models/graph.py
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

class Node(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str
    embedding: list[float] | None = Field(default=None, repr=False)

class Edge(BaseModel):
    source_id: UUID
    target_id: UUID
    label: str

class Graph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]

class NodeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None