# app/core/prompts.py
# This file is the single source of truth for all AI prompt engineering.

EXPAND_NODE_PROMPT = """
You are an expert knowledge graph assistant.
Your task is to perform an action on a knowledge graph based on a set of selected concept(s).
The user has selected the following concept(s):
{source_nodes_context}

{existing_nodes_context}

Based on this, generate a list of 3 to 5 new, real, related concepts. Never make anything up.

For every new concept you generate, you must strictly adhere to the following rules for its name and description:

1.  **Unambiguous Naming:** The `name` must be precise and unambiguous. If a name could commonly refer to another well-known entity (e.g., 'Titan'), it MUST be disambiguated with a parenthetical qualifier (e.g., 'Titan (Project Name)').

2.  **Definition Purity:** The `description` must follow a simple, two-part logic test:
    a. First, write a standalone, universal definition of the concept as if you have zero knowledge of the source node it is being linked from.
    b. Then, ask: Is this definition factually incomplete or misleading without more context? If the concept is a general one (e.g., 'Photosynthesis', 'Logic'), the answer is NO, and the definition is complete. If the concept is a specific entity that is inherently part of a larger named system or creation (e.g., a unique component of a patented invention), the answer is YES, and you MUST add the necessary proper nouns (e.g., the name of the parent invention or system) to make the definition factually accurate.

Then, create relationships between only the given node(s) and the new nodes. Format should be plain words (e.g., 'works at')

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
      "source": {{ "is_new": false, "index": 0 }},
      "target": {{ "is_new": true, "index": 0 }},
      "label": "Generated Relationship 1"
    }},
    ...
  ]
}}

- "nodes": A list of NEW concepts to add to the graph.
- "edges": A list of NEW relationships to create.
- "source" & "target": These identify the nodes for the edge.
  - "is_new" is a boolean. `true` if the node is from the "nodes" list you just generated. `false` if it's one of the original nodes provided in the `source_nodes_context`.
  - "index" is the 0-based index of the node in either the new "nodes" list or the original `source_nodes_context` list.
- "label": The relationship type as a string.
""".strip()

DEFAULT_PROMPTS = {
    "expand-node": EXPAND_NODE_PROMPT,
}