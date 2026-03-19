# Session 4: Reports + AI Commands + Feedback Loop

## Objective
Build the HTML Self-Knowledge Report, all remaining AI commands (/feedback, /insight, /question, /profile), thumbs up/down rating, usage tracking, and prompt caching.

## Prerequisites
- Session 3 complete (onboarding + profile builder working)
- Tier 1 and Tier 2 profiles exist

## Required Inputs
- Working bot with entries, profiles, topic summaries
- At least 10+ entries for meaningful AI output

## Application Files to Build/Verify

### 1. tools/mirror_reports.py (~200 lines) — NEW
HTML Self-Knowledge Report generator:
- `generate_report(profile, topics, highlights)` -> HTML string
- Sections: identity, values, patterns, relationships, goals, contradictions, blind spots, evolution
- Clean, readable HTML (no external CSS dependencies)
- Sent as document via Telegram

### 2. Updates to tools/mirror_bot.py
- `/feedback [topic]` — load Tier 1 + relevant Tier 2, call Claude with FEEDBACK_PROMPT
- `/feedback` (no topic) — load Tier 1 + all Tier 2, general feedback
- `/insight` — load Tier 1 + all Tier 2, call Claude with INSIGHT_PROMPT
- `/question [N]` — generate N personalized questions (default 1)
- `/profile` — display current Tier 1 profile
- `/report` — generate + send HTML report
- Thumbs up/down inline keyboard after every AI response
- Rating callback handler

### 3. Updates to tools/mirror_prompts.py
- Verify all prompts are complete: FEEDBACK_PROMPT, INSIGHT_PROMPT, QUESTION_PROMPT, PROFILE_DISPLAY_PROMPT

### 4. Prompt caching implementation
- Cache the system prompt (MIRROR_SYSTEM) across calls
- Cache Tier 1 profile when loaded
- Use Anthropic's prompt caching API (`cache_control` parameter)

## Tools to Build

### tools/test_commands.py — NEW
Test all AI commands without Telegram.
```
py -3.13 tools/test_commands.py [--dry-run]
```
Simulates /feedback, /insight, /question calls. Prints outputs + token usage.

### tools/generate_report.py — NEW
Generate a test report from current profile data.
```
py -3.13 tools/generate_report.py [--dry-run]
```
Outputs HTML to `.tmp/test_report.html` and opens in browser.

## Testing
1. `/feedback career` -> honest feedback citing entries by date
2. `/feedback` -> general feedback across all topics
3. `/insight` -> one specific, evidence-backed insight
4. `/question 3` -> 3 personalized questions
5. `/profile` -> readable profile summary
6. `/report` -> receive HTML document
7. Rate response thumbs up -> verify in `usage_tracking`
8. Rate response thumbs down -> verify in `usage_tracking`
9. `/cost` -> accurate usage + cost numbers
10. Anti-sycophancy check: send entry about feeling bad, ask for feedback -> should NOT be comforting

## Expected Output
- All 10 commands working
- HTML report generates cleanly
- Ratings stored correctly
- Prompt caching reducing costs
- Anti-sycophancy system prompt producing honest output

## Edge Cases
- **No profile exists yet**: Commands return "No profile built yet. Send more entries or run /start."
- **Empty topic summary**: Feedback says "Not enough data on {topic}."
- **Very long report**: Truncate in Telegram message, send full version as HTML file.
- **Claude refuses to be harsh**: Check system prompt. The anti-sycophancy prompt must override default behavior.

## Known Quirks
- Prompt caching: first call creates cache (~$3.75/M tokens), subsequent reads are $0.30/M. Break-even at ~3 calls.
- Inline keyboard for ratings must include the entry_id in callback data.
- HTML report should be self-contained (inline CSS, no external resources).
- Telegram message limit is 4096 characters — split long AI responses.
