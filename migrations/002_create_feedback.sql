-- Feedback table: stores every Q&A interaction so the bot can learn from
-- user ratings (👍/👎) and surface past helpful answers as extra context.

CREATE TABLE IF NOT EXISTS feedback (
    id         uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
    question   text        NOT NULL,
    answer     text        NOT NULL,
    channel_id text        NOT NULL DEFAULT '',
    user_id    text        NOT NULL DEFAULT '',
    rating     text        CHECK (rating IN ('positive', 'negative')),
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS feedback_rating_idx     ON feedback (rating);
CREATE INDEX IF NOT EXISTS feedback_created_at_idx ON feedback (created_at DESC);
