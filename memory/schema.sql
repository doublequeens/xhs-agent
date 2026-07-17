PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS contents (
    content_id TEXT PRIMARY KEY,

    status TEXT NOT NULL DEFAULT 'generated',
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',

    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    published_at TEXT,

    post_id TEXT,
    url TEXT,

    topic_id TEXT,
    topic TEXT NOT NULL,

    angle_id TEXT,
    angle TEXT,

    domain TEXT,
    subdomain TEXT,
    content_intent TEXT,
    profile_version TEXT,
    risk_level TEXT,

    target_group TEXT,
    core_pain TEXT,

    title TEXT,
    cover_copy TEXT,

    content TEXT,
    hashtags_json TEXT,

    content_format TEXT,
    visual_style TEXT,
    card_count INTEGER,
    storyboards TEXT,

    image_paths_json TEXT,

    strategy_tags_json TEXT,
    compliance_status TEXT,

    embedding_text TEXT,

    metadata_json TEXT,

    narrative_form TEXT,
    narrative_signature TEXT,
    template_family TEXT,
    frame_plan_signature TEXT,
    density_profile TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    content_id TEXT PRIMARY KEY,

    impressions INTEGER,
    views INTEGER DEFAULT 0,
    cover_click_rate REAL,
    likes INTEGER DEFAULT 0,
    saves INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    followers_gained INTEGER DEFAULT 0,
    avg_watch_time_seconds INTEGER,
    danmaku_count INTEGER,

    like_rate REAL DEFAULT 0,
    save_rate REAL DEFAULT 0,
    comment_rate REAL DEFAULT 0,
    share_rate REAL DEFAULT 0,
    engagement_rate REAL DEFAULT 0,

    performance_level TEXT DEFAULT 'unknown',

    updated_at TEXT NOT NULL,

    FOREIGN KEY (content_id) REFERENCES contents(content_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metrics_history (
    content_id TEXT NOT NULL,
    collected_date TEXT NOT NULL,
    source TEXT NOT NULL,

    impressions INTEGER,
    views INTEGER,
    cover_click_rate REAL,
    likes INTEGER,
    saves INTEGER,
    comments INTEGER,
    shares INTEGER,
    followers_gained INTEGER,
    avg_watch_time_seconds INTEGER,
    danmaku_count INTEGER,

    like_rate REAL,
    save_rate REAL,
    comment_rate REAL,
    share_rate REAL,
    engagement_rate REAL,

    performance_level TEXT,
    collected_at TEXT NOT NULL,

    PRIMARY KEY (content_id, collected_date),
    FOREIGN KEY (content_id) REFERENCES contents(content_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metrics_collection_runs (
    scheduled_date TEXT PRIMARY KEY,
    execution_date TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    exported_rows INTEGER NOT NULL DEFAULT 0,
    updated_rows INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    ambiguous_rows INTEGER NOT NULL DEFAULT 0,
    matched_post_ids INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_metrics_collection_runs_execution_date
ON metrics_collection_runs(execution_date);

CREATE TABLE IF NOT EXISTS memory_events (
    event_id TEXT PRIMARY KEY,
    content_id TEXT,
    event_type TEXT NOT NULL,
    event_time TEXT NOT NULL,
    payload_json TEXT,

    FOREIGN KEY (content_id) REFERENCES contents(content_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_contents_created_at
ON contents(created_at);

CREATE INDEX IF NOT EXISTS idx_contents_published_at
ON contents(published_at);

CREATE INDEX IF NOT EXISTS idx_contents_topic
ON contents(topic);

CREATE INDEX IF NOT EXISTS idx_contents_angle
ON contents(angle);

CREATE INDEX IF NOT EXISTS idx_contents_domain_subdomain
ON contents(domain, subdomain);

CREATE INDEX IF NOT EXISTS idx_contents_domain_subdomain_created_at
ON contents(domain, subdomain, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_metrics_performance_level
ON metrics(performance_level);

CREATE INDEX IF NOT EXISTS idx_metrics_engagement_rate
ON metrics(engagement_rate);

CREATE TABLE IF NOT EXISTS trend_signals (
    signal_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT,
    raw_title TEXT,
    normalized_signal TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    domain TEXT NOT NULL,
    subdomain TEXT NOT NULL,
    why_now TEXT NOT NULL,
    domain_translation TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    avoid_topics TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL,
    active_from TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trend_signals_scope_active
ON trend_signals(domain, subdomain, active_from, expires_at);

CREATE TABLE IF NOT EXISTS trend_collection_runs (
    collection_date TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    collected_signals INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS topic_generation_traces (
    run_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    subdomain TEXT NOT NULL,
    trends_num INTEGER NOT NULL,
    signals_used TEXT NOT NULL,
    creative_briefs_sampled TEXT NOT NULL,
    generated_candidates_count INTEGER NOT NULL,
    filtered_candidates_count INTEGER NOT NULL,
    final_trends TEXT NOT NULL,
    diversity_metrics TEXT NOT NULL,
    degraded_reason TEXT,
    created_at TEXT NOT NULL
);
