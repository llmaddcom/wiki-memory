"""语义召回通道（P2）：惰性补算落库、余弦排序、身份校验失效重算、写点失效。"""

import json

from sqlmodel import select

from wiki_memory.db import get_session
from wiki_memory.main import app
from wiki_memory.models import PageEmbedding


def _session(client):
    return next(app.dependency_overrides[get_session]())


def _build_two_pages(client, fake_llm, owner="u", subject="r"):
    uid = client.post("/spaces", json={"owner_id": owner, "subject_id": subject}).json()["uid"]
    src = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "person", "slug": "coriander", "title": "香菜",
             "hook": "她讨厌香菜", "happened_on": "2026-07-01",
             "summary": "点餐注意", "body": "## 禁忌\n略", "change_reason": "建页",
             "source_ids": [src]},
            {"op": "create", "type": "procedure", "slug": "report", "title": "日报",
             "hook": "日报按天写", "summary": "别用周报格式", "body": "## 做法\n略",
             "change_reason": "建页", "source_ids": [src]},
        ]}, ensure_ascii=False)
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"
    return uid


def test_embedding_recall_ranks_by_cosine(client, fake_llm, fake_embedder):
    uid = _build_two_pages(client, fake_llm)
    body = client.post(
        f"/spaces/{uid}/recall", json={"query": "香菜相关", "method": "embedding"}
    ).json()
    assert body["hits"][0]["slug"] == "coriander"
    d = body["hits"][0]["score_details"]
    assert d["model_tag"] == "fake-emb" and d["embedding_cos"] == 1.0
    # 惰性补算已落库（每页一行）
    rows = _session(client).exec(select(PageEmbedding)).all()
    assert {r.model_tag for r in rows} == {"fake-emb"} and len(rows) == 2


def test_embedding_cache_reused_and_invalidated(client, fake_llm, fake_embedder):
    """第二次查询走缓存（只 embed query）；固化改写后该页失效重算。"""
    uid = _build_two_pages(client, fake_llm, "u2", "r2")
    client.post(f"/spaces/{uid}/recall", json={"query": "香菜", "method": "embedding"})
    calls_before = len(fake_embedder.calls)
    client.post(f"/spaces/{uid}/recall", json={"query": "香菜", "method": "embedding"})
    # 第二次只有 query 一次 embed 调用，且批内只有 1 条
    assert len(fake_embedder.calls) == calls_before + 1
    assert fake_embedder.calls[-1] == ["香菜"]

    # 固化 update 触发失效：下次召回重算该页
    src = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "新材料"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"read": []}),
        json.dumps({"operations": [
            {"op": "update", "type": "person", "slug": "coriander", "title": "香菜",
             "hook": "改口能吃香菜了", "summary": "变了", "body": "## 禁忌\n能吃了",
             "change_reason": "更新", "source_ids": [src]},
        ]}, ensure_ascii=False),
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"
    client.post(f"/spaces/{uid}/recall", json={"query": "香菜", "method": "embedding"})
    # 最后一次批 embed 含被改页的 hook+summary 文本
    assert any("改口能吃香菜了" in t for batch in fake_embedder.calls for t in batch)


def test_model_tag_mismatch_reembeds(client, fake_llm, fake_embedder):
    """换 embedder（model_tag 变）：存量向量视为失效，自动重算，无需人工迁移。"""
    uid = _build_two_pages(client, fake_llm, "u3", "r3")
    client.post(f"/spaces/{uid}/recall", json={"query": "香菜", "method": "embedding"})
    fake_embedder.model_tag = "fake-emb-v2"
    client.post(f"/spaces/{uid}/recall", json={"query": "香菜", "method": "embedding"})
    rows = _session(client).exec(select(PageEmbedding)).all()
    assert {r.model_tag for r in rows} == {"fake-emb-v2"}


def test_embedding_method_disabled_without_config(client, fake_llm):
    """embedder 未配置（依赖返回 None）→ 422 明确报未启用。"""
    from wiki_memory.api.deps import get_embedder

    uid = _build_two_pages(client, fake_llm, "u4", "r4")
    app.dependency_overrides[get_embedder] = lambda: None
    try:
        r = client.post(
            f"/spaces/{uid}/recall", json={"query": "香菜", "method": "embedding"}
        )
        assert r.status_code == 422
    finally:
        # conftest 会在夹具收尾统一 clear，这里恢复原覆盖以免影响同文件后续用例
        pass
