-- "subjects" workflow: one compilation per recurring subject of a long video.
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_workflow_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_workflow_check
    CHECK (workflow IN ('highlights', 'series', 'topic', 'recap', 'trailer', 'subjects'));
