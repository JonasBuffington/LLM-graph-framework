# app/services/graph_service.py
from uuid import UUID
import asyncio
from neo4j import AsyncDriver
from neo4j.exceptions import SessionExpired, ServiceUnavailable
from app.models.graph import Node, Graph, Edge, NodeUpdate, NodeCreate
from app.db.repositories.graph_repository import GraphRepository
from app.core.exceptions import NodeNotFoundException
from app.services.ai_service import AIService
from app.services.embedding_service import EmbeddingService
from app.core.rag_config import SIMILARITY_THRESHOLD, MAX_SEMANTIC_CANDIDATES
from app.core.config import settings
from app.services.prompt_service import PromptService

def _get_embedding_text_for_node(node: Node) -> str:
    """Creates a rich, consistent text document for embedding."""
    return (
        f"Concept Name: {node.name}\n"
        f"Description: {node.description}"
    )

class GraphService:
    def __init__(self, driver: AsyncDriver, prompt_service: PromptService | None = None):
        self.repo = GraphRepository(driver)
        self.embedding_service = EmbeddingService(api_key=settings.GEMINI_API_KEY)
        self.prompt_service = prompt_service or PromptService()
        self.ai_service = AIService(
            api_key=settings.GEMINI_API_KEY,
            prompt_service=self.prompt_service
        )
    
    async def clear_workspace(self, user_id: str) -> None:
        """Clears all nodes and edges for a specific user."""
        await self._with_retry(self.repo.delete_all_nodes_for_user, user_id)

    async def create_node(self, node_data: NodeCreate, user_id: str) -> Node:
        node = Node(**node_data.model_dump(), userId=user_id)
        await self._ensure_embedding(node)
        return await self._with_retry(self.repo.add_node, node)

    async def get_graph(self, user_id: str) -> Graph:
        return await self._with_retry(self.repo.get_full_graph, user_id)

    async def create_edge(self, edge_data: Edge, user_id: str) -> Edge:
        return await self._with_retry(self.repo.add_edge, edge_data, user_id)

    async def update_node_properties(self, node_id: UUID, node_update: NodeUpdate, user_id: str) -> Node | None:
        return await self._with_retry(self.repo.update_node, node_id, node_update, user_id)
    
    async def get_node(self, node_id: UUID, user_id: str) -> Node | None:
        return await self._with_retry(self.repo.get_node_by_id, node_id, user_id)

    async def delete_node(self, node_id: UUID, user_id: str) -> bool:
        return await self._with_retry(self.repo.delete_node_by_id, node_id, user_id)

    async def delete_edge(self, edge_data: Edge, user_id: str) -> bool:
        return await self._with_retry(self.repo.delete_edge, edge_data, user_id)

    async def execute_ai_action(self, action_key: str, selected_node_ids: list[UUID], user_id: str) -> Graph:
        if not selected_node_ids:
            return Graph(nodes=[], edges=[])

        source_nodes = [node for node in await asyncio.gather(
            *[self._with_retry(self.repo.get_node_by_id, node_id, user_id) for node_id in selected_node_ids]
        ) if node is not None]

        if not source_nodes:
            raise NodeNotFoundException("None of the selected nodes were found.")

        await asyncio.gather(*[self._ensure_embedding(node) for node in source_nodes])

        # Gather context from all source nodes
        unique_neighbors = {}
        unique_semantic_nodes = {}
        excluded_ids = {n.id for n in source_nodes}

        # Collect 1-hop neighbors for all source nodes
        neighbor_tasks = [self._with_retry(self.repo.get_1_hop_neighbors, node.id, user_id) for node in source_nodes]
        for neighbors in await asyncio.gather(*neighbor_tasks):
            for neighbor in neighbors:
                if neighbor.id not in excluded_ids:
                    unique_neighbors[neighbor.id] = neighbor
        
        excluded_ids.update(unique_neighbors.keys())

        # Collect semantically similar nodes for all source nodes
        semantic_tasks = [
            self._with_retry(
                self.repo.find_semantically_similar_nodes,
                node.embedding, list(excluded_ids), user_id, SIMILARITY_THRESHOLD, MAX_SEMANTIC_CANDIDATES
            ) for node in source_nodes if node.embedding
        ]
        for semantic_results in await asyncio.gather(*semantic_tasks):
            for node in semantic_results:
                if node.id not in excluded_ids:
                    unique_semantic_nodes[node.id] = node

        final_context_nodes = list(unique_neighbors.values()) + list(unique_semantic_nodes.values())
        
        context_str = ""
        if final_context_nodes:
            context_items = "\n".join([f"- {n.name}: {n.description}" for n in final_context_nodes])
            context_str = (
                "To avoid creating duplicate concepts, be aware of these "
                "semantically similar or directly related concepts that already exist in the graph:\n"
                f"{context_items}"
            )

        new_nodes, new_edges = await self.ai_service.generate_graph_modification(
            source_nodes, user_id, action_key, context=context_str
        )

        if not new_nodes and not new_edges:
            return Graph(nodes=[], edges=[])

        for node in new_nodes:
            node.userId = user_id
        await asyncio.gather(*[self._ensure_embedding(node) for node in new_nodes])
        
        await self._with_retry(self.repo.add_subgraph, new_nodes, new_edges)

        return Graph(nodes=new_nodes, edges=new_edges)

    async def _ensure_embedding(self, node: Node) -> Node:
        if not node.embedding:
            embedding_text = _get_embedding_text_for_node(node)
            node.embedding = await self.embedding_service.get_embedding(embedding_text)
        return node

    async def _with_retry(self, func, *args, retries: int = 3, delay: float = 0.5, **kwargs):
        for attempt in range(retries):
            try:
                return await func(*args, **kwargs)
            except (SessionExpired, ServiceUnavailable):
                if attempt + 1 == retries:
                    raise
                await asyncio.sleep(delay * (attempt + 1))