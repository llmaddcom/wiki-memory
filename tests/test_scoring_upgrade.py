"""召回评分升级（P0-1）：hook 入词袋、sigmoid 归一化、score_details、时间 tie-break。"""

import json
from datetime import date

from wiki_memory.models import Page, PageType
from wiki_memory.recall.bm25 import Bm25Recall, normalize_score, raw_scores


def _page(slug: str, **kw) -> Page:
    defaults = dict(
        space_id=1, type=PageType.belief, slug=slug, title="", hook="",
        summary="", body="",
    )
    defaults.update(kw)
    return Page(**defaults)


def test_hook_participates_in_retrieval():
    """信息只在 hook 里的页面必须能被检索到（钩子是最高密度检索面）。"""
    pages = [
        _page("a", hook="她讨厌香菜", body="## 禁忌\n点餐注意。"),
        _page("b", title="日报习惯", body="## 做法\n按天写。"),
    ]
    hits = Bm25Recall().retrieve(pages, "香菜", max_pages=5).hits
    assert [h.page.slug for h in hits] == ["a"]


def test_scores_normalized_to_unit_interval():
    pages = [
        _page("a", title="香菜香菜香菜", hook="她讨厌香菜", summary="香菜", body="香菜 " * 50),
        _page("b", body="提到过一次香菜"),
    ]
    hits = Bm25Recall().retrieve(pages, "香菜", max_pages=5).hits
    assert all(0.0 < (h.score or 0) < 1.0 for h in hits)
    assert hits[0].page.slug == "a" and hits[0].score > hits[1].score


def test_normalize_monotone_and_tiered():
    """归一单调；同 raw 分下短 query 档（midpoint 低）得分更高。"""
    assert normalize_score(2.0, 3) < normalize_score(5.0, 3) < normalize_score(9.0, 3)
    assert normalize_score(4.0, 3) > normalize_score(4.0, 20)


def test_score_details_breakdown():
    pages = [_page("a", hook="她讨厌香菜")]
    hits = Bm25Recall().retrieve(pages, "香菜", max_pages=5).hits
    d = hits[0].score_details
    assert d is not None
    assert {"bm25_raw", "bm25_norm", "keyword_boost", "max_possible", "final"} <= set(d)
    assert d["bm25_raw"] > 0 and d["final"] == hits[0].score


def test_tie_break_by_happened_on():
    """完全同分时 happened_on 新者优先，缺失视为最旧沉底。"""
    same = dict(hook="她讨厌香菜")
    pages = [
        _page("old", happened_on=date(2026, 1, 1), **same),
        _page("none", **same),
        _page("new", happened_on=date(2026, 7, 1), **same),
    ]
    hits = Bm25Recall().retrieve(pages, "香菜", max_pages=5).hits
    assert [h.page.slug for h in hits] == ["new", "old", "none"]


def test_raw_scores_zero_query_or_pages():
    assert raw_scores([], "香菜") == []
    assert raw_scores([_page("a", body="香菜")], "") == []


def test_end_to_end_recall_carries_details(client, fake_llm):
    """HTTP 面：bm25 响应带 score_details 且 score 已是归一合成分。"""
    uid = client.post("/spaces", json={"owner_id": "u", "subject_id": "r"}).json()["uid"]
    src = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "person", "slug": "coriander", "title": "香菜",
             "hook": "她讨厌香菜", "summary": "点餐注意", "body": "## 禁忌\n讨厌香菜",
             "change_reason": "建页", "source_ids": [src]},
        ]}, ensure_ascii=False)
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"
    hit = client.post(
        f"/spaces/{uid}/recall", json={"query": "香菜", "method": "bm25"}
    ).json()["hits"][0]
    assert 0 < hit["score"] < 1
    assert hit["score_details"]["final"] == hit["score"]
