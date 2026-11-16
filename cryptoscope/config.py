import os
from pathlib import Path


class CryptoScopeConfig:
    # Binance's public market-data endpoint works in regions where api.binance.com
    # may return HTTP 451. Override it with CRYPTOSCOPE_BINANCE_URL if needed.
    API_URL = os.environ.get(
        "CRYPTOSCOPE_BINANCE_URL", "https://data-api.binance.vision"
    ).rstrip("/")
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    INTERVAL = "1h"
    DAYS = 365
    ASSET_NAMES = {
        "BTCUSDT": "Bitcoin",
        "ETHUSDT": "Ethereum",
        "SOLUSDT": "Solana",
        "BNBUSDT": "BNB",
        "XRPUSDT": "XRP",
    }

    # Absolute paths: launching Flask from a different working directory must
    # not silently create a second SQLite database.
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    DATA_FOLDER = os.path.abspath(
        os.environ.get("CRYPTOSCOPE_DATA_DIR", str(PROJECT_ROOT / "data"))
    )
    RAW_FOLDER = os.path.join(DATA_FOLDER, "raw")
    DATABASE_PATH = os.path.abspath(
        os.environ.get("CRYPTOSCOPE_DB_PATH", os.path.join(DATA_FOLDER, "cryptoscope.db"))
    )
