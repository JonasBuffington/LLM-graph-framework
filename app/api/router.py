# app/api/router.py
from uuid import UUID
from fastapi import APIRouter, Depends, status, HTTPException, Response, Header, Request
from pydantic import BaseModel
from app.models.graph import Node, Graph, Edge, NodeUpdate, NodeCreate
from app.models.prompt import PromptDocument, PromptUpdate
from app.services.graph_service import GraphService
from app.db.driver import get_db_driver
from neo4j import AsyncDriver
from app.core.exceptions import NodeNotFoundException
from app.services.prompt_service import PromptService
from app.core.limiter import limiter
from app.api.idempotency import IdempotentAPIRoute

router = APIRouter()
router.route_class = IdempotentAPIRoute

prompt_service = PromptService()

# --- New Request Model ---
class ActionRequest(BaseModel):
    action_key: str
    selected_node_ids: list[UUID]

# Dependency to extract the User ID from a header
def get_user_id(x_user_id: str = Header(..., description="Client-generated unique ID for the user workspace.")) -> str:
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-User-ID header is required.")
    return x_user_id

def get_prompt_service() -> PromptService:
    return prompt_service

def get_service(
    driver: AsyncDriver = Depends(get_db_driver),
    prompt_service: PromptService = Depends(get_prompt_service)
) -> GraphService:
    return GraphService(driver, prompt_service)

@router.delete("/graph", status_code=status.HTTP_204_NO_CONTENT, tags=["Graph"])
@limiter.limit("10/minute")
async def clear_workspace(
    request: Request,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    """Deletes all nodes and relationships for the given user's workspace."""
    await service.clear_workspace(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/graph", response_model=Graph, tags=["Graph"])
async def get_full_graph(
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    return await service.get_graph(user_id)

@router.post("/graph/execute-action", status_code=status.HTTP_201_CREATED, response_model=Graph, tags=["Graph Actions"])
@limiter.limit("15/minute")
async def execute_action(
    request: Request,
    action_request: ActionRequest,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    """Executes a complex, prompt-driven action on the graph."""
    try:
        created_graph = await service.execute_ai_action(
            action_request.action_key, action_request.selected_node_ids, user_id
        )
        if not created_graph.nodes and not created_graph.edges:
             raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI failed to generate a valid graph modification."
            )
        return created_graph
    except NodeNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/nodes", status_code=status.HTTP_201_CREATED, response_model=Node, tags=["Nodes"])
@limiter.limit("60/minute")
async def add_node(
    request: Request,
    node_data: NodeCreate,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    return await service.create_node(node_data, user_id)

@router.get("/nodes/{node_id}", response_model=Node, tags=["Nodes"])
@limiter.limit("200/minute")
async def get_node(
    request: Request,
    node_id: UUID,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    node = await service.get_node(node_id, user_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return node

@router.put("/nodes/{node_id}", response_model=Node, tags=["Nodes"])
@limiter.limit("60/minute")
async def update_node(
    request: Request,
    node_id: UUID,
    node_update: NodeUpdate,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    updated_node = await service.update_node_properties(node_id, node_update, user_id)
    if updated_node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return updated_node

@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Nodes"])
@limiter.limit("60/minute")
async def delete_node(
    request: Request,
    node_id: UUID,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    if not await service.delete_node(node_id, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/edges", status_code=status.HTTP_201_CREATED, response_model=Edge, tags=["Edges"])
@limiter.limit("120/minute")
async def add_edge(
    request: Request,
    edge: Edge,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    try:
        return await service.create_edge(edge, user_id)
    except NodeNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)

@router.delete("/edges", status_code=status.HTTP_204_NO_CONTENT, tags=["Edges"])
@limiter.limit("120/minute")
async def delete_edge(
    request: Request,
    edge: Edge,
    user_id: str = Depends(get_user_id),
    service: GraphService = Depends(get_service)
):
    if not await service.delete_edge(edge, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/prompts/{prompt_key}", response_model=PromptDocument, tags=["Prompts"])
async def get_prompt(
    prompt_key: str,
    user_id: str = Depends(get_user_id),
    prompt_service: PromptService = Depends(get_prompt_service)
):
    normalized_key = prompt_service.normalize_key(prompt_key)
    try:
        prompt_text = await prompt_service.get_prompt(normalized_key, user_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    return PromptDocument(key=normalized_key, prompt=prompt_text)

@router.put("/prompts/{prompt_key}", response_model=PromptDocument, tags=["Prompts"])
async def update_prompt(
    prompt_key: str,
    prompt_update: PromptUpdate,
    user_id: str = Depends(get_user_id),
    prompt_service: PromptService = Depends(get_prompt_service)
):
    normalized_key = prompt_service.normalize_key(prompt_key)
    try:
        updated_prompt = await prompt_service.upsert_prompt(normalized_key, prompt_update.prompt, user_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return PromptDocument(key=normalized_key, prompt=updated_prompt)