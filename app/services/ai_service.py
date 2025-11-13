# app/services/ai_service.py
import asyncio
import logging
import json
from typing import Any
from google.genai import types
import google.genai as genai
from pydantic import BaseModel, ValidationError
from app.models.graph import Node, Edge
from app.services.prompt_service import PromptService
from app.services.ai_response_parser import parse_ai_response_text
from uuid import UUID

logger = logging.getLogger(__name__)

# Pydantic models for parsing the specific JSON structure from the LLM.
class AI_Node(BaseModel):
    name: str
    description: str

class AI_NodeIdentifier(BaseModel):
    """Identifies a node, either pre-existing or newly created."""
    is_new: bool
    index: int # index in the new_nodes list or the original_nodes list

class AI_Edge(BaseModel):
    """Defines a relationship between any two nodes in the context."""
    source: AI_NodeIdentifier
    target: AI_NodeIdentifier
    label: str

class AI_Graph(BaseModel):
    """The AI's structured output for graph modifications."""
    nodes: list[AI_Node]
    edges: list[AI_Edge]

class AIService:
    def __init__(self, api_key: str, prompt_service: PromptService):
        self.client = genai.Client(api_key=api_key)
        self.prompt_service = prompt_service

    async def generate_graph_modification(
        self,
        source_nodes: list[Node],
        user_id: str,
        prompt_key: str,
        context: str = ""
    ) -> tuple[list[Node], list[Edge]]:
        prompt_template = await self.prompt_service.get_prompt(prompt_key, user_id)

        # Format source nodes for the prompt
        source_nodes_str = "\n".join(
            [f'- ID {i}: "{node.name}" (Description: {node.description})' for i, node in enumerate(source_nodes)]
        )

        prompt = prompt_template.format(
            source_nodes_context=source_nodes_str,
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
            raw_text = self._extract_structured_text(response)
            if not raw_text:
                logger.error("AI response did not contain structured JSON output.")
                return [], []
            ai_graph_data = parse_ai_response_text(raw_text)
            ai_graph = AI_Graph.model_validate(ai_graph_data)

        except (json.JSONDecodeError, ValidationError) as e:
            logger.error("AI response parsing failed: %s", e)
            logger.debug("Raw AI response text: %s", getattr(response, "text", "No response text available."))
            return [], []
        except Exception as e:
            logger.error("An unexpected error occurred with the Gemini API: %s", e)
            return [], []

        # Convert the AI's response models into our main application models
        new_nodes = [Node(name=ai_node.name, description=ai_node.description) for ai_node in ai_graph.nodes]
        
        def get_node_id(identifier: AI_NodeIdentifier) -> UUID | None:
            if identifier.is_new:
                if 0 <= identifier.index < len(new_nodes):
                    return new_nodes[identifier.index].id
            else:
                if 0 <= identifier.index < len(source_nodes):
                    return source_nodes[identifier.index].id
            return None

        new_edges = []
        for ai_edge in ai_graph.edges:
            source_id = get_node_id(ai_edge.source)
            target_id = get_node_id(ai_edge.target)

            if source_id and target_id:
                new_edges.append(Edge(source_id=source_id, target_id=target_id, label=ai_edge.label))

        return new_nodes, new_edges

    @staticmethod
    def _extract_structured_text(response: Any) -> str:
        """
        Attempt to extract the JSON payload emitted via structured output from the SDK response.
        """
        if response is None:
            return ""

        try:
            candidates = getattr(response, "candidates", None) or []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    inline_data = getattr(part, "inline_data", None)
                    part_mime = getattr(part, "mime_type", None)
                    inline_mime = getattr(inline_data, "mime_type", None) if inline_data else None
                    mime_type = part_mime or inline_mime or ""
                    if mime_type.lower().startswith("application/json"):
                        text_part = getattr(part, "text", None)
                        if text_part:
                            return text_part
                        if inline_data:
                            data = getattr(inline_data, "data", None)
                            if isinstance(data, bytes):
                                return data.decode("utf-8")
                            if data:
                                return str(data)
                    elif mime_type.lower().startswith("application/x-thought"):
                        logger.debug("Skipping thought-signature part in candidate.")
                        continue
                    elif mime_type.lower().startswith("text/"):
                        text_part = getattr(part, "text", None)
                        if text_part:
                            return text_part
                        if inline_data:
                            data = getattr(inline_data, "data", None)
                            if isinstance(data, bytes):
                                return data.decode("utf-8")
                            if data:
                                return str(data)
        except Exception as exc:
            logger.debug("Falling back to response.text due to extraction error: %s", exc)

        return getattr(response, "text", "") or ""
