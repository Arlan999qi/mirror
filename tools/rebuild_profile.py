"""Manually trigger a full profile rebuild.

Usage:
    py -3.13 tools/rebuild_profile.py              # Normal mode (Supabase)
    py -3.13 tools/rebuild_profile.py --dry-run    # Local SQLite mode
"""

import argparse
import logging
import os
import sys

import anthropic
from dotenv import load_dotenv

# Add tools/ to path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mirror_memory import MirrorMemory, PROJECT_ROOT

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mirror.rebuild")


def main():
    parser = argparse.ArgumentParser(description="Rebuild Mirror profile")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use local SQLite instead of Supabase")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    memory = MirrorMemory(dry_run=args.dry_run)
    claude_client = anthropic.Anthropic(api_key=api_key)

    entry_count = memory.get_entry_count()
    print(f"Found {entry_count} entries in database.")

    if entry_count == 0:
        print("No entries to rebuild from. Exiting.")
        sys.exit(0)

    # Rebuild Tier 1
    print("\nRebuilding Tier 1 (core profile)...")
    profile = memory.rebuild_profile(claude_client)
    if profile:
        print(f"Profile built ({len(profile)} chars).")
        print("\n--- PROFILE ---")
        print(profile)
        print("--- END ---\n")
    else:
        print("Profile rebuild failed.")

    # Rebuild Tier 2
    print("Rebuilding Tier 2 (topic summaries)...")
    topics = memory.rebuild_topic_summaries(claude_client)
    for topic, summary in topics.items():
        print(f"\n  [{topic}] {len(summary)} chars")

    print(f"\nDone. {len(topics)} topic summaries rebuilt.")


if __name__ == "__main__":
    main()
