#!/bin/bash
# Build-time DB download for Render
set -e

mkdir -p /opt/render

# Remove stale DB
rm -f /opt/render/purrtfolio.db /opt/render/purrtfolio.db.gz

# Download from GitHub Release (67MB compressed, follows redirects)
echo "Downloading DB..."
curl -fSL -o /opt/render/purrtfolio.db.gz \
  https://github.com/mcdawgzy/purrtfolio-tools/releases/download/db-v2026-09-26/purrtfolio.db.gz

# Decompress
echo "Decompressing..."
python3 -c "
import gzip, shutil
with gzip.open('/opt/render/purrtfolio.db.gz', 'rb') as fin, \
     open('/opt/render/purrtfolio.db', 'wb') as fout:
    shutil.copyfileobj(fin, fout)
"

rm -f /opt/render/purrtfolio.db.gz
echo "DB ready: $(ls -lh /opt/render/purrtfolio.db | awk '{print $5}')"
