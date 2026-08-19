CREATE TABLE agent_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('running', 'interrupted', 'awaiting_review', 'completed')),
    focus_keyword TEXT,
    domain TEXT,
    subdomain TEXT,
    topic_summary TEXT,
    title TEXT,
    last_node TEXT,
    error_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_agent_runs_thread_id ON agent_runs(thread_id);
CREATE INDEX idx_agent_runs_status_updated_at ON agent_runs(status, updated_at DESC);

INSERT INTO agent_runs (
    run_id, thread_id, status, focus_keyword, domain, subdomain,
    topic_summary, title, last_node, error_summary, created_at, updated_at
) VALUES (
    17, 'legacy-thread', 'awaiting_review', '旧关键词', 'beauty', 'skincare',
    '旧任务摘要', '旧任务标题', 'HUMAN_REVIEW', NULL,
    '2026-08-19T01:02:03.000000Z', '2026-08-19T01:02:04.000000Z'
);
