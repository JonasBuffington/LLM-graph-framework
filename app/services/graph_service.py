# app/services/graph_service.py
from uuid import UUID
import asyncio
from neo4j import AsyncDriver
from neo4j.exceptions import SessionExpired, ServiceUnavailable
from app.models.graph import Node, Graph, Edge, NodeUpdate
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

    async def create_node(self, node_data: Node, user_id: str) -> Node:
        node_data.userId = user_id
        await self._ensure_embedding(node_data)
        return await self._with_retry(self.repo.add_node, node_data)

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

    async def expand_node(self, node_id: UUID, user_id: str) -> Graph:
        source_node = await self._with_retry(self.repo.get_node_by_id, node_id, user_id)
        if not source_node:
            raise NodeNotFoundException()

        await self._ensure_embedding(source_node)

        structural_nodes = await self._with_retry(self.repo.get_1_hop_neighbors, node_id, user_id)
        
        excluded_ids = {n.id for n in structural_nodes}
        excluded_ids.add(source_node.id)
        
        semantic_nodes = await self._with_retry(
            self.repo.find_semantically_similar_nodes,
            source_node.embedding,
            list(excluded_ids),
            user_id,
            SIMILARITY_THRESHOLD,
            MAX_SEMANTIC_CANDIDATES,
        )

        final_context_nodes = structural_nodes + semantic_nodes
        
        context_str = ""
        if final_context_nodes:
            context_items = "\n".join([f"- {n.name}: {n.description}" for n in final_context_nodes])
            context_str = (
                "To avoid creating duplicate concepts, be aware of these "
                "semantically similar or directly related concepts that already exist in the graph:\n"
                f"{context_items}"
            )

        new_nodes, new_edges = await self.ai_service.generate_expansion(source_node, user_id, context=context_str)

        if not new_nodes:
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