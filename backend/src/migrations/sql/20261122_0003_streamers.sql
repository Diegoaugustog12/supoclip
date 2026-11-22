-- Automations: a streamer groups the channels of one person (their YouTube, Twitch and Kick).
CREATE TABLE IF NOT EXISTS streamers (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_streamers_user_name ON streamers (user_id, lower(name));

ALTER TABLE channel_watches ADD COLUMN IF NOT EXISTS streamer_id VARCHAR(36) REFERENCES streamers(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_channel_watches_streamer ON channel_watches (streamer_id);
