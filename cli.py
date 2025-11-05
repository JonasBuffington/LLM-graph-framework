import asyncio
import typer
from rich.console import Console
from rich.syntax import Syntax
import json
from uuid import UUID

from app.models.graph import Node
from app.services.ai_service import AIService
from app.core.config import settings
from app.db.driver import Neo4jDriver
from app.db.repositories.graph_repository import GraphRepository
from app.services.embedding_service import EmbeddingService
from app.core.rag_config import SIMILARITY_THRESHOLD, MAX_SEMANTIC_CANDIDATES

cli_app = typer.Typer()
console = Console()

def _get_embedding_text_for_node(node: Node) -> str:
    """Creates a rich, consistent text document for embedding."""
    galaxies_str = ", ".join(node.galaxies) if node.galaxies else "None"
    return (
        f"Concept Name: {node.name}\n"
        f"Description: {node.description}\n"
        f"Galaxies: {galaxies_str}"
    )

@cli_app.command()
def tune_prompt(
    name: str = typer.Option(..., "--name", "-n", help="The name of the concept node."),
    description: str = typer.Option(..., "--desc", "-d", help="The description of the concept."),
    galaxies: str = typer.Option(..., "--galaxies", "-g", help="Comma-separated list of galaxies."),
):
    """
    Calls the AIService directly to test and tune the prompt engineering.
    """
    # This command remains for simple, context-free prompt tuning.
    # (Implementation is unchanged)
    pass

@cli_app.command()
def test_expand(
    node_id: UUID = typer.Option(..., "--node-id", "-n", help="The UUID of the node to expand."),
):
    """
    Tests the full expansion orchestration using the Neo4j vector index.
    """
    if not settings.GEMINI_API_KEY:
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY is not set in your .env file.")
        raise typer.Exit(code=1)

    async def main():
        driver = await Neo4jDriver.get_driver()
        repo = GraphRepository(driver)
        
        source_node = await repo.get_node_by_id(node_id)
        if not source_node:
            console.print(f"[bold red]Error:[/bold red] Node with ID {node_id} not found.")
            return

        console.print(f"[cyan]--- Testing Retrieval from Persistent Vector Index ---[/cyan]")
        
        embedding_service = EmbeddingService(api_key=settings.GEMINI_API_KEY)
        if not source_node.embedding:
            console.print("[yellow]Warning: Source node missing embedding. Generating one for this test.[/yellow]")
            source_node.embedding = await embedding_service.get_embedding(
                _get_embedding_text_for_node(source_node)
            )

        # 1. Structural Retrieval
        structural_nodes = await repo.get_1_hop_neighbors(node_id)
        console.print(f"[cyan]Found {len(structural_nodes)} direct neighbors (structural search).[/cyan]")

        # 2. Semantic Retrieval from Neo4j
        excluded_ids = {n.id for n in structural_nodes}
        excluded_ids.add(source_node.id)
        
        semantic_nodes = await repo.find_semantically_similar_nodes(
            query_vector=source_node.embedding,
            excluded_node_ids=list(excluded_ids),
            threshold=SIMILARITY_THRESHOLD,
            limit=MAX_SEMANTIC_CANDIDATES
        )
        console.print(f"[cyan]Found {len(semantic_nodes)} relevant nodes from vector index (semantic search).[/cyan]")

        # 3. Combine and Format
        final_context_nodes = structural_nodes + semantic_nodes
        
        context_str = "[yellow]No context nodes found.[/yellow]"
        if final_context_nodes:
            context_items = "\n".join([f"- {n.name}" for n in final_context_nodes])
            context_str = (
                "To avoid creating duplicate concepts, be aware of these "
                "semantically similar or directly related concepts that already exist in the graph:\n"
                f"[yellow]{context_items}[/yellow]"
            )
        
        console.print("\n[bold green]CONTEXT FOR PROMPT:[/bold green]")
        console.print(context_str)

        console.print("\n[cyan]Querying AI with context...[/cyan]")
        ai_service = AIService(api_key=settings.GEMINI_API_KEY)
        new_nodes, new_edges = await ai_service.generate_expansion(source_node, context=context_str)

        console.print("\n[bold green]AI Generated Nodes:[/bold green]")
        nodes_json = json.dumps([node.model_dump(mode='json') for node in new_nodes], indent=2)
        console.print(Syntax(nodes_json, "json", theme="solarized-dark"))

        await Neo4jDriver.close_driver()

    asyncio.run(main())


if __name__ == "__main__":
    cli_app()