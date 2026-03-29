-- ============================================================
-- Migration 006: Kanban 状态扩展
-- 核心问题：001_init.sql 的 CHECK 约束限制了 status 可选值，
-- SQLite 不支持修改 CHECK，必须重建表。
-- 注意：使用 IF NOT EXISTS / IF EXISTS 保证幂等性，
--       因为 executescript() 自动提交，部分执行后重跑不会报错。
-- ============================================================

-- 关闭外键约束（DROP TABLE issues 时 executions 表有 FK 引用会报错）
PRAGMA foreign_keys=OFF;

-- 0. 清理上次可能残留的中间表
DROP TABLE IF EXISTS issues_new;

-- 1. 重建 issues 表（移除旧 CHECK 约束，状态校验改由应用层枚举负责）
CREATE TABLE issues_new (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  branch_name TEXT,
  human_instruction TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  workspace TEXT,
  pr_url TEXT,
  failure_reason TEXT,
  priority TEXT DEFAULT 'medium',
  spec TEXT
);

-- 2. 迁移数据，同时将 failed → waiting_human
INSERT INTO issues_new (id, title, description, status, branch_name, human_instruction,
                        created_at, updated_at, workspace, pr_url, failure_reason)
SELECT id, title, description,
       CASE WHEN status = 'failed' THEN 'waiting_human' ELSE status END,
       branch_name, human_instruction,
       created_at, updated_at, workspace, pr_url, failure_reason
FROM issues;

-- 3. 替换旧表
DROP TABLE issues;
ALTER TABLE issues_new RENAME TO issues;

-- 4. 重建索引
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);

-- 5. 恢复外键约束
PRAGMA foreign_keys=ON;
