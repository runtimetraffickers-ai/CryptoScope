"""Offline regression tests for deleted and empty CryptoScope databases."""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, Mock

from cryptoscope.config import CryptoScopeConfig
from cryptoscope.extract.binance_client import BinanceClient
from cryptoscope.load.database import DatabaseManager
from dashboard.services.etl_bootstrap import ETLBootstrapManager, etl_process_lock
from main import CryptoScopePipeline


class ETLRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        data_dir = Path(self.tempdir.name) / "data"
        self.dbfile = data_dir / "cryptoscope.db"

        for name, value in {
            "DATA_FOLDER": str(data_dir),
            "RAW_FOLDER": str(data_dir / "raw"),
            "DATABASE_PATH": str(self.dbfile),
        }.items():
            patcher = patch.object(CryptoScopeConfig, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = now - timedelta(hours=3)
        self.candles = []
        for index in range(3):
            opened = int((start + timedelta(hours=index)).timestamp() * 1000)
            self.candles.append([
                opened, "100.0", "120.0", "95.0", "110.0", "4.0",
                opened + 3599999, "450.0", 10, "0", "0", "0",
            ])

    def fake_historical(self, symbol, interval, days):
        return self.candles

    def test_missing_database_full_rebuild_then_incremental(self):
        self.assertFalse(self.dbfile.exists())
        with patch.object(BinanceClient, "get_historical_klines", Mock(side_effect=self.fake_historical)) as fetch, \
                patch.object(BinanceClient, "get_new_klines", return_value=[] ) as new:
            CryptoScopePipeline().run()
            self.assertEqual(fetch.call_count, len(CryptoScopeConfig.SYMBOLS))
            self.assertEqual(new.call_count, 0)
            db = DatabaseManager()
            self.assertEqual(db.missing_symbols(), [])
            with sqlite3.connect(self.dbfile) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fact_candles_1h").fetchone()[0], 15)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM etl_run_log WHERE status='SUCCESS'").fetchone()[0], 1)

            CryptoScopePipeline().run()
            self.assertEqual(fetch.call_count, len(CryptoScopeConfig.SYMBOLS))
            self.assertEqual(new.call_count, len(CryptoScopeConfig.SYMBOLS))
            with sqlite3.connect(self.dbfile) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM fact_candles_1h").fetchone()[0], 15)

    def test_empty_file_schema_and_missing_coins_detected(self):
        self.dbfile.parent.mkdir(parents=True)
        self.dbfile.touch()  # exactly 0 bytes, as in the uploaded ZIP
        self.assertEqual(self.dbfile.stat().st_size, 0)
        self.assertEqual(DatabaseManager().missing_symbols(), CryptoScopeConfig.SYMBOLS)
        with sqlite3.connect(self.dbfile) as conn:
            names = {x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("fact_candles_1h", names)

    def test_dashboard_starts_pipeline_without_blocking(self):
        with patch.object(BinanceClient, "get_historical_klines", self.fake_historical):
            manager = ETLBootstrapManager()
            state = manager.ensure_started()
            self.assertEqual(state["status"], "running")
            manager._thread.join(timeout=20)
            self.assertFalse(manager._thread.is_alive(), "ETL background job did not finish")
            self.assertEqual(manager.ensure_started()["status"], "ready")
            self.assertEqual(DatabaseManager().missing_symbols(), [])
            # No second pipeline run after the database is complete.
            self.assertEqual(manager.ensure_started()["status"], "ready")

    def test_deleted_database_rebuilds_again(self):
        with patch.object(BinanceClient, "get_historical_klines", self.fake_historical):
            manager = ETLBootstrapManager()
            manager.ensure_started()
            manager._thread.join(timeout=20)
            self.assertEqual(manager.ensure_started()["status"], "ready")
            self.dbfile.unlink()
            self.assertEqual(manager.ensure_started()["status"], "running")
            manager._thread.join(timeout=20)
            self.assertEqual(manager.ensure_started()["status"], "ready")
            self.assertEqual(DatabaseManager().missing_symbols(), [])

    def test_failed_bootstrap_retries_after_cooldown(self):
        with patch.object(BinanceClient, "get_historical_klines", side_effect=RuntimeError("mock outage")):
            manager = ETLBootstrapManager()
            manager.ensure_started()
            manager._thread.join(timeout=20)
            self.assertEqual(manager.ensure_started()["status"], "failed")

        # The next dashboard request, after the retry interval, should recover.
        manager.retry_after_failure = 0
        with patch.object(BinanceClient, "get_historical_klines", self.fake_historical):
            self.assertEqual(manager.ensure_started()["status"], "running")
            manager._thread.join(timeout=20)
            self.assertEqual(manager.ensure_started()["status"], "ready")

    @unittest.skipIf(os.name == "nt", "lock test assumes fcntl")
    def test_worker_lock_prevents_duplicate_bootstraps(self):
        with etl_process_lock() as first:
            self.assertTrue(first)
            with etl_process_lock() as second:
                self.assertFalse(second)
        with etl_process_lock() as third:
            self.assertTrue(third)


if __name__ == "__main__":
    unittest.main()
