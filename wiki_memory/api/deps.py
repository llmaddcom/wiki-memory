"""API 依赖装配：鉴权、DB 会话、space 解析、LLM 与固化引擎、召回策略。

Fake/Real 分叉只发生在这里（测试经 dependency_overrides 注入 FakeLLM），
路由代码不感知实现选择。
"""

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session

from ..config import settings
from ..consolidation.engine import ConsolidationEngine
from ..db import get_session
from ..embedding import OpenAICompatEmbedder
from ..llm import ChatLLM, OpenAICompatLLM
from ..models import Space
from ..recall import Bm25Recall, EmbeddingRecall, FuzzyRecall, LlmRecall, RecallStrategy
from ..repositories import space_repo


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def get_llm() -> ChatLLM:
    return OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
    )


def get_engine(llm: ChatLLM = Depends(get_llm)) -> ConsolidationEngine:
    return ConsolidationEngine(llm)


def get_space(space_uid: str, session: Session = Depends(get_session)) -> Space:
    space = space_repo.get_by_uid(session, space_uid)
    if space is None:
        raise HTTPException(status_code=404, detail="space not found")
    return space


def get_embedder() -> OpenAICompatEmbedder | None:
    """embedder 装配：api_base 留空 = 语义召回通道关闭（返回 None）。"""
    if not settings.embedder_api_base:
        return None
    return OpenAICompatEmbedder(
        api_base=settings.embedder_api_base,
        api_key=settings.embedder_api_key,
        model=settings.embedder_model,
        timeout=settings.embedder_timeout_seconds,
    )


def build_recall_strategy(
    method: str,
    llm: ChatLLM,
    session: Session,
    embedder: OpenAICompatEmbedder | None = None,
) -> RecallStrategy:
    if method == "fuzzy":
        return FuzzyRecall()
    if method == "bm25":
        return Bm25Recall()
    if method == "llm":
        return LlmRecall(llm)
    if method == "embedding":
        if embedder is None:
            raise HTTPException(
                status_code=422,
                detail="embedding recall 未启用：需配置 WIKIMEM_EMBEDDER_API_BASE",
            )
        return EmbeddingRecall(embedder, session)
    raise HTTPException(status_code=422, detail=f"unknown recall method: {method}")
