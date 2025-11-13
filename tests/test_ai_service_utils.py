from app.services.ai_service import AIService


class DummyInlineData:
    def __init__(self, mime_type: str, data: bytes | str):
        self.mime_type = mime_type
        self.data = data


class DummyPart:
    def __init__(self, mime_type: str, text: str | None = None, inline_data=None):
        self.mime_type = mime_type
        self.text = text
        self.inline_data = inline_data


class DummyContent:
    def __init__(self, parts):
        self.parts = parts


class DummyCandidate:
    def __init__(self, parts):
        self.content = DummyContent(parts)


class DummyResponse:
    def __init__(self, candidates=None, text="fallback"):
        self.candidates = candidates or []
        self.text = text


def test_extracts_structured_text_from_candidate():
    part = DummyPart(mime_type="application/json", text='{"nodes": [], "edges": []}')
    response = DummyResponse(candidates=[DummyCandidate([part])])

    extracted = AIService._extract_structured_text(response)
    assert extracted == '{"nodes": [], "edges": []}'


def test_extracts_inline_data_when_text_missing():
    inline = DummyInlineData("application/json", b'{"hello":"world"}')
    part = DummyPart(mime_type="application/json", inline_data=inline)
    response = DummyResponse(candidates=[DummyCandidate([part])], text="should-not-use")

    extracted = AIService._extract_structured_text(response)
    assert extracted == '{"hello":"world"}'


def test_falls_back_to_text_when_no_candidates():
    response = DummyResponse(candidates=[], text="fallback-json")
    assert AIService._extract_structured_text(response) == "fallback-json"
