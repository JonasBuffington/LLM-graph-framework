import asyncio
import json
from pathlib import Path
from typing import Any

from app.core.prompts import DEFAULT_PROMPTS


class PromptService:
    def __init__(self, store_path: Path | None = None):
        base_dir = Path(__file__).resolve().parents[1]
        self.store_path = store_path or base_dir / "data" / "prompts.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def get_prompt(self, key: str) -> str:
        normalized_key = self._normalize_key(key)

        async with self._lock:
            data = await self._read_store()

        if normalized_key in data:
            return data[normalized_key]

        if normalized_key in DEFAULT_PROMPTS:
            return DEFAULT_PROMPTS[normalized_key]

        raise KeyError(f"Prompt '{key}' not found.")

    async def upsert_prompt(self, key: str, prompt_text: str) -> str:
        normalized_key = self._normalize_key(key)
        sanitized_prompt = prompt_text.strip()

        if not sanitized_prompt:
            raise ValueError("Prompt text cannot be empty.")

        async with self._lock:
            data = await self._read_store()
            if normalized_key not in DEFAULT_PROMPTS and normalized_key not in data:
                raise KeyError(f"Prompt '{key}' not found.")
            data[normalized_key] = sanitized_prompt
            await self._write_store(data)

        return sanitized_prompt

    async def reset_prompt(self, key: str) -> str:
        normalized_key = self._normalize_key(key)
        if normalized_key not in DEFAULT_PROMPTS:
            raise KeyError(f"Prompt '{key}' not found.")

        default_prompt = DEFAULT_PROMPTS[normalized_key]

        async with self._lock:
            data = await self._read_store()
            data[normalized_key] = default_prompt
            await self._write_store(data)

        return default_prompt

    async def _read_store(self) -> dict[str, str]:
        if not self.store_path.exists():
            return {}

        def _read() -> dict[str, Any]:
            with self.store_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)

        return await asyncio.to_thread(_read)

    async def _write_store(self, data: dict[str, str]) -> None:
        def _write() -> None:
            with self.store_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)

        await asyncio.to_thread(_write)

    def normalize_key(self, key: str) -> str:
        return self._normalize_key(key)

    @staticmethod
    def _normalize_key(key: str) -> str:
        return key.strip().lower().replace(" ", "-").replace("_", "-")
