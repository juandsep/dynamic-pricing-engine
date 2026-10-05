#!/usr/bin/env bash
# Download UCI Online Retail II into data/raw/ (git-ignored).
#
# UCI throttles repeat downloads of the same file -- a second fetch ran at about
# 11 KB/s against 44 MB -- so the file is kept and a re-run skips the download.
set -euo pipefail

URL="https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${DP_DATA_DIR:-$ROOT/data}/raw"

if [ -f "$DEST/online_retail_II.xlsx" ]; then
    echo "already downloaded: $DEST/online_retail_II.xlsx"
    exit 0
fi

mkdir -p "$DEST"
echo "downloading $URL"
curl -sSL -o "$DEST/retailii.zip" "$URL"
unzip -o -q "$DEST/retailii.zip" -d "$DEST"
rm "$DEST/retailii.zip"
ls -lh "$DEST"
