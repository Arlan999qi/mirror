# Session 1: Core Bot + Silent Memory

## Objective
Build the core Telegram bot that silently saves journal entries, tags them with Claude, and stores them in Supabase. This is the foundation everything else builds on.

## Prerequisites
- Session 0 complete (all credentials verified, DB tables exist)

## Required Inputs
- Verified `.env` with all 5 keys
- 8 Supabase tables (empty, ready)

## Application Files to Build/Verify

### 1. tools/mirror_prompts.py (~150 lines)
All Claude prompts in one file. Key prompts for Session 1:
- `MIRROR_SYSTEM` — anti-sycophancy system prompt
- `TAGGING_PROMPT` — assigns importance (1-10) + topic tags
- `make_tagging_message()` — formats entry for tagging
- `build_context()` — combines profile + topic summaries into context block

Later sessions add: `FEEDBACK_PROMPT`, `INSIGHT_PROMPT`, `QUESTION_PROMPT`, `PROFILE_DISPLAY_PROMPT`

### 2. tools/mirror_memory.py (~250 lines)
3-tier memory management. Key methods:
- `MirrorMemory(dry_run=False)` — constructor, Supabase or SQLite
- `save_entry()` — Tier 3: save raw entry with recency weight
- `update_entry_tags()` — update importance + topics after AI tagging
- `load_profile()` / `save_profile()` — Tier 1: core profile CRUD
- `load_topic()` / `load_all_topics()` / `save_topic()` — Tier 2: topic summaries
- `get_recent_entries()` / `get_entry_count()` — Tier 3 queries
- `track_usage()` / `get_usage_today()` — usage tracking
- `rate_entry()` — thumbs up/down on entries

**SQLite fallback:** When Supabase is unavailable or `--dry-run`, falls back to `.tmp/mirror_fallback.db`.

**Recency weights:**
- <=30 days: 1.0
- 31-90 days: 0.7
- 91-180 days: 0.4
- 181-365 days: 0.2
- 365+ days: 0.1

### 3. tools/mirror_bot.py (~500-600 lines)
Main bot. Key components for Session 1:
- `authorized_only` decorator — silently drops unauthorized users
- `tag_entry()` — calls Claude Sonnet to tag entry (importance + topics)
- `handle_text()` — save -> tag -> "Saved"
- `handle_start()` — welcome message
- `handle_help()` — command list
- `handle_cost()` — show today's usage
- `handle_export()` — download entries as JSON
- `error_handler()` — log errors, don't crash
- `main()` — parse args, init memory/claude, register handlers, run polling

**Entry flow:**
1. Text message received
2. `save_entry()` immediately (zero AI dependency)
3. `tag_entry()` with Claude (importance + topics)
4. `update_entry_tags()` to store tags
5. Reply "Saved"

## Tools Used
- `tools/verify_setup.py` — run before starting to confirm credentials
- `tools/setup_db.py` — if tables need recreation

## Testing
**Tool:** `py -3.13 tools/mirror_bot.py --dry-run`
1. Bot starts without errors
2. Send text message from phone -> "Saved" reply
3. Check logs: entry saved with importance + topics
4. Send 5+ messages -> verify all saved
5. `/cost` -> shows usage stats
6. `/export` -> receive JSON file with all entries

**Unit test (no Telegram needed):**
```python
# Test memory layer
from mirror_memory import MirrorMemory
mem = MirrorMemory(dry_run=True)
eid = mem.save_entry("test", date.today(), entry_type="text")
assert eid is not None

# Test tagging
import mirror_bot
mirror_bot.memory = mem
mirror_bot.claude = anthropic.Anthropic()
importance, topics = mirror_bot.tag_entry("I got promoted today")
assert 5 <= importance <= 10
assert "career" in topics
```

## Expected Output
Bot running, accepting text messages, tagging with Claude, saving to Supabase/SQLite, replying "Saved".

## Edge Cases
- **Claude API down**: `tag_entry()` falls back to (5, ["daily_life"]). Entry still saved.
- **Supabase down**: MirrorMemory falls back to SQLite. Entries queued locally.
- **Unauthorized user**: Message silently dropped, warning logged.
- **Empty message**: Ignored (checked in handle_text).
- **Model ID**: Must be `claude-sonnet-4-6`, not the dated version.

## Known Quirks
- Sonnet pricing: input $3/M tokens, output $15/M tokens, cache read $0.30/M tokens.
- `python-telegram-bot` v22.7 uses async handlers.
- `httpx` and `telegram` loggers are noisy — set to WARNING level.
