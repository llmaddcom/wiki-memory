-- 一次性迁移（issue #6）：page / pagerevision 增加 hook、happened_on 两列。
-- 项目无迁移框架（db.py create_all 只建缺失的表，不改已有表结构），
-- 存量 SQLite 库需手工执行本脚本；新库 create_all 自动带上两列，无需执行。
--
-- 用法：sqlite3 /path/to/wiki_memory.db < scripts/add_hook_happened_on.sqlite.sql
-- 幂等性：SQLite 的 ALTER TABLE 不支持 IF NOT EXISTS，重复执行会报
-- "duplicate column name"，可安全忽略（说明已迁移过）。
--
-- 存量页 hook 为空、happened_on 为 NULL，由下次固化触及页面时自然回填；
-- 回填期召回 detail=hook 会降级用 summary 前 20 字（hook_fallback=true）。

ALTER TABLE page ADD COLUMN hook VARCHAR NOT NULL DEFAULT '';
ALTER TABLE page ADD COLUMN happened_on DATE;

ALTER TABLE pagerevision ADD COLUMN hook VARCHAR NOT NULL DEFAULT '';
ALTER TABLE pagerevision ADD COLUMN happened_on DATE;
