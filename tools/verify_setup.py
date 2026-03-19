"""Verify all credentials and connections for Mirror bot."""
import os
import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def check_telegram():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[FAIL] TELEGRAM_BOT_TOKEN not set")
        return
    resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("ok"):
            bot = data["result"]
            print(f"[OK]   Telegram bot: @{bot['username']} ({bot['first_name']})")
            return
    print(f"[FAIL] Telegram token invalid: {resp.text[:100]}")


def check_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("[FAIL] SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return
    resp = requests.get(
        f"{url}/rest/v1/",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=10,
    )
    if resp.status_code == 200:
        print(f"[OK]   Supabase connected: {url}")
    else:
        print(f"[WARN] Supabase responded with {resp.status_code}: {resp.text[:100]}")


def check_anthropic():
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        print("[FAIL] ANTHROPIC_API_KEY not set")
        return
    # Just check auth, don't burn tokens
    resp = requests.get(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        timeout=10,
    )
    if resp.status_code == 200:
        print("[OK]   Anthropic API key valid")
    elif resp.status_code == 401:
        print("[FAIL] Anthropic API key invalid")
    else:
        print(f"[WARN] Anthropic responded with {resp.status_code}")


def check_telegram_user_id():
    uid = os.getenv("TELEGRAM_USER_ID")
    if not uid:
        print("[MISS] TELEGRAM_USER_ID not set -- get yours from @userinfobot on Telegram")
    else:
        print(f"[OK]   TELEGRAM_USER_ID: {uid}")


if __name__ == "__main__":
    print("Mirror Bot - Setup Verification")
    print("=" * 40)
    check_telegram()
    check_supabase()
    check_anthropic()
    check_telegram_user_id()
    print("=" * 40)
