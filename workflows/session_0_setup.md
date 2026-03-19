# Session 0: Project Setup

## Objective
Get all infrastructure ready: credentials, database tables, Python dependencies, verified connections.

## Required Inputs
- Telegram bot token (from @BotFather)
- Telegram user ID (from @userinfobot)
- Supabase project URL + service_role key
- Anthropic API key

## Steps

### 1. Install Python dependencies
```
py -3.13 -m pip install python-telegram-bot supabase anthropic python-dotenv
```

### 2. Populate .env
All 5 keys must be set in `.env` (see `.env.example` for template):
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_USER_ID`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `ANTHROPIC_API_KEY`

### 3. Create database tables
**Tool:** `tools/setup_db.py`
```
py -3.13 tools/setup_db.py
```
Creates 8 tables + pgvector extension in Supabase. Verifies all tables exist.

### 4. Verify all connections
**Tool:** `tools/verify_setup.py`
```
py -3.13 tools/verify_setup.py
```
Checks: Telegram bot token, Supabase connection, Anthropic API key, Telegram user ID.

## Expected Output
All 4 checks show `[OK]`. All 8 tables exist in Supabase.

## Edge Cases
- **setup_db.py returns 404 on `/pg/query`**: Tables may already exist (created via Supabase dashboard). Verify manually using the supabase Python client.
- **Supabase service_role key vs anon key**: Must use `service_role` key. The anon key will fail on writes.
- **Model ID**: Use `claude-sonnet-4-6` (NOT `claude-sonnet-4-6-20250514` — that returns 404).

## Lessons Learned
- The Supabase `/pg/query` REST endpoint is not available on all instances. If DDL needs to be run, use the Supabase Dashboard SQL Editor or connect via psycopg2.
- Always verify tables exist after setup_db.py using the supabase Python client directly.
