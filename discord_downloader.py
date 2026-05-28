#!/usr/bin/env python3
"""
Discord Media Downloader - Windows version.

Uses DiscordChatExporter CLI to export messages and downloads media attachments.

Setup:
  1. Download DiscordChatExporter.Cli.win-x64.zip from:
     https://github.com/Tyrrrz/DiscordChatExporter/releases
  2. Extract and set DCE_PATH in .env or environment to the .exe path.
  3. Set DISCORD_TOKEN in .env or environment.
  4. Run: python discord_downloader.py
"""

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("Please install requests: pip install requests")
    sys.exit(1)

# Try to load .env file if python-dotenv is available
SCRIPT_DIR = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(SCRIPT_DIR / ".env")
except ImportError:
    # Fallback: manually parse .env file
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    value = value.strip()
                    # Strip surrounding quotes
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                        value = value[1:-1]
                    os.environ.setdefault(key.strip(), value)

# Configuration from environment
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
DCE_PATH = os.environ.get("DCE_PATH", str(SCRIPT_DIR / "DiscordChatExporter.Cli.exe"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", str(SCRIPT_DIR)))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(SCRIPT_DIR / "output")))

# Resolve relative DCE_PATH against SCRIPT_DIR
if not Path(DCE_PATH).is_absolute():
    DCE_PATH = str(SCRIPT_DIR / DCE_PATH)

MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".webm", ".webp", ".mov"}


def sanitize_name(name: str) -> str:
    """Strip non-alphanumeric characters except hyphens and underscores."""
    return re.sub(r"[^a-zA-Z0-9\-_]", "", name)


def run_dce(args: list[str]) -> tuple[bool, str]:
    """Run DiscordChatExporter CLI with given arguments. Returns (success, stdout)."""
    cmd = [DCE_PATH] + args
    if not Path(DCE_PATH).exists():
        print(f"ERROR: DCE executable not found at: {DCE_PATH}", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  DCE error: {result.stderr.strip()}", file=sys.stderr)
        return (False, "")
    return (True, result.stdout)


def get_guilds() -> list[tuple[str, str]]:
    """Get list of (guild_id, guild_name) tuples."""
    success, output = run_dce(["guilds", "-t", DISCORD_TOKEN])
    if not success:
        print("ERROR: Failed to retrieve guilds.", file=sys.stderr)
        sys.exit(1)
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
    success, output = run_dce(["channels", "--token", DISCORD_TOKEN, "--guild", guild_id])
    if not success:
        print(f"  WARNING: Failed to retrieve channels for guild {guild_id}, skipping.")
        return []
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


def export_channel(entry: dict) -> Path | None:
    """Export channel messages to JSON, appending if file exists. Returns None on failure."""
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
            success, _ = run_dce(args)

            if not success:
                print(f"  WARNING: Failed to export channel {entry['channel_name']}, skipping.")
                if tmp_path.exists():
                    tmp_path.unlink()
                return json_path  # Still return existing JSON for downloads

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
        success, _ = run_dce(args)
        if not success:
            print(f"  WARNING: Failed to export channel {entry['channel_name']}, skipping.")
            return None

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
    """Download a file to dest using a .tmp intermediate. Returns True on success."""
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(tmp_dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        tmp_dest.rename(dest)
        return True
    except requests.RequestException as e:
        print(f"    Failed to download {url}: {e}")
        tmp_dest.unlink(missing_ok=True)
        return False


def make_download_filename(message_id: str, original_filename: str) -> str:
    """Build the download filename prefixed with message ID."""
    stem = Path(original_filename).stem[:50]
    ext = Path(original_filename).suffix
    return f"{message_id}_{stem}{ext}"


def cleanup_tmp_files(directory: Path):
    """Remove leftover .tmp files from interrupted downloads."""
    if not directory.exists():
        return
    for tmp_file in directory.glob("*.tmp"):
        print(f"    Removing incomplete download: {tmp_file.name}")
        tmp_file.unlink()


def is_message_already_downloaded(download_dir: Path, message_id: str) -> bool:
    """Check if any file in download_dir starts with the message ID prefix."""
    prefix = f"{message_id}_"
    for f in download_dir.iterdir():
        if f.name.startswith(prefix) and not f.name.endswith(".tmp"):
            return True
    return False


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
    download_dir = OUTPUT_DIR / entry['guild_name'] / entry['channel_name']
    download_dir.mkdir(parents=True, exist_ok=True)

    # Clean up any .tmp files from interrupted previous runs
    cleanup_tmp_files(download_dir)

    # Build set of existing message IDs to skip already-downloaded
    existing_message_ids: set[str] = set()
    for f in download_dir.iterdir():
        if not f.name.endswith(".tmp") and "_" in f.name:
            existing_message_ids.add(f.name.split("_", 1)[0])

    downloaded = 0
    skipped = 0
    for message in messages:
        message_id = message.get("id", "")

        # Skip entire message if already downloaded
        if message_id in existing_message_ids:
            skipped += 1
            continue

        # Check attachments
        for attachment in message.get("attachments", []):
            url = attachment.get("url", "")
            filename = attachment.get("fileName", "")
            if not filename:
                parsed = urlparse(url)
                filename = Path(parsed.path).name
            if is_media_file(filename):
                dest_name = make_download_filename(message_id, filename)
                dest = get_unique_path(download_dir / dest_name)
                if not dest.exists():
                    print(f"    Downloading: {dest_name}")
                    if download_file(url, dest):
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
                        dest_name = make_download_filename(message_id, filename)
                        dest = get_unique_path(download_dir / dest_name)
                        if not dest.exists():
                            print(f"    Downloading: {dest_name}")
                            if download_file(url, dest):
                                downloaded += 1

        # Check content for direct URLs
        content = message.get("content", "")
        if content.startswith("http"):
            url = content.split()[0].split("?")[0]
            parsed = urlparse(url)
            filename = Path(parsed.path).name
            if is_media_file(filename):
                dest_name = make_download_filename(message_id, filename)
                dest = get_unique_path(download_dir / dest_name)
                if not dest.exists():
                    print(f"    Downloading: {dest_name}")
                    if download_file(url, dest):
                        downloaded += 1

    print(f"  Downloaded {downloaded} media files to {download_dir}")
    if skipped:
        print(f"  Skipped {skipped} already-downloaded messages.")


def main():
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN is required.")
        print("Set it in your environment or in a .env file.")
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

        # Download media (skip if export failed and no existing JSON)
        if json_path:
            download_media_from_json(json_path, entry)

    print("\nDone!")


if __name__ == "__main__":
    main()
