---
description: Mirror bot development patterns — how to add commands, jobs, prompts, DB queries, config keys, and tables
globs: tools/*.py
---

# Mirror Developer Guide

Six patterns for extending the Mirror bot. All examples reference actual code.

---

## 1. Add a Command

File: `tools/mirror_bot.py`

```python
@authorized_only
async def handle_mycommand(update, context):
    """Description."""
    args = context.args or []
    # Load memory context
    profile = memory.load_profile()
    topics = memory.load_topic_summaries()
    ctx = build_context(profile, topics)
    # Call Claude
    prompt = MY_PROMPT.format(context=ctx)
    text, _ = call_claude(prompt, max_tokens=1000)
    if text:
        await _send_ai_response(update, text)
```

Register in `main()`:
```python
app.add_handler(CommandHandler("mycommand", handle_mycommand))
```

Add to `handle_help()` text.

---

## 2. Add a Scheduled Job

File: `tools/mirror_bot.py`

```python
async def my_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback."""
    data = context.job.data  # optional passed data
    # do work...
    await context.bot.send_message(chat_id=AUTHORIZED_USER_ID, text="Done.")
```

Register in `main()`:
```python
# Daily at 9am on weekdays
app.job_queue.run_daily(my_job, time=time(hour=9, tzinfo=user_tz), days=(0,1,2,3,4), name="my_job")
# Monthly on the 1st
app.job_queue.run_monthly(my_job, when=time(hour=9, tzinfo=user_tz), day=1, name="my_job")
```

Remove existing jobs before rescheduling:
```python
for job in job_queue.get_jobs_by_name("my_job"):
    job.schedule_removal()
```

---

## 3. Add a Prompt

File: `tools/mirror_prompts.py`

```python
# Simple constant
MY_PROMPT = """Based on {context}, do X."""

# Dynamic with fallback
def make_my_prompt(custom_param=None):
    if not custom_param:
        return MY_PROMPT
    return f"""..."""
```

Use `build_context(profile, topic_summaries)` to build standard context string. Use `.format()` for parameters.

---

## 4. Add a DB Query

File: `tools/mirror_memory.py`

```python
def get_something(self, param):
    """Get something. Returns list or empty list on failure."""
    if isinstance(param, str):
        param = date.fromisoformat(param)
    if self._using_sqlite:
        try:
            cur = self._fallback_db.execute("SELECT * FROM table WHERE col = ?", (param,))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            logger.error("SQLite query failed: %s", e)
            return []
    try:
        result = self.sb.table("table").select("*").eq("col", param).execute()
        return result.data or []
    except Exception as e:
        logger.error("Query failed: %s", e)
        return []
```

Key rules: check `self._using_sqlite` first, wrap in try/except, return safe defaults (None, [], 0, False).

---

## 5. Use the Config System

File: `tools/mirror_memory.py`

```python
# Read (cached, falls back to _DEFAULT_CONFIG)
value = self.load_config("my_key")

# Write (invalidates cache)
self.save_config("my_key", new_value, updated_by="source")

# Apply from self-improvement approval
self.apply_config_change({"config_key": "my_key", "proposed_value": new_value, "id": "change_1"})
```

For new config keys: add default to `_DEFAULT_CONFIG` dict and seed row in `setup_db.py`.

---

## 6. Add a DB Table

File: `tools/setup_db.py`

```python
# Add to STATEMENTS list
("my_table", """CREATE TABLE IF NOT EXISTS my_table (
    id BIGSERIAL PRIMARY KEY,
    field TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
)"""),

# Optional seed data (separate entry)
("my_table seed", """INSERT INTO my_table (field) VALUES ('default')
ON CONFLICT DO NOTHING"""),
```

Add table name to `EXPECTED_TABLES` list for verification.

---

## Key Helpers to Reuse

| Helper | Location | Purpose |
|--------|----------|---------|
| `call_claude(prompt, max_tokens)` | `mirror_bot.py` | Cached Claude API call, returns `(text, usage)` |
| `_send_ai_response(update, text)` | `mirror_bot.py` | Split long messages + add rating buttons |
| `build_context(profile, topics)` | `mirror_prompts.py` | Build standard context string from Tier 1 + Tier 2 |
| `make_tagging_prompt(criteria, topics)` | `mirror_prompts.py` | Dynamic tagging prompt with config values |
| `@authorized_only` | `mirror_bot.py` | Decorator — restricts to `TELEGRAM_USER_ID` |
| `track_usage(model, input, output, cached)` | `mirror_bot.py` | Log API costs to `usage_tracking` table |
