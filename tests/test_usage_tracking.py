"""usage 命中记录（P0-3）：召回/联想展开累加，预览读取不计数，重写与回滚保留。"""

import json


def _build_page(client, fake_llm, content="材料"):
    uid = client.post("/spaces", json={"owner_id": "u", "subject_id": "r"}).json()["uid"]
    src = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": content}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "person", "slug": "coriander", "title": "香菜",
             "hook": "她讨厌香菜", "happened_on": "2026-07-01",
             "summary": "点餐注意", "body": "## 禁忌\n讨厌香菜",
             "change_reason": "建页", "source_ids": [src]},
        ]}, ensure_ascii=False)
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"
    return uid


def _hit_count(client, uid, slug="coriander") -> int:
    return client.get(f"/spaces/{uid}/pages/{slug}").json()["hit_count"]


def test_recall_hit_increments(client, fake_llm):
    uid = _build_page(client, fake_llm)
    assert _hit_count(client, uid) == 0
    client.post(f"/spaces/{uid}/recall", json={"query": "香菜", "method": "bm25"})
    client.post(f"/spaces/{uid}/recall", json={"query": "香菜", "method": "bm25"})
    page = client.get(f"/spaces/{uid}/pages/coriander").json()
    assert page["hit_count"] == 2 and page["last_hit_at"] is not None
    # 未命中的查询不计数
    client.post(f"/spaces/{uid}/recall", json={"query": "量子力学", "method": "bm25"})
    assert _hit_count(client, uid) == 2


def test_associate_track_param(client, fake_llm):
    """GET 带 ?track=associate 记账（联想展开=最强使用信号）；普通读取不计。"""
    uid = _build_page(client, fake_llm)
    client.get(f"/spaces/{uid}/pages/coriander")  # 预览/审计读取
    assert _hit_count(client, uid) == 0
    r = client.get(f"/spaces/{uid}/pages/coriander", params={"track": "associate"})
    assert r.json()["hit_count"] == 1
    assert _hit_count(client, uid) == 1


def test_usage_survives_rollback(client, fake_llm):
    """usage 是第一方观测数据：回滚（内容重写）绝不清零。"""
    uid = _build_page(client, fake_llm)
    client.get(f"/spaces/{uid}/pages/coriander", params={"track": "associate"})
    # 一次更新产生第 2 版，再回滚到第 1 版
    src2 = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料二"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"read": []}),
        json.dumps({"operations": [
            {"op": "update", "type": "person", "slug": "coriander", "title": "香菜",
             "hook": "改口不讨厌香菜了", "summary": "变了", "body": "## 禁忌\n现在能吃香菜",
             "change_reason": "更新", "source_ids": [src2]},
        ]}, ensure_ascii=False),
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"
    assert _hit_count(client, uid) == 1
    client.post(f"/spaces/{uid}/pages/coriander/rollback", json={"seq": 1})
    assert _hit_count(client, uid) == 1


def test_usage_survives_redact(client, fake_llm):
    """两源页面删一源触发 REDACT 重写：hit_count 保留，hook/happened_on 按重写落库。"""
    uid = client.post("/spaces", json={"owner_id": "u2", "subject_id": "r2"}).json()["uid"]
    s1 = client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "turn", "content": "会话甲材料",
              "external_ref": {"system": "t", "session_id": "s-1"}},
    ).json()["id"]
    s2 = client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "turn", "content": "会话乙材料",
              "external_ref": {"system": "t", "session_id": "s-2"}},
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "belief", "slug": "mixed", "title": "混合页",
             "hook": "旧钩子旧钩子", "happened_on": "2026-07-01",
             "summary": "两源支撑", "body": "## 结论\n甲乙", "change_reason": "建页",
             "source_ids": [s1, s2]},
        ]}, ensure_ascii=False)
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"
    client.get(f"/spaces/{uid}/pages/mixed", params={"track": "associate"})

    fake_llm.responses = [
        json.dumps({"title": "混合页", "hook": "重写后的钩子", "happened_on": None,
                    "summary": "只余乙", "body": "## 结论\n乙", "confidence": None},
                   ensure_ascii=False)
    ]
    r = client.post(
        f"/spaces/{uid}/sources/delete-by-ref",
        json={"external_ref": {"system": "t", "session_id": "s-1"}},
    )
    assert r.json()["reconsolidated_pages"] == ["mixed"]
    page = client.get(f"/spaces/{uid}/pages/mixed").json()
    assert page["hit_count"] == 1  # 重写保留 usage
    assert page["hook"] == "重写后的钩子"  # REDACT 补 hook（既有缺口修复）
    assert page["happened_on"] is None  # 日期可能出自被删材料：按重写置空
