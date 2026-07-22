-- 一次性迁移（记忆优化 P0-3）：page 增加 hit_count / last_hit_at 两列（usage 命中记录）。
-- 项目无迁移框架（db.py create_all 只建缺失的表，不改已有表结构），
-- 存量 Postgres 库需手工执行本脚本；新库 create_all 自动带上两列，无需执行。
-- 同批新增的 keyword / pagekeyword / pageembedding 三张**新表**由 create_all
-- 启动时自建，不需要 SQL。
--
-- 用法：psql "$DATABASE_URL" -f scripts/add_usage_columns.postgres.sql
-- IF NOT EXISTS 保证幂等，重复执行安全。
--
-- 存量页 hit_count=0、last_hit_at=NULL，由召回命中 / 联想展开自然累加。

ALTER TABLE page ADD COLUMN IF NOT EXISTS hit_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE page ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMP;
