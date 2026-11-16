# CryptoScope — ETL + Dashboard

CryptoScope tracks BTC, ETH, SOL, BNB and XRP with one year of closed hourly
candles from Binance, validated using Pydantic and stored in SQLite.

## Setup

From the project root:

```bash
python -m pip install -r requirements.txt
```

## Run the dashboard (automatic recovery enabled)

```bash
python -m dashboard.app
```

Opening the dashboard automatically starts the full ETL in a background thread
**if the database is missing, has zero bytes, has no tables, or any configured
symbol has no saved candles**. Pages stay responsive and show an initialization
banner until historical data is ready. When all five symbols are populated,
normal history and analysis APIs resume. Browser pages reload when the download
finishes.

The startup process:

1. Creates `data/cryptoscope.db` and its tables if absent.
2. Checks for at least one stored candle for each configured symbol.
3. Runs `CryptoScopePipeline` if any symbol has no records. Missing symbols
   fetch a full year; symbols with records use incremental extraction.
4. Uses an OS lock to avoid duplicate bootstrap ETLs across web workers.
5. Retains existing candles; duplicate SQLite candle inserts are ignored.

**Check progress:** `http://127.0.0.1:5000/api/etl/status`

Statuses include `running`, `waiting`, `ready`, and `failed`. Failed bootstrap
runs are retried on a subsequent browser/API request after 60 seconds. For more
detailed errors consult the Python terminal or web-server error log.

## Manual ETL

```bash
python main.py
```

This also works on a deleted SQLite database; tables are created before
`RawExtractor` queries the latest candle.

## Configurations

- `CRYPTOSCOPE_DATA_DIR` — optional absolute directory for data files.
- `CRYPTOSCOPE_DB_PATH` — optional absolute SQLite file path.
- `CRYPTOSCOPE_BINANCE_URL` — Binance API base URL; defaults to
  `https://data-api.binance.vision` to avoid regions blocking `api.binance.com`.
- `CRYPTOSCOPE_AUTO_ETL=false` — disable automatic dashboard recovery.
- `CRYPTOSCOPE_PRODUCTION=true` — production flag for Flask startup.

Database and raw-cache paths are absolute by default (relative to the project
root), so they will not change depending on your terminal's current directory.

## Tests (offline; uses mocked Binance data)

```bash
python -m unittest discover -s tests -v
```

For hosting platforms that frequently recycle web workers (for example,
PythonAnywhere WSGI hosting), a web-worker background thread is not a reliable
replacement for a scheduled standalone `python main.py` job. The automatic
bootstrap is implemented, but run the ETL as a separate scheduled job for
reliable production recovery and ongoing updates.
