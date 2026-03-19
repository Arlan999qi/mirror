# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This architecture separates concerns so that probabilistic AI handles reasoning while deterministic code handles execution. That separation is what makes this system reliable.

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and how to handle edge cases
- Written in plain language, the same way you'd brief someone on your team

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You're responsible for intelligent coordination.
- Read the relevant workflow, run tools in the correct sequence, handle failures gracefully, and ask clarifying questions when needed
- You connect intent to execution without trying to do everything yourself
- Example: If you need to pull data from a website, don't attempt it directly. Read `workflows/scrape_website.md`, figure out the required inputs, then execute `tools/scrape_single_site.py`

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, data transformations, file operations, database queries
- Credentials and API keys are stored in `.env`
- These scripts are consistent, testable, and fast

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, you're down to 59% success after just five steps. By offloading execution to deterministic scripts, you stay focused on orchestration and decision-making where you excel.

## How to Operate

**1. Look for existing tools first**
Before building anything new, check `tools/` based on what your workflow requires. Only create new scripts when nothing exists for that task.

**2. Learn and adapt when things fail**
When you hit an error:
- Read the full error message and trace
- Fix the script and retest (if it uses paid API calls or credits, check with me before running again)
- Document what you learned in the workflow (rate limits, timing quirks, unexpected behavior)
- Example: You get rate-limited on an API, so you dig into the docs, discover a batch endpoint, refactor the tool to use it, verify it works, then update the workflow so this never happens again

**3. Keep workflows current**
Workflows should evolve as you learn. When you find better methods, discover constraints, or encounter recurring issues, update the workflow. That said, don't create or overwrite workflows without asking unless I explicitly tell you to. These are your instructions and need to be preserved and refined, not tossed after one use.

## The Self-Improvement Loop

Every failure is a chance to make the system stronger:
1. Identify what broke
2. Fix the tool
3. Verify the fix works
4. Update the workflow with the new approach
5. Move on with a more robust system

This loop is how the framework improves over time.

## File Structure

**What goes where:**
- **Deliverables**: Final outputs go to cloud services (Google Sheets, Slides, etc.) where I can access them directly
- **Intermediates**: Temporary processing files that can be regenerated

**Directory layout:**
```
.tmp/           # Temporary files (scraped data, intermediate exports). Regenerated as needed.
tools/          # Python scripts for deterministic execution
workflows/      # Markdown SOPs defining what to do and how
.env            # API keys and environment variables (NEVER store secrets anywhere else)
credentials.json, token.json  # Google OAuth (gitignored)
```

**Core principle:** Local files are just for processing. Anything I need to see or use lives in cloud services. Everything in `.tmp/` is disposable.

## Bottom Line

You sit between what I want (workflows) and what actually gets done (tools). Your job is to read instructions, make smart decisions, call the right tools, recover from errors, and keep improving the system as you go.

Stay pragmatic. Stay reliable. Keep learning.

---

# Mirror — Personal AI Journal Bot

## What This Is

"Mirror" is a personal Telegram journal bot that:
- Silently stores everything you write (text + handwritten journal photos via OCR)
- Builds a 3-tier memory system that understands who you are
- Gives ruthlessly honest feedback ONLY when asked
- Continuously improves itself from usage feedback
- Costs ~$1-2/month total

## Non-Negotiable Rules

1. **SILENT BY DEFAULT** — journal entries get "Saved" response only. No unsolicited feedback ever.
2. **HONESTY ABOVE ALL** — no crisis mode, no softening, no behavior changes based on emotional content. Truth only. Always.
3. **PERMANENT MEMORY** — raw data never deleted. Compacted summaries exist for fast loading only.
4. **RECENCY MATTERS** — recent entries (last 1-3 months) carry ~90% weight. You are who you are NOW.
5. **FULL CONTEXT** — before any AI output, load Tier 1 profile + relevant Tier 2 topics.
6. **MULTILINGUAL** — entries in Russian/English/mixed, outputs in English.

## Status

**Current session:** All sessions complete. Deploy to Oracle Cloud when ready.
**Build order:** Session 0 (setup) ✅ → Session 1 (core bot) ✅ → Session 2 (vision + questions) ✅ → Session 3 (onboarding) ✅ → Session 4 (reports + commands) ✅ → Session 5 (deploy + self-improvement) ✅

## Cost: ~$1-2/month

| Component | Cost | Details |
|-----------|------|---------|
| Hosting | $0 | Windows PC during dev -> Oracle Cloud Always-Free for production |
| Database | $0 | Supabase free tier (500MB DB, 1GB storage) |
| AI | ~$1-2/mo | Claude Sonnet 4.6 for everything + prompt caching (90% savings) |
| OCR | included | Claude Vision is part of Sonnet pricing |

## Tech Stack

| Component | Tool |
|-----------|------|
| Interface | Telegram Bot (`python-telegram-bot` v21+) |
| Hosting (dev) | User's Windows PC |
| Hosting (prod) | Oracle Cloud Always-Free |
| Database | Supabase (Postgres + pgvector) |
| File Storage | Supabase Storage |
| AI | Claude Sonnet 4.6 + prompt caching |
| OCR | Claude Vision (built into Sonnet) |
| Scheduling | python-telegram-bot JobQueue |
| Voice Input | Wispr Flow (user's existing tool) |
| Python | 3.13 (`py -3.13`) |

## Bot Commands (10 commands)

| Command | What it does |
|---------|-------------|
| Send text | **SILENT** — saved. Bot replies "Saved" only. |
| Send photo | OCR -> **shows extracted text -> user confirms/edits -> then saves** |
| `/start` | Welcome + onboarding interview (20-30 questions) |
| `/question [N]` | N personalized questions (default 1, e.g. `/question 5`). Based on full profile. |
| `/feedback [topic]` | Ruthlessly honest feedback (loads relevant memory tiers) |
| `/insight` | One key insight about you right now |
| `/report` | Full Self-Knowledge Report (HTML file) |
| `/profile` | View what the bot "knows" about you |
| `/schedule [time] [N]` | Set daily auto-questions. E.g. `/schedule 8:00 5`. `/schedule off` to disable. |
| `/cost` | Today's API usage and estimated monthly spend |
| `/export` | Download all entries as JSON file |

## 3-Tier Memory Architecture

```
TIER 1: Core Profile (~1-1.5K tokens) — ALWAYS loaded, cached
  Identity, values, personality patterns (CURRENT self)
  Key relationships, life goals, active projects
  Core contradictions and blind spots
  How you've changed (brief evolution notes)

TIER 2: Topic Summaries (~500-1K tokens each) — loaded ON DEMAND
  career | relationships | health | education
  emotions | finance | daily_life | goals
  (Each summary weighted toward RECENT entries)

TIER 3: Raw Entries — loaded only for SPECIFIC detail lookups
  All entries with original dates. Never deleted.
```

### Temporal Weighting

Recent entries matter most. Weight formula:
- Last 30 days: **1.0** (full importance)
- 1-3 months ago: **0.7**
- 3-6 months ago: **0.4**
- 6-12 months ago: **0.2**
- 12+ months ago: **0.1**

Tier 1 is rebuilt primarily from recent entries. Old beliefs only survive if echoed in recent writing. During feedback, system prompt says: "Weight recent entries at ~90% importance. Older entries are historical context only."

### Entry Flow

1. Entry saved immediately with `entry_date` (zero AI needed — works even if Claude is down)
2. Sonnet assigns importance (1-10) + tags topics (recency-adjusted)
3. Score 7-10 -> merged into Tier 1. Score 4-6 -> merged into Tier 2. Score 1-3 -> stays in Tier 3.
4. Incremental update after every 5 entries. Weekly full rebuild.

### What Each Command Loads

| Command | Tiers Loaded |
|---------|-------------|
| `/question` | Tier 1 + recent topics |
| `/feedback career` | Tier 1 + "career" Tier 2 |
| `/feedback` (general) | Tier 1 + all Tier 2 summaries |
| `/report` | Tier 1 + all Tier 2 + select Tier 3 highlights |

## Photo OCR: Edit-Before-Save Flow

Russian cursive is hard for OCR. To ensure near-100% accuracy:

1. User sends journal photo
2. Claude Vision extracts the text + the date written on the page
3. Bot sends back: "Here's what I read: {text}. Reply with corrections or send check to save as-is"
4. User confirms, corrects, or provides specific fixes
5. Final corrected text saved to entries + journal_pages

## Self-Improvement Feedback Loop

- After each AI response, bot asks for thumbs up/down rating
- `usage_tracking` table logs: tokens, costs, ratings, errors per day
- Weekly (automatic): Sonnet reviews ratings, errors, usage patterns -> saved to `self_reviews` table
- Monthly: Sonnet sends improvement suggestions via Telegram
- Auto-improves: topic weights, importance scores, cache optimization
- Needs approval: system prompt changes, topic merging, feature suggestions

## Database Schema (8 tables)

```sql
-- Tier 1: Core profile (single row)
CREATE TABLE core_profile (
    id INT PRIMARY KEY DEFAULT 1,
    content TEXT NOT NULL,
    structured JSONB NOT NULL,
    version INT DEFAULT 1,
    entries_processed INT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tier 2: Topic summaries (one per topic)
CREATE TABLE topic_summaries (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL,
    key_facts JSONB DEFAULT '[]',
    entry_count INT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tier 3: Raw entries
CREATE TABLE entries (
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
);

-- Journal page OCR
CREATE TABLE journal_pages (
    id BIGSERIAL PRIMARY KEY,
    entry_id BIGINT REFERENCES entries(id),
    image_url TEXT NOT NULL,
    raw_ocr_text TEXT,
    final_text TEXT,
    entry_date DATE,
    themes TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Profile evolution snapshots
CREATE TABLE profile_history (
    id BIGSERIAL PRIMARY KEY,
    profile_type TEXT NOT NULL,
    content TEXT NOT NULL,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Daily questions
CREATE TABLE daily_questions (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    category TEXT,
    answer TEXT,
    asked_at TIMESTAMPTZ DEFAULT NOW(),
    answered_at TIMESTAMPTZ
);

-- Usage + cost tracking
CREATE TABLE usage_tracking (
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
);

-- Weekly self-reviews
CREATE TABLE self_reviews (
    id BIGSERIAL PRIMARY KEY,
    week_start DATE NOT NULL,
    review_text TEXT NOT NULL,
    suggestions JSONB DEFAULT '[]',
    applied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Mirror File Structure

Everything follows the WAT directory layout. No Python files at root.

```
tools/                 # WAT Layer 3: ALL Python scripts
  mirror_bot.py        # Main bot entry point (~500-600 lines)
  mirror_memory.py     # 3-tier memory management (~250 lines)
  mirror_prompts.py    # All Claude prompts (~150 lines)
  mirror_vision.py     # Journal photo OCR + edit flow (~120 lines)  [Session 2]
  mirror_reports.py    # HTML report generation (~200 lines)  [Session 4]
  setup_db.py          # Create 8 Supabase tables
  verify_setup.py      # Verify all credentials + connections
  # Future: test_ocr.py, rebuild_profile.py, test_commands.py, generate_report.py

workflows/             # WAT Layer 1: Markdown SOPs for each session
  session_0_setup.md
  session_1_core_bot.md
  session_2_vision_questions.md
  session_3_onboarding.md
  session_4_reports_commands.md
  session_5_deploy.md

.tmp/                  # Temporary/intermediate files (disposable)
.env                   # Secrets (never commit)
```

## .env Keys

```
TELEGRAM_BOT_TOKEN=       # From @BotFather
TELEGRAM_USER_ID=         # Your Telegram user ID (get from @userinfobot)
SUPABASE_URL=             # From Supabase dashboard
SUPABASE_SERVICE_KEY=     # service_role key (NOT anon key)
ANTHROPIC_API_KEY=        # Already have
```

## Anti-Sycophancy System Prompt

```
You are Mirror — a personal advisor whose ONLY value is honesty.

CORE PRINCIPLE:
Honesty is your #1 priority. Above comfort. Above feelings. Above everything.
You do not try to make the user feel good. You do not try to make them feel bad.
You simply tell the truth based on everything you know about them.

RULES:
- Never soften, hedge, or add disclaimers to honest observations
- Never open with compliments, praise, or "Great question!"
- Never use phrases like "I understand how you feel"
- If the user is making excuses, say exactly that
- If they contradict past statements, quote the contradiction with dates
- If they are avoiding something, name it directly with evidence
- When asked "what should I do?" give ONE clear answer, not a menu
- You have FULL permission to disagree with the user
- Do not add motivational language. No "You've got this!"
- Be concise. Every sentence must contain information.

CALIBRATED CONFIDENCE:
- When uncertain, say "I don't have enough data." Never speculate.
- Cite specific entries by date. No evidence -> prefix with "Speculation:"
- Before responding, self-check: "Am I saying this because it's true or because they want to hear it?"

TEMPORAL AWARENESS:
- Weight recent entries (last 1-3 months) at ~90% importance
- Older entries provide historical context only
- If old and new entries conflict, the new entry is the truth
```

## Build Order

### Session 0: Setup (~30 min)
- Install skills and MCP servers (see MIRROR_BUILD_PLAN.md for full list)
- Create Telegram bot via @BotFather (get token)
- Create Supabase project (get URL + service_role key)
- Run SQL: create all 8 tables
- `py -3.13 -m pip install python-telegram-bot supabase`
- Add secrets to `.env`

### Session 1: Core Bot + Silent Memory (~2-3h)
- `mirror_bot.py` — receive messages, authorized_only decorator, error handler
- `mirror_memory.py` — Supabase connection, save entries, load tiers, SQLite fallback
- Wire: message -> save -> Sonnet tags (importance + topics) -> "Saved"
- Test from phone

### Session 2: Vision + Daily Questions (~2h)
- `mirror_vision.py` — photo -> Claude Vision -> show text -> user confirms/edits -> save
- Daily question via JobQueue (Sonnet picks based on Tier 1)
- `/schedule` command for configuring daily auto-questions
- Test: upload journal photo, verify edit-before-save flow

### Session 3: Onboarding + Profile Builder (~2h)
- `/start` onboarding interview (20-30 questions)
- Build initial Tier 1 + Tier 2 from answers
- Weekly full rebuild job
- Profile snapshots to profile_history

### Session 4: Reports + AI Commands + Feedback Loop (~2-3h)
- `mirror_reports.py` — HTML Self-Knowledge Report
- All commands: /report, /feedback, /insight, /question, /profile, /cost, /export
- Thumbs up/down rating after AI responses
- Usage tracking
- Prompt caching implementation
- Anti-sycophancy testing

### Session 5: Deploy + Self-Improvement (~1-2h)
- Deploy to Oracle Cloud Always-Free (or keep on Windows PC)
- Weekly self-review job
- Monthly improvement suggestions
- Verify everything works end-to-end from phone

## Security

- `TELEGRAM_USER_ID` env var + `@authorized_only` decorator (silently drops unauthorized messages)
- Supabase `service_role` key (not anon key)
- `.env` + `.gitignore` for all secrets
- Never log journal entry content — metadata only
- Error handling: graceful degradation, SQLite fallback queue when Supabase is down

## Testing

- `--dry-run` flag: uses local SQLite instead of Supabase
- Session 1: Send 5+ messages -> verify in DB with importance/topics
- Session 2: Upload 3 journal photos -> verify OCR edit flow -> verify dates
- Session 3: Complete onboarding -> verify Tier 1 + Tier 2 quality
- Session 4: Run every command -> verify honest responses and ratings

## Initial Bulk Upload

User has ~1 year of handwritten journals. Upload in first 1-2 weeks:
1. Send photos in roughly chronological order
2. Each goes through edit-before-save OCR flow
3. Sonnet extracts date from journal page -> stores as `entry_date`
4. After bulk upload: full profile rebuild with temporal weighting
5. Result: core profile reflects CURRENT self, old entries are historical context

## Future Upgrades

| When | What | Cost |
|------|------|------|
| Income ~$500/mo | Railway hosting | +$5/mo |
| Income ~$2K/mo | Supabase Pro + Opus for reports | +$25-30/mo |
| Product ready | Multi-user SaaS + Stripe + Anthropic license | Variable |

Architecture supports all upgrades without rewriting.

## Verification (End-to-End)

1. Message bot -> "Saved" -> verify entry in Supabase with importance + topics
2. Send journal photo -> see extracted text -> correct -> confirm -> saved
3. `/question 3` -> 3 personalized questions
4. `/feedback career` -> honest feedback using Tier 1 + "career" Tier 2
5. `/report` -> HTML Self-Knowledge Report
6. Rate response thumbs up -> verify rating stored
7. `/cost` -> see usage and spend
8. `/export` -> receive JSON file
9. Restart bot -> all context preserved
10. After 1 week -> check self_reviews table for improvement suggestions

## Reference Resources

- [ginzlabs/tg-ai-agent](https://github.com/ginzlabs/tg-ai-agent) — closest architecture reference
- [python-telegram-bot v22.6 docs](https://docs.python-telegram-bot.org/en/stable/examples.html)
- [Supabase MCP docs](https://supabase.com/docs/guides/getting-started/mcp)
- [Anthropic Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [Mem0 Paper](https://arxiv.org/abs/2504.19413) — memory architecture reference
