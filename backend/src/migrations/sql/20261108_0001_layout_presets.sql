-- Layouts drawn on the layout page (backend/src/media/custom_layout.py).
-- The spec column holds the validated JSON. A task copies it into its own metadata
-- when it is created, so editing or deleting a preset never changes a run in progress.
CREATE TABLE IF NOT EXISTS layout_presets (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    spec JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_layout_presets_user ON layout_presets (user_id, created_at DESC);
