"""近似页去重防线（P1-6）与高 salience pending 临时召回（P1-8）。"""

import json


def _uid(client, owner="u", subject="r"):
    return client.post("/spaces", json={"owner_id": owner, "subject_id": subject}).json()["uid"]


def test_near_duplicate_marked_not_rejudged(client, fake_llm):
    """slug 未命中但高度相似的新建页：照常落库 + attrs 标 possible_duplicate（保守检测，不改判）。"""
    uid = _uid(client)
    s1 = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料一"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "person", "slug": "coriander", "title": "小美讨厌香菜",
             "hook": "她讨厌香菜", "summary": "小美讨厌香菜，点餐注意避开",
             "body": "## 禁忌\n讨厌香菜", "change_reason": "建页", "source_ids": [s1]},
        ]}, ensure_ascii=False)
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"

    # 固化 LLM 劣化：同主题换了个 slug 再建一页
    s2 = client.post(
        f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料二"}
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"read": []}),
        json.dumps({"operations": [
            {"op": "create", "type": "person", "slug": "xiaomei-food", "title": "小美讨厌香菜",
             "hook": "她讨厌香菜", "summary": "小美讨厌香菜，点餐注意避开",
             "body": "## 禁忌\n还是讨厌香菜", "change_reason": "建页", "source_ids": [s2]},
        ]}, ensure_ascii=False),
    ]
    assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"

    dup = client.get(f"/spaces/{uid}/pages/xiaomei-food").json()
    assert dup["attrs"]["possible_duplicate"] == ["coriander"]
    # 原页不受影响、不被自动融合（有损操作禁入）
    assert client.get(f"/spaces/{uid}/pages/coriander").status_code == 200


def test_unrelated_create_not_marked(client, fake_llm):
    uid = _uid(client, "u2", "r2")
    for i, (slug, title, summary) in enumerate([
        ("coriander", "香菜偏好", "小美讨厌香菜"),
        ("deploy-flow", "上线流程", "周四封版周五发布，先跑冒烟"),
    ]):
        src = client.post(
            f"/spaces/{uid}/sources", json={"kind": "manual", "content": f"材料{i}"}
        ).json()["id"]
        ops = json.dumps({"operations": [
            {"op": "create", "type": "belief", "slug": slug, "title": title,
             "hook": title, "summary": summary, "body": "## 结论\n略",
             "change_reason": "建页", "source_ids": [src]},
        ]}, ensure_ascii=False)
        fake_llm.responses = [ops] if i == 0 else [json.dumps({"read": []}), ops]
        assert client.post(f"/spaces/{uid}/consolidate", json={}).json()["status"] == "succeeded"
    page = client.get(f"/spaces/{uid}/pages/deploy-flow").json()
    assert not (page["attrs"] or {}).get("possible_duplicate")


def test_high_salience_pending_provisional_recall(client, fake_llm):
    """salience ≥ 阈值的 pending 材料参与 BM25 并标 provisional；低 salience 不参与。"""
    uid = _uid(client, "u3", "r3")
    client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "correction", "content": "别再叫我张先生，叫我老张", "salience": 0.9},
    )
    client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "turn", "content": "用户：今天老张聊了天气\nAI：嗯", "salience": 0.2},
    )
    body = client.post(
        f"/spaces/{uid}/recall", json={"query": "老张", "method": "bm25", "detail": "hook"}
    ).json()
    assert len(body["hits"]) == 1
    hit = body["hits"][0]
    assert hit["provisional"] is True and hit["slug"].startswith("pending-")
    assert "（待固化）" in body["context_block"]
    assert "[[" not in body["context_block"]  # 临时命中无展开页可点名


def test_provisional_exits_after_consolidation(client, fake_llm):
    """固化把 pending 转终态后，临时召回自然退出，正式页面接管。"""
    uid = _uid(client, "u4", "r4")
    src = client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "correction", "content": "别再叫我张先生，叫我老张", "salience": 0.9},
    ).json()["id"]
    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "person", "slug": "lao-zhang", "title": "称呼偏好",
             "hook": "称呼偏好老张", "summary": "勿称张先生", "body": "## 偏好\n叫老张",
             "keywords": ["老张"], "change_reason": "建页", "source_ids": [src]},
        ]}, ensure_ascii=False)
    ]
    assert client.post(
        f"/spaces/{uid}/consolidate", json={"trigger": "correction", "max_sources": 5}
    ).json()["status"] == "succeeded"
    hits = client.post(
        f"/spaces/{uid}/recall", json={"query": "老张", "method": "bm25"}
    ).json()["hits"]
    assert [h["slug"] for h in hits] == ["lao-zhang"]
    assert all(not h["provisional"] for h in hits)
