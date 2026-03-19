# Session 5: Deploy + Self-Improvement

## Objective
Deploy the bot for persistent operation and set up the self-improvement feedback loop (weekly reviews, monthly suggestions).

## Prerequisites
- Session 4 complete (all commands working, ratings, reports)
- Bot fully tested end-to-end from phone

## Required Inputs
- Complete working bot
- Decision: Oracle Cloud Always-Free vs keep on Windows PC

## Steps

### 1. Deployment (choose one)

**Option A: Keep on Windows PC (simplest)**
- Run as background process or Windows Task Scheduler
- `py -3.13 tools/mirror_bot.py` in a persistent terminal
- Downside: stops when PC is off or restarts

**Option B: Oracle Cloud Always-Free**
- Create Always-Free Ampere A1 instance (4 OCPUs, 24GB RAM)
- Install Python 3.13 + dependencies
- Upload bot files + .env
- Run with systemd service for auto-restart
- Tool: `tools/deploy_oracle.py` (creates systemd unit file, handles setup)

### 2. Weekly self-review job
Add to tools/mirror_bot.py:
- JobQueue job: runs every Sunday
- Loads past week: entries count, AI calls, ratings, errors
- Calls Claude to review patterns and suggest improvements
- Saves to `self_reviews` table
- Does NOT auto-apply changes — just records suggestions

### 3. Monthly improvement suggestions
Add to tools/mirror_bot.py:
- JobQueue job: runs 1st of each month
- Loads all self_reviews from past month
- Calls Claude to synthesize improvement suggestions
- Sends summary to user via Telegram
- Categories: auto-apply (topic weights, cache tuning) vs needs-approval (prompt changes, features)

### 4. End-to-end verification
Run the full verification checklist from CLAUDE.md:
1. Message bot -> "Saved" -> verify in Supabase
2. Send journal photo -> OCR edit flow -> saved
3. `/question 3` -> personalized questions
4. `/feedback career` -> honest feedback
5. `/report` -> HTML report
6. Rate response -> rating stored
7. `/cost` -> accurate usage
8. `/export` -> JSON file
9. Restart bot -> context preserved
10. Check `self_reviews` -> improvement suggestions

## Tools to Build

### tools/deploy_oracle.py — NEW (if Oracle Cloud chosen)
Generates deployment artifacts:
- systemd service file
- Setup script for Oracle Cloud instance
- .env transfer instructions

### tools/run_self_review.py — NEW
Manually trigger a weekly self-review.
```
py -3.13 tools/run_self_review.py [--dry-run]
```

## Expected Output
- Bot running persistently
- Weekly self-reviews generating insights
- Monthly suggestions arriving via Telegram
- Full end-to-end verification passing

## Edge Cases
- **Bot crashes**: systemd restarts automatically (Oracle) or manual restart (Windows)
- **Supabase free tier limits**: 500MB DB, 1GB storage. Monitor with `/cost`.
- **Self-review with no data**: Skip review, log "insufficient data"
- **Oracle Cloud session timeout**: systemd keeps process alive

## Known Quirks
- Oracle Cloud Always-Free ARM instances: use `aarch64` Python builds
- JobQueue schedules reset on bot restart — store schedule config in DB or .env
- Self-review costs ~$0.02-0.05 per run (weekly = ~$0.10-0.20/month)
