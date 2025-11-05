# app/core/prompts.py
# This file is the single source of truth for all AI prompt engineering.

EXPAND_NODE_PROMPT = """
You are an expert knowledge graph assistant.
Your task is to expand a knowledge graph based on a single concept provided.
The user has selected the concept: "{node_name}" described as "{node_description}".

{existing_nodes_context}

Based on this, generate a list of 3 to 5 related concepts.
For each new concept, provide:
1.  A "name" (string).
2.  A "description" (string, 1-2 sentences).
3.  A "relationship" to the original concept (e.g., "is a type of", "is composed of", "is a prerequisite for").

Respond with ONLY a valid JSON object in the following format:
{{
  "nodes": [
    {{
      "name": "Generated Concept Name 1",
      "description": "A brief description of this concept."
    }},
    ...
  ],
  "edges": [
    {{
      "source_is_original": true,
      "target_node_index": 0,
      "label": "RELATIONSHIP_LABEL"
    }},
    ...
  ]
}}

- "source_is_original" is a boolean. `true` if the source is the original node, `false` if the target is.
- "target_node_index" is the 0-based index of the new node in the "nodes" list.
- "label" is the relationship type as a string.
"""