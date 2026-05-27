FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl unzip jq && \
    rm -rf /var/lib/apt/lists/*

# Download latest DiscordChatExporter CLI linux-x64
RUN LATEST_URL=$(curl -s https://api.github.com/repos/Tyrrrz/DiscordChatExporter/releases/latest \
    | jq -r '.assets[] | select(.name == "DiscordChatExporter.Cli.linux-x64.zip") | .browser_download_url') && \
    curl -L -o /tmp/dce.zip "$LATEST_URL" && \
    unzip /tmp/dce.zip -d /opt/dce && \
    chmod +x /opt/dce/DiscordChatExporter.Cli && \
    rm /tmp/dce.zip

# Install Python dependencies
RUN pip install --no-cache-dir requests

# Create volume mount points
RUN mkdir -p /config /output

VOLUME ["/config", "/output"]

COPY discord_downloader.py /app/discord_downloader.py

WORKDIR /app

ENTRYPOINT ["python", "/app/discord_downloader.py"]
