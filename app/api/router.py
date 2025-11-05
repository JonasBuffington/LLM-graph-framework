# app/api/router.py
from uuid import UUID
from fastapi import APIRouter, Depends, status, HTTPException, Response
from app.models.graph import Node, Graph, Edge, NodeUpdate
from app.models.prompt import PromptDocument, PromptUpdate
from app.services.graph_service import GraphService
from app.db.driver import get_db_driver
from neo4j import AsyncDriver
from app.core.exceptions import NodeNotFoundException
from app.services.prompt_service import PromptService

# This single router will handle all API endpoints for the skeleton.
router = APIRouter()
prompt_service = PromptService()

# Dependency provider for the GraphService
def get_prompt_service() -> PromptService:
    return prompt_service

def get_service(
    driver: AsyncDriver = Depends(get_db_driver),
    prompt_service: PromptService = Depends(get_prompt_service)
) -> GraphService:
    return GraphService(driver, prompt_service)

@router.get("/graph", response_model=Graph, tags=["Graph"])
async def get_full_graph(service: GraphService = Depends(get_service)):
    """Retrieves the entire knowledge graph."""
    return await service.get_graph()

@router.post("/nodes", status_code=status.HTTP_201_CREATED, response_model=Node, tags=["Nodes"])
async def add_node(node: Node, service: GraphService = Depends(get_service)):
    """Adds a new node to the graph."""
    return await service.create_node(node)

@router.get("/nodes/{node_id}", response_model=Node, tags=["Nodes"])
async def get_node(node_id: UUID, service: GraphService = Depends(get_service)):
    """Retrieves a single node by its ID."""
    node = await service.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return node

@router.put("/nodes/{node_id}", response_model=Node, tags=["Nodes"])
async def update_node(
    node_id: UUID,
    node_update: NodeUpdate,
    service: GraphService = Depends(get_service)
):
    """Updates properties of a specific node."""
    updated_node = await service.update_node_properties(node_id, node_update)
    if updated_node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return updated_node

@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Nodes"])
async def delete_node(node_id: UUID, service: GraphService = Depends(get_service)):
    """Deletes a node and all its relationships."""
    if not await service.delete_node(node_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/nodes/{node_id}/expand", status_code=status.HTTP_201_CREATED, response_model=Graph, tags=["Nodes"])
async def expand_node(node_id: UUID, service: GraphService = Depends(get_service)):
    """
    Expands a node by generating new, related nodes and edges using an AI model.
    """
    try:
        created_graph = await service.expand_node(node_id)
        if not created_graph.nodes:
             raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI failed to generate valid expansion."
            )
        return created_graph
    except NodeNotFoundException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node to expand not found")

@router.post("/edges", status_code=status.HTTP_201_CREATED, response_model=Edge, tags=["Edges"])
async def add_edge(edge: Edge, service: GraphService = Depends(get_service)):
    """
    Adds a new edge (relationship) between two nodes in the graph.
    Raises 404 if either node does not exist.
    """
    try:
        return await service.create_edge(edge)
    except NodeNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)

@router.delete("/edges", status_code=status.HTTP_204_NO_CONTENT, tags=["Edges"])
async def delete_edge(edge: Edge, service: GraphService = Depends(get_service)):
    """Deletes an edge between two nodes."""
    if not await service.delete_edge(edge):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/prompts/{prompt_key}", response_model=PromptDocument, tags=["Prompts"])
async def get_prompt(
    prompt_key: str,
    prompt_service: PromptService = Depends(get_prompt_service)
):
    """Retrieve a workspace-level prompt template."""
    normalized_key = prompt_service.normalize_key(prompt_key)
    try:
        prompt_text = await prompt_service.get_prompt(normalized_key)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")

    return PromptDocument(key=normalized_key, prompt=prompt_text)

@router.put("/prompts/{prompt_key}", response_model=PromptDocument, tags=["Prompts"])
async def update_prompt(
    prompt_key: str,
    prompt_update: PromptUpdate,
    prompt_service: PromptService = Depends(get_prompt_service)
):
    """Update a workspace-level prompt template."""
    normalized_key = prompt_service.normalize_key(prompt_key)
    try:
        updated_prompt = await prompt_service.upsert_prompt(normalized_key, prompt_update.prompt)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PromptDocument(key=normalized_key, prompt=updated_prompt)
