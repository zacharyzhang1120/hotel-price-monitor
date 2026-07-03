"""Application configuration."""

import os
from pathlib import Path

# Project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{DATA_DIR / 'hotel_prices.db'}"
)

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# Scraper settings
SCRAPE_TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT", "45000"))  # ms
SCRAPE_GOTO_WAIT_UNTIL = os.getenv("SCRAPE_GOTO_WAIT_UNTIL", "domcontentloaded")
SCRAPE_DELAY_MIN_MS = int(os.getenv("SCRAPE_DELAY_MIN_MS", "2000"))
SCRAPE_DELAY_MAX_MS = int(os.getenv("SCRAPE_DELAY_MAX_MS", "5000"))
SCRAPE_CONCURRENCY = int(os.getenv("SCRAPE_CONCURRENCY", "1"))
SCRAPE_MAPPING_TIMEOUT = int(os.getenv("SCRAPE_MAPPING_TIMEOUT", "180"))  # seconds
SCRAPE_PROBE_TIMEOUT = int(os.getenv("SCRAPE_PROBE_TIMEOUT", "90"))  # seconds
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SCRAPER_MODE = os.getenv("SCRAPER_MODE", "mock")  # mock | real | mixed
ENABLED_PLATFORMS = [
    item.strip()
    for item in os.getenv("ENABLED_PLATFORMS", "ctrip").split(",")
    if item.strip()
]
REAL_PLATFORMS = [
    item.strip()
    for item in os.getenv("REAL_PLATFORMS", "").split(",")
    if item.strip()
]

# Scheduler
SCRAPE_SCHEDULE_HOURS = [
    int(item.strip())
    for item in os.getenv("SCRAPE_SCHEDULE_HOURS", "8,11,14,17,20,23").split(",")
    if item.strip()
]
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "false").lower() == "true"
SCHEDULED_SCRAPE_SCOPE = os.getenv("SCHEDULED_SCRAPE_SCOPE", "today")
SCHEDULER_HEALTH_GRACE_MINUTES = int(os.getenv("SCHEDULER_HEALTH_GRACE_MINUTES", "45"))
BACKUP_RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "30"))

# Report push
REPORT_PUSH_ENABLED = os.getenv("REPORT_PUSH_ENABLED", "false").lower() == "true"
WECOM_WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL", "")
WECOM_PUSH_TIMEOUT = float(os.getenv("WECOM_PUSH_TIMEOUT", "10"))

# Platforms
PLATFORMS = ["ctrip"]

# Future days to scrape (today + N days)
FUTURE_DAYS = int(os.getenv("FUTURE_DAYS", "7"))

# Do not use very old records as "recent effective" fallback prices.
PRICE_FALLBACK_MAX_AGE_HOURS = int(os.getenv("PRICE_FALLBACK_MAX_AGE_HOURS", "24"))

# Ctrip login session
CTRIP_STATE_FILE = DATA_DIR / "ctrip_state.json"
CTRIP_LOGIN_URL = "https://passport.ctrip.com/user/login"

# Performance: block image/font/media to speed up scraping
SCRAPE_BLOCK_RESOURCES = os.getenv("SCRAPE_BLOCK_RESOURCES", "false").lower() == "true"

# Smart render wait tuning
SCRAPE_RENDER_WAIT_MAX_MS = int(os.getenv("SCRAPE_RENDER_WAIT_MAX_MS", "5000"))
SCRAPE_RENDER_WAIT_INTERVAL_MS = int(os.getenv("SCRAPE_RENDER_WAIT_INTERVAL_MS", "500"))

# Optional aggressive blocking (default off — may break page rendering)
SCRAPE_BLOCK_STYLESHEET = os.getenv("SCRAPE_BLOCK_STYLESHEET", "false").lower() == "true"

# Today-first scraping: scrape today's prices first, then future dates in background
SCRAPE_TODAY_FIRST = os.getenv("SCRAPE_TODAY_FIRST", "true").lower() == "true"

# Fast timeout for today phase (shorter, so slow hotels don't block results)
SCRAPE_FAST_MAPPING_TIMEOUT = int(os.getenv("SCRAPE_FAST_MAPPING_TIMEOUT", "120"))

# Background scheduled scraping can be tuned independently after real-world tests.
SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT = int(os.getenv("SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT", "120"))

# For unattended scheduled runs, retry timeout failures once after the first pass.
SCHEDULED_SCRAPE_RETRY_FAILED_TODAY = os.getenv("SCHEDULED_SCRAPE_RETRY_FAILED_TODAY", "true").lower() == "true"
