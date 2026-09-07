#!/usr/bin/env python3
"""
Keep-alive and health check for Purrtfolio Tools.
Runs every 10 minutes via cron (or GitHub Actions / Render cron).
"""
import os
import sys
import urllib.request
import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.expanduser('~/purrtfolio_keepalive.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

RENDER_API = 'https://one3f-tracker-wpj6.onrender.com'
GITHUB_PAGES = 'https://mcdawgzy.github.io/purrtfolio-tools/'

def check_endpoint(url, name, timeout=30):
    """Check a single endpoint and return (success, response_time_ms)."""
    try:
        start = datetime.now()
        req = urllib.request.Request(url, headers={'User-Agent': 'Purrtfolio-KeepAlive/1.0'})
        response = urllib.request.urlopen(req, timeout=timeout)
        elapsed = (datetime.now() - start).total_seconds() * 1000
        if response.status == 200:
            logger.info(f'{name}: OK ({elapsed:.0f}ms)')
            return True, elapsed
        else:
            logger.warning(f'{name}: HTTP {response.status}')
            return False, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (datetime.now() - start).total_seconds() * 1000
        logger.error(f'{name}: HTTP {e.code} - {e.reason}')
        return False, elapsed
    except Exception as e:
        elapsed = (datetime.now() - start).total_seconds() * 1000
        logger.error(f'{name}: {type(e).__name__}: {e}')
        return False, elapsed

def main():
    logger.info('=== Purrtfolio Tools Keep-Alive Check ===')
    
    # Check GitHub Pages
    check_endpoint(GITHUB_PAGES, 'GitHub Pages', timeout=10)
    
    # Check Render API health
    check_endpoint(f'{RENDER_API}/api/health', 'Render API /health', timeout=10)
    
    # Check key API endpoints (warm up cold starts)
    check_endpoint(f'{RENDER_API}/api/meta', 'Render API /meta', timeout=60)
    check_endpoint(f'{RENDER_API}/api/funds', 'Render API /funds', timeout=30)
    
    logger.info('=== Keep-Alive Check Complete ===')
    return 0

if __name__ == '__main__':
    sys.exit(main())
