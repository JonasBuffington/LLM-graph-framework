# app/services/graph_service.py
import asyncio
from uuid import UUID
from neo4j import AsyncDriver
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

    async def create_node(self, node_data: Node) -> Node:
        embedding_text = _get_embedding_text_for_node(node_data)
        node_data.embedding = await self.embedding_service.get_embedding(embedding_text)
        return await self.repo.add_node(node_data)

    async def get_graph(self) -> Graph:
        return await self.repo.get_full_graph()

    async def create_edge(self, edge_data: Edge) -> Edge:
        return await self.repo.add_edge(edge_data)

    async def update_node_properties(self, node_id: UUID, node_update: NodeUpdate) -> Node | None:
        return await self.repo.update_node(node_id, node_update)
    
    async def get_node(self, node_id: UUID) -> Node | None:
        return await self.repo.get_node_by_id(node_id)

    async def delete_node(self, node_id: UUID) -> bool:
        return await self.repo.delete_node_by_id(node_id)

    async def delete_edge(self, edge_data: Edge) -> bool:
        return await self.repo.delete_edge(edge_data)

    async def expand_node(self, node_id: UUID) -> Graph:
        source_node = await self.repo.get_node_by_id(node_id)
        if not source_node:
            raise NodeNotFoundException()

        if not source_node.embedding:
            embedding_text = _get_embedding_text_for_node(source_node)
            source_node.embedding = await self.embedding_service.get_embedding(embedding_text)

        structural_nodes = await self.repo.get_1_hop_neighbors(node_id)
        
        excluded_ids = {n.id for n in structural_nodes}
        excluded_ids.add(source_node.id)
        
        semantic_nodes = await self.repo.find_semantically_similar_nodes(
            query_vector=source_node.embedding,
            excluded_node_ids=list(excluded_ids),
            threshold=SIMILARITY_THRESHOLD,
            limit=MAX_SEMANTIC_CANDIDATES
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

        new_nodes, new_edges = await self.ai_service.generate_expansion(source_node, context=context_str)

        if not new_nodes:
            return Graph(nodes=[], edges=[])

        await asyncio.gather(
            *[self.create_node(node) for node in new_nodes]
        )
        
        await asyncio.gather(
            *[self.repo.add_edge(edge) for edge in new_edges]
        )

        return Graph(nodes=new_nodes, edges=new_edges)
