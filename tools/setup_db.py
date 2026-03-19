"""One-time setup: create all 8 tables in Supabase."""
import os
import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",

    """CREATE TABLE IF NOT EXISTS core_profile (
        id INT PRIMARY KEY DEFAULT 1,
        content TEXT NOT NULL,
        structured JSONB NOT NULL,
        version INT DEFAULT 1,
        entries_processed INT DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )""",

    """CREATE TABLE IF NOT EXISTS topic_summaries (
        id BIGSERIAL PRIMARY KEY,
        topic TEXT NOT NULL UNIQUE,
        summary TEXT NOT NULL,
        key_facts JSONB DEFAULT '[]',
        entry_count INT DEFAULT 0,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )""",

    """CREATE TABLE IF NOT EXISTS entries (
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
    )""",

    """CREATE TABLE IF NOT EXISTS journal_pages (
        id BIGSERIAL PRIMARY KEY,
        entry_id BIGINT REFERENCES entries(id),
        image_url TEXT NOT NULL,
        raw_ocr_text TEXT,
        final_text TEXT,
        entry_date DATE,
        themes TEXT[],
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",

    """CREATE TABLE IF NOT EXISTS profile_history (
        id BIGSERIAL PRIMARY KEY,
        profile_type TEXT NOT NULL,
        content TEXT NOT NULL,
        raw_json JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",

    """CREATE TABLE IF NOT EXISTS daily_questions (
        id BIGSERIAL PRIMARY KEY,
        question TEXT NOT NULL,
        category TEXT,
        answer TEXT,
        asked_at TIMESTAMPTZ DEFAULT NOW(),
        answered_at TIMESTAMPTZ
    )""",

    """CREATE TABLE IF NOT EXISTS usage_tracking (
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
    )""",

    """CREATE TABLE IF NOT EXISTS self_reviews (
        id BIGSERIAL PRIMARY KEY,
        week_start DATE NOT NULL,
        review_text TEXT NOT NULL,
        suggestions JSONB DEFAULT '[]',
        applied BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
]


def run_sql(sql):
    """Execute SQL via Supabase's pg-meta endpoint."""
    resp = requests.post(
        f"{SUPABASE_URL}/pg/query",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        },
        json={"query": sql},
        timeout=15,
    )
    return resp


def main():
    print("Creating 8 tables + pgvector extension...\n")

    for i, sql in enumerate(STATEMENTS):
        name = sql.strip().split("\n")[0][:60]
        resp = run_sql(sql)
        if resp.status_code in (200, 201):
            print(f"  [{i+1}/{len(STATEMENTS)}] OK   {name}")
        else:
            print(f"  [{i+1}/{len(STATEMENTS)}] FAIL {name}")
            print(f"         {resp.status_code}: {resp.text[:200]}")

    # Verify tables exist
    print("\nVerifying tables...")
    resp = run_sql("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    if resp.status_code == 200:
        tables = [row.get("table_name", row) for row in resp.json()]
        expected = ["core_profile", "daily_questions", "entries", "journal_pages",
                    "profile_history", "self_reviews", "topic_summaries", "usage_tracking"]
        for t in expected:
            status = "OK" if t in tables else "MISSING"
            print(f"  [{status}] {t}")
    else:
        print(f"  Could not verify: {resp.status_code} {resp.text[:200]}")


if __name__ == "__main__":
    main()
