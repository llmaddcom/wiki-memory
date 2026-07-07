"""delete-by-source：预览影响面 → 硬删 source + 证据回收 + 混合页重固化 → 失败原子回退。"""

import json
import threading
import time

from wiki_memory.api.routes import sources as sources_route


def _setup_space(client, fake_llm):
    """三页布局：
    - session-a-only：证据全来自会话 A（s1+s2）→ 删除对象
    - mixed-page   ：证据横跨会话 A 与 B（s2+s3）→ 重固化对象
    - observer     ：证据只有 s3，但 [[链接]] 指向 session-a-only → 不受回收波及
    """
    r = client.post("/spaces", json={"owner_id": "u-del", "subject_id": "r-del"})
    uid = r.json()["uid"]

    def ingest(content, ref=None):
        r = client.post(
            f"/spaces/{uid}/sources",
            json={"kind": "turn", "content": content, "external_ref": ref},
        )
        return r.json()["id"]

    s1 = ingest("用户：我家住幸福路 1 号。AI：记住了。",
                {"system": "createrole", "session_id": "A", "turn_id": "t1"})
    s2 = ingest("用户：我讨厌香菜，另外周五交周报。AI：好的。",
                {"system": "createrole", "session_id": "A", "turn_id": "t2"})
    s3 = ingest("用户：再确认下，周五交周报。AI：没问题。",
                {"system": "createrole", "session_id": "B", "turn_id": "t9"})
    s4 = ingest("人工投喂的资料。")  # 无 external_ref，永远不该被匹配

    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "person", "slug": "session-a-only",
             "title": "住址与口味", "summary": "住幸福路 1 号；讨厌香菜",
             "body": "## 偏好\n住幸福路 1 号，讨厌香菜。",
             "change_reason": "建页", "source_ids": [s1, s2]},
            {"op": "create", "type": "procedure", "slug": "mixed-page",
             "title": "周报约定", "summary": "周五交周报；讨厌香菜的用户提的",
             "body": "## 做法\n周五交周报。提出人详见 [[session-a-only]]，其讨厌香菜。",
             "change_reason": "建页", "source_ids": [s2, s3]},
            {"op": "create", "type": "belief", "slug": "observer",
             "title": "旁观页", "summary": "只依赖会话 B",
             "body": "## 结论\n参考 [[session-a-only]]。",
             "change_reason": "建页", "source_ids": [s3]},
        ]}, ensure_ascii=False)
    ]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded"
    return uid, (s1, s2, s3, s4)


def test_preview_partitions_pages(client, fake_llm):
    uid, (s1, s2, s3, s4) = _setup_space(client, fake_llm)

    # 会话 A：命中 s1+s2；session-a-only 全部证据被删 → 删除；mixed-page 还有 s3 → 重固化
    r = client.post(
        f"/spaces/{uid}/sources/delete-by-ref/preview",
        json={"external_ref": {"system": "createrole", "session_id": "A"}},
    )
    body = r.json()
    assert body["matched_sources"] == 2
    assert body["matched_source_ids"] == sorted([s1, s2])
    assert body["pages_to_delete"] == ["session-a-only"]
    assert body["pages_to_reconsolidate"] == ["mixed-page"]

    # 子集匹配可以更细：加 turn_id 只命中一条
    r = client.post(
        f"/spaces/{uid}/sources/delete-by-ref/preview",
        json={"external_ref": {"system": "createrole", "session_id": "A", "turn_id": "t1"}},
    )
    assert r.json()["matched_source_ids"] == [s1]

    # 预览不动库
    assert len(client.get(f"/spaces/{uid}/sources").json()) == 4

    # 空 external_ref 拒绝（否则等于删全库）
    r = client.post(f"/spaces/{uid}/sources/delete-by-ref/preview", json={"external_ref": {}})
    assert r.status_code == 422


def test_execute_deletes_and_reconsolidates(client, fake_llm):
    uid, (s1, s2, s3, s4) = _setup_space(client, fake_llm)

    # 重固化 LLM：用剩余材料（s3）重写 mixed-page，剔除"讨厌香菜"（只有会话 A 支撑）
    fake_llm.responses = [
        json.dumps({"title": "周报约定", "summary": "周五交周报",
                    "body": "## 做法\n周五交周报。提出人详见 [[session-a-only]]。",
                    "confidence": 0.6}, ensure_ascii=False)
    ]
    r = client.post(
        f"/spaces/{uid}/sources/delete-by-ref",
        json={"external_ref": {"system": "createrole", "session_id": "A"}},
    )
    body = r.json()
    assert body["deleted_sources"] == 2
    assert body["deleted_pages"] == ["session-a-only"]
    assert body["reconsolidated_pages"] == ["mixed-page"]
    assert body["run_id"]

    # source 硬删：s1/s2 消失，s3/s4 保留
    remaining = {s["id"] for s in client.get(f"/spaces/{uid}/sources").json()}
    assert remaining == {s3, s4}

    # 全证据页连修订历史一起消失
    assert client.get(f"/spaces/{uid}/pages/session-a-only").status_code == 404
    assert client.get(f"/spaces/{uid}/pages/session-a-only/revisions").status_code == 404

    # 混合页：正文重写、留新修订、出处只剩 s3
    page = client.get(f"/spaces/{uid}/pages/mixed-page").json()
    assert "香菜" not in page["body"] and "周报" in page["body"]
    revs = client.get(f"/spaces/{uid}/pages/mixed-page/revisions").json()
    assert [rv["seq"] for rv in revs] == [1, 2]
    assert "重固化" in revs[-1]["change_reason"]
    ev = client.get(f"/spaces/{uid}/pages/mixed-page/evidence").json()
    assert {e["source_id"] for e in ev} == {s3}

    # 指向被删页面的链接变悬空（observer 未被触碰，正文保留 [[session-a-only]]）
    dangling = client.get(f"/spaces/{uid}/links", params={"dangling": True}).json()
    assert {l["to_slug"] for l in dangling} == {"session-a-only"}
    assert "session-a-only" in client.get(f"/spaces/{uid}/pages/observer").json()["body"]

    # 审计留痕：run 记录 trigger 与触碰页面
    runs = client.get(f"/spaces/{uid}/runs").json()
    del_run = next(r for r in runs if r["trigger"] == "delete_by_source")
    assert del_run["status"] == "succeeded"
    assert sorted(del_run["pages_touched"]) == ["mixed-page", "session-a-only"]
    assert sorted(del_run["source_ids"]) == sorted([s1, s2])


def test_execute_atomic_on_llm_failure(client, fake_llm):
    """重固化 LLM 输出垃圾 → 502，库无任何变更（不能出现 source 删了页面还在的中间态）。"""
    uid, (s1, s2, s3, s4) = _setup_space(client, fake_llm)
    fake_llm.responses = ["我不会输出 JSON。"]
    r = client.post(
        f"/spaces/{uid}/sources/delete-by-ref",
        json={"external_ref": {"system": "createrole", "session_id": "A"}},
    )
    assert r.status_code == 502

    assert len(client.get(f"/spaces/{uid}/sources").json()) == 4
    assert client.get(f"/spaces/{uid}/pages/session-a-only").status_code == 200
    page = client.get(f"/spaces/{uid}/pages/mixed-page").json()
    assert "香菜" in page["body"]
    runs = client.get(f"/spaces/{uid}/runs").json()
    del_run = next(r for r in runs if r["trigger"] == "delete_by_source")
    assert del_run["status"] == "failed" and del_run["error"]


def test_concurrent_delete_by_ref_serialized_per_space(client, fake_llm, monkeypatch):
    """同一 space 的两个 delete-by-ref 必须串行执行。

    线上事故：连删两个会话触发两个并发遗忘，后落库者在影响面评估时看到的
    "剩余证据" source 已被先落库者硬删 → evidence 外键违规 → 500 整体回滚，
    该会话的记忆残留。串行化后后者的评估发生在前者提交之后，不会再引用死 source。
    """
    r = client.post("/spaces", json={"owner_id": "u-race", "subject_id": "r-race"})
    uid = r.json()["uid"]

    overlap = {"active": 0, "max": 0}
    guard = threading.Lock()
    real_execute = sources_route.deletion.execute

    def tracked_execute(session, space, ref, llm):
        with guard:
            overlap["active"] += 1
            overlap["max"] = max(overlap["max"], overlap["active"])
        time.sleep(0.1)  # 模拟重固化的 LLM 耗时，放大并发窗口
        try:
            return real_execute(session, space, ref, llm)
        finally:
            with guard:
                overlap["active"] -= 1

    monkeypatch.setattr(sources_route.deletion, "execute", tracked_execute)

    statuses = []

    def delete(session_id):
        r = client.post(
            f"/spaces/{uid}/sources/delete-by-ref",
            json={"external_ref": {"system": "createrole", "session_id": session_id}},
        )
        statuses.append(r.status_code)

    threads = [threading.Thread(target=delete, args=(sid,)) for sid in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert statuses == [200, 200]
    assert overlap["max"] == 1  # 任一时刻至多一个 delete-by-ref 在执行


def test_execute_no_match_is_noop(client, fake_llm):
    uid, _ = _setup_space(client, fake_llm)
    r = client.post(
        f"/spaces/{uid}/sources/delete-by-ref",
        json={"external_ref": {"system": "createrole", "session_id": "nope"}},
    )
    body = r.json()
    assert body == {"deleted_sources": 0, "deleted_pages": [],
                    "reconsolidated_pages": [], "run_id": None}
    assert len(client.get(f"/spaces/{uid}/sources").json()) == 4
    assert fake_llm.responses == []  # 没有多余的 LLM 调用
