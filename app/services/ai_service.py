# app/services/ai_service.py
import asyncio
from google.genai import types
import google.genai as genai
import json
from pydantic import BaseModel, ValidationError
from app.models.graph import Node, Edge
from app.services.prompt_service import PromptService

# Pydantic models for parsing the specific JSON structure from the LLM.
class AI_Node(BaseModel):
    name: str
    description: str

class AI_Edge(BaseModel):
    source_is_original: bool
    target_node_index: int
    label: str

class AI_Graph(BaseModel):
    nodes: list[AI_Node]
    edges: list[AI_Edge]

class AIService:
    def __init__(self, api_key: str, prompt_service: PromptService):
        self.client = genai.Client(api_key=api_key)
        self.prompt_service = prompt_service

    async def generate_expansion(self, source_node: Node, context: str = "") -> tuple[list[Node], list[Edge]]:
        prompt_template = await self.prompt_service.get_prompt("expand-node")

        prompt = prompt_template.format(
            node_name=source_node.name,
            node_description=source_node.description,
            existing_nodes_context=context
        )

        generation_config = types.GenerateContentConfig(
            response_mime_type="application/json"
        )

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-flash-latest',
                contents=prompt,
                config=generation_config
            )
            
            ai_graph_data = json.loads(response.text)
            ai_graph = AI_Graph.model_validate(ai_graph_data)

        except (json.JSONDecodeError, ValidationError) as e:
            print(f"AI response parsing failed: {e}")
            print(f"Raw AI response text: {getattr(response, 'text', 'No response text available.')}")
            return [], []
        except Exception as e:
            print(f"An unexpected error occurred with the Gemini API: {e}")
            return [], []

        # Convert the AI's response models into our main application models
        new_nodes = [Node(name=ai_node.name, description=ai_node.description) for ai_node in ai_graph.nodes]
        
        new_edges = []
        for ai_edge in ai_graph.edges:
            if ai_edge.target_node_index >= len(new_nodes):
                continue
            target_node = new_nodes[ai_edge.target_node_index]
            
            if ai_edge.source_is_original:
                source_id = source_node.id
                target_id = target_node.id
            else:
                source_id = target_node.id
                target_id = source_node.id

            new_edges.append(Edge(source_id=source_id, target_id=target_id, label=ai_edge.label))

        return new_nodes, new_edges
