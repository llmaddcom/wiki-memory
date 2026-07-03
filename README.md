# wiki-memory

Wiki 式长期记忆服务（独立、不耦合任何上游产品）。核心思想：**记忆不是日志的别名，
是被固化过程蒸馏出来的认识。**

不可变的经历材料（source）由内置的 LLM 固化引擎（"睡眠"）蒸馏成一个分型、互链、
带修订历史的 wiki；召回策略可选（fuzzy / bm25 / llm）。对应人类记忆系统：

```
上游(日记/对话/纠正/技能执行)          ← 情节来源，永不被本服务修改
  → source        不可变快照            ← 海马体输入
  → consolidation "睡眠"固化（唯一写通路）← 海马体回放→皮层
  → page          当前认识（六型分类）    ← 皮层语义记忆
  → page_revision + evidence            ← 可解释、可回滚、可审计
  → page_link     [[链接]] 软图谱        ← 联想结构（甩掉重型知识图谱）
```

设计原则（也写进了固化 prompt，见 `wiki_memory/consolidation/prompts.py`）：

- **蒸馏，不转录**：绝大多数日常内容不值得留下，零操作是合法结果（遗忘是功能）。
- **改写优先于新增**：新经历先尝试更新已有认识，wiki 越用越稠密而不是越用越臃肿。
- **矛盾显式化**：认识变化写在页面里（"曾认为 X，现在 Y"），不静默覆盖。
- **出处可下钻**：每版认识经 evidence 指回 source，回答"凭什么这么认为"。

## 目录结构

```
wiki_memory/
  models/            一张表一个文件（space/source/page/page_revision/evidence/page_link/consolidation_run）
  repositories/      一张表一个仓储文件，封装常用 CRUD，上层不手写 select
  consolidation/     固化引擎（两阶段：选页读全文 → 产出操作）+ prompt（记忆哲学所在）
  recall/            召回策略：fuzzy（词频）/ bm25（默认）/ llm（最准最慢）+ 对话注入格式
  llm/               LLM 可替换轴（Protocol + OpenAI 兼容适配器）
  api/               deps 装配 / schemas DTO / routes 一类资源一个文件
  web/index.html     /ui 记忆预览（Obsidian 风格，零依赖单文件）
docs/contract.md     对外契约：输入内容规范 + 召回注入格式 + 接入循环
tests/               FakeLLM 端到端（不需要真实 LLM）
```

## 页面类型

| type | 含义 | 正文模板 |
|---|---|---|
| `lesson` | 犯过的错 | 情境 / 错在哪 / 为什么 / 下次怎么做 |
| `event` | 大事记 | 经过 / 影响 |
| `person` | 人物画像 | 关系 / 偏好 / 禁忌 / 承诺与约定 |
| `belief` | 认识/论点（带 confidence） | 结论 / 依据 / 已知反例或不确定性 |
| `procedure` | 程序性经验 | 适用场景 / 做法 / 已知失败模式 |
| `self` | 数字人自我/成长状态 | 当前状态 / 变化及原因 |

## 身份与隔离

一个 space = 一份独立记忆库，身份是 `uid`：

- 上游自带 UUID：`POST /spaces {"uid": "your-uuid"}`（幂等）；
- 按业务标签：`POST /spaces {"owner_id": "u1", "subject_id": "roleA"}`（幂等 get-or-create）；
- 全不传：服务生成新 uid。

按用户列举（记忆预览入口）：`GET /spaces?owner_id=u1`。

## 召回

`POST /spaces/{uid}/recall`，`method` 三档按精度/速度取舍：

| method | 原理 | 延迟 | 适用 |
|---|---|---|---|
| `bm25`（默认） | 内存 BM25，中文二元组分词 | 毫秒 | 常规回合 |
| `fuzzy` | 加权词频（标题×3/摘要×2/正文×1） | 毫秒 | 宽松关键词 |
| `llm` | LLM 读索引点名页面 | 一次 LLM 往返 | 高价值场景 |

响应含 `context_block`——可直接注入 LLM 对话的 `<recalled_memory>` 文本块
（格式契约见 `docs/contract.md`）。向量检索是预留的下一档，页面规模超出关键词方法时再上。

## 运行

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env   # 配 WIKIMEM_LLM_BASE_URL / MODEL；换 Postgres 改 WIKIMEM_DATABASE_URL
.venv/bin/uvicorn wiki_memory.main:app --port 8020
# 浏览器打开 http://127.0.0.1:8020/ui 预览记忆；/docs 看 OpenAPI
.venv/bin/python -m pytest   # 测试（FakeLLM，不需要真实 LLM）
```

## API 速览

```
POST /spaces                                身份见"身份与隔离"；GET /spaces?owner_id= 列举
POST /spaces/{uid}/sources                  ingest 经历材料（格式规范见 docs/contract.md）
GET  /spaces/{uid}/sources?status=pending

POST /spaces/{uid}/consolidate              触发固化（上游挂日记后/会话结束/cron 均可）
GET  /spaces/{uid}/runs                     固化日志（消费的 source、动过的页、token 开销）

GET  /spaces/{uid}/index                    索引页（type/slug/title/summary 一行一页）
GET  /spaces/{uid}/pages/{slug}             页面全文；/revisions 修订史；/evidence 出处链
POST /spaces/{uid}/pages/{slug}/rollback    {seq} 回滚（拷旧版为新版，历史不丢）
GET  /spaces/{uid}/links?dangling=true      软图谱边；悬空链接 = "值得建页"信号

POST /spaces/{uid}/recall                   {query, method, max_pages} → hits + context_block
GET  /ui                                    记忆预览界面
```

## 明确不做的（当前版本）

- 定时调度（上游用 cron 调 consolidate 即可）；
- 向量/embedding 检索（预留下一档）；
- 固化引擎与回滚之外的页面写入 API（wiki 由 LLM 维护，人只审阅与回滚）。
