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

    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    content_id TEXT PRIMARY KEY,

    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    saves INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    followers_gained INTEGER DEFAULT 0,

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

CREATE INDEX IF NOT EXISTS idx_metrics_performance_level
ON metrics(performance_level);

CREATE INDEX IF NOT EXISTS idx_metrics_engagement_rate
ON metrics(engagement_rate);
