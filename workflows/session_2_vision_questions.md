# Session 2: Vision (OCR) + Daily Questions

## Objective
Add journal photo OCR with edit-before-save flow, and daily question generation via JobQueue.

## Prerequisites
- Session 1 complete (core bot running, text entries working)

## Required Inputs
- Working bot from Session 1
- Claude Vision access (included in Sonnet pricing)

## Application Files to Build/Verify

### 1. tools/mirror_vision.py (~120 lines) — NEW
Photo OCR + edit flow:
- `extract_text_from_photo(image_bytes)` — calls Claude Vision with OCR_PROMPT, returns `{text, date, confidence}`
- Edit-before-save conversation state management

**OCR Flow:**
1. User sends photo
2. Claude Vision extracts text + date
3. Bot sends: "Here's what I read: {text}. Reply with corrections or send ✓ to save as-is"
4. User confirms, corrects, or provides fixes
5. Final text saved to `entries` + `journal_pages` tables

### 2. Updates to tools/mirror_bot.py
- Add photo handler using `tools/mirror_vision.py`
- Add conversation state for OCR edit flow
- Add `/schedule` command handler
- Add daily question JobQueue integration

### 3. Updates to tools/mirror_prompts.py
- Add `OCR_PROMPT` — extract text from handwritten journal photo
- Add `QUESTION_PROMPT` — generate personalized questions based on profile

## Tools to Build

### tools/test_ocr.py — NEW
Test OCR on a sample image without running the full bot.
```
py -3.13 tools/test_ocr.py path/to/journal_photo.jpg
```
Calls Claude Vision, prints extracted text + confidence.

## Testing
1. Upload journal photo -> see extracted text
2. Reply with correction -> see updated text
3. Send ✓ -> "Saved" + entry in DB with correct date
4. `/schedule 8:00 3` -> confirm schedule set
5. Wait for scheduled time -> receive 3 personalized questions
6. `/schedule off` -> confirm disabled

## Expected Output
- Photos processed through edit-before-save flow
- Journal pages stored in `journal_pages` table with OCR text
- Daily questions delivered on schedule

## Edge Cases
- **Unreadable handwriting**: Show low confidence warning, still let user edit
- **No date on page**: Ask user to provide the date
- **Mixed Russian/English cursive**: Claude Vision handles both — prompt explicitly asks for it
- **Multiple photos in sequence**: Each enters its own edit flow
- **User sends photo during active edit flow**: Queue it, finish current edit first

## Known Quirks
- Claude Vision input tokens are higher for images (~1000-2000 tokens per photo)
- Russian cursive accuracy varies — the edit step is critical for reliability
- JobQueue requires the bot to stay running (no persistence across restarts)
