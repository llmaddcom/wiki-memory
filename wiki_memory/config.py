"""服务配置——「三个家」口径（对齐 createrole#400）：每个键只有一个主人、一个可写位置。

- 部署接入（``Settings``，来源 ``.env`` / 环境变量，``WIKIMEM_`` 前缀）：只放最底层——
  本机监听、数据库连接串、模型接入端点/密钥/模型名、服务鉴权密钥。主人是装机/运维，
  新部署只需填完这一层就能起服务。
- 系统调优（``SystemConfig``，唯一来源 ``config/system.yaml``，进 git，改动走 PR）：
  固化/召回算法参数、各类超时、批量与陈旧阈值。主人是本仓工程。取值 = 文件 > 代码默认；
  缺文件/缺键/null 用代码默认，坏值**仅该项**回退并告警，文件里多出的未知键告警（死键）。
  **没有 env 覆盖口**——退役的同名 ENV（见 ``RETIRED_ENV``）启动期告警并忽略，不再新增。
- 业务配置：本服务没有管理面，业务参数（召回 method/max_pages/detail、固化 trigger/
  max_sources 上限内取值）由上游按调用入参逐次传入，不在本服务落配置。

新增系统键只改两处：``SystemConfig`` 加字段（带默认）+ ``SYSTEM_KNOBS`` 加声明，
再在 ``config/system.yaml`` 显式写出（``tests/test_system_config.py`` 对账：文件须恰好
声明全部系统键，不缺不多）。
"""

import logging
import os
import typing
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("wiki_memory.config")

_REPO_ROOT = Path(__file__).resolve().parents[1]
# 系统键的唯一可写位置（进 git）。
SYSTEM_YAML_PATH = _REPO_ROOT / "config" / "system.yaml"
DOTENV_PATH = _REPO_ROOT / ".env"


# ── 部署接入（.env）───────────────────────────────────────────────────────────


class Settings(BaseSettings):
    """部署接入层：只放连接/密钥/本机项。全部可由环境变量 / .env 覆盖（WIKIMEM_ 前缀）。

    ``extra="ignore"``：.env 里的未知键（含退役的旋钮 ENV）不阻断启动，由
    ``warn_retired_env`` 单独告警。
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="WIKIMEM_", extra="ignore"
    )

    # ---- 本机 ----
    # 监听地址与端口（scripts/run.sh 与 `python -m wiki_memory.main` 读取）
    host: str = "0.0.0.0"
    port: int = 8020

    # ---- 数据库 ----
    # sqlite 单文件起步；换 Postgres 只需改 URL，如
    # postgresql+psycopg://user:pass@127.0.0.1:5432/wiki_memory
    database_url: str = "sqlite:///./wiki_memory.db"

    # ---- 模型接入 ----
    # 固化/召回所用 LLM（OpenAI 兼容 /chat/completions 端点，vLLM 等均可）
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = ""
    # 语义召回 embedder（OpenAI 兼容 /embeddings 端点）；api_base 留空 = 通道关闭，
    # recall method=embedding 将返回 422。model 名同时是向量身份标（换模型自动失效重算）。
    embedder_api_base: str = ""
    embedder_api_key: str = "EMPTY"
    embedder_model: str = ""

    # ---- 密钥 ----
    # 设置后所有请求须带 X-API-Key 头；留空则不鉴权（内网/本机模式）
    api_key: str = ""


# 退役的旋钮 ENV → 现在的家（system.yaml 的 section.name）。启动期告警并忽略。
RETIRED_ENV: dict[str, str] = {
    "WIKIMEM_LLM_TIMEOUT_SECONDS": "llm.timeout_seconds",
    "WIKIMEM_EMBEDDER_TIMEOUT_SECONDS": "embedder.timeout_seconds",
    "WIKIMEM_CONSOLIDATE_MAX_SOURCES": "consolidation.max_sources",
    "WIKIMEM_PENDING_RECALL_MIN_SALIENCE": "recall.pending_min_salience",
}


def _dotenv_keys(path: Path) -> set[str]:
    """.env 里出现的键名（只认整行 KEY=VALUE，与 pydantic-settings 的解析口径一致即可）。"""
    if not path.exists():
        return set()
    keys: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            keys.add(key)
    except OSError:
        return set()
    return keys


def warn_retired_env(
    env: typing.Mapping[str, str] | None = None, dotenv: Path = DOTENV_PATH
) -> list[str]:
    """检出仍在设置的退役 ENV，逐个告警并返回其名单（值一律忽略，系统键只认 system.yaml）。"""
    present = set(os.environ if env is None else env) | _dotenv_keys(dotenv)
    hit = sorted(k for k in RETIRED_ENV if k in present)
    for key in hit:
        logger.warning(
            "环境变量 %s 已退役（系统调优只认 config/system.yaml 的 %s），值被忽略",
            key,
            RETIRED_ENV[key],
        )
    return hit


# ── 系统调优（config/system.yaml）────────────────────────────────────────────


@dataclass
class SystemConfig:
    """系统键的代码默认（单一事实源：字段默认值即兜底值，类型注解即解析类型）。

    可变 dataclass：消费方在调用时读 ``system.<field>``，测试可 monkeypatch 单项。
    """

    # llm
    llm_timeout_seconds: float = 300.0
    llm_temperature: float = 0.2
    # embedder
    embedder_timeout_seconds: float = 30.0
    # consolidation
    consolidation_max_sources: int = 20
    consolidation_run_stale_seconds: int = 1800
    consolidation_duplicate_jaccard_threshold: float = 0.5
    # recall
    recall_pending_min_salience: float = 0.8
    recall_bm25_k1: float = 1.5
    recall_bm25_b: float = 0.75
    recall_keyword_boost_scale: float = 0.5
    recall_keyword_demotion_coeff: float = 0.01
    recall_keyword_max_query_terms: int = 8

    # 本次装载中取自 system.yaml 的键（section.name），启动日志/排障用；不是系统键。
    file_keys: frozenset[str] = field(default_factory=frozenset, compare=False)


@dataclass(frozen=True, slots=True)
class SystemKnob:
    """一个系统键的声明：``key`` 形如 ``section.name``（system.yaml 的落点），
    ``field`` 是 ``SystemConfig`` 的同名字段；范围校验不过视为坏值回退默认。"""

    field: str
    key: str
    description: str
    min_value: float | None = None
    max_value: float | None = None
    exclusive_min: bool = False

    def check_range(self, value: float) -> None:
        if self.min_value is not None:
            if self.exclusive_min and not value > self.min_value:
                raise ValueError(f"应 > {self.min_value}")
            if not self.exclusive_min and value < self.min_value:
                raise ValueError(f"应 ≥ {self.min_value}")
        if self.max_value is not None and value > self.max_value:
            raise ValueError(f"应 ≤ {self.max_value}")


SYSTEM_KNOBS: tuple[SystemKnob, ...] = (
    SystemKnob(
        "llm_timeout_seconds", "llm.timeout_seconds",
        "单次固化/召回 LLM 请求超时（秒；固化一次两跳、含长上下文，故放宽）",
        min_value=0, exclusive_min=True,
    ),
    SystemKnob(
        "llm_temperature", "llm.temperature",
        "固化/召回 LLM 采样温度（结构化抽取偏低温）",
        min_value=0.0, max_value=2.0,
    ),
    SystemKnob(
        "embedder_timeout_seconds", "embedder.timeout_seconds",
        "单次 embed 请求超时（秒；批量补算一批一请求）",
        min_value=0, exclusive_min=True,
    ),
    SystemKnob(
        "consolidation_max_sources", "consolidation.max_sources",
        "单次固化最多消费的 pending source 数（调用方未传 max_sources 时的默认；上限与 API 入参同为 200）",
        min_value=1, max_value=200,
    ),
    SystemKnob(
        "consolidation_run_stale_seconds", "consolidation.run_stale_seconds",
        "running 状态固化运行的陈旧阈值（秒；超过视为进程崩溃残留的死运行，放行新跑）",
        min_value=0, exclusive_min=True,
    ),
    SystemKnob(
        "consolidation_duplicate_jaccard_threshold", "consolidation.duplicate_jaccard_threshold",
        "近似页保守检测阈值（新建页与既有页 title+hook+summary 词袋 Jaccard ≥ 此值只标 possible_duplicate，不改判）",
        min_value=0.0, max_value=1.0,
    ),
    SystemKnob(
        "recall_pending_min_salience", "recall.pending_min_salience",
        "高显著性 pending source 临时召回阈值（salience ≥ 此值的待固化材料参与 bm25/fuzzy 现算；>1 即通道关闭）",
        min_value=0.0,
    ),
    SystemKnob(
        "recall_bm25_k1", "recall.bm25_k1",
        "BM25 词频饱和参数 k1",
        min_value=0.0,
    ),
    SystemKnob(
        "recall_bm25_b", "recall.bm25_b",
        "BM25 文档长度归一参数 b（[0,1]）",
        min_value=0.0, max_value=1.0,
    ),
    SystemKnob(
        "recall_keyword_boost_scale", "recall.keyword_boost_scale",
        "关键字倒排通道单关键字 boost 上限（bm25 归一分之上的最大加分）",
        min_value=0.0,
    ),
    SystemKnob(
        "recall_keyword_demotion_coeff", "recall.keyword_demotion_coeff",
        "关键字降权系数 c：boost = scale / (1 + c·(n_pages−1)²)，0.01 的半衰点在 n≈11",
        min_value=0.0,
    ),
    SystemKnob(
        "recall_keyword_max_query_terms", "recall.keyword_max_query_terms",
        "query 侧参与匹配的关键字上限（去重后）",
        min_value=1,
    ),
)

SYSTEM_KEYS: frozenset[str] = frozenset(k.key for k in SYSTEM_KNOBS)


def _read_system_yaml(path: Path) -> dict[str, Any]:
    """装载 system.yaml；缺文件 / 解析失败整体回退空 dict（全部用代码默认）。"""
    if not path.exists():
        logger.warning("系统调优文件 %s 不存在，系统键全部用代码默认", path)
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("系统调优文件 %s 解析失败，系统键全部用代码默认：%s", path, exc)
        return {}
    if not isinstance(raw, dict):
        logger.warning("系统调优文件 %s 顶层不是映射，系统键全部用代码默认", path)
        return {}
    return raw


def _coerce(raw: Any, kind: type) -> Any:
    """按字段类型解析 yaml 标量：bool 不当数字用；int 拒绝带小数；str 允许（"300"）。"""
    if isinstance(raw, bool):
        raise TypeError("布尔值不是数字")
    if kind is float:
        return float(raw)
    if kind is int:
        if isinstance(raw, float):
            if not raw.is_integer():
                raise ValueError("应为整数")
            return int(raw)
        if isinstance(raw, str):
            return int(raw.strip())
        return int(raw)
    return kind(raw)


def load_system_config(path: Path = SYSTEM_YAML_PATH) -> SystemConfig:
    """system.yaml → SystemConfig：缺键/null 用代码默认，坏值仅该项回退并告警。"""
    data = _read_system_yaml(path)
    cfg = SystemConfig()
    hints = typing.get_type_hints(SystemConfig)
    from_file: set[str] = set()

    for knob in SYSTEM_KNOBS:
        section, _, name = knob.key.partition(".")
        body = data.get(section)
        if not isinstance(body, dict) or body.get(name) is None:
            continue  # 缺键 / null = 未设置，用代码默认
        raw = body[name]
        default = getattr(cfg, knob.field)
        try:
            value = _coerce(raw, hints[knob.field])
            knob.check_range(value)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "system.yaml 的 %s 取值非法（%r：%s），该项回退代码默认 %r",
                knob.key, raw, exc, default,
            )
            continue
        setattr(cfg, knob.field, value)
        from_file.add(knob.key)

    # 死键告警：文件里声明了但代码不认的键（多半是改名/退役后没同步）。
    for section, body in data.items():
        if not isinstance(body, dict):
            logger.warning("system.yaml 的顶层键 %s 不是分组映射，已忽略", section)
            continue
        for name in body:
            key = f"{section}.{name}"
            if key not in SYSTEM_KEYS:
                logger.warning("system.yaml 的 %s 不是已知系统键，已忽略（死键）", key)

    cfg.file_keys = frozenset(from_file)
    return cfg


def system_knob_fields() -> tuple[str, ...]:
    """SystemConfig 里属于系统键的字段名（排除 file_keys 这类元数据）。对账测试用。"""
    return tuple(f.name for f in fields(SystemConfig) if f.name != "file_keys")


settings = Settings()
warn_retired_env()
system = load_system_config()
