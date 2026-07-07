# 对外契约：输入内容规范与召回注入格式

wiki-memory 不耦合任何上游产品。任何系统（数字人后端、聊天应用、agent 框架）
按本契约接入即可。身份用 space uid 隔离：上游可自带 UUID（跨系统对齐），
也可不传由服务生成。

## 1. 输入规范（ingest source）

`POST /spaces/{uid}/sources`，`content` 是固化 LLM 将要阅读的原文，规则：

- **纯文本**，禁止塞 provider SDK 的原始 JSON 响应或带内部 id 的结构体。
- **自含**：不依赖上游上下文也能读懂（人名、任务名写全）。
- **单条一事**：一条 source 对应一次经历（一个回合 / 一天日记 / 一次纠正）。

各 kind 的推荐格式与 salience：

| kind | content 格式 | salience 建议 |
|---|---|---|
| `turn` | `用户：…\nAI：…`（一回合一条，多轮拼接可读即可） | 0.0~0.3；出现失败/情绪波动 0.5+ |
| `diary` | `[YYYY-MM-DD] 当天回顾正文`（上游日记板块的产物） | 0.2~0.5 |
| `correction` | 用户的纠正/要求原话，如 `别再叫我张先生，叫我老张` | **0.8~1.0** |
| `skill_run` | `任务：… 工具：… 结果：成功/失败(原因) 输出摘要：…` | 失败 0.6+，成功 0.2 |
| `document` | 文档正文或其摘录 | 按重要性 |
| `manual` | 任意人工投喂文本 | 按重要性 |

`external_ref` 放上游出处指针（如 `{"system":"myapp","session_id":"…","turn_id":"…"}`），
服务不解释其内容，只原样保存供审计下钻。`occurred_at` 传事件真实发生时间。

**写入门控在上游**：不是每条消息都值得 ingest。寒暄可以不送（省固化成本），
送了也没关系——固化会把无价值的 source 标 `skipped`（遗忘是功能）。

## 2. 召回规范（recall → 注入 LLM 对话）

`POST /spaces/{uid}/recall`，`{"query": "...", "method": "fuzzy|bm25|llm", "max_pages": 3}`

- `query` 用**当前用户输入**（或加上任务概述），不要传整个对话历史。
- method 取舍：`bm25`（默认，毫秒级，词面匹配）→ `fuzzy`（更宽松的词频）→
  `llm`（语义最准，一次 LLM 往返延迟，高价值场景用）。

响应中的 `context_block` 是**可直接注入对话**的标准文本块：

```xml
<recalled_memory>
<memory type="lesson" slug="report-format-mistake" title="把日报发成了周报" updated_at="2026-07-03">
## 情境
…（页面 markdown 正文）…
</memory>
</recalled_memory>
```

注入位置（任选其一，推荐前者）：

1. **当前回合 user 消息之前**拼接（只注当前回合，历史回合不重复注入）；
2. system prompt 尾部。

空召回返回空字符串——**不要注入空块**。`hits[]` 里有逐页的 slug/score/summary，
供上游做自己的过滤或展示（如"我为什么这么回答"的溯源 UI）。

## 3. 固化时机（上游自定）

`POST /spaces/{uid}/consolidate`。服务不内置调度，推荐挂在：
日记生成后（按天）、会话结束时、或 cron。高显著性事件（correction）
之后可立即触发一次小固化，实现"刚说的话不转头就忘"。

## 4. 典型接入循环（伪代码）

```python
# 生成回复前：召回
r = post(f"/spaces/{uid}/recall", json={"query": user_input, "method": "bm25"})
if r["context_block"]:
    prompt = r["context_block"] + "\n\n" + user_input

# 回合收敛后：ingest（异步，失败不阻断对话）
post(f"/spaces/{uid}/sources", json={"kind": "turn",
     "content": f"用户：{user_input}\nAI：{reply}", "salience": salience})

# 合适的时机：固化
post(f"/spaces/{uid}/consolidate", json={"trigger": "session_end"})
```

## 5. 按上游来源删除（delete-by-source）

上游删除原始数据（典型：用户删除一个会话）时，须连带遗忘由它沉淀的记忆——
数据主权优先于"记忆不可删"的拟人比喻，删除语义 = **隐私删除**。匹配键是
ingest 时随 source 存入的 `external_ref`：请求体里给出的键值对做**子集匹配**
（每个键都相等才命中）。至少传一个键，应带上 `system`，推荐
`{"system": "...", "session_id": "..."}`。

**预览（dry-run，不动库）**，供删除确认对话框展示"将遗忘 N 条、M 条因还有
其他来源会保留"：

```
POST /spaces/{uid}/sources/delete-by-ref/preview
{"external_ref": {"system": "myapp", "session_id": "s-42"}}
→ {"matched_sources": 3, "matched_source_ids": [7, 8, 9],
   "pages_to_delete": ["…"], "pages_to_reconsolidate": ["…"]}
```

**执行（不可恢复）**：

```
POST /spaces/{uid}/sources/delete-by-ref
{"external_ref": {"system": "myapp", "session_id": "s-42"}}
→ {"deleted_sources": 3, "deleted_pages": ["…"],
   "reconsolidated_pages": ["…"], "run_id": 12}
```

处置规则：

- 命中的 source **硬删除**（content 是含隐私的全文快照，tombstone/归档
  不满足隐私删除语义）。
- 经证据链（evidence）回收受影响页面：
  - **唯一证据全部来自被删 source** 的页面：删除，含全部修订历史
    （修订正文可能引述被删内容，仅归档不够）；
  - **还有其他证据**的页面：剔除对应 evidence 行，用剩余 source 触发
    针对性重固化重写正文，确保被删内容不再出现在页面与后续修订中，
    结论本身若仍有支撑则保留。
- 返回执行汇总供上游审计留痕；`run_id` 关联本次运行日志（token 开销、
  触碰页面）。重固化失败时**整体回退**（未做任何删除）返回 502，可重试。
- 同一 space 的写入口（本端点与固化）**串行执行**：上游连删多个会话时
  逐个排队，避免后落库者引用先落库者已硬删的 source（外键违规回滚）。
  并发调用是安全的，只是会等待。

删除边界：

- 只回收**直接证据**。页面间 `[[链接]]`、经既往合并产生的间接影响不追溯
  （追溯会退化为删全库）；指向被删页面的链接变悬空——不是错误，交给
  后续固化的悬空愈合/清理。
- 当日日记的重生成/删除是上游职责；wiki-memory 只见到 `kind=diary` 的
  source,同样按上述 external_ref 语义回收。

## 6. 记忆预览

浏览器打开 `/ui`，输入 space uid 即可 Obsidian 式浏览：索引分组、页面正文、
[[互链]] 跳转（悬空标红）、修订历史、出处下钻、来源与固化日志。
按用户列举记忆库：`GET /spaces?owner_id=xxx`。
