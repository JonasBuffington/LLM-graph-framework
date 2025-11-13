import json
import logging
import re
from json import JSONDecodeError, JSONDecoder
from typing import Any

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_LATEX_COMMAND_RE = re.compile(r"(?<!\\)\\([A-Za-z]+)")
_INVALID_ESCAPE_RE = re.compile(r'\\([^"\\/bfnrtu])')
_FORBIDDEN_KEYS = {
    "thought",
    "thoughts",
    "thought_signature",
    "thought-signature",
    "thoughtSignature",
    "thoughtSignatureBlock",
}
_CONTROL_CHAR_REPLACEMENTS = {
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}
_VALID_SINGLE_ESCAPES = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = _CODE_FENCE_RE.match(stripped)
    return match.group(1) if match else stripped


def _escape_invalid_backslashes(text: str) -> str:
    def _replace(match: re.Match) -> str:
        return "\\\\" + match.group(1)

    return _INVALID_ESCAPE_RE.sub(_replace, text)


def _escape_latex_commands(text: str) -> str:
    def _replace(match: re.Match) -> str:
        command = match.group(1)
        if len(command) == 1 and command in _VALID_SINGLE_ESCAPES:
            return match.group(0)
        return "\\\\" + command

    return _LATEX_COMMAND_RE.sub(_replace, text)


def _normalize_control_characters(text: str) -> str:
    for needle, replacement in _CONTROL_CHAR_REPLACEMENTS.items():
        text = text.replace(needle, replacement)
    return text


def _generate_candidates(base_text: str) -> list[str]:
    candidates: list[str] = []

    def _add(candidate: str):
        candidate = candidate.strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    _add(base_text)
    _add(_escape_latex_commands(base_text))
    _add(_escape_invalid_backslashes(base_text))
    _add(_escape_invalid_backslashes(_escape_latex_commands(base_text)))
    return candidates


def _remove_forbidden_fields(payload: Any):
    if isinstance(payload, dict):
        return {
            key: _remove_forbidden_fields(value)
            for key, value in payload.items()
            if key not in _FORBIDDEN_KEYS
        }
    if isinstance(payload, list):
        return [_remove_forbidden_fields(item) for item in payload]
    return payload


def parse_ai_response_text(raw_text: str) -> dict[str, Any]:
    """
    Sanitize and parse the raw model text emitted through structured outputs.
    """
    cleaned = _strip_code_fence(raw_text or "")
    if not cleaned.strip():
        raise JSONDecodeError("AI response payload is empty", raw_text, 0)
    cleaned = cleaned.lstrip("\ufeff")
    cleaned = _normalize_control_characters(cleaned)

    decoder_strict = JSONDecoder()
    decoder_lax = JSONDecoder(strict=False)
    decoders = (decoder_strict, decoder_lax)

    last_error: JSONDecodeError | None = None
    for candidate in _generate_candidates(cleaned):
        for decoder in decoders:
            try:
                parsed = decoder.decode(candidate)
                return _remove_forbidden_fields(parsed)
            except JSONDecodeError as exc:
                last_error = exc
                continue

    logger.error("Failed to parse AI response after sanitization attempts: %s", last_error)
    raise last_error if last_error else JSONDecodeError("Unable to parse AI response", raw_text, 0)
