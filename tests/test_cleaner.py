"""Unit tests for opencode_session_cleaner.

These tests are hermetic: they use a temporary SQLite fixture and mock both
the binary resolution and ``subprocess.run``. No real session is ever deleted.
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import opencode_session_cleaner as cleaner  # noqa: E402


def make_db(path, directories):
    """Create a temp DB with ``session``/``session_v2`` and old rows."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE session "
        "(id TEXT, directory TEXT, title TEXT, time_updated INTEGER)"
    )
    con.execute(
        "CREATE TABLE session_v2 "
        "(id TEXT, directory TEXT, title TEXT, time_updated INTEGER)"
    )
    old = cleaner.now_ms() - int(40 * cleaner.MS_PER_DAY)
    for i, directory in enumerate(directories):
        con.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?)",
            (f"session-{i}", directory, f"title {i}", old),
        )
    con.commit()
    con.close()


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "opencode.db")
        make_db(self.db, ["/work/alpha", "/work/beta"])
        self.cfg = os.path.join(self.tmp.name, "config.json")
        self._write_config({"days": 30, "db_path": self.db, "opencode_bin": "opencode"})

    def tearDown(self):
        self.tmp.cleanup()

    def _write_config(self, data):
        with open(self.cfg, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def _run(self, extra, run_result):
        """Run main() with mocked binary resolution and subprocess."""
        with mock.patch.object(
            cleaner, "resolve_binary", return_value="/fake/opencode"
        ), mock.patch.object(cleaner.subprocess, "run") as run:
            run.return_value = run_result
            with redirect_stdout(io.StringIO()):
                code = cleaner.main(["--config", self.cfg] + extra)
        return code, run

    def test_apply_success(self):
        result = mock.Mock(returncode=0, stdout="deleted", stderr="")
        code, run = self._run(["--apply"], result)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)

    def test_not_found_skipped(self):
        result = mock.Mock(returncode=1, stdout="Session not found", stderr="")
        code, run = self._run(["--apply"], result)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)

    def test_real_error_exit_1(self):
        result = mock.Mock(returncode=1, stdout="boom", stderr="failure")
        code, run = self._run(["--apply"], result)
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 2)

    def test_dry_run_never_calls_cli(self):
        result = mock.Mock(returncode=0, stdout="", stderr="")
        code, run = self._run([], result)
        self.assertEqual(code, 0)
        run.assert_not_called()

    def test_config_days_applied(self):
        self._write_config({"days": 100, "db_path": self.db, "opencode_bin": "opencode"})
        result = mock.Mock(returncode=0, stdout="ok", stderr="")
        code, run = self._run(["--apply"], result)
        self.assertEqual(code, 0)
        run.assert_not_called()

    def test_cli_days_overrides_config(self):
        self._write_config({"days": 100, "db_path": self.db, "opencode_bin": "opencode"})
        result = mock.Mock(returncode=0, stdout="ok", stderr="")
        code, run = self._run(["--apply", "--days", "30"], result)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)

    def test_protect_skips_matching_sessions(self):
        result = mock.Mock(returncode=0, stdout="ok", stderr="")
        code, run = self._run(["--apply", "--protect", "/work/alpha"], result)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)

    def test_missing_db_exits_1(self):
        self._write_config({"days": 30, "db_path": self.db + ".missing"})
        result = mock.Mock(returncode=0, stdout="", stderr="")
        code, run = self._run(["--apply"], result)
        self.assertEqual(code, 1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
