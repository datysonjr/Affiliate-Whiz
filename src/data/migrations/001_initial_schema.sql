-- 001_initial_schema.sql
-- Core tables for OpenClaw local dev mode.

-- Agent run history: every plan->execute->report cycle is recorded here.
CREATE TABLE IF NOT EXISTS agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL UNIQUE,
    agent_name      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending|running|success|failed|skipped
    dry_run         INTEGER NOT NULL DEFAULT 1,
    plan_output     TEXT,                                -- JSON
    exec_output     TEXT,                                -- JSON
    report_output   TEXT,                                -- JSON
    error           TEXT,
    duration_s      REAL    DEFAULT 0.0,
    started_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);

-- Task queue persistence: tasks that are enqueued for processing.
CREATE TABLE IF NOT EXISTS task_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT    NOT NULL UNIQUE,
    agent_name      TEXT    NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 5,
    payload         TEXT,           -- JSON
    status          TEXT    NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
    enqueued_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at      TEXT,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status);

-- Sites managed by OpenClaw.
CREATE TABLE IF NOT EXISTS sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT    NOT NULL UNIQUE,
    niche           TEXT    NOT NULL DEFAULT '',
    cms_type        TEXT    NOT NULL DEFAULT 'wordpress',
    status          TEXT    NOT NULL DEFAULT 'active',
    posts_count     INTEGER NOT NULL DEFAULT 0,
    monthly_traffic INTEGER NOT NULL DEFAULT 0,
    monthly_revenue REAL    NOT NULL DEFAULT 0.0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Content pieces (articles, reviews, etc.).
CREATE TABLE IF NOT EXISTS content (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    slug            TEXT    NOT NULL,
    site_id         INTEGER REFERENCES sites(id),
    status          TEXT    NOT NULL DEFAULT 'draft',  -- draft|review|approved|published|archived
    content_type    TEXT    NOT NULL DEFAULT 'blog_post',
    word_count      INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT    NOT NULL DEFAULT '',
    primary_keyword TEXT    NOT NULL DEFAULT '',
    seo_score       REAL    DEFAULT 0.0,
    published_at    TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_content_site ON content(site_id);
CREATE INDEX IF NOT EXISTS idx_content_status ON content(status);

-- Affiliate offers tracked by the system.
CREATE TABLE IF NOT EXISTS offers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    merchant        TEXT    NOT NULL DEFAULT '',
    network         TEXT    NOT NULL DEFAULT '',
    url             TEXT    NOT NULL DEFAULT '',
    commission_rate REAL    NOT NULL DEFAULT 0.0,
    score           INTEGER NOT NULL DEFAULT 0,
    tier            TEXT    NOT NULL DEFAULT 'C',  -- A|B|C|rejected
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_offers_tier ON offers(tier);

-- System events log (for audit trail).
CREATE TABLE IF NOT EXISTS system_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT 'system',
    message         TEXT    NOT NULL DEFAULT '',
    details         TEXT,           -- JSON
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_type ON system_events(event_type);
