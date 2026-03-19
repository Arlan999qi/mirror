# Agent Instructions

**WAT framework** (Workflows, Agents, Tools): AI handles reasoning, deterministic scripts handle execution.

- `workflows/` — Markdown SOPs (instructions for each task)
- `tools/` — Python scripts (execution). Check here first before building anything new
- `.env` — All secrets. Never store elsewhere
- `.tmp/` — Disposable intermediate files

**Your role:** Read workflows, run tools in sequence, handle failures, improve workflows when you learn something new. Don't create/overwrite workflows without asking.

**On errors:** Read full trace → fix script → retest (check with user before re-running paid API calls) → update workflow with learnings.

---

# Mirror — Personal AI Journal Bot

Personal Telegram journal bot: silently stores text + handwritten journal photos (OCR), builds 3-tier memory, gives honest feedback only when asked. Cost: ~$1-2/month.

## Non-Negotiable Rules

1. **SILENT BY DEFAULT** — entries get "Saved" only. No unsolicited feedback.
2. **HONESTY ABOVE ALL** — no softening, no crisis mode. Truth only.
3. **PERMANENT MEMORY** — raw data never deleted.
4. **RECENCY MATTERS** — last 1-3 months carry ~90% weight.
5. **FULL CONTEXT** — load Tier 1 + relevant Tier 2 before any AI output.
6. **MULTILINGUAL** — entries in Russian/English/mixed, outputs in English.

## Tech Stack

| Component | Tool |
|-----------|------|
| Interface | Telegram Bot (`python-telegram-bot` v21+) |
| Database | Supabase (Postgres + pgvector), SQLite fallback |
| AI | Claude Sonnet 4.6 + prompt caching |
| OCR | Claude Vision (built into Sonnet) |
| Python | 3.13 (`py -3.13`) |
| Hosting | Windows PC (dev) / Oracle Cloud Always-Free (prod) |

## Bot Commands

| Command | What it does |
|---------|-------------|
| Send text | **SILENT** — saved, bot replies "Saved" only |
| Send photo | OCR → show text → user confirms/edits → saves |
| `/start` | Onboarding interview (20-30 questions) |
| `/question [N]` | N personalized questions (default 1) |
| `/feedback [topic]` | Honest feedback using relevant memory tiers |
| `/insight` | One key insight about you right now |
| `/report` | Full Self-Knowledge Report (HTML) |
| `/profile` | View what the bot knows about you |
| `/schedule [time] [N]` | Daily auto-questions. `/schedule off` to disable |
| `/cost` | Today's API usage and estimated spend |
| `/export` | Download all entries as JSON |

## 3-Tier Memory

| Tier | What | When Loaded |
|------|------|-------------|
| **Tier 1** | Core profile (~1-1.5K tokens): identity, values, relationships, goals, blind spots | ALWAYS (cached) |
| **Tier 2** | Topic summaries (~500-1K each): career, relationships, health, education, emotions, finance, daily_life, goals | On demand per command |
| **Tier 3** | Raw entries with dates | Specific detail lookups only |

Recency weights and rebuild logic → see `tools/mirror_memory.py:_recency_weight()`

## File Map

```
tools/
  mirror_bot.py        # Main entry point — all handlers, commands, jobs
  mirror_memory.py     # 3-tier memory: save/load/rebuild, Supabase + SQLite fallback
  mirror_prompts.py    # All Claude prompts (system, tagging, OCR, feedback, reports)
  mirror_vision.py     # Photo OCR + edit-before-save flow
  mirror_reports.py    # HTML Self-Knowledge Report generator
  setup_db.py          # Create all DB tables (schema is here)
  verify_setup.py      # Verify credentials + connections
  rebuild_profile.py   # Manual Tier 1 + Tier 2 rebuild
  run_self_review.py   # Manual weekly self-review trigger
  test_ocr.py          # OCR test script
  deploy_oracle.py     # Oracle Cloud deployment helper

workflows/             # Session SOPs (session_0 through session_5)
.claude/skills/        # 6 local skills (Telegram, PDF, memory, OCR, RAG)
.tmp/                  # Disposable: fallback DB, reports, exports, deploy scripts
```

## Key Implementation Details

- **Anti-sycophancy prompt** → `mirror_prompts.py:MIRROR_SYSTEM`
- **Database schema (8 tables)** → `setup_db.py` (core_profile, topic_summaries, entries, journal_pages, profile_history, daily_questions, usage_tracking, self_reviews)
- **Entry flow:** save immediately → Sonnet tags importance (1-10) + topics → score 7-10 merges to Tier 1, 4-6 to Tier 2, 1-3 stays Tier 3. Incremental update every 5 entries, weekly full rebuild.
- **OCR flow:** photo → Claude Vision → show text → user confirms/edits → save to entries + journal_pages
- **Env vars** → see `.env.example` for required keys
- **Security:** `@authorized_only` decorator (checks `TELEGRAM_USER_ID`), service_role key, never log entry content
- **Testing:** `--dry-run` flag uses local SQLite instead of Supabase
- **Self-improvement:** weekly self-review (automatic), monthly improvement suggestions via Telegram. Details in `mirror_memory.py`

## Build Status

Sessions 0-5 complete. All core features implemented and deployed.
Session history → `workflows/session_*.md`
