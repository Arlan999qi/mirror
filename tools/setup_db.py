"""One-time setup: create all 9 tables in Supabase via direct Postgres connection."""
import os
import psycopg2
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")

STATEMENTS = [
    ("pgvector extension", "CREATE EXTENSION IF NOT EXISTS vector"),

    ("core_profile", """CREATE TABLE IF NOT EXISTS core_profile (
        id INT PRIMARY KEY DEFAULT 1,
        content TEXT NOT NULL,
        structured JSONB NOT NULL,
        version INT DEFAULT 1,
        entries_processed INT DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )"""),

    ("topic_summaries", """CREATE TABLE IF NOT EXISTS topic_summaries (
        id BIGSERIAL PRIMARY KEY,
        topic TEXT NOT NULL UNIQUE,
        summary TEXT NOT NULL,
        key_facts JSONB DEFAULT '[]',
        entry_count INT DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )"""),

    ("entries", """CREATE TABLE IF NOT EXISTS entries (
        id BIGSERIAL PRIMARY KEY,
        telegram_message_id BIGINT UNIQUE,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        entry_date DATE NOT NULL,
        topics TEXT[] DEFAULT '{}',
        importance SMALLINT DEFAULT 5,
        recency_weight NUMERIC(3,2),
        embedding VECTOR(1536),
        rating SMALLINT,
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW()
    )"""),

    ("journal_pages", """CREATE TABLE IF NOT EXISTS journal_pages (
        id BIGSERIAL PRIMARY KEY,
        entry_id BIGINT REFERENCES entries(id),
        image_url TEXT NOT NULL,
        raw_ocr_text TEXT,
        final_text TEXT,
        entry_date DATE,
        themes TEXT[],
        created_at TIMESTAMPTZ DEFAULT NOW()
    )"""),

    ("profile_history", """CREATE TABLE IF NOT EXISTS profile_history (
        id BIGSERIAL PRIMARY KEY,
        profile_type TEXT NOT NULL,
        content TEXT NOT NULL,
        raw_json JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )"""),

    ("daily_questions", """CREATE TABLE IF NOT EXISTS daily_questions (
        id BIGSERIAL PRIMARY KEY,
        question TEXT NOT NULL,
        category TEXT,
        answer TEXT,
        asked_at TIMESTAMPTZ DEFAULT NOW(),
        answered_at TIMESTAMPTZ
    )"""),

    ("usage_tracking", """CREATE TABLE IF NOT EXISTS usage_tracking (
        id BIGSERIAL PRIMARY KEY,
        date DATE NOT NULL,
        entries_count INT DEFAULT 0,
        ai_calls_count INT DEFAULT 0,
        input_tokens INT DEFAULT 0,
        output_tokens INT DEFAULT 0,
        cache_read_tokens INT DEFAULT 0,
        estimated_cost_cents NUMERIC(10,2) DEFAULT 0,
        ratings_positive INT DEFAULT 0,
        ratings_negative INT DEFAULT 0,
        errors_count INT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )"""),

    ("self_reviews", """CREATE TABLE IF NOT EXISTS self_reviews (
        id BIGSERIAL PRIMARY KEY,
        week_start DATE NOT NULL,
        review_text TEXT NOT NULL,
        suggestions JSONB DEFAULT '[]',
        applied BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )"""),

    ("bot_config", """CREATE TABLE IF NOT EXISTS bot_config (
        key TEXT PRIMARY KEY,
        value JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        updated_by TEXT DEFAULT 'system'
    )"""),

    ("bot_config seed data", """INSERT INTO bot_config (key, value) VALUES
        ('recency_weights', '{"30": 1.0, "90": 0.7, "180": 0.4, "365": 0.2, "inf": 0.1}'::jsonb),
        ('topics', '["career", "relationships", "health", "education", "emotions", "finance", "daily_life", "goals"]'::jsonb),
        ('importance_criteria', '"1-3: routine activities, weather, what I ate, small tasks. 4-6: reflections on work, relationship dynamics, health changes, moderate decisions. 7-8: significant realizations, major decisions, emotional breakthroughs. 9-10: life-changing events, core identity shifts, fundamental belief changes."'::jsonb),
        ('rebuild_limit', '500'::jsonb)
    ON CONFLICT (key) DO NOTHING"""),
]

EXPECTED_TABLES = [
    "bot_config", "core_profile", "daily_questions", "entries", "journal_pages",
    "profile_history", "self_reviews", "topic_summaries", "usage_tracking",
]


def main():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set in .env")
        print("Get it from: Supabase Dashboard → Settings → Database → Connection string (URI)")
        print("Format: postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres")
        return

    print("Connecting to Postgres...\n")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
    except Exception as e:
        print(f"ERROR: Could not connect: {e}")
        return

    cur = conn.cursor()
    total = len(STATEMENTS)
    print(f"Running {total} statements...\n")

    for i, (name, sql) in enumerate(STATEMENTS):
        try:
            cur.execute(sql)
            print(f"  [{i+1}/{total}] OK   {name}")
        except Exception as e:
            print(f"  [{i+1}/{total}] FAIL {name}")
            print(f"         {e}")

    # Verify tables exist
    print("\nVerifying tables...")
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    existing = {row[0] for row in cur.fetchall()}
    for t in EXPECTED_TABLES:
        status = "OK" if t in existing else "MISSING"
        print(f"  [{status}] {t}")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
