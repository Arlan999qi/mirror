"""Manually trigger a weekly self-review.

Usage:
    py -3.13 tools/run_self_review.py              # Run against Supabase
    py -3.13 tools/run_self_review.py --dry-run    # Run against local SQLite
"""

import argparse
import os
import sys

from dotenv import load_dotenv

# Project root is one level up from tools/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from mirror_memory import MirrorMemory


def main():
    parser = argparse.ArgumentParser(description="Run Mirror weekly self-review")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use local SQLite instead of Supabase")
    args = parser.parse_args()

    memory = MirrorMemory(dry_run=args.dry_run)
    mode = "DRY-RUN (SQLite)" if args.dry_run else "LIVE (Supabase)"
    print(f"Running self-review in {mode} mode...")

    review_text, suggestions = memory.run_weekly_self_review()

    if review_text:
        print("\n=== WEEKLY SELF-REVIEW ===\n")
        print(review_text)
        print("\n=== END ===")
    else:
        print("No data for self-review (need at least 1 day of usage tracking).")


if __name__ == "__main__":
    main()
