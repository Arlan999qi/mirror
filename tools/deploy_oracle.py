"""Generate deployment artifacts for Oracle Cloud Always-Free.

Creates:
1. systemd service file (mirror-bot.service)
2. Setup script (setup_oracle.sh) -- installs deps, creates user, deploys files
3. Update script (update_bot.sh) -- pulls latest files and restarts

Usage:
    py -3.13 tools/deploy_oracle.py

Outputs go to .tmp/deploy/
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_DIR = os.path.join(PROJECT_ROOT, ".tmp", "deploy")


def generate_systemd_service():
    """Generate the systemd unit file for the Mirror bot."""
    return """[Unit]
Description=Mirror Telegram Journal Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mirror
Group=mirror
WorkingDirectory=/opt/mirror
ExecStart=/usr/bin/python3.13 tools/mirror_bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mirror-bot

# Environment
EnvironmentFile=/opt/mirror/.env

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/opt/mirror/.tmp

[Install]
WantedBy=multi-user.target
"""


def generate_setup_script():
    """Generate the initial setup script for Oracle Cloud."""
    return """#!/bin/bash
# Mirror Bot -- Oracle Cloud Setup Script
# Run as root on a fresh Oracle Cloud Always-Free instance (Ubuntu/Oracle Linux)
set -euo pipefail

echo "=== Mirror Bot Setup ==="

# 1. System updates
echo "[1/7] Updating system packages..."
if command -v apt-get &> /dev/null; then
    apt-get update -y && apt-get upgrade -y
    apt-get install -y software-properties-common
elif command -v dnf &> /dev/null; then
    dnf update -y
fi

# 2. Install Python 3.13
echo "[2/7] Installing Python 3.13..."
if command -v apt-get &> /dev/null; then
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -y
    apt-get install -y python3.13 python3.13-venv python3.13-dev
elif command -v dnf &> /dev/null; then
    dnf install -y python3.13 python3.13-pip
fi

# 3. Create mirror user
echo "[3/7] Creating mirror user..."
if ! id -u mirror &>/dev/null; then
    useradd --system --shell /bin/bash --home-dir /opt/mirror --create-home mirror
fi

# 4. Create directory structure
echo "[4/7] Setting up directory structure..."
mkdir -p /opt/mirror/tools
mkdir -p /opt/mirror/workflows
mkdir -p /opt/mirror/.tmp

# 5. Copy files (run this after scp/rsync)
echo "[5/7] Directory structure ready."
echo "  Now copy your bot files:"
echo "    scp tools/*.py mirror@<server-ip>:/opt/mirror/tools/"
echo "    scp .env mirror@<server-ip>:/opt/mirror/.env"
echo ""

# 6. Install Python dependencies
echo "[6/7] Installing Python dependencies..."
python3.13 -m pip install --break-system-packages \\
    python-telegram-bot[job-queue] \\
    supabase \\
    anthropic \\
    python-dotenv

# 7. Install and enable systemd service
echo "[7/7] Installing systemd service..."
cp /opt/mirror/.tmp/deploy/mirror-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable mirror-bot

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy bot files to /opt/mirror/ (see step 5 above)"
echo "  2. Copy .env to /opt/mirror/.env"
echo "  3. Set permissions: chown -R mirror:mirror /opt/mirror"
echo "  4. Start the bot: systemctl start mirror-bot"
echo "  5. Check status: systemctl status mirror-bot"
echo "  6. View logs: journalctl -u mirror-bot -f"
"""


def generate_update_script():
    """Generate a script to update the bot and restart."""
    return """#!/bin/bash
# Mirror Bot -- Update Script
# Run on the Oracle Cloud server to deploy new code
set -euo pipefail

echo "=== Updating Mirror Bot ==="

BOT_DIR=/opt/mirror

# Stop the bot
echo "[1/4] Stopping bot..."
systemctl stop mirror-bot

# Backup current files
echo "[2/4] Backing up..."
cp -r $BOT_DIR/tools $BOT_DIR/.tmp/tools_backup_$(date +%Y%m%d)

# Copy new files (assumes they're in /tmp/mirror-update/)
echo "[3/4] Deploying new files..."
if [ -d /tmp/mirror-update/tools ]; then
    cp /tmp/mirror-update/tools/*.py $BOT_DIR/tools/
    chown -R mirror:mirror $BOT_DIR/tools/
    echo "  Files updated."
else
    echo "  No files found in /tmp/mirror-update/tools/"
    echo "  Upload new files first: scp tools/*.py root@<server>:/tmp/mirror-update/tools/"
fi

# Restart
echo "[4/4] Starting bot..."
systemctl start mirror-bot

echo ""
echo "=== Update Complete ==="
echo "Status: $(systemctl is-active mirror-bot)"
echo "Logs: journalctl -u mirror-bot -f"
"""


def generate_deploy_commands():
    """Generate a quick-reference of deploy commands."""
    return """# Mirror Bot -- Deployment Quick Reference
# ==========================================

# === First-time deploy ===
# 1. Create Oracle Cloud Always-Free instance (Ampere A1, Ubuntu 22.04+)
# 2. SSH in and run setup:
ssh ubuntu@<server-ip>
sudo bash setup_oracle.sh

# 3. Copy files from your Windows PC:
scp -r tools/*.py ubuntu@<server-ip>:/opt/mirror/tools/
scp .env ubuntu@<server-ip>:/opt/mirror/.env

# 4. Fix permissions and start:
ssh ubuntu@<server-ip>
sudo chown -R mirror:mirror /opt/mirror
sudo systemctl start mirror-bot
sudo systemctl status mirror-bot

# === View logs ===
sudo journalctl -u mirror-bot -f          # Live tail
sudo journalctl -u mirror-bot --since today  # Today's logs

# === Restart / Stop ===
sudo systemctl restart mirror-bot
sudo systemctl stop mirror-bot

# === Update bot code ===
# From your Windows PC:
scp tools/*.py ubuntu@<server-ip>:/tmp/mirror-update/tools/
# On the server:
sudo bash /opt/mirror/.tmp/deploy/update_bot.sh

# === Check if bot is running ===
sudo systemctl is-active mirror-bot

# === Open firewall (Oracle Cloud specific) ===
# No inbound ports needed -- bot uses polling (outbound HTTPS only)
"""


def main():
    os.makedirs(DEPLOY_DIR, exist_ok=True)

    files = {
        "mirror-bot.service": generate_systemd_service(),
        "setup_oracle.sh": generate_setup_script(),
        "update_bot.sh": generate_update_script(),
        "DEPLOY_COMMANDS.md": generate_deploy_commands(),
    }

    for filename, content in files.items():
        path = os.path.join(DEPLOY_DIR, filename)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        print(f"  Created: {path}")

    print(f"\nAll deployment files generated in {DEPLOY_DIR}")
    print("\nNext steps:")
    print("  1. Create an Oracle Cloud Always-Free instance (Ampere A1, Ubuntu 22.04+)")
    print("  2. SCP the deploy files + bot code to the server")
    print("  3. Run setup_oracle.sh as root")
    print("  4. See DEPLOY_COMMANDS.md for full reference")


if __name__ == "__main__":
    main()
