import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from wiki_memory.api.deps import get_llm
from wiki_memory.db import get_session
from wiki_memory.llm.base import ChatResult
from wiki_memory.main import app


class FakeLLM:
    """按队列吐回复的假 LLM。测试先塞好每次 complete 的返回文本。"""

    def __init__(self):
        self.responses: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.response_formats: list[dict | None] = []  # 每次调用收到的 response_format

    def complete(self, system: str, user: str, response_format: dict | None = None) -> ChatResult:
        self.calls.append((system, user))
        self.response_formats.append(response_format)
        if not self.responses:
            raise AssertionError("FakeLLM: no queued response")
        return ChatResult(text=self.responses.pop(0), prompt_tokens=10, completion_tokens=5)


@pytest.fixture()
def fake_llm():
    return FakeLLM()


@pytest.fixture()
def client(fake_llm):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_llm] = lambda: fake_llm
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
