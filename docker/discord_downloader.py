#!/usr/bin/env python3
"""
Discord Media Downloader - Linux/Docker version.

Uses DiscordChatExporter CLI to export messages and downloads media attachments.

Volumes:
  /config  - contains export.csv (generated) and download.csv (user-curated)
  /output  - contains JSON exports and downloaded media files
"""

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

# Configuration from environment
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
DCE_PATH = os.environ.get("DCE_PATH", "/opt/dce/DiscordChatExporter.Cli")
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))

MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".webm", ".webp", ".mov"}


def sanitize_name(name: str) -> str:
    """Strip non-alphanumeric characters except hyphens and underscores."""
    return re.sub(r"[^a-zA-Z0-9\-_]", "", name)


def run_dce(args: list[str]) -> str:
    """Run DiscordChatExporter CLI with given arguments."""
    cmd = [DCE_PATH] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"DCE error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def get_guilds() -> list[tuple[str, str]]:
    """Get list of (guild_id, guild_name) tuples."""
    output = run_dce(["guilds", "-t", DISCORD_TOKEN])
    guilds = []
    for line in output.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            guild_id = parts[0].strip()
            guild_name = parts[1].strip()
            guilds.append((guild_id, guild_name))
    return guilds


def get_channels(guild_id: str) -> list[tuple[str, str]]:
    """Get list of (channel_id, channel_name) tuples for a guild."""
    output = run_dce(["channels", "--token", DISCORD_TOKEN, "--guild", guild_id])
    channels = []
    for line in output.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            channel_id = parts[0].strip()
            channel_name = parts[1].strip()
            channels.append((channel_id, channel_name))
    return channels


def generate_export_csv():
    """Generate export.csv with all guilds and their channels."""
    export_path = CONFIG_DIR / "export.csv"
    print("Generating export.csv...")

    guilds = get_guilds()
    rows = []

    for guild_id, guild_name in guilds:
        if guild_id == "0":  # Skip Direct Messages
            continue
        sanitized_guild = sanitize_name(guild_name)
        channels = get_channels(guild_id)
        for channel_id, channel_name in channels:
            sanitized_channel = sanitize_name(channel_name)
            rows.append([sanitized_guild, guild_id, sanitized_channel, channel_id])

    with open(export_path, "w", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)

    print(f"Wrote {len(rows)} entries to {export_path}")
    print("Create download.csv with the entries you want to download, then re-run.")


def read_download_csv() -> list[dict]:
    """Read download.csv and return list of entries."""
    download_path = CONFIG_DIR / "download.csv"
    if not download_path.exists():
        print(f"No download.csv found at {download_path}")
        print("Copy desired entries from export.csv into download.csv and re-run.")
        sys.exit(0)

    entries = []
    with open(download_path, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 4:
                entries.append({
                    "guild_name": row[0],
                    "guild_id": row[1],
                    "channel_name": row[2],
                    "channel_id": row[3],
                })
    return entries


def get_last_message_id(json_path: Path) -> str | None:
    """Get the last message ID from an existing JSON export."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        messages = data.get("messages", [])
        if messages:
            return messages[-1]["id"]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


def export_channel(entry: dict) -> Path:
    """Export channel messages to JSON, appending if file exists."""
    filename = f"{entry['guild_name']}_{entry['channel_name']}.json"
    json_path = OUTPUT_DIR / filename

    if json_path.exists():
        last_id = get_last_message_id(json_path)
        if last_id:
            print(f"  Incremental export after message {last_id}...")
            tmp_path = OUTPUT_DIR / f"{filename}.tmp"
            args = [
                "export", "-t", DISCORD_TOKEN,
                "-c", entry["channel_id"],
                "-f", "Json",
                "-o", str(tmp_path),
                "--after", last_id,
            ]
            run_dce(args)

            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                try:
                    with open(tmp_path, "r", encoding="utf-8") as f:
                        new_data = json.load(f)
                    new_messages = new_data.get("messages", [])

                    if new_messages:
                        with open(json_path, "r", encoding="utf-8") as f:
                            existing_data = json.load(f)
                        existing_data["messages"].extend(new_messages)
                        with open(json_path, "w", encoding="utf-8") as f:
                            json.dump(existing_data, f, indent=2)
                        print(f"  Appended {len(new_messages)} new messages.")
                    else:
                        print("  No new messages.")
                except (json.JSONDecodeError, KeyError):
                    print("  Failed to parse incremental export, skipping merge.")
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                print("  No new messages.")
                if tmp_path.exists():
                    tmp_path.unlink()
            return json_path
    else:
        print(f"  Full export to {filename}...")
        args = [
            "export", "-t", DISCORD_TOKEN,
            "-c", entry["channel_id"],
            "-f", "Json",
            "-o", str(json_path),
        ]
        run_dce(args)

    return json_path


def is_media_file(filename: str) -> bool:
    """Check if a filename has a media extension."""
    ext = Path(filename).suffix.lower().split("?")[0]
    return ext in MEDIA_EXTENSIONS


def get_unique_path(filepath: Path) -> Path:
    """Get a unique file path by appending _1, _2, etc."""
    if not filepath.exists():
        return filepath
    stem = filepath.stem
    suffix = filepath.suffix
    parent = filepath.parent
    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def download_file(url: str, dest: Path):
    """Download a file from URL to destination path."""
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    except requests.RequestException as e:
        print(f"    Failed to download {url}: {e}")


def download_media_from_json(json_path: Path, entry: dict):
    """Download media attachments from exported JSON."""
    if not json_path.exists():
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  Error reading {json_path}: {e}")
        return

    messages = data.get("messages", [])
    download_dir = OUTPUT_DIR / f"{entry['guild_name']}_{entry['channel_name']}"
    download_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for message in messages:
        # Check attachments
        for attachment in message.get("attachments", []):
            url = attachment.get("url", "")
            filename = attachment.get("fileName", "")
            if not filename:
                parsed = urlparse(url)
                filename = Path(parsed.path).name
            if is_media_file(filename):
                dest = get_unique_path(download_dir / filename)
                if not dest.exists():
                    print(f"    Downloading: {filename}")
                    download_file(url, dest)
                    downloaded += 1

        # Check embeds with media
        for embed in message.get("embeds", []):
            for field in ("thumbnail", "image", "video"):
                media = embed.get(field)
                if media and media.get("url"):
                    url = media["url"]
                    parsed = urlparse(url)
                    filename = Path(parsed.path).name
                    if is_media_file(filename):
                        dest = get_unique_path(download_dir / filename)
                        if not dest.exists():
                            print(f"    Downloading: {filename}")
                            download_file(url, dest)
                            downloaded += 1

        # Check content for direct URLs
        content = message.get("content", "")
        if content.startswith("http"):
            url = content.split()[0].split("?")[0]
            parsed = urlparse(url)
            filename = Path(parsed.path).name
            if is_media_file(filename):
                dest = get_unique_path(download_dir / filename)
                if not dest.exists():
                    print(f"    Downloading: {filename}")
                    download_file(url, dest)
                    downloaded += 1

    print(f"  Downloaded {downloaded} media files to {download_dir}")


def main():
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable is required.")
        sys.exit(1)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    export_path = CONFIG_DIR / "export.csv"

    # First run: generate export.csv
    if not export_path.exists():
        generate_export_csv()
        return

    # Process download.csv
    entries = read_download_csv()
    if not entries:
        print("download.csv is empty. Add entries and re-run.")
        return

    print(f"Processing {len(entries)} channel(s)...")
    for entry in entries:
        print(f"\n[{entry['guild_name']}/{entry['channel_name']}]")

        # Export messages
        json_path = export_channel(entry)

        # Download media
        download_media_from_json(json_path, entry)

    print("\nDone!")


if __name__ == "__main__":
    main()
