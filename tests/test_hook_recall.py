"""三元结构（hook/happened_on）：落库与语义校验、hook 级召回裁剪、
单页 evidence_dates、结构化输出（json_schema）与降级路径。"""

import json

import httpx
import pytest

from wiki_memory.llm.base import LLMError
from wiki_memory.llm.openai_compat import OpenAICompatLLM


def _create_space(client, **kw):
    r = client.post("/spaces", json=kw or {"owner_id": "u1", "subject_id": "role1"})
    assert r.status_code == 200
    return r.json()["uid"]


def test_hook_happened_on_persist_and_validate(client, fake_llm):
    """hook 超 20 字截断、happened_on 非法置空（操作不丢弃）；修订快照与回滚同步三元字段。"""
    uid = _create_space(client)
    src = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料一"}
    ).json()["id"]

    long_hook = "钩" * 25
    fake_llm.responses = [
        json.dumps(
            {
                "operations": [
                    {"op": "create", "type": "belief", "slug": "long-hook", "title": "超长钩子",
                     "hook": long_hook, "happened_on": "2026-07-01",
                     "summary": "某认识", "body": "## 结论\n内容甲",
                     "change_reason": "建页", "source_ids": [src]},
                    {"op": "create", "type": "belief", "slug": "bad-date", "title": "坏日期",
                     "hook": "正常钩子", "happened_on": "上周某天",
                     "summary": "另一认识", "body": "## 结论\n内容乙",
                     "change_reason": "建页", "source_ids": [src]},
                ]
            },
            ensure_ascii=False,
        )
    ]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded"

    # write 阶段带 json_schema 约束（空 wiki 跳过 select 阶段）
    assert [f["json_schema"]["name"] for f in fake_llm.response_formats] == ["write_plan"]
    assert fake_llm.response_formats[0]["type"] == "json_schema"

    page = client.get(f"/spaces/{uid}/pages/long-hook").json()
    assert page["hook"] == "钩" * 20  # 超 20 字截断
    assert page["happened_on"] == "2026-07-01"
    page2 = client.get(f"/spaces/{uid}/pages/bad-date").json()
    assert page2["hook"] == "正常钩子"
    assert page2["happened_on"] is None  # 非法日期置空，操作本身照常落库

    # 修订快照同步含三元字段
    revs = client.get(f"/spaces/{uid}/pages/long-hook/revisions").json()
    assert revs[0]["hook"] == "钩" * 20 and revs[0]["happened_on"] == "2026-07-01"

    # 二次固化（wiki 非空）：select 与 write 阶段都带各自 schema
    src2 = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料二"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"read": []}),
        json.dumps(
            {"operations": [
                {"op": "update", "type": "belief", "slug": "long-hook", "title": "超长钩子",
                 "hook": "改后的钩子", "happened_on": None,
                 "summary": "更新后", "body": "## 结论\n新内容",
                 "change_reason": "更新", "source_ids": [src2]},
            ]},
            ensure_ascii=False,
        ),
    ]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded"
    assert [f["json_schema"]["name"] for f in fake_llm.response_formats[1:]] == [
        "select_plan", "write_plan",
    ]
    assert client.get(f"/spaces/{uid}/pages/long-hook").json()["hook"] == "改后的钩子"

    # 回滚还原三元字段（快照的意义）
    r = client.post(f"/spaces/{uid}/pages/long-hook/rollback", json={"seq": 1})
    assert r.json()["hook"] == "钩" * 20 and r.json()["happened_on"] == "2026-07-01"


_SUMMARY_B = "日报要按天维度输出，别用周报格式凑数，周五另交周总结"


def _build_two_pages(client, fake_llm):
    """页 A 有 hook + happened_on；页 B hook 为空（模拟存量页，走 fallback）。"""
    uid = _create_space(client, owner_id="u8", subject_id="r8")
    src = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps(
            {"operations": [
                {"op": "create", "type": "person", "slug": "coriander", "title": "香菜偏好",
                 "hook": "她讨厌香菜", "happened_on": "2026-07-01",
                 "summary": "小美讨厌香菜，点餐注意", "body": "## 禁忌\n小美讨厌香菜。",
                 "change_reason": "建页", "source_ids": [src]},
                {"op": "create", "type": "procedure", "slug": "report-habit", "title": "日报习惯",
                 "summary": _SUMMARY_B, "body": "## 做法\n日报按天写。",
                 "change_reason": "建页", "source_ids": [src]},
            ]},
            ensure_ascii=False,
        )
    ]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded"
    return uid


def test_recall_detail_hook(client, fake_llm):
    """detail=hook：响应只含钩子字段（无 body/summary），存量页降级 summary 前 20 字。"""
    uid = _build_two_pages(client, fake_llm)

    r = client.post(
        f"/spaces/{uid}/recall",
        json={"query": "香菜 日报", "method": "bm25", "detail": "hook"},
    )
    body = r.json()
    hits = {h["slug"]: h for h in body["hits"]}
    assert set(hits) == {"coriander", "report-habit"}
    for h in body["hits"]:
        assert set(h) == {"slug", "title", "type", "hook", "happened_on", "score", "hook_fallback"}

    a = hits["coriander"]
    assert a["hook"] == "她讨厌香菜" and a["happened_on"] == "2026-07-01"
    assert a["hook_fallback"] is False and a["score"] > 0
    b = hits["report-habit"]
    assert b["hook"] == _SUMMARY_B[:20]  # 降级：summary 前 20 字
    assert b["hook_fallback"] is True and b["happened_on"] is None

    # context_block 渲染为钩子行（[[slug]] 供模型点名展开），不泄漏正文
    assert "- [[coriander]] 她讨厌香菜（2026-07-01）" in body["context_block"]
    assert f"- [[report-habit]] {_SUMMARY_B[:20]}" in body["context_block"]
    assert "小美讨厌香菜。" not in body["context_block"]

    # 空命中：hits 与 context_block 都为空，不报错
    r = client.post(
        f"/spaces/{uid}/recall", json={"query": "量子力学", "method": "bm25", "detail": "hook"}
    )
    assert r.json()["hits"] == [] and r.json()["context_block"] == ""


def test_recall_default_full_unchanged(client, fake_llm):
    """不传 detail：响应字段集与旧版完全一致（无新增键），且 hook 模式体积更小。"""
    uid = _build_two_pages(client, fake_llm)

    r_full = client.post(f"/spaces/{uid}/recall", json={"query": "香菜 日报", "method": "bm25"})
    for h in r_full.json()["hits"]:
        assert set(h) == {"slug", "title", "type", "summary", "score", "body", "updated_at"}
    assert "## 禁忌" in r_full.json()["context_block"]

    r_hook = client.post(
        f"/spaces/{uid}/recall",
        json={"query": "香菜 日报", "method": "bm25", "detail": "hook"},
    )
    assert len(r_hook.content) < len(r_full.content)


def test_expand_pages_order_and_context_block(client, fake_llm):
    """批量展开：按请求顺序返回，context_block 含正文（与 recall full 同款）。"""
    uid = _build_two_pages(client, fake_llm)

    r = client.post(
        f"/spaces/{uid}/pages/expand",
        json={"slugs": ["report-habit", "coriander"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert [h["slug"] for h in body["hits"]] == ["report-habit", "coriander"]
    assert body["missing"] == []
    assert "日报按天写" in body["context_block"]
    assert "小美讨厌香菜" in body["context_block"]
    # 顺序：先 report-habit 再 coriander
    assert body["context_block"].index("report-habit") < body["context_block"].index(
        "coriander"
    )


def test_expand_pages_missing_and_archived(client, fake_llm):
    """无效/归档 slug 进 missing；有效页仍展开。"""
    uid = _build_two_pages(client, fake_llm)
    assert client.post(f"/spaces/{uid}/pages/coriander/archive").status_code == 200

    r = client.post(
        f"/spaces/{uid}/pages/expand",
        json={"slugs": ["coriander", "no-such-page", "report-habit"]},
    )
    body = r.json()
    assert [h["slug"] for h in body["hits"]] == ["report-habit"]
    assert body["missing"] == ["coriander", "no-such-page"]
    assert "日报按天写" in body["context_block"]
    assert "小美讨厌香菜" not in body["context_block"]


def test_page_detail_evidence_dates(client, fake_llm):
    """单页响应附 evidence_dates：全部修订关联 source 的日期，去重升序。"""
    uid = _create_space(client, owner_id="u7", subject_id="r7")
    ids = [
        client.post(
            f"/spaces/{uid}/sources",
            json={"kind": "diary", "content": c, "occurred_at": t},
        ).json()["id"]
        for c, t in [
            ("[2026-07-01] 白天的事", "2026-07-01T09:00:00"),
            ("[2026-06-30] 前一天的事", "2026-06-30T22:00:00"),
            ("[2026-07-01] 晚上的事", "2026-07-01T18:00:00"),  # 与第一条同日，应去重
        ]
    ]
    fake_llm.responses = [
        json.dumps(
            {"operations": [
                {"op": "create", "type": "event", "slug": "trip", "title": "出行",
                 "hook": "连着两天在外奔波", "happened_on": "2026-07-01",
                 "summary": "6/30~7/1 的出行", "body": "## 经过\n1. 出发。\n2. 返回。",
                 "change_reason": "建页", "source_ids": ids},
            ]},
            ensure_ascii=False,
        )
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"

    page = client.get(f"/spaces/{uid}/pages/trip").json()
    assert page["evidence_dates"] == ["2026-06-30", "2026-07-01"]
    assert page["hook"] == "连着两天在外奔波"  # 全字段照常返回


# -- OpenAICompatLLM 的 response_format 透传与降级 ---------------------------


def _ok_response(url):
    return httpx.Response(
        200,
        request=httpx.Request("POST", url),
        json={
            "choices": [{"message": {"content": '{"operations": []}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    )


def test_response_format_passthrough_and_fallback(monkeypatch):
    """端点拒绝 response_format（如不支持 json_schema 的中转）时重试一次纯文本模式。"""
    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if "response_format" in json:
            return httpx.Response(
                400, request=httpx.Request("POST", url), json={"error": "unsupported"}
            )
        return _ok_response(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    llm = OpenAICompatLLM("http://llm.local/v1", "key", "model-x")
    fmt = {"type": "json_schema", "json_schema": {"name": "write_plan", "schema": {}}}
    res = llm.complete("system", "user", response_format=fmt)
    assert res.text == '{"operations": []}'
    assert len(calls) == 2
    assert calls[0]["response_format"] == fmt
    assert "response_format" not in calls[1]  # 降级重试不带约束


def test_response_format_supported_single_request(monkeypatch):
    """端点支持时只发一次请求；不传 response_format 的调用不带该字段。"""
    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _ok_response(url)

    monkeypatch.setattr(httpx, "post", fake_post)
    llm = OpenAICompatLLM("http://llm.local/v1", "key", "model-x")
    llm.complete("system", "user", response_format={"type": "json_schema", "json_schema": {}})
    llm.complete("system", "user")
    assert len(calls) == 2
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_response_format_both_attempts_fail(monkeypatch):
    """带与不带 response_format 都失败 → 抛 LLMError（共尝试两次）。"""
    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return httpx.Response(500, request=httpx.Request("POST", url), json={})

    monkeypatch.setattr(httpx, "post", fake_post)
    llm = OpenAICompatLLM("http://llm.local/v1", "key", "model-x")
    with pytest.raises(LLMError):
        llm.complete("system", "user", response_format={"type": "json_schema"})
    assert len(calls) == 2
