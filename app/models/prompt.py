from pydantic import BaseModel


class PromptDocument(BaseModel):
    key: str
    prompt: str


class PromptUpdate(BaseModel):
    prompt: str
