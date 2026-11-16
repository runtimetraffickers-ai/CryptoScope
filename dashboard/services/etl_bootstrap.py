"""Start a missing-history ETL without blocking HTTP requests.

There is one thread per Flask worker, guarded by an OS-level nonblocking file
lock so multiple web workers cannot rebuild the same database concurrently.
"""

import logging
import os
import threading
import time
from contextlib import contextmanager

from cryptoscope.config import CryptoScopeConfig
from cryptoscope.load.database import DatabaseManager

LOGGER = logging.getLogger(__name__)


@contextmanager
def etl_process_lock():
    """Cross-process advisory lock; released even if ETL fails.

    A lock file is intentionally kept on disk: it is the OS lock (not the file's
    existence) that makes this safe against killed/restarted processes.
    """
    os.makedirs(CryptoScopeConfig.DATA_FOLDER, exist_ok=True)
    path = os.path.join(CryptoScopeConfig.DATA_FOLDER, ".etl_bootstrap.lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            # Locking one byte requires a byte in the file on some Windows builds.
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError:
                locked = False
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError:
                locked = False

        yield locked
    finally:
        if locked:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class ETLBootstrapManager:
    """Ensure missing coin history is rebuilt once, with a retry cooldown."""

    def __init__(self, pipeline_factory=None, database=None):
        # Lazy import avoids importing / constructing the pipeline before needed.
        self._pipeline_factory = pipeline_factory
        self.db = database or DatabaseManager()
        self._mutex = threading.Lock()
        self._thread = None
        self._state = "idle"
        self._error = None
        self._last_attempt = 0.0
        self.retry_after_failure = 60.0
        self.retry_after_external_lock = 5.0

    def _run_pipeline(self):
        try:
            with etl_process_lock() as acquired:
                if not acquired:
                    with self._mutex:
                        self._state = "waiting"
                    return

                # Another worker may have completed between our check and lock.
                if self.db.missing_symbols():
                    if self._pipeline_factory is None:
                        from main import CryptoScopePipeline
                        factory = CryptoScopePipeline
                    else:
                        factory = self._pipeline_factory
                    factory().run()

                missing = self.db.missing_symbols()
                if missing:
                    raise RuntimeError(
                        "ETL completed without historical candles for: "
                        + ", ".join(missing)
                    )

            with self._mutex:
                self._state = "ready"
                self._error = None
            LOGGER.info("CryptoScope ETL is ready")

        except Exception as exc:
            LOGGER.exception("CryptoScope initial ETL failed")
            with self._mutex:
                self._state = "failed"
                self._error = str(exc)

    def ensure_started(self):
        """Create schema if absent and launch rebuild if any coin has no rows."""
        try:
            missing = self.db.missing_symbols()
        except Exception as exc:
            LOGGER.exception("Failed to inspect CryptoScope database")
            with self._mutex:
                self._state = "failed"
                self._error = str(exc)
                self._last_attempt = time.monotonic()
            return self.status()

        with self._mutex:
            if not missing:
                self._state = "ready"
                self._error = None
                return {"status": "ready", "missing_symbols": []}

            if self._thread is not None and self._thread.is_alive():
                return {"status": "running", "missing_symbols": missing}

            now = time.monotonic()
            cooldown = (
                self.retry_after_external_lock if self._state == "waiting"
                else self.retry_after_failure
            )
            if self._state in ("failed", "waiting") and now - self._last_attempt < cooldown:
                return {"status": self._state, "missing_symbols": missing}

            self._state = "running"
            self._error = None
            self._last_attempt = now
            self._thread = threading.Thread(
                target=self._run_pipeline,
                name="cryptoscope-initial-etl",
                daemon=True,
            )
            self._thread.start()
            return {"status": "running", "missing_symbols": missing}

    def status(self):
        with self._mutex:
            state = self._state
            error = self._error
        return {"status": state, "error": error}
