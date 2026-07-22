-- 一次性迁移（记忆优化 P0-3）：page 增加 hit_count / last_hit_at 两列（usage 命中记录）。
-- 项目无迁移框架（db.py create_all 只建缺失的表，不改已有表结构），
-- 存量 SQLite 库需手工执行本脚本；新库 create_all 自动带上两列，无需执行。
-- 同批新增的 keyword / pagekeyword / pageembedding 三张**新表**由 create_all
-- 启动时自建，不需要 SQL。
--
-- 用法：sqlite3 /path/to/wiki_memory.db < scripts/add_usage_columns.sqlite.sql
-- 幂等性：SQLite 的 ALTER TABLE 不支持 IF NOT EXISTS，重复执行会报
-- "duplicate column name"，可安全忽略（说明已迁移过）。

ALTER TABLE page ADD COLUMN hit_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE page ADD COLUMN last_hit_at TIMESTAMP;
