# Session 3: Onboarding + Profile Builder

## Objective
Build the `/start` onboarding interview (20-30 questions) and the profile rebuild system that constructs Tier 1 + Tier 2 from entries.

## Prerequisites
- Session 2 complete (OCR + questions working)

## Required Inputs
- Working bot with text + photo entry saving
- Entries in database (from testing)

## Application File Updates

### 1. Updates to tools/mirror_bot.py
- Replace placeholder `/start` with full onboarding conversation flow
- 20 questions asked one at a time
- Each answer saved as an entry with `type="onboarding"`
- After all questions: trigger initial profile build
- Add `/profile` command to view current Tier 1 profile

### 2. Updates to tools/mirror_memory.py
- `rebuild_profile()` — gather entries, call Claude to build Tier 1
- `rebuild_topic_summaries()` — gather entries by topic, build Tier 2 for each
- `save_profile_snapshot()` — save to `profile_history` table
- Weekly rebuild job integration

### 3. Updates to tools/mirror_prompts.py
- `ONBOARDING_QUESTIONS` list (20 questions)
- `ONBOARDING_INTRO` template
- `PROFILE_REBUILD_PROMPT` — builds core profile from entries
- `TOPIC_SUMMARY_PROMPT` — builds per-topic summary

## Tools to Build

### tools/rebuild_profile.py — NEW
Manually trigger a full profile rebuild.
```
py -3.13 tools/rebuild_profile.py [--dry-run]
```
Loads all entries, calls Claude to build Tier 1 + all Tier 2 summaries, saves results.

## Testing
1. `/start` -> receive first onboarding question
2. Answer 20 questions -> all saved as entries
3. After last answer -> profile built automatically
4. `/profile` -> see coherent Tier 1 profile
5. Check `profile_history` table -> snapshot saved
6. Run `tools/rebuild_profile.py` -> verify manual rebuild works
7. Wait 1 week (or trigger manually) -> weekly rebuild runs

## Expected Output
- Complete onboarding flow
- Tier 1 core profile built from answers
- Tier 2 topic summaries built
- Profile snapshot in `profile_history`

## Edge Cases
- **User abandons onboarding mid-way**: Save what they answered, don't lose progress. Allow resuming.
- **User already has entries (skipped onboarding)**: Profile can be built from existing entries without onboarding.
- **Too few entries for profile**: Claude returns partial profile with "I don't have enough data" markers.
- **Rebuild with 0 entries**: Return empty profile, don't crash.

## Known Quirks
- Profile rebuild uses significant tokens (~2-5K input for entries + ~1K output). Track cost.
- Claude prompt caching will help here — the system prompt + profile rebuild prompt are cacheable.
- `profile_history` grows over time — consider monthly cleanup of old snapshots.
