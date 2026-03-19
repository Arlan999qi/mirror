"""Mirror -- Personal AI Journal Bot.

Core bot: receives messages, saves silently, tags with Claude.
Session 2: photo OCR with edit-before-save, daily questions via JobQueue.
Session 4: AI commands (/feedback, /insight, /question, /report),
           thumbs up/down ratings, prompt caching.

Usage:
    py -3.13 tools/mirror_bot.py              # Normal mode (Supabase)
    py -3.13 tools/mirror_bot.py --dry-run    # Local SQLite mode
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import anthropic
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from mirror_memory import MirrorMemory, PROJECT_ROOT
from mirror_prompts import (
    TAGGING_PROMPT, QUESTION_PROMPT, MIRROR_SYSTEM,
    FEEDBACK_PROMPT, INSIGHT_PROMPT, REPORT_PROMPT,
    ONBOARDING_INTRO, ONBOARDING_QUESTIONS, PROFILE_DISPLAY_PROMPT,
    make_tagging_message, build_context,
)
from mirror_reports import generate_report_html, parse_report_json
from mirror_vision import (
    extract_text_from_photo, start_edit_flow, get_pending,
    apply_correction, set_date, finish_edit_flow,
)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# -- Logging ----------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mirror.bot")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# -- Globals ----------------------------------------------------------

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0"))
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

memory = None
claude = None

# -- Onboarding state -------------------------------------------------
# {user_id: {"step": int, "total": int}}
_onboarding = {}


# -- Authorization ----------------------------------------------------

def authorized_only(func):
    """Decorator: silently drop messages from unauthorized users."""
    async def wrapper(update, context):
        if update.effective_user.id != AUTHORIZED_USER_ID:
            logger.warning("Unauthorized access attempt from user %s", update.effective_user.id)
            return
        return await func(update, context)
    return wrapper


# -- AI Tagging -------------------------------------------------------

def tag_entry(content):
    """Use Claude to assign importance (1-10) and topic tags.

    Returns (importance, topics). Falls back to (5, ["daily_life"]) on error.
    """
    if claude is None:
        return 5, ["daily_life"]

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system=[{
                "type": "text",
                "text": TAGGING_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": make_tagging_message(content)}],
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)
        importance = max(1, min(10, int(result.get("importance", 5))))
        topics = result.get("topics", ["daily_life"])

        # Track usage
        usage = response.usage
        cost_cents = (usage.input_tokens * 0.3 + usage.output_tokens * 1.5) / 100_000
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        memory.track_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cost_cents=cost_cents,
        )

        return importance, topics

    except Exception as e:
        logger.error("Tagging failed: %s", e)
        memory.track_usage(is_error=True)
        return 5, ["daily_life"]


# -- Daily Questions --------------------------------------------------

def generate_questions(n=1):
    """Use Claude to generate personalized journal questions."""
    if claude is None:
        return None

    profile = memory.load_profile()
    topics = memory.load_all_topics()
    context = build_context(profile, topics)

    prompt = QUESTION_PROMPT.format(n=n, context=context)

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=MIRROR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()

        usage = response.usage
        cost_cents = (usage.input_tokens * 0.3 + usage.output_tokens * 1.5) / 100_000
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        memory.track_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cost_cents=cost_cents,
        )

        return text

    except Exception as e:
        logger.error("Question generation failed: %s", e)
        memory.track_usage(is_error=True)
        return None


async def daily_question_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback: send daily questions to the user."""
    n = context.job.data or 1
    text = generate_questions(n)
    if text:
        await context.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=text)
        logger.info("Sent %d daily question(s)", n)
    else:
        logger.warning("Failed to generate daily questions")


# -- AI Call Helper (with prompt caching) -----------------------------

def call_claude(prompt, max_tokens=800):
    """Call Claude with MIRROR_SYSTEM cached, track usage.

    Returns (response_text, usage_info) or (None, None) on failure.
    """
    if claude is None:
        return None, None

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=[{
                "type": "text",
                "text": MIRROR_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()

        usage = response.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
        # Pricing: input $3/M, output $15/M, cache write $3.75/M, cache read $0.30/M
        input_cost = (usage.input_tokens - cache_read - cache_create) * 3.0
        cache_read_cost = cache_read * 0.30
        cache_create_cost = cache_create * 3.75
        output_cost = usage.output_tokens * 15.0
        cost_cents = (input_cost + cache_read_cost + cache_create_cost + output_cost) / 100_000

        memory.track_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cost_cents=cost_cents,
        )

        return text, {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read": cache_read,
            "cache_create": cache_create,
            "cost_cents": cost_cents,
        }

    except Exception as e:
        logger.error("Claude call failed: %s", e)
        memory.track_usage(is_error=True)
        return None, None


# -- Rating Keyboard --------------------------------------------------

def _rating_keyboard(response_id):
    """Create inline keyboard with thumbs up/down for rating."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍", callback_data=f"rate:+:{response_id}"),
        InlineKeyboardButton("👎", callback_data=f"rate:-:{response_id}"),
    ]])


async def _send_ai_response(update, text, response_id=None):
    """Send an AI response with rating buttons, splitting if needed."""
    MAX_LEN = 4000
    rid = response_id or "0"

    if len(text) <= MAX_LEN:
        await update.message.reply_text(
            text, reply_markup=_rating_keyboard(rid)
        )
    else:
        # Split on double newlines
        chunks = []
        current = ""
        for paragraph in text.split("\n\n"):
            if len(current) + len(paragraph) + 2 > MAX_LEN:
                if current:
                    chunks.append(current.strip())
                current = paragraph
            else:
                current = current + "\n\n" + paragraph if current else paragraph
        if current:
            chunks.append(current.strip())

        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1:
                await update.message.reply_text(
                    chunk, reply_markup=_rating_keyboard(rid)
                )
            else:
                await update.message.reply_text(chunk)


# -- Handlers ---------------------------------------------------------

@authorized_only
async def handle_text(update, context):
    """Receive text message -> check onboarding/OCR -> save -> tag -> reply Saved."""
    text = update.message.text
    if not text or not text.strip():
        return

    user_id = update.effective_user.id

    # -- Onboarding flow --
    if user_id in _onboarding:
        if text.strip().lower() in ("skip", "/skip"):
            # Skip this question
            step = _onboarding[user_id]["step"]
            total = _onboarding[user_id]["total"]
            logger.info("Onboarding Q%d skipped", step + 1)
        else:
            # Save answer as onboarding entry
            step = _onboarding[user_id]["step"]
            total = _onboarding[user_id]["total"]
            question = ONBOARDING_QUESTIONS[step]

            entry_id = memory.save_entry(
                content=f"[Onboarding Q{step+1}] {question}\n\n{text.strip()}",
                entry_date=date.today(),
                entry_type="onboarding",
                telegram_message_id=update.message.message_id,
            )
            if entry_id:
                importance, topics = tag_entry(text.strip())
                memory.update_entry_tags(entry_id, importance, topics)

        # Advance to next question
        next_step = step + 1
        if next_step < total:
            _onboarding[user_id]["step"] = next_step
            q_num = next_step + 1
            await update.message.reply_text(
                f"({q_num}/{total}) {ONBOARDING_QUESTIONS[next_step]}"
            )
        else:
            # Onboarding complete
            del _onboarding[user_id]
            await update.message.reply_text(
                "Onboarding complete. Building your profile..."
            )
            # Trigger profile rebuild
            profile = memory.rebuild_profile(claude)
            memory.rebuild_topic_summaries(claude)
            if profile:
                await update.message.reply_text(
                    "Profile built. Use /profile to see it.\n"
                    "From now on, just write. Everything is saved silently."
                )
            else:
                await update.message.reply_text(
                    "Profile build had issues (check logs). "
                    "Just start writing -- I'll rebuild later."
                )
            logger.info("Onboarding complete, profile rebuilt")
        return

    pending = get_pending(user_id)

    # -- OCR edit-before-save flow --
    if pending:
        check_marks = {"v", "V", "ok", "OK", "Ok"}
        if text.strip() in check_marks:
            # User confirms OCR text as-is
            return await _save_ocr_entry(update, user_id, pending)

        if text.strip().lower().startswith("date:"):
            # User provides/corrects the date with prefix
            date_str = text.strip()[5:].strip()
            set_date(user_id, date_str)
            await update.message.reply_text(
                f"Date set to {date_str}. Send 'ok' to save or keep editing."
            )
            return

        # Detect bare date (YYYY-MM-DD, DD.MM.YYYY, DD/MM/YYYY, etc.)
        bare = text.strip()
        date_match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', bare)
        if not date_match:
            date_match = re.match(r'^(\d{1,2})[./](\d{1,2})[./](\d{4})$', bare)
            if date_match:
                # DD.MM.YYYY or DD/MM/YYYY -> YYYY-MM-DD
                bare = f"{date_match.group(3)}-{date_match.group(2).zfill(2)}-{date_match.group(1).zfill(2)}"
                date_match = True
        if date_match:
            if date_match is not True:
                bare = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
            set_date(user_id, bare)
            await update.message.reply_text(
                f"Date set to {bare}. Send 'ok' to save or keep editing."
            )
            return

        # User provides corrected text
        apply_correction(user_id, text.strip())
        pending = get_pending(user_id)
        date_info = f"\nDate: {pending['date']}" if pending.get("date") else "\nNo date found. Send a date (YYYY-MM-DD) to set one."
        await update.message.reply_text(
            f"Updated. Current text:\n\n{pending['text']}{date_info}\n\n"
            "Send 'ok' to save, or send another correction."
        )
        return

    # -- Normal text entry flow --
    entry_id = memory.save_entry(
        content=text,
        entry_date=date.today(),
        entry_type="text",
        telegram_message_id=update.message.message_id,
    )

    if entry_id is None:
        await update.message.reply_text("Error saving entry. Check logs.")
        return

    importance, topics = tag_entry(text)
    memory.update_entry_tags(entry_id, importance, topics)

    await update.message.reply_text("Saved")
    logger.info("Entry %s saved (importance=%d, topics=%s)", entry_id, importance, topics)


@authorized_only
async def handle_photo(update, context):
    """Receive photo -> OCR with Claude Vision -> start edit flow."""
    if claude is None:
        await update.message.reply_text("Claude not configured. Cannot process photos.")
        return

    user_id = update.effective_user.id

    # If there's already a pending OCR, warn
    if get_pending(user_id):
        await update.message.reply_text(
            "You have a pending OCR edit. Send 'ok' to save it first, or send a correction."
        )
        return

    # Download the highest-resolution photo
    photo = update.message.photo[-1]
    file = await photo.get_file()
    image_bytes = await file.download_as_bytearray()

    await update.message.reply_text("Reading your handwriting...")

    ocr_result, usage_info = extract_text_from_photo(claude, bytes(image_bytes))

    if ocr_result is None:
        await update.message.reply_text("Could not read the photo. Try a clearer image.")
        memory.track_usage(is_error=True)
        return

    # Track OCR usage
    if usage_info:
        memory.track_usage(
            input_tokens=usage_info["input_tokens"],
            output_tokens=usage_info["output_tokens"],
            cache_read_tokens=usage_info["cache_read_tokens"],
            cost_cents=usage_info["cost_cents"],
        )

    # Start edit flow
    start_edit_flow(user_id, ocr_result, usage_info)

    confidence = ocr_result.get("confidence", "unknown")
    date_info = f"\nDate found: {ocr_result.get('date')}" if ocr_result.get("date") else "\nNo date found on page. Send a date (YYYY-MM-DD) to set one."
    confidence_warning = ""
    if confidence == "low":
        confidence_warning = "\n(Low confidence -- please review carefully)"

    await update.message.reply_text(
        f"Here's what I read:{confidence_warning}\n\n"
        f"{ocr_result.get('text', '')}"
        f"{date_info}\n\n"
        "Send 'ok' to save, send a date (YYYY-MM-DD), or reply with corrected text."
    )
    logger.info("OCR complete (confidence=%s)", confidence)


async def _save_ocr_entry(update, user_id, pending):
    """Finalize and save an OCR entry."""
    data = finish_edit_flow(user_id)
    text = data["text"]

    # Parse entry date
    entry_date = date.today()
    if data.get("date"):
        try:
            entry_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        except ValueError:
            pass

    # Save to entries table
    entry_id = memory.save_entry(
        content=text,
        entry_date=entry_date,
        entry_type="journal_photo",
        telegram_message_id=update.message.message_id,
    )

    if entry_id is None:
        await update.message.reply_text("Error saving entry. Check logs.")
        return

    # Tag with Claude
    importance, topics = tag_entry(text)
    memory.update_entry_tags(entry_id, importance, topics)

    # Save to journal_pages table
    memory.save_journal_page(
        entry_id=entry_id,
        image_url=data.get("image_url"),
        raw_ocr_text=text,
        final_text=text,
        entry_date=entry_date.isoformat(),
        themes=topics,
    )

    await update.message.reply_text("Saved")
    logger.info("OCR entry %s saved (date=%s, importance=%d, topics=%s)",
                entry_id, entry_date, importance, topics)


@authorized_only
async def handle_start(update, context):
    """Start onboarding, resume interrupted onboarding, or welcome back."""
    user_id = update.effective_user.id
    total = len(ONBOARDING_QUESTIONS)
    onboarding_done = memory.get_onboarding_progress()

    if onboarding_done > 0 and onboarding_done < total:
        # Resume interrupted onboarding
        _onboarding[user_id] = {"step": onboarding_done, "total": total}
        q_num = onboarding_done + 1
        await update.message.reply_text(
            f"Resuming onboarding from where you left off.\n\n"
            f"({q_num}/{total}) {ONBOARDING_QUESTIONS[onboarding_done]}"
        )
        logger.info("Onboarding resumed at Q%d for user %s", q_num, user_id)
        return

    if onboarding_done >= total:
        # Fully completed onboarding
        count = memory.get_entry_count()
        await update.message.reply_text(
            f"Welcome back. {count} entries stored.\n"
            "Just write. I save everything silently.\n"
            "Send photos of journal pages for OCR.\n"
            "Use /help to see available commands."
        )
        return

    # Fresh start -- no onboarding entries at all
    _onboarding[user_id] = {"step": 0, "total": total}

    await update.message.reply_text(ONBOARDING_INTRO)
    await update.message.reply_text(
        f"(1/{total}) {ONBOARDING_QUESTIONS[0]}"
    )
    logger.info("Onboarding started for user %s (%d questions)", user_id, total)


@authorized_only
async def handle_help(update, context):
    """Show available commands."""
    await update.message.reply_text(
        "Commands:\n"
        "/start - Welcome / onboarding\n"
        "/question [N] - N personalized questions (default 1)\n"
        "/feedback [topic] - Ruthlessly honest feedback\n"
        "/insight - One key insight about you\n"
        "/report - Self-Knowledge Report (HTML)\n"
        "/profile - View your core profile\n"
        "/rebuild - Rebuild profile from all entries\n"
        "/cost - Today's API usage\n"
        "/export - Download entries as JSON\n"
        "/schedule [HH:MM] [N] - Daily auto-questions\n"
        "/schedule off - Disable daily questions\n\n"
        "Photos: Send a journal page photo for OCR.\n"
        "During onboarding: /skip to skip a question."
    )


@authorized_only
async def handle_schedule(update, context):
    """Set or disable daily auto-questions.

    Usage:
        /schedule 8:00 3    -> 3 questions daily at 8:00
        /schedule 20:30     -> 1 question daily at 20:30
        /schedule off       -> disable
    """
    args = context.args or []
    job_queue = context.application.job_queue

    # Remove existing daily question jobs
    current_jobs = job_queue.get_jobs_by_name("daily_questions")
    for job in current_jobs:
        job.schedule_removal()

    if not args or (len(args) == 1 and args[0].lower() == "off"):
        await update.message.reply_text("Daily questions disabled.")
        logger.info("Daily questions disabled")
        return

    # Parse time (in user's local timezone)
    user_tz = ZoneInfo("Asia/Kuala_Lumpur")
    time_str = args[0]
    try:
        hour, minute = map(int, time_str.split(":"))
        target_time = time(hour=hour, minute=minute, tzinfo=user_tz)
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Invalid time format. Use HH:MM (e.g. /schedule 8:00 3)"
        )
        return

    # Parse question count
    n = 1
    if len(args) > 1:
        try:
            n = max(1, min(10, int(args[1])))
        except ValueError:
            pass

    job_queue.run_daily(
        daily_question_job,
        time=target_time,
        name="daily_questions",
        data=n,
    )

    await update.message.reply_text(
        f"Daily questions set: {n} question(s) at {time_str} (Malaysia time)."
    )
    logger.info("Daily questions scheduled: %d at %s Malaysia time", n, time_str)


@authorized_only
async def handle_cost(update, context):
    """Show today's usage stats."""
    usage = memory.get_usage_today()
    if not usage:
        await update.message.reply_text("No usage data for today yet.")
        return

    cost = float(usage.get("estimated_cost_cents", 0))
    monthly_est = cost * 30

    await update.message.reply_text(
        f"Today's usage:\n"
        f"  Entries: {usage.get('entries_count', 0)}\n"
        f"  AI calls: {usage.get('ai_calls_count', 0)}\n"
        f"  Tokens in: {usage.get('input_tokens', 0):,}\n"
        f"  Tokens out: {usage.get('output_tokens', 0):,}\n"
        f"  Cache reads: {usage.get('cache_read_tokens', 0):,}\n"
        f"  Cost today: ${cost / 100:.4f}\n"
        f"  Est. monthly: ${monthly_est / 100:.2f}"
    )


@authorized_only
async def handle_export(update, context):
    """Export all entries as JSON file."""
    entries = memory.get_recent_entries(limit=10000)
    if not entries:
        await update.message.reply_text("No entries to export.")
        return

    for e in entries:
        e.pop("embedding", None)

    export_path = os.path.join(PROJECT_ROOT, ".tmp", "mirror_export.json")
    os.makedirs(os.path.dirname(export_path), exist_ok=True)

    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2, default=str)

    await update.message.reply_document(
        document=open(export_path, "rb"),
        filename="mirror_export.json",
        caption=f"{len(entries)} entries exported."
    )


@authorized_only
async def handle_skip(update, context):
    """Skip current onboarding question."""
    user_id = update.effective_user.id
    if user_id not in _onboarding:
        await update.message.reply_text("Nothing to skip.")
        return

    step = _onboarding[user_id]["step"]
    total = _onboarding[user_id]["total"]
    logger.info("Onboarding Q%d skipped", step + 1)

    next_step = step + 1
    if next_step < total:
        _onboarding[user_id]["step"] = next_step
        await update.message.reply_text(
            f"Skipped. ({next_step+1}/{total}) {ONBOARDING_QUESTIONS[next_step]}"
        )
    else:
        del _onboarding[user_id]
        await update.message.reply_text(
            "Onboarding complete. Building your profile..."
        )
        profile = memory.rebuild_profile(claude)
        memory.rebuild_topic_summaries(claude)
        if profile:
            await update.message.reply_text(
                "Profile built. Use /profile to see it.\n"
                "From now on, just write. Everything is saved silently."
            )
        else:
            await update.message.reply_text(
                "Profile build had issues (check logs). "
                "Just start writing -- I'll rebuild later."
            )


@authorized_only
async def handle_profile(update, context):
    """Show the user's Tier 1 core profile."""
    profile = memory.load_profile()
    if not profile:
        await update.message.reply_text(
            "No profile built yet. Use /start to begin onboarding, "
            "or keep writing entries and I'll build one after enough data."
        )
        return

    # Split into chunks for Telegram's 4096 char limit
    MAX_LEN = 4000
    if len(profile) <= MAX_LEN:
        await update.message.reply_text(profile)
    else:
        # Split on double newlines (section boundaries) to keep it clean
        chunks = []
        current = ""
        for paragraph in profile.split("\n\n"):
            if len(current) + len(paragraph) + 2 > MAX_LEN:
                if current:
                    chunks.append(current.strip())
                current = paragraph
            else:
                current = current + "\n\n" + paragraph if current else paragraph
        if current:
            chunks.append(current.strip())

        for i, chunk in enumerate(chunks):
            await update.message.reply_text(chunk)


@authorized_only
async def handle_rebuild(update, context):
    """Manually trigger a full profile rebuild."""
    await update.message.reply_text("Rebuilding profile...")

    profile = memory.rebuild_profile(claude)
    topics = memory.rebuild_topic_summaries(claude)

    if profile:
        topic_count = len(topics)
        await update.message.reply_text(
            f"Profile rebuilt. {topic_count} topic summaries updated.\n"
            "Use /profile to view."
        )
    else:
        await update.message.reply_text("Rebuild failed. Check logs.")


@authorized_only
async def handle_question(update, context):
    """Generate personalized journal questions."""
    args = context.args or []
    n = 1
    if args:
        try:
            n = max(1, min(10, int(args[0])))
        except ValueError:
            pass

    profile = memory.load_profile()
    if not profile:
        await update.message.reply_text(
            "No profile built yet. Send more entries or run /start."
        )
        return

    topics = memory.load_all_topics()
    ctx = build_context(profile, topics)
    prompt = QUESTION_PROMPT.format(n=n, context=ctx)

    text, _ = call_claude(prompt, max_tokens=500)
    if text:
        await _send_ai_response(update, text)
        logger.info("Generated %d question(s)", n)
    else:
        await update.message.reply_text("Failed to generate questions. Check logs.")


@authorized_only
async def handle_feedback(update, context):
    """Provide ruthlessly honest feedback, optionally on a specific topic."""
    args = context.args or []
    topic_arg = " ".join(args).strip() if args else None

    profile = memory.load_profile()
    if not profile:
        await update.message.reply_text(
            "No profile built yet. Send more entries or run /start."
        )
        return

    if topic_arg:
        # Load specific topic
        topic_summary = memory.load_topic(topic_arg)
        if not topic_summary:
            await update.message.reply_text(
                f"Not enough data on \"{topic_arg}\". "
                f"Available topics: career, relationships, health, education, "
                f"emotions, finance, daily_life, goals"
            )
            return
        topics = {topic_arg: topic_summary}
    else:
        topics = memory.load_all_topics()

    ctx = build_context(profile, topics)
    display_topic = topic_arg or "general"
    prompt = FEEDBACK_PROMPT.format(context=ctx, topic=display_topic)

    text, _ = call_claude(prompt, max_tokens=1000)
    if text:
        await _send_ai_response(update, text)
        logger.info("Feedback generated (topic=%s)", display_topic)
    else:
        await update.message.reply_text("Failed to generate feedback. Check logs.")


@authorized_only
async def handle_insight(update, context):
    """Share one key insight about the user right now."""
    profile = memory.load_profile()
    if not profile:
        await update.message.reply_text(
            "No profile built yet. Send more entries or run /start."
        )
        return

    topics = memory.load_all_topics()
    ctx = build_context(profile, topics)
    prompt = INSIGHT_PROMPT.format(context=ctx)

    text, _ = call_claude(prompt, max_tokens=500)
    if text:
        await _send_ai_response(update, text)
        logger.info("Insight generated")
    else:
        await update.message.reply_text("Failed to generate insight. Check logs.")


@authorized_only
async def handle_report(update, context):
    """Generate and send HTML Self-Knowledge Report."""
    profile = memory.load_profile()
    if not profile:
        await update.message.reply_text(
            "No profile built yet. Send more entries or run /start."
        )
        return

    await update.message.reply_text("Generating your Self-Knowledge Report...")

    topics = memory.load_all_topics()
    ctx = build_context(profile, topics)
    prompt = REPORT_PROMPT.format(context=ctx)

    text, _ = call_claude(prompt, max_tokens=2000)
    if not text:
        await update.message.reply_text("Report generation failed. Check logs.")
        return

    report_data = parse_report_json(text)
    if not report_data:
        # Fallback: send raw text
        await update.message.reply_text("Could not parse report. Raw output:")
        await _send_ai_response(update, text)
        return

    html = generate_report_html(report_data, profile_text=profile)

    # Save and send as file
    report_path = os.path.join(PROJECT_ROOT, ".tmp", "mirror_report.html")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    await update.message.reply_document(
        document=open(report_path, "rb"),
        filename=f"mirror_report_{date.today().isoformat()}.html",
        caption="Your Self-Knowledge Report."
    )
    logger.info("Report generated and sent")


@authorized_only
async def handle_rating_callback(update, context):
    """Handle thumbs up/down rating from inline keyboard."""
    query = update.callback_query

    try:
        await query.answer()
    except Exception:
        pass  # Telegram rejects stale callbacks (>30s old) -- still record the rating

    data = query.data  # format: "rate:+:response_id" or "rate:-:response_id"
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "rate":
        return

    rating = 1 if parts[1] == "+" else -1
    response_id = parts[2]

    # Track the rating
    memory.track_usage(rating=rating)

    label = "positive" if rating > 0 else "negative"
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass  # Can't edit old messages -- rating is still saved
    logger.info("Rating: %s (response_id=%s)", label, response_id)


async def weekly_rebuild_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback: full profile rebuild every week."""
    logger.info("Starting weekly profile rebuild...")
    profile = memory.rebuild_profile(claude)
    topics = memory.rebuild_topic_summaries(claude)
    if profile:
        topic_count = len(topics)
        await context.bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=f"Weekly profile rebuild complete. {topic_count} topics updated."
        )
        logger.info("Weekly rebuild done: %d topics", topic_count)
    else:
        logger.warning("Weekly rebuild failed or no entries")


async def weekly_self_review_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback: run weekly self-review every Sunday."""
    logger.info("Starting weekly self-review...")
    review_text, _ = memory.run_weekly_self_review(claude)
    if review_text:
        logger.info("Weekly self-review saved")
    else:
        logger.info("Weekly self-review skipped (no data)")


async def monthly_improvement_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue callback: monthly improvement summary on 1st of each month."""
    logger.info("Starting monthly improvement summary...")
    text = memory.run_monthly_improvement(claude)
    if text:
        # Send to user via Telegram
        MAX_LEN = 4000
        if len(text) <= MAX_LEN:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=f"Monthly Mirror Self-Review:\n\n{text}",
            )
        else:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=f"Monthly Mirror Self-Review:\n\n{text[:MAX_LEN]}",
            )
        logger.info("Monthly improvement summary sent to user")
    else:
        logger.info("Monthly improvement skipped (no reviews)")


# -- Error Handler ----------------------------------------------------

async def error_handler(update, context):
    """Log errors without crashing the bot."""
    logger.error("Update %s caused error: %s", update, context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("Something went wrong. Check logs.")
        except Exception:
            pass


# -- Main -------------------------------------------------------------

def main():
    global memory, claude

    parser = argparse.ArgumentParser(description="Mirror Journal Bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use local SQLite instead of Supabase")
    args = parser.parse_args()

    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not AUTHORIZED_USER_ID:
        print("ERROR: TELEGRAM_USER_ID not set in .env")
        sys.exit(1)

    memory = MirrorMemory(dry_run=args.dry_run)
    mode = "DRY-RUN (SQLite)" if args.dry_run else "LIVE (Supabase)"
    logger.info("Starting Mirror bot in %s mode", mode)

    if ANTHROPIC_KEY:
        claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        logger.info("Claude client initialized")
    else:
        logger.warning("ANTHROPIC_API_KEY not set -- tagging disabled")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("cost", handle_cost))
    app.add_handler(CommandHandler("export", handle_export))
    app.add_handler(CommandHandler("schedule", handle_schedule))
    app.add_handler(CommandHandler("profile", handle_profile))
    app.add_handler(CommandHandler("rebuild", handle_rebuild))
    app.add_handler(CommandHandler("skip", handle_skip))
    app.add_handler(CommandHandler("question", handle_question))
    app.add_handler(CommandHandler("feedback", handle_feedback))
    app.add_handler(CommandHandler("insight", handle_insight))
    app.add_handler(CommandHandler("report", handle_report))

    # Callback handler for ratings
    app.add_handler(CallbackQueryHandler(handle_rating_callback, pattern=r"^rate:"))

    # Message handlers
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(error_handler)

    # Weekly profile rebuild -- every Sunday at 3:00 AM Malaysia time
    user_tz = ZoneInfo("Asia/Kuala_Lumpur")
    app.job_queue.run_daily(
        weekly_rebuild_job,
        time=time(hour=3, minute=0, tzinfo=user_tz),
        days=(6,),  # Sunday
        name="weekly_rebuild",
    )
    logger.info("Weekly rebuild scheduled: Sundays at 03:00 Malaysia time")

    # Weekly self-review -- every Sunday at 3:30 AM (after rebuild finishes)
    app.job_queue.run_daily(
        weekly_self_review_job,
        time=time(hour=3, minute=30, tzinfo=user_tz),
        days=(6,),  # Sunday
        name="weekly_self_review",
    )
    logger.info("Weekly self-review scheduled: Sundays at 03:30 Malaysia time")

    # Monthly improvement -- 1st of each month at 9:00 AM
    app.job_queue.run_monthly(
        monthly_improvement_job,
        when=time(hour=9, minute=0, tzinfo=user_tz),
        day=1,
        name="monthly_improvement",
    )
    logger.info("Monthly improvement scheduled: 1st of each month at 09:00 Malaysia time")

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
