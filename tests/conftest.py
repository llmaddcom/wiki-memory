import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from wiki_memory.api.deps import get_embedder, get_llm
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


class FakeEmbedder:
    """确定性假 embedder：按「轴词」出现与否产二维向量，便于断言余弦排序。

    axes 是两个子串：文本含 axes[0] → [1, 0]，含 axes[1] → [0, 1]，
    都含 → [1, 1]，都不含 → [0.01, 0.01]（非零，避免零向量特判干扰断言）。
    """

    def __init__(self, axes: tuple[str, str] = ("香菜", "日报"), model_tag: str = "fake-emb"):
        self.axes = axes
        self.model_tag = model_tag
        self.calls: list[list[str]] = []  # 每次 embed 的输入批（惰性补算行为断言用）

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            x = 1.0 if self.axes[0] in text else 0.0
            y = 1.0 if self.axes[1] in text else 0.0
            vectors.append([x, y] if (x or y) else [0.01, 0.01])
        return vectors


@pytest.fixture()
def fake_llm():
    return FakeLLM()


@pytest.fixture()
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture()
def client(fake_llm, fake_embedder):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_llm] = lambda: fake_llm
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
