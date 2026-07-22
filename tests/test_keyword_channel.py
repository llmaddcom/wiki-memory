"""关键字倒排通道（P1-5）：固化生成落库、并集召回加分、降权、删除联动。"""

import json

from wiki_memory.models import Page, PageType
from wiki_memory.recall.keywords import keyword_boosts


def _uid(client, owner="u", subject="r"):
    return client.post("/spaces", json={"owner_id": owner, "subject_id": subject}).json()["uid"]


def _consolidate_one(client, fake_llm, uid, *, slug, hook, summary, body, keywords,
                     ref=None, first=True):
    src = client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "manual", "content": f"{slug} 材料", "external_ref": ref},
    ).json()["id"]
    ops = json.dumps({"operations": [
        {"op": "create", "type": "belief", "slug": slug, "title": slug,
         "hook": hook, "summary": summary, "body": body, "keywords": keywords,
         "change_reason": "建页", "source_ids": [src]},
    ]}, ensure_ascii=False)
    fake_llm.responses = [ops] if first else [json.dumps({"read": []}), ops]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded", r.json()


def test_keywords_boost_and_union(client, fake_llm):
    """关键字直达但词面 miss 的页也进候选（并集），boost 体现在 score_details。"""
    uid = _uid(client)
    # 页面全字段都不含「老张」字面，只靠关键字直达
    _consolidate_one(
        client, fake_llm, uid, slug="boss", hook="上司爱喝美式",
        summary="汇报对象的习惯", body="## 偏好\n咖啡只喝美式", keywords=["老张", "美式咖啡"],
    )
    hits = client.post(
        f"/spaces/{uid}/recall", json={"query": "老张喜欢什么", "method": "bm25"}
    ).json()["hits"]
    assert [h["slug"] for h in hits] == ["boss"]
    d = hits[0]["score_details"]
    assert d["bm25_raw"] == 0.0 and d["keyword_boost"] > 0
    assert d["max_possible"] == 1.5  # 自适应分母：有关键字命中


def test_keyword_only_additive_never_gates(client, fake_llm):
    """无关键字命中时纯 BM25 照常（分母 1.0，不稀释）。"""
    uid = _uid(client, "u2", "r2")
    _consolidate_one(
        client, fake_llm, uid, slug="coriander", hook="她讨厌香菜",
        summary="点餐注意", body="## 禁忌\n讨厌香菜", keywords=["香菜"],
    )
    hits = client.post(
        f"/spaces/{uid}/recall", json={"query": "点餐注意什么", "method": "bm25"}
    ).json()["hits"]
    assert hits and hits[0]["score_details"]["max_possible"] == 1.0


def test_demotion_by_page_count(client, fake_llm):
    """同一关键字指向页面越多 boost 越低（万能词降权）。"""
    from wiki_memory.db import get_session
    from wiki_memory.main import app

    uid = _uid(client, "u3", "r3")
    _consolidate_one(client, fake_llm, uid, slug="p1", hook="钩子一",
                     summary="s", body="b", keywords=["专名甲", "泛词"])
    _consolidate_one(client, fake_llm, uid, slug="p2", hook="钩子二",
                     summary="s", body="b", keywords=["泛词"], first=False)
    _consolidate_one(client, fake_llm, uid, slug="p3", hook="钩子三",
                     summary="s", body="b", keywords=["泛词"], first=False)

    override = app.dependency_overrides[get_session]
    session = next(override())
    from sqlmodel import select
    from wiki_memory.models import Space
    space = session.exec(select(Space).where(Space.uid == uid)).one()
    only = keyword_boosts(session, space.id, "专名甲的情况")
    both = keyword_boosts(session, space.id, "专名甲和泛词")
    # 专名甲只指向 p1：满 boost；泛词指向 3 页：降权后更低
    p1_id = next(iter(only))  # 单键：只有 p1
    assert only[p1_id] == 0.5
    demoted = min(both.values())
    assert demoted < 0.5
    # 同页多关键字命中取 max 不累加：p1 命中专名甲(0.5)+泛词(低) → 仍 0.5
    assert both[p1_id] == 0.5


def test_hard_delete_clears_keyword_links(client, fake_llm):
    """单源页面随会话删除硬删：page_keyword 链接同步清除，关键字不再直达。"""
    uid = _uid(client, "u4", "r4")
    _consolidate_one(
        client, fake_llm, uid, slug="gone", hook="将被删的钩子",
        summary="s", body="b", keywords=["独有专名"],
        ref={"system": "t", "session_id": "s-9"},
    )
    r = client.post(
        f"/spaces/{uid}/sources/delete-by-ref",
        json={"external_ref": {"system": "t", "session_id": "s-9"}},
    )
    assert r.json()["deleted_pages"] == ["gone"]
    hits = client.post(
        f"/spaces/{uid}/recall", json={"query": "独有专名", "method": "bm25"}
    ).json()["hits"]
    assert hits == []


def test_archived_page_not_reachable_via_keyword(client, fake_llm):
    """归档页退出召回：关键字通道同样查不到（active 过滤在查询侧）。"""
    uid = _uid(client, "u5", "r5")
    _consolidate_one(client, fake_llm, uid, slug="arch", hook="即将归档",
                     summary="s", body="b", keywords=["归档专名"])
    client.post(f"/spaces/{uid}/pages/arch/archive")
    hits = client.post(
        f"/spaces/{uid}/recall", json={"query": "归档专名", "method": "bm25"}
    ).json()["hits"]
    assert hits == []


def test_normalize_terms():
    from wiki_memory.repositories.keyword_repo import normalize_terms

    assert normalize_terms([" 老张 ", "老张", "", "A" * 40, 42, "美式"]) == ["老张", "美式"]
    assert len(normalize_terms([f"词{i}" for i in range(20)])) == 8
