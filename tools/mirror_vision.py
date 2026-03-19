"""Journal photo OCR + PDF extraction via Claude Vision.

Handles:
- Extracting text from handwritten journal photos (single + album mode)
- Extracting text from PDF documents (native Claude document support)
- Session-based state for multi-page edit-before-save flow
"""

import base64
import json
import logging

from mirror_prompts import OCR_PROMPT

logger = logging.getLogger("mirror.vision")

# PDF extraction prompt (similar to OCR but for typed/printed documents)
PDF_OCR_PROMPT = """You are a document text extractor. The user sends a PDF document (scanned or digital).

Extract ALL text from the document. Also look for dates mentioned in the document.

Return a JSON object with:
- "text": the full extracted text, preserving paragraph breaks and page structure
- "date": the most relevant date found (format: YYYY-MM-DD) or null if none found
- "confidence": "high", "medium", or "low" based on text clarity

Rules:
- Preserve the original language (Russian, English, or mixed)
- Maintain paragraph and page structure
- If text spans multiple pages, separate with clear page breaks
- Return ONLY valid JSON. No explanation."""


def extract_text_from_photo(claude_client, image_bytes, media_type="image/jpeg"):
    """Call Claude Vision to OCR a handwritten journal photo.

    Returns (result_dict, usage_info) or (None, None) on failure.
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


def extract_text_from_pdf(claude_client, pdf_bytes):
    """Extract text from a PDF using Claude's native document support.

    Returns (result_dict, usage_info) or (None, None) on failure.
    """
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    try:
        response = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=PDF_OCR_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract all text from this document.",
                    },
                ],
            }],
        )

        text = response.content[0].text.strip()
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
        logger.error("PDF extraction failed: %s", e)
        return None, None


# -- Session-based state for edit-before-save flow --

class OCRSession:
    """Tracks state for single photo, album, or PDF entry creation."""

    def __init__(self, session_type="single", media_group_id=None):
        self.session_type = session_type  # "single", "album", "pdf"
        self.media_group_id = media_group_id
        self.pages = []           # list of {text, date, confidence, image_url, usage_info, page_num}
        self.combined_text = ""
        self.combined_date = None
        self.combined_confidence = "low"
        self.total_usage = {"input_tokens": 0, "output_tokens": 0,
                            "cache_read_tokens": 0, "cost_cents": 0}

    def add_page(self, ocr_result, usage_info, image_url=None, page_num=None):
        """Add an OCR'd page to this session."""
        page = {
            "text": ocr_result.get("text", ""),
            "date": ocr_result.get("date"),
            "confidence": ocr_result.get("confidence", "low"),
            "image_url": image_url,
            "usage_info": usage_info,
            "page_num": page_num if page_num is not None else len(self.pages) + 1,
        }
        self.pages.append(page)

        # Accumulate usage
        if usage_info:
            for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cost_cents"):
                self.total_usage[key] = self.total_usage.get(key, 0) + (usage_info.get(key, 0) or 0)

    def assemble(self):
        """Combine all pages into a single text. Call after all pages are added."""
        if not self.pages:
            return

        # Sort by page number
        sorted_pages = sorted(self.pages, key=lambda p: p.get("page_num", 0))

        if len(sorted_pages) == 1:
            # Single page — no separators
            self.combined_text = sorted_pages[0]["text"]
            self.combined_date = sorted_pages[0]["date"]
            self.combined_confidence = sorted_pages[0]["confidence"]
        else:
            # Multi-page — add separators
            parts = []
            for p in sorted_pages:
                parts.append(f"--- Page {p['page_num']} ---\n{p['text']}")
            self.combined_text = "\n\n".join(parts)

            # Pick earliest non-null date
            dates = [p["date"] for p in sorted_pages if p.get("date")]
            self.combined_date = min(dates) if dates else None

            # Worst confidence wins
            confidences = [p["confidence"] for p in sorted_pages]
            if "low" in confidences:
                self.combined_confidence = "low"
            elif "medium" in confidences:
                self.combined_confidence = "medium"
            else:
                self.combined_confidence = "high"


# Session storage
_sessions = {}  # {user_id: OCRSession}


def create_session(user_id, session_type="single", media_group_id=None):
    """Create a new OCR session for a user."""
    session = OCRSession(session_type=session_type, media_group_id=media_group_id)
    _sessions[user_id] = session
    return session


def get_session(user_id):
    """Get the active session for a user, or None."""
    return _sessions.get(user_id)


def finish_session(user_id):
    """Remove and return the session for a user."""
    return _sessions.pop(user_id, None)


# -- Backward-compatible API (wraps sessions) --

def start_edit_flow(user_id, ocr_result, usage_info, image_url=None):
    """Store OCR result while user reviews/edits. Creates a single-page session."""
    session = create_session(user_id, session_type="single")
    session.add_page(ocr_result, usage_info, image_url=image_url)
    session.assemble()


def get_pending(user_id):
    """Get pending OCR result for a user, or None. Backward compat wrapper."""
    session = get_session(user_id)
    if session is None:
        return None
    return {
        "text": session.combined_text,
        "date": session.combined_date,
        "confidence": session.combined_confidence,
        "image_url": session.pages[0]["image_url"] if session.pages else None,
        "usage_info": session.total_usage,
    }


def apply_correction(user_id, corrected_text):
    """Update the pending text with user's correction."""
    session = get_session(user_id)
    if session:
        session.combined_text = corrected_text


def set_date(user_id, date_str):
    """Update the pending date."""
    session = get_session(user_id)
    if session:
        session.combined_date = date_str


def finish_edit_flow(user_id):
    """Remove and return the pending OCR data. Backward compat wrapper."""
    session = finish_session(user_id)
    if session is None:
        return None
    return {
        "text": session.combined_text,
        "date": session.combined_date,
        "confidence": session.combined_confidence,
        "image_url": session.pages[0]["image_url"] if session.pages else None,
        "usage_info": session.total_usage,
        "session": session,  # Include full session for multi-page saves
    }
