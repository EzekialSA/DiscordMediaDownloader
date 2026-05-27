# DiscordMediaDownloader

Automated Discord channel media archiver. Uses [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) CLI to export messages and downloads all media attachments (.png, .jpg, .jpeg, .gif, .mp4, .webm, .webp, .mov).

## How It Works

1. **First run** — lists all your guilds/channels and writes `export.csv`
2. **You curate** — copy entries from `export.csv` into `download.csv` for channels you want
3. **Subsequent runs** — exports messages as JSON (incremental if file exists) then downloads media

## Windows Setup

1. Download [DiscordChatExporter CLI (win-x64)](https://github.com/Tyrrrz/DiscordChatExporter/releases) and extract
2. Copy `.env.example` to `.env` and set your `DISCORD_TOKEN` and `DCE_PATH`
3. Install dependencies: `pip install requests python-dotenv`
4. Run: `python discord_downloader.py`

## Docker Setup (Linux)

```bash
cd docker
cp .env.example .env
# Edit .env with your DISCORD_TOKEN
docker compose up --build
```

### Volumes

| Volume | Container Path | Purpose |
|--------|---------------|---------|
| `discord-config` | `/config` | Config files (`export.csv`, `download.csv`) |
| `discord-output` | `/output` | JSON exports and downloaded media |

## CSV Format

```
GuildName,GuildID,ChannelName,ChannelID
NewAngels18,1479095332427272294,HOLYTEXTSget-id-verified,1485526215627505784
NewAngels18,1479095332427272294,HOLYTEXTSanswer-questions,1479234650034671838
```

Names are sanitized (only alphanumeric, hyphens, underscores kept).

## Legacy

- `main.go` — Original Go media downloader (reads `messages.json` directly)
- `bot.py` — Original Discord bot for message deletion
