"""Test OCR on a journal photo without running the full bot.

Usage:
    py -3.13 tools/test_ocr.py path/to/journal_photo.jpg
"""

import os
import sys

import anthropic
from dotenv import load_dotenv

# Add tools/ to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mirror_vision import extract_text_from_photo

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def main():
    if len(sys.argv) < 2:
        print("Usage: py -3.13 tools/test_ocr.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        print(f"File not found: {image_path}")
        sys.exit(1)

    ext = os.path.splitext(image_path)[1].lower()
    media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    media_type = media_types.get(ext, "image/jpeg")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    print(f"Processing {image_path} ({len(image_bytes):,} bytes)...")
    result, usage = extract_text_from_photo(client, image_bytes, media_type)

    if result is None:
        print("OCR failed. Check the image quality.")
        sys.exit(1)

    print(f"\nConfidence: {result.get('confidence', 'unknown')}")
    print(f"Date found: {result.get('date', 'none')}")
    print(f"\n--- Extracted text ---\n{result.get('text', '')}\n---")

    if usage:
        cost = usage["cost_cents"]
        print(f"\nTokens: {usage['input_tokens']} in / {usage['output_tokens']} out")
        print(f"Cost: ${cost / 100:.4f}")


if __name__ == "__main__":
    main()
