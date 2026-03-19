"""Journal photo OCR via Claude Vision + edit-before-save flow.

Handles:
- Extracting text from handwritten journal photos
- Conversation state for the edit-before-save cycle
- Saving finalized text to entries + journal_pages tables
"""

import base64
import json
import logging

from mirror_prompts import OCR_PROMPT

logger = logging.getLogger("mirror.vision")


def extract_text_from_photo(claude_client, image_bytes, media_type="image/jpeg"):
    """Call Claude Vision to OCR a handwritten journal photo.

    Returns dict: {text, date, confidence} or None on failure.
    Also returns usage dict for cost tracking.
    """
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    try:
        response = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=OCR_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract all text from this handwritten journal page.",
                    },
                ],
            }],
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)

        usage_info = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        }
        cost_cents = (usage_info["input_tokens"] * 0.3 + usage_info["output_tokens"] * 1.5) / 100_000
        usage_info["cost_cents"] = cost_cents

        return result, usage_info

    except Exception as e:
        logger.error("OCR extraction failed: %s", e)
        return None, None


# -- Conversation state for edit-before-save flow --

# {user_id: {text, date, confidence, image_url, usage_info}}
_pending_ocr = {}


def start_edit_flow(user_id, ocr_result, usage_info, image_url=None):
    """Store OCR result while user reviews/edits."""
    _pending_ocr[user_id] = {
        "text": ocr_result.get("text", ""),
        "date": ocr_result.get("date"),
        "confidence": ocr_result.get("confidence", "low"),
        "image_url": image_url,
        "usage_info": usage_info,
    }


def get_pending(user_id):
    """Get pending OCR result for a user, or None."""
    return _pending_ocr.get(user_id)


def apply_correction(user_id, corrected_text):
    """Update the pending text with user's correction."""
    if user_id in _pending_ocr:
        _pending_ocr[user_id]["text"] = corrected_text


def set_date(user_id, date_str):
    """Update the pending date."""
    if user_id in _pending_ocr:
        _pending_ocr[user_id]["date"] = date_str


def finish_edit_flow(user_id):
    """Remove and return the pending OCR data."""
    return _pending_ocr.pop(user_id, None)
