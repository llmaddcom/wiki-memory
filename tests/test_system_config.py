"""配置三个家的对账（issue #15）：system.yaml 恰好声明全部系统键；系统键只认文件、
缺键/坏值单项回退；退役 ENV 告警并忽略；.env.example 只留连接/密钥/本机项。"""

import logging
from pathlib import Path

import yaml

from wiki_memory import config
from wiki_memory.config import (
    RETIRED_ENV,
    SYSTEM_KEYS,
    SYSTEM_KNOBS,
    SYSTEM_YAML_PATH,
    Settings,
    SystemConfig,
    load_system_config,
    system_knob_fields,
    warn_retired_env,
)

_REPO = Path(__file__).resolve().parents[1]


def _yaml_keys(path: Path) -> set[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {f"{s}.{n}" for s, body in data.items() for n in (body or {})}


def test_knob_table_matches_system_config_fields():
    """声明表与 SystemConfig 字段一一对应，key 不重复。"""
    assert tuple(k.field for k in SYSTEM_KNOBS) == system_knob_fields()
    assert len(SYSTEM_KEYS) == len(SYSTEM_KNOBS)
    assert all(k.description for k in SYSTEM_KNOBS)


def test_system_yaml_declares_exactly_all_system_keys():
    """config/system.yaml 是系统键唯一可写位置：必须不缺不多（缺 = 无家可归，多 = 死键）。"""
    in_file = _yaml_keys(SYSTEM_YAML_PATH)
    assert in_file == set(SYSTEM_KEYS), (
        f"system.yaml 缺: {set(SYSTEM_KEYS) - in_file}; 多: {in_file - set(SYSTEM_KEYS)}"
    )


def test_system_yaml_in_repo_is_valid_and_matches_code_defaults():
    """仓库自带的 system.yaml 每个值都合法（无回退告警），且与代码默认一致——
    默认值只有一个事实源，改默认要两处同步。"""
    cfg = load_system_config(SYSTEM_YAML_PATH)
    assert cfg.file_keys == SYSTEM_KEYS
    assert cfg == SystemConfig()


def test_file_value_wins_missing_and_bad_values_fall_back(tmp_path, caplog):
    path = tmp_path / "system.yaml"
    path.write_text(
        "llm:\n  timeout_seconds: 42\n  temperature: 9\n"  # 9 超范围 → 回退
        "recall:\n  bm25_b: null\n  keyword_max_query_terms: 2.5\n"  # null=未设；非整数 → 回退
        "consolidation:\n  max_sources: 'abc'\n  run_stale_seconds: true\n",  # 坏值 / bool → 回退
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="wiki_memory.config"):
        cfg = load_system_config(path)
    assert cfg.llm_timeout_seconds == 42.0
    assert cfg.file_keys == {"llm.timeout_seconds"}
    d = SystemConfig()
    assert cfg.llm_temperature == d.llm_temperature
    assert cfg.recall_bm25_b == d.recall_bm25_b
    assert cfg.recall_keyword_max_query_terms == d.recall_keyword_max_query_terms
    assert cfg.consolidation_max_sources == d.consolidation_max_sources
    assert cfg.consolidation_run_stale_seconds == d.consolidation_run_stale_seconds
    warned = {r.getMessage() for r in caplog.records}
    for key in (
        "llm.temperature",
        "recall.keyword_max_query_terms",
        "consolidation.max_sources",
        "consolidation.run_stale_seconds",
    ):
        assert any(key in m and "回退" in m for m in warned), key


def test_missing_file_and_unknown_keys(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="wiki_memory.config"):
        cfg = load_system_config(tmp_path / "missing.yaml")
    assert cfg == SystemConfig() and cfg.file_keys == frozenset()
    assert any("不存在" in r.getMessage() for r in caplog.records)

    path = tmp_path / "system.yaml"
    path.write_text("recall:\n  nope: 1\nghost:\n  x: 2\nbad: 3\n", encoding="utf-8")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="wiki_memory.config"):
        cfg = load_system_config(path)
    assert cfg == SystemConfig()
    msgs = [r.getMessage() for r in caplog.records]
    assert any("recall.nope" in m and "死键" in m for m in msgs)
    assert any("ghost.x" in m for m in msgs)
    assert any("bad" in m and "不是分组映射" in m for m in msgs)


def test_retired_env_is_warned_and_ignored(tmp_path, caplog, monkeypatch):
    """退役 ENV 不再有覆盖口：环境变量与 .env 里出现都告警，且不阻断 Settings 装载。"""
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "WIKIMEM_LLM_MODEL=m\nWIKIMEM_CONSOLIDATE_MAX_SOURCES=99\n", encoding="utf-8"
    )
    env = {"WIKIMEM_LLM_TIMEOUT_SECONDS": "5"}
    with caplog.at_level(logging.WARNING, logger="wiki_memory.config"):
        hit = warn_retired_env(env=env, dotenv=dotenv)
    assert hit == ["WIKIMEM_CONSOLIDATE_MAX_SOURCES", "WIKIMEM_LLM_TIMEOUT_SECONDS"]
    msgs = [r.getMessage() for r in caplog.records]
    assert any("consolidation.max_sources" in m for m in msgs)
    assert any("llm.timeout_seconds" in m for m in msgs)

    # 退役键出现在 .env 里不得让 Settings 炸（extra="ignore"）。
    monkeypatch.chdir(tmp_path)
    for key in RETIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=dotenv)
    assert s.llm_model == "m"
    assert not hasattr(s, "consolidate_max_sources")


def test_settings_only_holds_deploy_keys():
    """Settings 只剩连接/密钥/本机项：退役的旋钮字段不得回流。"""
    names = set(Settings.model_fields)
    assert names == {
        "host", "port", "database_url",
        "llm_base_url", "llm_api_key", "llm_model",
        "embedder_api_base", "embedder_api_key", "embedder_model",
        "api_key",
    }
    # 退役 ENV 的名字与任一 Settings 字段都对不上（否则退役表与字段表打架）。
    assert not any(k.removeprefix("WIKIMEM_").lower() in names for k in RETIRED_ENV)


def test_env_example_declares_exactly_all_deploy_keys():
    """.env.example 只留最底层项：与 Settings 字段恰好一致，且不含退役键。"""
    text = (_REPO / ".env.example").read_text(encoding="utf-8")
    declared = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    expected = {f"WIKIMEM_{name.upper()}" for name in Settings.model_fields}
    assert declared == expected, f"缺: {expected - declared}; 多: {declared - expected}"
    assert not (declared & set(RETIRED_ENV))


def test_consumers_read_system_at_call_time(monkeypatch):
    """系统键是运行时读取（非 import 期快照）：改 system 单项即生效——测试可 monkeypatch。"""
    from wiki_memory.models import Page, PageType
    from wiki_memory.recall.bm25 import raw_scores

    page = Page(space_id=1, type=PageType.belief, slug="p", title="香菜", hook="", summary="", body="香菜 香菜")
    before = raw_scores([page], "香菜")[0][1]
    monkeypatch.setattr(config.system, "recall_bm25_k1", 0.0)
    after = raw_scores([page], "香菜")[0][1]
    assert after != before
