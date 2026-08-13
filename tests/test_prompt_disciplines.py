"""固化 prompt 补强（P0-2）：五条抽取纪律、约束解码收紧、REDACT schema 补字段。"""

from wiki_memory.consolidation import prompts
from wiki_memory.consolidation.engine import PageOp, RedactPlan, WritePlan


def test_consolidate_system_has_disciplines():
    s = prompts.CONSOLIDATE_SYSTEM
    # 1 时间锚定（含演算示例 + 禁用系统当前日期）
    assert "occurred_at" in s and "2026-07-03 离职" in s
    # 2 反泛化（动机句 + hook 专名要求）
    assert "名字被改写的记忆" in s
    assert "副经理" in s
    # 3 状态变迁带前态
    assert "旧态+新态+原因" in s
    # 4 No Meta-Extraction 双向版
    assert "被分享的内容" in s and "会话行为" in s
    # 5 穷尽自查
    assert "穷尽自查" in s
    # 关键字生成规则
    assert "keywords" in s and "泛化词" in s


def test_consolidate_system_hook_discipline():
    """issue #13：hook 是单行中文「何时用我」句，禁关键词化/夹英文，≤30 字先改写不硬截。"""
    s = prompts.CONSOLIDATE_SYSTEM
    assert "何时用我" in s and "单行完整中文句" in s
    assert "不得夹英文" in s and "不进钩子文案" in s
    assert "30 字" in s and "不要硬截" in s
    assert "关键词堆砌" in s


def test_select_system_requires_similar_pages():
    assert "同一主题" in prompts.CONSOLIDATE_SELECT_SYSTEM


def test_redact_system_covers_hook_and_date():
    s = prompts.REDACT_SYSTEM
    assert "hook" in s and "happened_on" in s
    assert "何时用我" in s  # 重固化侧同一套钩子句口径


def test_pageop_schema_constraints():
    """长度/条数约束进 json schema（vLLM 约束解码在生成侧压住）。"""
    schema = WritePlan.model_json_schema()
    op = schema["$defs"]["PageOp"]["properties"]
    assert op["hook"]["maxLength"] == 30
    assert op["summary"]["maxLength"] == 300
    assert op["keywords"]["maxItems"] == 8


def test_redact_schema_constraints():
    props = RedactPlan.model_json_schema()["properties"]
    assert {"title", "hook", "happened_on", "summary", "body", "confidence"} <= set(props)
    assert props["hook"]["maxLength"] == 30


def test_pageop_defaults_tolerant():
    """schema 只约束生成；解析侧仍宽容（缺省字段不炸）。"""
    op = PageOp(op="create", slug="s")
    assert op.hook == "" and op.keywords == []
