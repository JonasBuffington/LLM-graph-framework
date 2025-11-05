# app/db/repositories/graph_repository.py
from uuid import UUID
from neo4j import AsyncDriver
from app.models.graph import Node, Edge, Graph, NodeUpdate
from app.core.exceptions import NodeNotFoundException

class GraphRepository:
    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def get_full_graph(self) -> Graph:
        query = """
        MATCH (n:Concept)
        OPTIONAL MATCH (n)-[r]->(m:Concept)
        RETURN collect(DISTINCT n) as nodes, collect(DISTINCT r) as relationships
        """
        async with self.driver.session() as session:
            result = await session.run(query)
            record = await result.single()

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

    async def add_edge(self, edge: Edge) -> Edge:
        query = """
        MATCH (a:Concept {id: $source_id})
        MATCH (b:Concept {id: $target_id})
        CALL apoc.create.relationship(a, $rel_type, {}, b) YIELD rel
        RETURN type(rel) as label
        """
        async with self.driver.session() as session:
            result = await session.run(query, {
                "source_id": str(edge.source_id),
                "target_id": str(edge.target_id),
                "rel_type": edge.label
            })
            if await result.single() is None:
                raise NodeNotFoundException("One or both nodes for the edge not found.")
            return edge

    async def update_node(self, node_id: UUID, node_update: NodeUpdate) -> Node | None:
        props_to_update = node_update.model_dump(exclude_unset=True)

        if not props_to_update:
            return await self.get_node_by_id(node_id)

        query = """
        MATCH (n:Concept {id: $node_id})
        SET n += $props
        RETURN n
        """
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id), "props": props_to_update})
            record = await result.single()
            return Node.model_validate(record["n"]) if record else None

    async def add_node(self, node: Node) -> Node:
        query = """
        MERGE (n:Concept {id: $node_id})
        ON CREATE SET
            n.name = $name,
            n.description = $description,
            n.embedding = $embedding
        RETURN n
        """
        async with self.driver.session() as session:
            result = await session.run(query, {
                "node_id": str(node.id),
                "name": node.name,
                "description": node.description,
                "embedding": node.embedding,
            })
            record = await result.single()
            return Node.model_validate(record["n"])
    
    async def get_node_by_id(self, node_id: UUID) -> Node | None:
        query = "MATCH (n:Concept {id: $node_id}) RETURN n"
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id)})
            record = await result.single()
            return Node.model_validate(record["n"]) if record else None

    async def delete_node_by_id(self, node_id: UUID) -> bool:
        query = "MATCH (n:Concept {id: $node_id}) DETACH DELETE n"
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id)})
            summary = await result.consume()
            return summary.counters.nodes_deleted > 0

    async def delete_edge(self, edge: Edge) -> bool:
        # Simplified: No user check.
        query = """
        MATCH (a:Concept {id: $source_id})
        MATCH (b:Concept {id: $target_id})
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
                "rel_type": edge.label
            })
            record = await result.single()
            return record["was_deleted"] if record else False
    
    async def get_1_hop_neighbors(self, node_id: UUID) -> list[Node]:
        query = """
        MATCH (source:Concept {id: $node_id})--(neighbor:Concept)
        RETURN DISTINCT neighbor
        """
        async with self.driver.session() as session:
            result = await session.run(query, {"node_id": str(node_id)})
            records = [record async for record in result]
            return [Node.model_validate(record["neighbor"]) for record in records]

    async def find_semantically_similar_nodes(
        self,
        query_vector: list[float],
        excluded_node_ids: list[UUID],
        threshold: float,
        limit: int
    ) -> list[Node]:
        excluded_ids_str = [str(uuid) for uuid in excluded_node_ids]
        query = """
            CALL db.index.vector.queryNodes('concept_embeddings', $limit, $query_vector)
            YIELD node, score
            WHERE score >= $threshold AND NOT node.id IN $excluded_ids
            RETURN node
        """
        async with self.driver.session() as session:
            result = await session.run(query, {
                "limit": limit,
                "query_vector": query_vector,
                "threshold": threshold,
                "excluded_ids": excluded_ids_str
            })
            records = [record async for record in result]
            return [Node.model_validate(record["node"]) for record in records]
