import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "data" / "test_hotel_prices.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["SCRAPER_MODE"] = "mock"
os.environ["SCHEDULER_ENABLED"] = "false"
