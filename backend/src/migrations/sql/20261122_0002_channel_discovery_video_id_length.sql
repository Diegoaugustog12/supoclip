-- Kick video ids are 36-character UUIDs.
ALTER TABLE channel_discoveries ALTER COLUMN video_id TYPE VARCHAR(64);
