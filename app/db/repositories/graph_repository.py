# app/db/repositories/graph_repository.py
from uuid import UUID
from neo4j import AsyncDriver
from app.models.graph import Node, Edge, Graph, NodeUpdate
from app.core.exceptions import NodeNotFoundException

class GraphRepository:
    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def delete_all_nodes_for_user(self, user_id: str) -> int:
        """
        Deletes all nodes (and their relationships) for a given user.
        Returns the number of nodes deleted.
        """
        
        query = "MATCH (n:Concept {userId: $userId}) DETACH DELETE n RETURN count(n) as deleted_count"
        async with self.driver.session() as session:
            result = await session.run(query, {"userId": user_id})
            record = await result.single()
            return record["deleted_count"] if record else 0

    async def get_full_graph(self, user_id: str) -> Graph:
        query = """
        MATCH (n:Concept {userId: $userId})
        OPTIONAL MATCH (n)-[r]->(m:Concept {userId: $userId})
        RETURN collect(DISTINCT n) as nodes, collect(DISTINCT r) as relationships
        """
        async with self.driver.session() as session:
            result = await session.run(query, {"userId": user_id})
            record = await result.single()
            # ... (rest of the function is unchanged)
            if not record or not record["nodes"]:
                return Graph(nodes=[], edges=[])

            nodes_data = record["nodes"]
            rels_data = record["relationships"]

            nodes = [Node.model_validate(node_props) for node_props in nodes_data]

            edges = []
            for rel in rels_data:
                if rel is None:
                    continue
                start_node_id = rel.start_node["id"]
                end_node_id = rel.end_node["id"]
                edges.append(
                    Edge(
                        source_id=start_node_id,
                        target_id=end_node_id,
                        label=rel.type
                    )
                )

            return Graph(nodes=nodes, edges=edges)

    async def add_edge(self, edge: Edge, user_id: str) -> Edge:
        query = """
        MATCH (a:Concept {id: $source_id, userId: $userId})
        MATCH (b:Concept {id: $target_id, userId: $userId})
        CALL apoc.create.relationship(a, $rel_type, {}, b) YIELD rel
        RETURN type(rel) as label
        """
        async with self.driver.session() as session:
            result = await session.run(query, {
                "source_id": str(edge.source_id),
                "target_id": str(edge.target_id),
                "rel_type": edge.label,
                "userId": user_id
            })
            if await result.single() is None:
                raise NodeNotFoundException("One or both nodes for the edge not found in this workspace.")
            return edge
    
    async def add_subgraph(self, nodes: list[Node], edges: list[Edge]) -> None:
        nodes_payload = [
            {
                "id": str(node.id),
                "name": node.name,
                "description": node.description,
                "embedding": node.embedding,
                "userId": node.userId,
            }
            for node in nodes
        ]
        # ... (rest of the function is unchanged)
        edges_payload = [
            {
                "source_id": str(edge.source_id),
                "target_id": str(edge.target_id),
                "label": edge.label,
            }
            for edge in edges
        ]

        async with self.driver.session() as session:
            await session.execute_write(
                self._create_subgraph,
                nodes_payload,
                edges_payload,
            )

    @staticmethod
    async def _create_subgraph(tx, nodes_payload, edges_payload):
        if nodes_payload:
            node_query = """
            UNWIND $nodes AS nodeData
            MERGE (n:Concept {id: nodeData.id})
            ON CREATE SET
                n.name = nodeData.name,
                n.description = nodeData.description,
                n.embedding = nodeData.embedding,
                n.userId = nodeData.userId
            """
            node_result = await tx.run(node_query, {"nodes": nodes_payload})
            await node_result.consume()
        # ... (edge query is unchanged)
        if edges_payload:
            edge_query = """
            UNWIND $edges AS edgeData
            MATCH (source:Concept {id: edgeData.source_id})
            MATCH (target:Concept {id: edgeData.target_id})
            CALL apoc.create.relationship(source, edgeData.label, {}, target) YIELD rel
            RETURN count(rel) as created_edges
            """
            edge_result = await tx.run(edge_query, {"edges": edges_payload})
            await edge_result.consume()

    async def update_node(self, node_id: UUID, node_update: NodeUpdate, user_id: str) -> Node | None:
        props_to_update = node_update.model_dump(exclude_unset=True)

        if not props_to_update:
            return await self.get_node_by_id(node_id, user_id)

        query = """
        MATCH (n:Concept {id: $node_id, userId: $userId})
        SET n += $props
        RETURN n
        """
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id), "props": props_to_update, "userId": user_id})
            record = await result.single()
            return Node.model_validate(record["n"]) if record else None

    async def add_node(self, node: Node) -> Node:
        query = """
        MERGE (n:Concept {id: $node_id})
        ON CREATE SET
            n.name = $name,
            n.description = $description,
            n.embedding = $embedding,
            n.userId = $userId
        RETURN n
        """
        async with self.driver.session() as session:
            result = await session.run(query, {
                "node_id": str(node.id),
                "name": node.name,
                "description": node.description,
                "embedding": node.embedding,
                "userId": node.userId,
            })
            record = await result.single()
            return Node.model_validate(record["n"])
    
    async def get_node_by_id(self, node_id: UUID, user_id: str) -> Node | None:
        query = "MATCH (n:Concept {id: $node_id, userId: $userId}) RETURN n"
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id), "userId": user_id})
            record = await result.single()
            return Node.model_validate(record["n"]) if record else None

    async def delete_node_by_id(self, node_id: UUID, user_id: str) -> bool:
        query = "MATCH (n:Concept {id: $node_id, userId: $userId}) DETACH DELETE n"
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id), "userId": user_id})
            summary = await result.consume()
            return summary.counters.nodes_deleted > 0

    async def delete_edge(self, edge: Edge, user_id: str) -> bool:
        query = """
        MATCH (a:Concept {id: $source_id, userId: $userId})
        MATCH (b:Concept {id: $target_id, userId: $userId})
        CALL apoc.cypher.do_it(
            'MATCH (a)-[r:' + $rel_type + ']->(b) DELETE r RETURN count(r) as deleted_count',
            {a: a, b: b}
        ) YIELD value
        RETURN value.deleted_count > 0 as was_deleted
        """
        async with self.driver.session() as session:
            result = await session.run(query, {
                "source_id": str(edge.source_id),
                "target_id": str(edge.target_id),
                "rel_type": edge.label,
                "userId": user_id
            })
            record = await result.single()
            return record["was_deleted"] if record else False
    
    async def get_1_hop_neighbors(self, node_id: UUID, user_id: str) -> list[Node]:
        query = """
        MATCH (source:Concept {id: $node_id, userId: $userId})--(neighbor:Concept)
        WHERE neighbor.userId = $userId
        RETURN DISTINCT neighbor
        """
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id), "userId": user_id})
            records = [record async for record in result]
            return [Node.model_validate(record["neighbor"]) for record in records]

    async def find_semantically_similar_nodes(
        self,
        query_vector: list[float],
        excluded_node_ids: list[UUID],
        user_id: str,
        threshold: float,
        limit: int
    ) -> list[Node]:
        excluded_ids_str = [str(uuid) for uuid in excluded_node_ids]
        query = """
            CALL db.index.vector.queryNodes('concept_embeddings', $limit, $query_vector)
            YIELD node, score
            WHERE score >= $threshold AND node.userId = $userId AND NOT node.id IN $excluded_ids
            RETURN node
        """
        async with self.driver.session() as session:
            result = await session.run(query, {
                "limit": limit,
                "query_vector": query_vector,
                "threshold": threshold,
                "excluded_ids": excluded_ids_str,
                "userId": user_id
            })
            records = [record async for record in result]
            return [Node.model_validate(record["node"]) for record in records]