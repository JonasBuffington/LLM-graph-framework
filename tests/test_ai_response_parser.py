import pytest

from app.services.ai_response_parser import parse_ai_response_text


def test_parses_code_fenced_json():
    raw = """```json
    {"nodes": [], "edges": []}
    ```"""
    parsed = parse_ai_response_text(raw)
    assert parsed == {"nodes": [], "edges": []}


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            r'{"nodes": [{"name": "Integral", "description": "Uses \_subscripts"}], "edges": []}',
            "Uses \\_subscripts",
        ),
        (
            r'{"nodes": [{"name": "Trig", "description": "Angle \\theta"}], "edges": []}',
            "Angle \\theta",
        ),
    ],
)
def test_escapes_problematic_backslashes(raw, expected):
    parsed = parse_ai_response_text(raw)
    assert parsed["nodes"][0]["description"] == expected


def test_drops_thought_signature():
    raw = r'{"nodes": [], "edges": [], "thought-signature": {"id": "abc"}}'
    parsed = parse_ai_response_text(raw)
    assert "thought-signature" not in parsed
