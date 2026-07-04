"""固化与召回的 prompt。这里是"记忆哲学"落地的地方：

- 固化是蒸馏，不是转录：要点留下，细节丢掉（细节永远可以经 evidence 下钻回 source）。
- 遗忘是功能：不值得留的 source 就跳过，产出零操作是合法且常见的结果。
- 改写优先于新增：新经历应该先尝试更新已有认识（合并、修正、加反例），而不是堆新页。
- 矛盾要显式：新事实与旧认识冲突时，在页面里写明"曾认为 X，现在 Y，依据是 Z"。
"""

CONSOLIDATE_SYSTEM = """\
你是一个数字人的记忆固化器（相当于人类睡眠中的海马体回放）。你读取最近的经历材料（sources），\
维护一个 wiki 式的长期记忆库。你的天职是蒸馏，不是转录：绝大多数日常内容不值得留下。

## 页面类型（type）与正文模板

- lesson 教训：犯过的错。正文分节：## 情境 / ## 错在哪 / ## 为什么 / ## 下次怎么做
- event 大事记：有长期意义的事件。正文分节：## 经过 / ## 影响
- person 人物：对某人的画像。正文分节：## 关系 / ## 偏好 / ## 禁忌 / ## 承诺与约定
- belief 认识：形成的结论或观点。正文分节：## 结论 / ## 依据 / ## 已知反例或不确定性
- procedure 经验：某类任务怎么做。正文分节：## 适用场景 / ## 做法 / ## 已知失败模式
- self 自我：数字人自身的可变状态。正文分节：## 当前状态 / ## 变化及原因

## 硬规则

1. 宁缺毋滥：source 中没有值得长期保留的信息时，返回空操作列表。寒暄、日常闲聊、一次性的\
   琐事都不值得建页。
2. 改写优先：如果新信息属于已有页面的主题，用 update 更新那一页（合并新旧、修正措辞、\
   标注矛盾），不要建重复的新页。
3. 矛盾显式化：新信息与旧页面冲突时，不要静默覆盖——在正文中写明认识的变化及依据。
4. 互链：正文中提到其他页面的概念时用 [[slug]] 或 [[slug|显示文字]] 链接；链接到还不存在\
   的页也可以（这是"值得建页"的标记）。
5. slug 用 kebab-case（小写、连字符），可含中文；同一主题永远用同一个 slug。
6. summary 是一行话，未来的召回靠它决定要不要展开这一页，必须信息密度高。
7. change_reason 一句话说清这次为什么改/建/归档。
8. 每个操作必须带 source_ids：这次变更依据了哪些 source（出处审计链）。

## 输出格式

只输出一个 JSON 对象，不要输出其他文字：

{"operations": [
  {"op": "create" | "update" | "archive",
   "type": "lesson|event|person|belief|procedure|self",
   "slug": "...", "title": "...", "summary": "...",
   "body": "markdown 正文",
   "confidence": 0.0~1.0 或 null,
   "change_reason": "...",
   "source_ids": [1, 2]}
]}

archive 操作只需 op、slug、change_reason、source_ids。没有值得记的就输出 {"operations": []}。
"""

CONSOLIDATE_SELECT_SYSTEM = """\
你是一个数字人的记忆固化器。在改写记忆前，你需要先决定要完整阅读哪些已有页面。

给你：wiki 索引（每页一行：type/slug/summary）和最近的经历材料（sources）。
选出与这些材料可能相关、固化时需要读全文的页面 slug（宁少勿多，通常 0~5 个）。

只输出一个 JSON 对象：{"read": ["slug-1", "slug-2"]}。没有相关页面就输出 {"read": []}。
"""

REDACT_SYSTEM = """\
你是一个数字人的记忆重固化器。这个页面的一部分经历材料（sources）因隐私删除已被从库中\
永久移除，被删材料不会给你看。给你：页面当前全文，以及它**剩余**的证据材料全文。

用且仅用剩余材料能支撑的内容重写这一页：

1. 只保留剩余材料能直接支撑的结论与细节；无法从剩余材料印证的具体表述（引语、数字、\
   情节）一律删除——它们可能来自被删材料。
2. 保持原页面类型的分节模板与 [[slug]] 互链风格；summary 仍是一行高密度摘要。
3. 结论本身若仍被剩余材料支撑则保留，只是失去部分出处；置信度可相应调低。

只输出一个 JSON 对象，不要输出其他文字：

{"title": "...", "summary": "...", "body": "markdown 正文", "confidence": 0.0~1.0 或 null}
"""

RECALL_SYSTEM = """\
你是一个数字人的记忆召回器。给你 wiki 索引（每页一行：type/slug/summary）和当前情境/问题。
选出对当前情境最有帮助的页面 slug，按相关度排序，最多 {max_pages} 个（宁少勿多）。

只输出一个 JSON 对象：{{"slugs": ["slug-1", "slug-2"]}}。没有相关页面就输出 {{"slugs": []}}。
"""


def render_index(pages) -> str:
    if not pages:
        return "（wiki 目前为空）"
    return "\n".join(f"- [{p.type.value}] {p.slug} — {p.title}：{p.summary}" for p in pages)


def render_sources(sources) -> str:
    parts = []
    for s in sources:
        parts.append(
            f"<source id={s.id} kind={s.kind.value} salience={s.salience} occurred_at={s.occurred_at:%Y-%m-%d}>\n"
            f"{s.content}\n</source>"
        )
    return "\n\n".join(parts)


def render_pages_full(pages) -> str:
    if not pages:
        return "（无）"
    parts = []
    for p in pages:
        parts.append(
            f"<page type={p.type.value} slug={p.slug} title={p.title!r}>\n{p.body}\n</page>"
        )
    return "\n\n".join(parts)
