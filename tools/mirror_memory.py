"""3-tier memory management for Mirror bot.

Tier 1: Core Profile (always loaded, single row)
Tier 2: Topic Summaries (loaded on demand, one per topic)
Tier 3: Raw Entries (loaded for specific lookups)

Falls back to SQLite queue when Supabase is unavailable.
"""

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone

import anthropic
from supabase import create_client, Client

from mirror_prompts import (
    PROFILE_REBUILD_PROMPT, TOPIC_SUMMARY_PROMPT, MIRROR_SYSTEM,
    SELF_REVIEW_PROMPT, MONTHLY_IMPROVEMENT_PROMPT,
)

logger = logging.getLogger("mirror.memory")

# Project root is one level up from tools/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOPICS = ["career", "relationships", "health", "education",
          "emotions", "finance", "daily_life", "goals"]

# Default config values (used when bot_config table is unavailable)
_DEFAULT_CONFIG = {
    "recency_weights": {"30": 1.0, "90": 0.7, "180": 0.4, "365": 0.2, "inf": 0.1},
    "topics": TOPICS,
    "importance_criteria": (
        "1-3: routine activities, weather, what I ate, small tasks. "
        "4-6: reflections on work, relationship dynamics, health changes, moderate decisions. "
        "7-8: significant realizations, major decisions, emotional breakthroughs. "
        "9-10: life-changing events, core identity shifts, fundamental belief changes."
    ),
    "rebuild_limit": 500,
}


class MirrorMemory:
    """Manages all database operations for the Mirror bot."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.sb = None
        self._fallback_db = None
        self._config_cache = {}

        if dry_run:
            self._init_sqlite()
        else:
            self._init_supabase()

    def _init_supabase(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            logger.error("SUPABASE_URL or SUPABASE_SERVICE_KEY not set, using SQLite fallback")
            self._init_sqlite()
            return
        try:
            self.sb = create_client(url, key)
            logger.info("Connected to Supabase")
        except Exception as e:
            logger.error("Supabase connection failed: %s -- using SQLite fallback", e)
            self._init_sqlite()

    def _init_sqlite(self):
        """SQLite fallback for --dry-run or when Supabase is down."""
        db_path = os.path.join(PROJECT_ROOT, ".tmp", "mirror_fallback.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._fallback_db = sqlite3.connect(db_path)
        self._fallback_db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_message_id INTEGER UNIQUE,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                topics TEXT DEFAULT '[]',
                importance INTEGER DEFAULT 5,
                recency_weight REAL,
                rating INTEGER,
                metadata TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._fallback_db.commit()
        logger.info("Using SQLite fallback at %s", db_path)

    @property
    def _using_sqlite(self):
        return self.sb is None

    # -- Config System --------------------------------------------------------

    def load_config(self, key):
        """Load a config value from bot_config table. Falls back to defaults."""
        if key in self._config_cache:
            return self._config_cache[key]

        if self._using_sqlite:
            value = _DEFAULT_CONFIG.get(key)
            if value is not None:
                self._config_cache[key] = value
            return value

        try:
            result = (self.sb.table("bot_config")
                      .select("value")
                      .eq("key", key)
                      .execute())
            if result.data:
                value = result.data[0]["value"]
                self._config_cache[key] = value
                return value
        except Exception as e:
            logger.error("Failed to load config '%s': %s", key, e)

        # Fall back to default
        value = _DEFAULT_CONFIG.get(key)
        if value is not None:
            self._config_cache[key] = value
        return value

    def save_config(self, key, value, updated_by="system"):
        """Upsert a config value into bot_config table. Clears cache."""
        self._config_cache.pop(key, None)
        if self._using_sqlite:
            return False
        try:
            self.sb.table("bot_config").upsert({
                "key": key,
                "value": value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": updated_by,
            }, on_conflict="key").execute()
            logger.info("Config '%s' updated by %s", key, updated_by)
            return True
        except Exception as e:
            logger.error("Failed to save config '%s': %s", key, e)
            return False

    def apply_config_change(self, change):
        """Apply an approved self-improvement change to bot_config.

        Args:
            change: dict with 'config_key', 'proposed_value', 'id' fields.
        Returns:
            True if applied successfully.
        """
        config_key = change.get("config_key")
        proposed_value = change.get("proposed_value")
        change_id = change.get("id", "unknown")

        if not config_key or proposed_value is None:
            logger.error("Invalid config change: missing config_key or proposed_value")
            return False

        return self.save_config(config_key, proposed_value, updated_by=f"self_review_{change_id}")

    def get_topics(self):
        """Get topic list from config, falling back to module-level TOPICS."""
        return self.load_config("topics") or TOPICS

    def _recency_weight(self, entry_date):
        """Calculate temporal weight using config-driven thresholds."""
        if isinstance(entry_date, str):
            entry_date = date.fromisoformat(entry_date)
        days_ago = (date.today() - entry_date).days
        weights = self.load_config("recency_weights") or _DEFAULT_CONFIG["recency_weights"]
        # Sort thresholds numerically (skip "inf")
        thresholds = []
        inf_weight = 0.1
        for k, v in weights.items():
            if k == "inf":
                inf_weight = v
            else:
                thresholds.append((int(k), v))
        thresholds.sort()
        for threshold, weight in thresholds:
            if days_ago <= threshold:
                return weight
        return inf_weight

    def save_entry(self, content, entry_date, entry_type="text",
                   telegram_message_id=None, topics=None, importance=5,
                   metadata=None):
        """Save a journal entry. Returns entry ID or None on failure."""
        weight = self._recency_weight(entry_date)
        topics = topics or []
        metadata = metadata or {}

        if self._using_sqlite:
            return self._save_entry_sqlite(
                content, entry_date, entry_type, telegram_message_id,
                topics, importance, weight, metadata
            )

        try:
            row = {
                "type": entry_type,
                "content": content,
                "entry_date": entry_date.isoformat(),
                "topics": topics,
                "importance": importance,
                "recency_weight": weight,
                "metadata": metadata,
            }
            if telegram_message_id is not None:
                row["telegram_message_id"] = telegram_message_id

            result = self.sb.table("entries").insert(row).execute()
            entry_id = result.data[0]["id"] if result.data else None
            logger.info("Saved entry %s (importance=%d, topics=%s)", entry_id, importance, topics)
            return entry_id
        except Exception as e:
            logger.error("Supabase save failed: %s -- falling back to SQLite", e)
            self._init_sqlite()
            return self._save_entry_sqlite(
                content, entry_date, entry_type, telegram_message_id,
                topics, importance, weight, metadata
            )

    def _save_entry_sqlite(self, content, entry_date, entry_type,
                           telegram_message_id, topics, importance, weight, metadata):
        try:
            cur = self._fallback_db.execute(
                """INSERT INTO entries (telegram_message_id, type, content, entry_date,
                   topics, importance, recency_weight, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (telegram_message_id, entry_type, content, entry_date.isoformat(),
                 json.dumps(topics), importance, weight, json.dumps(metadata))
            )
            self._fallback_db.commit()
            return cur.lastrowid
        except Exception as e:
            logger.error("SQLite save failed: %s", e)
            return None

    def update_entry_tags(self, entry_id, importance, topics):
        """Update importance and topics after AI tagging."""
        if self._using_sqlite:
            try:
                self._fallback_db.execute(
                    "UPDATE entries SET importance=?, topics=? WHERE id=?",
                    (importance, json.dumps(topics), entry_id)
                )
                self._fallback_db.commit()
                return True
            except Exception as e:
                logger.error("SQLite update failed: %s", e)
                return False

        try:
            self.sb.table("entries").update({
                "importance": importance,
                "topics": topics,
            }).eq("id", entry_id).execute()
            return True
        except Exception as e:
            logger.error("Supabase update failed: %s", e)
            return False

    def load_profile(self):
        """Load Tier 1 core profile. Returns content string or None."""
        if self._using_sqlite:
            return None
        try:
            result = self.sb.table("core_profile").select("content").eq("id", 1).execute()
            if result.data:
                return result.data[0]["content"]
            return None
        except Exception as e:
            logger.error("Failed to load profile: %s", e)
            return None

    def save_profile(self, content, structured, entries_processed=0):
        """Save/update Tier 1 core profile (upsert)."""
        if self._using_sqlite:
            return False
        try:
            self.sb.table("core_profile").upsert({
                "id": 1,
                "content": content,
                "structured": structured,
                "entries_processed": entries_processed,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return True
        except Exception as e:
            logger.error("Failed to save profile: %s", e)
            return False

    def load_topic(self, topic):
        """Load a single Tier 2 topic summary."""
        if self._using_sqlite:
            return None
        try:
            result = (self.sb.table("topic_summaries")
                      .select("summary")
                      .eq("topic", topic)
                      .execute())
            if result.data:
                return result.data[0]["summary"]
            return None
        except Exception as e:
            logger.error("Failed to load topic: %s", e)
            return None

    def load_all_topics(self):
        """Load all Tier 2 topic summaries. Returns {topic: summary}."""
        if self._using_sqlite:
            return {}
        try:
            result = self.sb.table("topic_summaries").select("topic, summary").execute()
            return {row["topic"]: row["summary"] for row in (result.data or [])}
        except Exception as e:
            logger.error("Failed to load topics: %s", e)
            return {}

    def save_topic(self, topic, summary, key_facts=None, entry_count=0):
        """Save/update a Tier 2 topic summary (upsert)."""
        if self._using_sqlite:
            return False
        try:
            self.sb.table("topic_summaries").upsert({
                "topic": topic,
                "summary": summary,
                "key_facts": key_facts or [],
                "entry_count": entry_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="topic").execute()
            return True
        except Exception as e:
            logger.error("Failed to save topic: %s", e)
            return False

    def get_recent_entries(self, limit=20):
        """Get recent entries ordered by date descending."""
        if self._using_sqlite:
            try:
                cur = self._fallback_db.execute(
                    "SELECT * FROM entries ORDER BY entry_date DESC LIMIT ?", (limit,)
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            except Exception as e:
                logger.error("SQLite query failed: %s", e)
                return []
        try:
            result = (self.sb.table("entries")
                      .select("*")
                      .order("entry_date", desc=True)
                      .limit(limit)
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error("Failed to get recent entries: %s", e)
            return []

    def get_entries_by_date(self, target_date):
        """Get all entries from a specific date."""
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)
        date_str = target_date.isoformat()

        if self._using_sqlite:
            try:
                cur = self._fallback_db.execute(
                    "SELECT * FROM entries WHERE entry_date = ? ORDER BY created_at",
                    (date_str,)
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            except Exception as e:
                logger.error("SQLite date query failed: %s", e)
                return []
        try:
            result = (self.sb.table("entries")
                      .select("*")
                      .eq("entry_date", date_str)
                      .order("created_at")
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error("Failed to get entries by date: %s", e)
            return []

    def get_entries_in_range(self, start_date, end_date):
        """Get entries between two dates (inclusive)."""
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        if self._using_sqlite:
            try:
                cur = self._fallback_db.execute(
                    "SELECT * FROM entries WHERE entry_date BETWEEN ? AND ? ORDER BY entry_date",
                    (start_date.isoformat(), end_date.isoformat())
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            except Exception as e:
                logger.error("SQLite range query failed: %s", e)
                return []
        try:
            result = (self.sb.table("entries")
                      .select("*")
                      .gte("entry_date", start_date.isoformat())
                      .lte("entry_date", end_date.isoformat())
                      .order("entry_date")
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error("Failed to get entries in range: %s", e)
            return []

    def get_entry_count(self):
        """Get total number of entries."""
        if self._using_sqlite:
            try:
                cur = self._fallback_db.execute("SELECT COUNT(*) FROM entries")
                return cur.fetchone()[0]
            except Exception:
                return 0
        try:
            result = (self.sb.table("entries")
                      .select("id", count="exact")
                      .execute())
            return result.count or 0
        except Exception:
            return 0

    # -- Daily Questions --------------------------------------------------

    def save_daily_questions(self, questions):
        """Save generated questions to daily_questions table.

        Args:
            questions: list of question strings
        """
        if self._using_sqlite:
            return
        try:
            rows = [{"question": q, "category": "daily"} for q in questions]
            self.sb.table("daily_questions").insert(rows).execute()
            logger.info("Saved %d daily questions", len(questions))
        except Exception as e:
            logger.error("Failed to save daily questions: %s", e)

    def get_recent_questions(self, days=14):
        """Get questions asked in the last N days to avoid repeats."""
        if self._using_sqlite:
            return []
        try:
            cutoff = (datetime.now(timezone.utc) -
                      timedelta(days=days)).isoformat()
            result = (self.sb.table("daily_questions")
                      .select("question, asked_at")
                      .gte("asked_at", cutoff)
                      .order("asked_at", desc=True)
                      .execute())
            return [row["question"] for row in (result.data or [])]
        except Exception as e:
            logger.error("Failed to get recent questions: %s", e)
            return []

    def track_usage(self, input_tokens=0, output_tokens=0, cache_read_tokens=0,
                    cost_cents=0, is_entry=False, rating=None, is_error=False):
        """Increment daily usage counters."""
        if self._using_sqlite:
            return
        today = date.today().isoformat()
        try:
            result = (self.sb.table("usage_tracking")
                      .select("*")
                      .eq("date", today)
                      .execute())
            if result.data:
                row = result.data[0]
                updates = {
                    "ai_calls_count": row["ai_calls_count"] + 1,
                    "input_tokens": row["input_tokens"] + input_tokens,
                    "output_tokens": row["output_tokens"] + output_tokens,
                    "cache_read_tokens": row["cache_read_tokens"] + cache_read_tokens,
                    "estimated_cost_cents": float(row["estimated_cost_cents"]) + cost_cents,
                }
                if is_entry:
                    updates["entries_count"] = row["entries_count"] + 1
                if rating is not None:
                    if rating > 0:
                        updates["ratings_positive"] = row["ratings_positive"] + 1
                    else:
                        updates["ratings_negative"] = row["ratings_negative"] + 1
                if is_error:
                    updates["errors_count"] = row["errors_count"] + 1
                (self.sb.table("usage_tracking")
                 .update(updates)
                 .eq("id", row["id"])
                 .execute())
            else:
                self.sb.table("usage_tracking").insert({
                    "date": today,
                    "entries_count": 1 if is_entry else 0,
                    "ai_calls_count": 1,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "estimated_cost_cents": cost_cents,
                    "ratings_positive": 1 if rating and rating > 0 else 0,
                    "ratings_negative": 1 if rating and rating < 0 else 0,
                    "errors_count": 1 if is_error else 0,
                }).execute()
        except Exception as e:
            logger.error("Usage tracking failed: %s", e)

    def get_usage_today(self):
        """Get today usage stats."""
        if self._using_sqlite:
            return None
        try:
            result = (self.sb.table("usage_tracking")
                      .select("*")
                      .eq("date", date.today().isoformat())
                      .execute())
            return result.data[0] if result.data else None
        except Exception:
            return None

    def save_journal_page(self, entry_id, image_url, raw_ocr_text, final_text,
                          entry_date=None, themes=None):
        """Save a journal page OCR record linked to an entry."""
        if self._using_sqlite:
            return None
        try:
            row = {
                "entry_id": entry_id,
                "image_url": image_url or "",
                "raw_ocr_text": raw_ocr_text,
                "final_text": final_text,
            }
            if entry_date:
                row["entry_date"] = entry_date
            if themes:
                row["themes"] = themes
            result = self.sb.table("journal_pages").insert(row).execute()
            return result.data[0]["id"] if result.data else None
        except Exception as e:
            logger.error("Failed to save journal page: %s", e)
            return None

    def rate_entry(self, entry_id, rating):
        """Store thumbs up (1) / down (-1) rating on an entry."""
        if self._using_sqlite:
            try:
                self._fallback_db.execute(
                    "UPDATE entries SET rating=? WHERE id=?", (rating, entry_id)
                )
                self._fallback_db.commit()
                return True
            except Exception:
                return False
        try:
            self.sb.table("entries").update({"rating": rating}).eq("id", entry_id).execute()
            return True
        except Exception as e:
            logger.error("Rating failed: %s", e)
            return False

    # -- Profile Rebuild --------------------------------------------------

    def get_all_entries_for_rebuild(self, limit=None):
        """Get all entries ordered by date descending, for profile rebuild."""
        if limit is None:
            limit = self.load_config("rebuild_limit") or 500
        if self._using_sqlite:
            try:
                cur = self._fallback_db.execute(
                    "SELECT * FROM entries ORDER BY entry_date DESC LIMIT ?", (limit,)
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            except Exception as e:
                logger.error("SQLite query failed: %s", e)
                return []
        try:
            result = (self.sb.table("entries")
                      .select("*")
                      .order("entry_date", desc=True)
                      .limit(limit)
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error("Failed to get entries for rebuild: %s", e)
            return []

    def _format_entries_for_prompt(self, entries):
        """Format entries into a text block for Claude prompts."""
        if not entries:
            return "(No entries)"
        lines = []
        for e in entries:
            d = e.get("entry_date", "unknown")
            weight = e.get("recency_weight", "?")
            content = e.get("content", "")
            topics = e.get("topics", [])
            if isinstance(topics, str):
                try:
                    topics = json.loads(topics)
                except (json.JSONDecodeError, TypeError):
                    topics = []
            imp = e.get("importance", 5)
            lines.append(f"[{d}] (importance={imp}, weight={weight}, topics={topics})\n{content}")
        return "\n---\n".join(lines)

    def rebuild_profile(self, claude_client=None):
        """Rebuild Tier 1 core profile from all entries.

        Returns the profile text or None on failure.
        """
        if claude_client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.error("No Anthropic API key for profile rebuild")
                return None
            claude_client = anthropic.Anthropic(api_key=api_key)

        entries = self.get_all_entries_for_rebuild()
        if not entries:
            logger.warning("No entries found for profile rebuild")
            return None

        # Recalculate recency weights based on current date
        for e in entries:
            ed = e.get("entry_date")
            if ed:
                if isinstance(ed, str):
                    ed = date.fromisoformat(ed)
                e["recency_weight"] = self._recency_weight(ed)

        formatted = self._format_entries_for_prompt(entries)
        prompt = PROFILE_REBUILD_PROMPT.format(entries=formatted)

        try:
            response = claude_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                system=MIRROR_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            profile_text = response.content[0].text.strip()

            # Save to core_profile
            self.save_profile(
                content=profile_text,
                structured={"rebuild_date": date.today().isoformat(),
                             "entry_count": len(entries)},
                entries_processed=len(entries),
            )

            # Save snapshot to profile_history
            self.save_profile_snapshot(profile_text, len(entries))

            # Track usage
            usage = response.usage
            cost_cents = (usage.input_tokens * 0.3 + usage.output_tokens * 1.5) / 100_000
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            self.track_usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=cache_read,
                cost_cents=cost_cents,
            )

            logger.info("Profile rebuilt from %d entries", len(entries))
            return profile_text

        except Exception as e:
            logger.error("Profile rebuild failed: %s", e)
            self.track_usage(is_error=True)
            return None

    def rebuild_topic_summaries(self, claude_client=None):
        """Rebuild all Tier 2 topic summaries from entries.

        Returns dict {topic: summary} for topics that had entries.
        """
        if claude_client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.error("No Anthropic API key for topic rebuild")
                return {}
            claude_client = anthropic.Anthropic(api_key=api_key)

        all_entries = self.get_all_entries_for_rebuild()
        if not all_entries:
            logger.warning("No entries for topic rebuild")
            return {}

        # Recalculate recency weights based on current date
        for e in all_entries:
            ed = e.get("entry_date")
            if ed:
                if isinstance(ed, str):
                    ed = date.fromisoformat(ed)
                e["recency_weight"] = self._recency_weight(ed)

        results = {}
        for topic in self.get_topics():
            # Filter entries that include this topic
            topic_entries = []
            for e in all_entries:
                entry_topics = e.get("topics", [])
                if isinstance(entry_topics, str):
                    try:
                        entry_topics = json.loads(entry_topics)
                    except (json.JSONDecodeError, TypeError):
                        entry_topics = []
                if topic in entry_topics:
                    topic_entries.append(e)

            if not topic_entries:
                continue

            formatted = self._format_entries_for_prompt(topic_entries)
            prompt = TOPIC_SUMMARY_PROMPT.format(topic=topic, entries=formatted)

            try:
                response = claude_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1000,
                    system=MIRROR_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                )

                summary = response.content[0].text.strip()
                self.save_topic(topic, summary, entry_count=len(topic_entries))
                results[topic] = summary

                # Track usage
                usage = response.usage
                cost_cents = (usage.input_tokens * 0.3 + usage.output_tokens * 1.5) / 100_000
                cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
                self.track_usage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=cache_read,
                    cost_cents=cost_cents,
                )

                logger.info("Topic '%s' rebuilt from %d entries", topic, len(topic_entries))

            except Exception as e:
                logger.error("Topic rebuild failed for '%s': %s", topic, e)
                self.track_usage(is_error=True)

        return results

    def save_profile_snapshot(self, profile_text, entry_count=0):
        """Save a profile snapshot to profile_history."""
        if self._using_sqlite:
            return None
        try:
            result = self.sb.table("profile_history").insert({
                "profile_type": "tier1_rebuild",
                "content": profile_text,
                "raw_json": {"entry_count": entry_count,
                              "rebuild_date": date.today().isoformat()},
            }).execute()
            return result.data[0]["id"] if result.data else None
        except Exception as e:
            logger.error("Failed to save profile snapshot: %s", e)
            return None

    def get_onboarding_progress(self):
        """Check how many onboarding entries exist. Returns count."""
        if self._using_sqlite:
            try:
                cur = self._fallback_db.execute(
                    "SELECT COUNT(*) FROM entries WHERE type='onboarding'"
                )
                return cur.fetchone()[0]
            except Exception:
                return 0
        try:
            result = (self.sb.table("entries")
                      .select("id", count="exact")
                      .eq("type", "onboarding")
                      .execute())
            return result.count or 0
        except Exception:
            return 0

    # -- Self-Improvement Loop --------------------------------------------

    def get_topic_entry_counts(self):
        """Get entry count per topic. Returns {topic: count}."""
        if self._using_sqlite:
            return {}
        try:
            result = self.sb.rpc("get_topic_counts", {}).execute()
            if result.data:
                return {row["topic"]: row["count"] for row in result.data}
        except Exception:
            pass
        # Fallback: count manually from recent entries
        try:
            entries = self.get_all_entries_for_rebuild()
            counts = {}
            for e in entries:
                topics = e.get("topics", [])
                if isinstance(topics, str):
                    try:
                        topics = json.loads(topics)
                    except (json.JSONDecodeError, TypeError):
                        topics = []
                for t in topics:
                    counts[t] = counts.get(t, 0) + 1
            return counts
        except Exception as e:
            logger.error("Failed to get topic counts: %s", e)
            return {}

    def _get_config_summary(self):
        """Build a text summary of current config values for prompts."""
        weights = self.load_config("recency_weights")
        topics = self.get_topics()
        criteria = self.load_config("importance_criteria")
        rebuild_limit = self.load_config("rebuild_limit")
        return (
            f"Recency weights: {json.dumps(weights)}\n"
            f"Topics: {json.dumps(topics)}\n"
            f"Importance criteria: {criteria}\n"
            f"Rebuild limit: {rebuild_limit}"
        )

    def get_usage_range(self, start_date, end_date):
        """Get usage tracking rows for a date range. Returns list of dicts."""
        if self._using_sqlite:
            return []
        try:
            result = (self.sb.table("usage_tracking")
                      .select("*")
                      .gte("date", start_date.isoformat())
                      .lte("date", end_date.isoformat())
                      .order("date")
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error("Failed to get usage range: %s", e)
            return []

    def save_self_review(self, week_start, review_text, suggestions=None):
        """Save a weekly self-review to self_reviews table."""
        if self._using_sqlite:
            return None
        try:
            result = self.sb.table("self_reviews").insert({
                "week_start": week_start.isoformat(),
                "review_text": review_text,
                "suggestions": suggestions or [],
                "applied": False,
            }).execute()
            return result.data[0]["id"] if result.data else None
        except Exception as e:
            logger.error("Failed to save self-review: %s", e)
            return None

    def get_recent_self_reviews(self, limit=4):
        """Get recent self-reviews (default last 4 weeks)."""
        if self._using_sqlite:
            return []
        try:
            result = (self.sb.table("self_reviews")
                      .select("*")
                      .order("week_start", desc=True)
                      .limit(limit)
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error("Failed to get self-reviews: %s", e)
            return []

    def run_weekly_self_review(self, claude_client=None):
        """Run a weekly self-review: analyze usage, ratings, errors.

        Returns (review_text, suggestions_list) or (None, None) on failure.
        """
        if claude_client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.error("No Anthropic API key for self-review")
                return None, None
            claude_client = anthropic.Anthropic(api_key=api_key)

        # Get past 7 days of usage
        today = date.today()
        week_start = date.fromordinal(today.toordinal() - 7)
        usage_rows = self.get_usage_range(week_start, today)

        if not usage_rows:
            logger.info("No usage data for self-review (week of %s)", week_start)
            return None, None

        # Format usage data
        total_entries = sum(r.get("entries_count", 0) for r in usage_rows)
        total_ai_calls = sum(r.get("ai_calls_count", 0) for r in usage_rows)
        total_input = sum(r.get("input_tokens", 0) for r in usage_rows)
        total_output = sum(r.get("output_tokens", 0) for r in usage_rows)
        total_cache = sum(r.get("cache_read_tokens", 0) for r in usage_rows)
        total_cost = sum(float(r.get("estimated_cost_cents", 0)) for r in usage_rows)
        total_pos = sum(r.get("ratings_positive", 0) for r in usage_rows)
        total_neg = sum(r.get("ratings_negative", 0) for r in usage_rows)
        total_errors = sum(r.get("errors_count", 0) for r in usage_rows)

        usage_data = (
            f"Period: {week_start} to {today}\n"
            f"Active days: {len(usage_rows)}\n"
            f"Total entries: {total_entries}\n"
            f"AI calls: {total_ai_calls}\n"
            f"Tokens in: {total_input:,} | out: {total_output:,} | cache reads: {total_cache:,}\n"
            f"Total cost: ${total_cost / 100:.4f}"
        )
        ratings_summary = (
            f"Positive: {total_pos} | Negative: {total_neg} | "
            f"Ratio: {total_pos}/{total_pos + total_neg if total_pos + total_neg else 'N/A'}"
        )
        error_summary = f"Total errors: {total_errors}" if total_errors else "No errors this week."

        prompt = SELF_REVIEW_PROMPT.format(
            usage_data=usage_data,
            ratings_summary=ratings_summary,
            error_summary=error_summary,
            config_summary=self._get_config_summary(),
        )

        try:
            response = claude_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=800,
                system=MIRROR_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            review_text = response.content[0].text.strip()

            # Track usage
            usage = response.usage
            cost_cents = (usage.input_tokens * 0.3 + usage.output_tokens * 1.5) / 100_000
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            self.track_usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=cache_read,
                cost_cents=cost_cents,
            )

            # Parse suggestions JSON from review text
            suggestions = []
            try:
                # Look for JSON array in the response
                import re
                json_match = re.search(r'\[[\s\S]*?\]', review_text)
                if json_match:
                    suggestions = json.loads(json_match.group())
            except (json.JSONDecodeError, TypeError):
                pass

            # Save to self_reviews
            self.save_self_review(week_start, review_text, suggestions=suggestions)
            logger.info("Weekly self-review saved (week of %s), %d suggestions", week_start, len(suggestions))
            return review_text, suggestions

        except Exception as e:
            logger.error("Weekly self-review failed: %s", e)
            self.track_usage(is_error=True)
            return None, None

    def run_monthly_improvement(self, claude_client=None):
        """Synthesize past month's data into structured improvement proposals.

        Returns (summary_text, proposals_list) or (None, None) on failure.
        """
        if claude_client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.error("No Anthropic API key for monthly improvement")
                return None, None
            claude_client = anthropic.Anthropic(api_key=api_key)

        reviews = self.get_recent_self_reviews(limit=4)
        if not reviews:
            logger.info("No self-reviews for monthly improvement")
            return None, None

        reviews_text = "\n\n---\n\n".join(
            f"Week of {r['week_start']}:\n{r['review_text']}" for r in reviews
        )

        # Get month's usage totals
        today = date.today()
        month_start = date(today.year, today.month, 1)
        usage_rows = self.get_usage_range(month_start, today)
        total_cost = sum(float(r.get("estimated_cost_cents", 0)) for r in usage_rows)
        total_entries = sum(r.get("entries_count", 0) for r in usage_rows)
        total_ai_calls = sum(r.get("ai_calls_count", 0) for r in usage_rows)
        total_cache = sum(r.get("cache_read_tokens", 0) for r in usage_rows)
        total_pos = sum(r.get("ratings_positive", 0) for r in usage_rows)
        total_neg = sum(r.get("ratings_negative", 0) for r in usage_rows)
        monthly_usage = (
            f"Period: {month_start} to {today}\n"
            f"Total entries: {total_entries}\n"
            f"AI calls: {total_ai_calls}\n"
            f"Cache read tokens: {total_cache:,}\n"
            f"Ratings: {total_pos} positive, {total_neg} negative\n"
            f"Total cost: ${total_cost / 100:.4f}"
        )

        # Gather context
        topic_counts = self.get_topic_entry_counts()
        topic_summaries = self.load_all_topics()
        recent = self.get_recent_entries(limit=20)

        topic_counts_text = "\n".join(f"  {t}: {c} entries" for t, c in sorted(topic_counts.items(), key=lambda x: -x[1])) or "No data"
        topic_summaries_text = "\n\n".join(f"=== {t.upper()} ===\n{s}" for t, s in topic_summaries.items()) or "No summaries yet"
        recent_text = self._format_entries_for_prompt(recent) if recent else "No recent entries"

        prompt = MONTHLY_IMPROVEMENT_PROMPT.format(
            reviews=reviews_text,
            monthly_usage=monthly_usage,
            config_summary=self._get_config_summary(),
            topic_counts=topic_counts_text,
            topic_summaries=topic_summaries_text,
            recent_entries=recent_text,
        )

        try:
            response = claude_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=MIRROR_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()

            # Track usage
            usage = response.usage
            cost_cents = (usage.input_tokens * 0.3 + usage.output_tokens * 1.5) / 100_000
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            self.track_usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=cache_read,
                cost_cents=cost_cents,
            )

            # Parse structured JSON response
            import re
            proposals = []
            summary = ""
            try:
                # Try to find JSON object in response
                json_match = re.search(r'\{[\s\S]*\}', text)
                if json_match:
                    parsed = json.loads(json_match.group())
                    proposals = parsed.get("proposed_changes", [])
                    summary = parsed.get("summary", "")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Failed to parse monthly improvement JSON: %s", e)
                summary = text  # Fall back to raw text

            logger.info("Monthly improvement: %d proposals generated", len(proposals))
            return summary, proposals

        except Exception as e:
            logger.error("Monthly improvement failed: %s", e)
            self.track_usage(is_error=True)
            return None, None
