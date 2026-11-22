-- Automations: YouTube channels a user follows. The worker checks each channel every few
-- minutes (backend/src/channel_watch.py) and records every new video as a discovery that
-- waits for the user's approval. Nothing is clipped or posted until the user approves it.
-- allows_clips is the user's own note that the channel's owner lets people cut their videos.
CREATE TABLE IF NOT EXISTS channel_watches (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel_url TEXT NOT NULL,
    title VARCHAR(200) NOT NULL DEFAULT '',
    allows_clips BOOLEAN NOT NULL DEFAULT false,
    active BOOLEAN NOT NULL DEFAULT true,
    last_checked_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, channel_url)
);
CREATE INDEX IF NOT EXISTS ix_channel_watches_due ON channel_watches (active, last_checked_at);

-- status: baseline (already there when the channel was added), pending, approved, dismissed.
CREATE TABLE IF NOT EXISTS channel_discoveries (
    id VARCHAR(36) PRIMARY KEY,
    watch_id VARCHAR(36) NOT NULL REFERENCES channel_watches(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_id VARCHAR(32) NOT NULL,
    url TEXT NOT NULL,
    title VARCHAR(500) NOT NULL DEFAULT '',
    duration_seconds INTEGER,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    task_id VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (watch_id, video_id)
);
CREATE INDEX IF NOT EXISTS ix_channel_discoveries_user ON channel_discoveries (user_id, status, created_at DESC);
