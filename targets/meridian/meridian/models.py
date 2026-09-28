from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class CollectionInput(Input):
    name: str = Field(min_length=1, max_length=120)
    access: Literal["team", "restricted"] = "team"


class DocumentInput(Input):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=100000)
    metadata: dict = Field(default_factory=dict)


class DocumentUpdate(DocumentInput):
    expected_revision: int = Field(ge=1)


class SearchInput(Input):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=6, ge=1, le=20)


class SourceInput(Input):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    collection_id: str
    url: str = Field(max_length=2000)


class HookDocument(DocumentInput):
    delivery_id: str = Field(min_length=8, max_length=100)


class WorkflowStep(Input):
    kind: Literal["collect", "summarize", "publish"]
    config: dict = Field(default_factory=dict)


class WorkflowInput(Input):
    name: str = Field(min_length=1, max_length=120)
    steps: list[WorkflowStep] = Field(min_length=2, max_length=8)
    run_role: Literal["admin", "analyst"] = "analyst"


class RunInput(Input):
    delay_seconds: int = Field(default=0, ge=0, le=300)


class ExportInput(RunInput):
    collection_id: str
    format: Literal["json", "markdown"] = "markdown"


class RoleInput(Input):
    role: Literal["admin", "analyst", "viewer"]


class ChatInput(Input):
    message: str = Field(min_length=1, max_length=4000)
    tools_enabled: bool = False


class ConversationInput(Input):
    title: str = Field(default="Research session", min_length=1, max_length=200)
