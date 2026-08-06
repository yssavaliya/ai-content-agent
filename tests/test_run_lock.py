import os
import time
import unittest
from pathlib import Path

from ai_content_agent.application.run_lock import RunLock, RunLockError, lock_path_for_database


class RunLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock_path = Path("agent-test.lock")
        if self.lock_path.exists():
            self.lock_path.unlink()

    def tearDown(self) -> None:
        if self.lock_path.exists():
            self.lock_path.unlink()

    def test_acquire_and_release(self):
        with RunLock(self.lock_path):
            self.assertTrue(self.lock_path.exists())
        self.assertFalse(self.lock_path.exists())

    def test_release_is_idempotent(self):
        lock = RunLock(self.lock_path)
        lock.acquire()
        lock.release()
        lock.release()
        self.assertFalse(self.lock_path.exists())

    def test_second_holder_fails_after_timeout(self):
        first = RunLock(self.lock_path, timeout_seconds=0.5)
        first.acquire()
        try:
            second = RunLock(self.lock_path, timeout_seconds=0.5)
            with self.assertRaises(RunLockError):
                second.acquire()
        finally:
            first.release()

    def test_stale_lock_is_broken(self):
        self.lock_path.write_text("pid=999999 created_at=stale\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(self.lock_path, (old, old))
        with RunLock(self.lock_path, stale_seconds=60):
            self.assertTrue(self.lock_path.exists())
        self.assertFalse(self.lock_path.exists())

    def test_context_manager_releases_on_exception(self):
        with self.assertRaises(RuntimeError):
            with RunLock(self.lock_path):
                raise RuntimeError("boom")
        self.assertFalse(self.lock_path.exists())

    def test_lock_path_next_to_database(self):
        path = lock_path_for_database("data/agent.db")
        self.assertEqual(path, Path("data/agent.db.lock"))


if __name__ == "__main__":
    unittest.main()
