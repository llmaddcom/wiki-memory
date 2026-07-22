"""固化质量 golden set —— 真端点档（P2-10）。

默认跳过；手动跑：

    WIKIMEM_GOLDEN=1 .venv/bin/python -m pytest tests/test_golden_real_llm.py -v -s

用 .env 配置的真实 LLM 端点逐组跑固化，断言产出操作满足抽取纪律：
hook ≤20 字非空话、无相对时间词、专名保留、遗忘用例产零操作。
CI 档（FakeLLM）只校验 prompt 组装与 schema 约束，见 test_prompt_disciplines.py。
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from wiki_memory.config import settings
from wiki_memory.consolidation.engine import ConsolidationEngine
from wiki_memory.llm.openai_compat import OpenAICompatLLM
from wiki_memory.models import Page, RunStatus, Space
from wiki_memory.repositories import source_repo

pytestmark = pytest.mark.skipif(
    os.environ.get("WIKIMEM_GOLDEN") != "1",
    reason="真端点 golden set：需 WIKIMEM_GOLDEN=1 手动运行",
)

_CASES = json.loads(
    (Path(__file__).parent / "golden_cases.json").read_text(encoding="utf-8")
)["cases"]

# hook 空话与操作字段里的转录腔/相对时间的通用禁令（所有用例统一断言）
_HOOK_BANNED = re.compile(r"关于.*的(记忆|认识)|的一些认识")
_GLOBAL_FORBIDDEN = ("上周", "上个月", "最近几天")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_golden_case(case, db_session):
    space = Space(owner_id="golden", subject_id=case["name"])
    db_session.add(space)
    db_session.commit()
    db_session.refresh(space)
    for src in case["sources"]:
        source_repo.add(
            db_session,
            space_id=space.id,
            kind=src["kind"],
            content=src["content"],
            salience=src.get("salience", 0.5),
            occurred_at=datetime.fromisoformat(src["occurred_at"]),
        )

    llm = OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
    )
    run = ConsolidationEngine(llm).run(db_session, space, trigger="golden")
    assert run.status == RunStatus.succeeded, run.error

    pages = list(db_session.query(Page).filter(Page.space_id == space.id).all())
    expect = case["expect"]
    n = len(run.pages_touched or [])
    assert expect["min_ops"] <= n <= expect["max_ops"], (
        f"操作数 {n} 不在 [{expect['min_ops']}, {expect['max_ops']}]：{run.pages_touched}"
    )
    if n == 0:
        return

    corpus = "\n".join(f"{p.hook}\n{p.summary}\n{p.body}" for p in pages)
    if expect["must_mention_any"]:
        assert any(term in corpus for term in expect["must_mention_any"]), (
            f"专名丢失（反泛化违规）：{expect['must_mention_any']} 均未出现\n{corpus}"
        )
    for pattern in list(expect["forbid_patterns"]) + list(_GLOBAL_FORBIDDEN):
        assert pattern not in corpus, f"禁令词出现：{pattern!r}\n{corpus}"
    for p in pages:
        assert p.hook.strip(), f"页 {p.slug} hook 为空"
        assert len(p.hook) <= 20
        assert not _HOOK_BANNED.search(p.hook), f"hook 空话：{p.hook!r}"
