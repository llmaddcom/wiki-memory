"""端到端：ingest → 固化建页 → 二次固化改写 → 出处链 → 回滚 → 多策略召回 → 遗忘(skip)。"""

import json


def _create_space(client, **kw):
    r = client.post("/spaces", json=kw or {"owner_id": "u1", "subject_id": "role1"})
    assert r.status_code == 200
    return r.json()["uid"]


def test_full_loop(client, fake_llm):
    uid = _create_space(client)

    # 1. ingest 两条 source：一条有价值（用户纠正），一条寒暄
    r = client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "correction", "content": "别再叫我张先生，叫我老张。上次任务里你把日报发成了周报。", "salience": 0.9},
    )
    src1 = r.json()["id"]
    r = client.post(f"/spaces/{uid}/sources", json={"kind": "turn", "content": "用户：早上好。AI：早上好呀。"})
    src2 = r.json()["id"]

    # 2. 第一次固化：wiki 为空 → 跳过阶段一，只有一次 LLM 调用（写操作）
    fake_llm.responses = [
        json.dumps(
            {
                "operations": [
                    {
                        "op": "create",
                        "type": "lesson",
                        "slug": "report-format-mistake",
                        "title": "把日报发成了周报",
                        "summary": "给[[lao-zhang]]的日报误用了周报格式，需按天维度输出",
                        "body": "## 情境\n给[[lao-zhang|老张]]交日报。\n\n## 错在哪\n用了周报格式。\n\n## 为什么\n没确认周期。\n\n## 下次怎么做\n先确认报告周期。",
                        "confidence": None,
                        "change_reason": "用户明确指出的错误",
                        "source_ids": [src1],
                    },
                    {
                        "op": "create",
                        "type": "person",
                        "slug": "lao-zhang",
                        "title": "老张",
                        "summary": "称呼偏好：老张（勿称张先生）",
                        "body": "## 关系\n主要用户。\n\n## 偏好\n称呼\"老张\"。\n\n## 禁忌\n不要叫\"张先生\"。\n\n## 承诺与约定\n（暂无）",
                        "confidence": None,
                        "change_reason": "用户纠正称呼",
                        "source_ids": [src1],
                    },
                ]
            },
            ensure_ascii=False,
        )
    ]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    run = r.json()
    assert run["status"] == "succeeded"
    assert sorted(run["pages_touched"]) == ["lao-zhang", "report-format-mistake"]
    assert len(fake_llm.calls) == 1  # 空 wiki 跳过阶段一

    # 3. source 状态：被引用的 consolidated，寒暄 skipped（遗忘是功能）
    sources = {s["id"]: s for s in client.get(f"/spaces/{uid}/sources").json()}
    assert sources[src1]["status"] == "consolidated"
    assert sources[src2]["status"] == "skipped"

    # 4. 索引 + 链接图谱：lesson 页链到 person 页（同批建页也应愈合，不悬空）
    index = client.get(f"/spaces/{uid}/index").json()
    assert {e["slug"] for e in index} == {"lao-zhang", "report-format-mistake"}
    links = client.get(f"/spaces/{uid}/links").json()
    assert any(l["to_slug"] == "lao-zhang" and l["to_page_id"] for l in links)

    # 5. 出处链：lesson 页第 1 版 evidence 指回 src1
    ev = client.get(f"/spaces/{uid}/pages/report-format-mistake/evidence").json()
    assert ev[0]["source_id"] == src1 and ev[0]["revision_seq"] == 1

    # 6. 二次固化：新 source → 阶段一选读 person 页 → update 产生第 2 版
    r = client.post(
        f"/spaces/{uid}/sources",
        json={"kind": "diary", "content": "今天老张说他每周五要一份周总结。", "salience": 0.5},
    )
    src3 = r.json()["id"]
    fake_llm.responses = [
        json.dumps({"read": ["lao-zhang"]}),
        json.dumps(
            {
                "operations": [
                    {
                        "op": "update",
                        "type": "person",
                        "slug": "lao-zhang",
                        "title": "老张",
                        "summary": "称呼偏好：老张；每周五要周总结",
                        "body": "## 关系\n主要用户。\n\n## 偏好\n称呼\"老张\"。\n\n## 禁忌\n不要叫\"张先生\"。\n\n## 承诺与约定\n每周五提供周总结。",
                        "confidence": None,
                        "change_reason": "新增周五周总结的约定",
                        "source_ids": [src3],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    ]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded"
    revs = client.get(f"/spaces/{uid}/pages/lao-zhang/revisions").json()
    assert [rv["seq"] for rv in revs] == [1, 2]
    assert "周总结" in client.get(f"/spaces/{uid}/pages/lao-zhang").json()["body"]

    # 7. 回滚到第 1 版：产生第 3 版，内容等于第 1 版，历史不丢
    r = client.post(f"/spaces/{uid}/pages/lao-zhang/rollback", json={"seq": 1})
    assert "周总结" not in r.json()["body"]
    revs = client.get(f"/spaces/{uid}/pages/lao-zhang/revisions").json()
    assert [rv["seq"] for rv in revs] == [1, 2, 3]
    assert revs[2]["trigger"] == "rollback"

    # 8. LLM 召回：读索引点名页面，context_block 可直接注入对话
    fake_llm.responses = [json.dumps({"slugs": ["report-format-mistake"]})]
    r = client.post(
        f"/spaces/{uid}/recall",
        json={"query": "又要给老张写报告了，注意什么？", "method": "llm"},
    )
    body = r.json()
    assert [h["slug"] for h in body["hits"]] == ["report-format-mistake"]
    assert "<recalled_memory>" in body["context_block"]
    assert "先确认报告周期" in body["context_block"]


def test_keyword_recall_no_llm(client, fake_llm):
    """fuzzy / bm25 召回不经过 LLM：毫秒级、零 token。"""
    uid = _create_space(client, owner_id="u9", subject_id="r9")
    client.post(f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料"})
    fake_llm.responses = [
        json.dumps(
            {
                "operations": [
                    {"op": "create", "type": "lesson", "slug": "report-mistake",
                     "title": "日报格式出错", "summary": "日报误用周报格式",
                     "body": "## 情境\n交日报。\n\n## 下次怎么做\n先确认报告周期。",
                     "change_reason": "建页", "source_ids": [1]},
                    {"op": "create", "type": "belief", "slug": "coffee-preference",
                     "title": "咖啡偏好", "summary": "用户喜欢冰美式",
                     "body": "## 结论\n用户偏好冰美式咖啡。",
                     "change_reason": "建页", "source_ids": [1]},
                ]
            },
            ensure_ascii=False,
        )
    ]
    client.post(f"/spaces/{uid}/consolidate", json={})
    fake_llm.calls.clear()

    for method in ("bm25", "fuzzy"):
        r = client.post(
            f"/spaces/{uid}/recall", json={"query": "写日报要注意什么", "method": method}
        )
        body = r.json()
        assert body["method"] == method
        assert body["hits"][0]["slug"] == "report-mistake", method
        assert body["hits"][0]["score"] > 0
        assert "先确认报告周期" in body["context_block"]
    # 无关查询 → 空命中 + 空 context_block（上游不应注入空块）
    r = client.post(f"/spaces/{uid}/recall", json={"query": "量子力学", "method": "bm25"})
    assert r.json()["hits"] == [] and r.json()["context_block"] == ""
    assert fake_llm.calls == []  # 全程没碰 LLM


def test_space_uid_identity(client, fake_llm):
    """uid 三种用法：自带 UUID 幂等；owner+subject 幂等；全不传生成新库。"""
    r = client.post("/spaces", json={"uid": "my-app-uuid-0001"})
    assert r.json()["uid"] == "my-app-uuid-0001"
    r2 = client.post("/spaces", json={"uid": "my-app-uuid-0001"})
    assert r2.json()["id"] == r.json()["id"]  # 幂等

    a = client.post("/spaces", json={"owner_id": "u1", "subject_id": "r1"}).json()
    b = client.post("/spaces", json={"owner_id": "u1", "subject_id": "r1"}).json()
    assert a["id"] == b["id"]

    c = client.post("/spaces", json={}).json()
    d = client.post("/spaces", json={}).json()
    assert c["uid"] != d["uid"]  # 匿名各自新建

    # owner_id 分组列举（记忆预览入口）
    spaces = client.get("/spaces", params={"owner_id": "u1"}).json()
    assert [s["id"] for s in spaces] == [a["id"]]

    # 隔离：别的 space 看不到数据
    client.post(f"/spaces/{a['uid']}/sources", json={"kind": "manual", "content": "A 的记忆材料"})
    assert client.get(f"/spaces/{c['uid']}/sources").json() == []
    assert client.get("/spaces/no-such-uid/index").status_code == 404


def test_consolidate_zero_ops_and_failure(client, fake_llm):
    uid = _create_space(client, owner_id="u3", subject_id="r3")
    # 无 pending source：直接成功，不调 LLM
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded" and r.json()["pages_touched"] == []
    assert fake_llm.calls == []

    # 全是寒暄 → 零操作合法，source 标 skipped
    client.post(f"/spaces/{uid}/sources", json={"kind": "turn", "content": "你好。你好呀。"})
    fake_llm.responses = [json.dumps({"operations": []})]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    assert r.json()["status"] == "succeeded"
    assert client.get(f"/spaces/{uid}/sources").json()[0]["status"] == "skipped"

    # LLM 输出垃圾 → run 失败，source 保持 pending 可重试
    client.post(f"/spaces/{uid}/sources", json={"kind": "manual", "content": "重要材料", "salience": 1.0})
    fake_llm.responses = ["我不会输出 JSON。"]
    r = client.post(f"/spaces/{uid}/consolidate", json={})
    run = r.json()
    assert run["status"] == "failed" and run["error"]
    pending = client.get(f"/spaces/{uid}/sources", params={"status": "pending"}).json()
    assert len(pending) == 1


def test_ui_served(client):
    r = client.get("/ui")
    assert r.status_code == 200
    assert "wiki-memory 记忆预览" in r.text


def test_archive_and_delete_space(client, fake_llm):
    """人工归档退出索引/召回但留痕；删 space 级联清空。"""
    uid = _create_space(client, owner_id="u5", subject_id="r5")
    client.post(f"/spaces/{uid}/sources", json={"kind": "manual", "content": "材料"})
    fake_llm.responses = [
        json.dumps({"operations": [
            {"op": "create", "type": "belief", "slug": "b1", "title": "认识一",
             "summary": "某认识", "body": "## 结论\n内容甲", "change_reason": "建页", "source_ids": [1]}
        ]}, ensure_ascii=False)
    ]
    client.post(f"/spaces/{uid}/consolidate", json={})

    # 归档：退出索引，修订留痕；幂等
    r = client.post(f"/spaces/{uid}/pages/b1/archive")
    assert r.json()["status"] == "archived"
    assert client.get(f"/spaces/{uid}/index").json() == []
    revs = client.get(f"/spaces/{uid}/pages/b1/revisions").json()
    assert revs[-1]["change_reason"].startswith("人工归档")
    assert client.post(f"/spaces/{uid}/pages/b1/archive").status_code == 200
    # 归档页不再被召回
    r = client.post(f"/spaces/{uid}/recall", json={"query": "内容甲 认识", "method": "bm25"})
    assert r.json()["hits"] == []

    # 删 space：级联清空 + 404
    counts = client.delete(f"/spaces/{uid}").json()
    assert counts["pages"] == 1 and counts["sources"] >= 1
    assert client.get(f"/spaces/{uid}/index").status_code == 404


def test_consolidate_mutex_returns_active_run(fake_llm):
    """同 space 已有进行中的固化时，再触发直接返回该 run（不双跑 LLM）；陈旧 running 放行新跑。"""
    from datetime import timedelta

    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from wiki_memory.consolidation.engine import ConsolidationEngine
    from wiki_memory.models import ConsolidationRun, RunStatus, Space, utcnow

    engine_db = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine_db)
    engine = ConsolidationEngine(fake_llm)
    with Session(engine_db) as session:
        space = Space(owner_id="u6", subject_id="r6")
        session.add(space)
        session.commit()
        session.refresh(space)

        # 有进行中的固化 → 直接返回它，不新建、不调 LLM
        active = ConsolidationRun(space_id=space.id, status=RunStatus.running)
        session.add(active)
        session.commit()
        session.refresh(active)
        got = engine.run(session, space)
        assert got.id == active.id and fake_llm.calls == []

        # running 但已陈旧（视为死运行）→ 放行新跑（无 pending → 直接 succeeded）
        active.started_at = utcnow() - timedelta(seconds=3600)
        session.add(active)
        session.commit()
        fresh = engine.run(session, space)
        assert fresh.id != active.id and fresh.status == RunStatus.succeeded
