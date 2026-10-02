#!/usr/bin/env python3
"""OpenCode session cleaner (KISS, portable).

Deletes OpenCode sessions whose last activity (``time_updated``) is older than
a configurable number of days, with optional protected directory prefixes.

Safety:
- Default is dry-run; sessions are only deleted with ``--apply``.
- The SQLite database is opened read-only (``mode=ro``). This script never
  issues ``DELETE``/``UPDATE``/``VACUUM`` against the database.
- Deletion happens exclusively through the official CLI
  (``opencode session delete <id>``), resolved via ``shutil.which``.

Standard library only.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

# --- neutral defaults (override via --config / CLI flags) ---
DEFAULTS = {
    "days": 30,
    "protect_paths": [],  # empty by default; no path is special-cased
    "db_path": "~/.local/share/opencode/opencode.db",  # XDG data dir
    "opencode_bin": "opencode",  # resolved via shutil.which
}
CONFIG_KEYS = ("days", "protect_paths", "db_path", "opencode_bin")

MS_PER_DAY = 86_400_000.0
TITLE_MAX = 50

# CLI message emitted when a session no longer exists (harmless).
NOT_FOUND_MARKER = "session not found"

LOG_PREFIX = "[opencode-session-cleaner]"


class ConfigError(Exception):
    """Raised for invalid or unreadable configuration."""


def is_not_found(output):
    """True if the CLI reports that the session does not (or no longer) exist."""
    return NOT_FOUND_MARKER in (output or "").lower()


def now_ms():
    return int(time.time() * 1000)


def normalize(path):
    """Absolute, symlink-resolved path without trailing separator."""
    if not path:
        return None
    return os.path.realpath(os.path.expanduser(path))


def is_protected(directory, protected_roots):
    """True if directory equals a root or lies below it."""
    norm = normalize(directory)
    if norm is None:
        return False
    for root in protected_roots:
        if norm == root or norm.startswith(root + os.sep):
            return True
    return False


def resolve_binary(name):
    """Resolve the opencode executable via PATH (shutil.which)."""
    if not name:
        return None
    found = shutil.which(name)
    if found:
        return found
    return None


def validate_config(config):
    """Validate a merged config mapping; raise ConfigError on problems."""
    days = config.get("days")
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ConfigError("'days' must be a positive integer")

    protect = config.get("protect_paths")
    if not isinstance(protect, list) or not all(isinstance(p, str) for p in protect):
        raise ConfigError("'protect_paths' must be a list of strings")

    db_path = config.get("db_path")
    if not isinstance(db_path, str) or not db_path:
        raise ConfigError("'db_path' must be a non-empty string")

    opencode_bin = config.get("opencode_bin")
    if not isinstance(opencode_bin, str) or not opencode_bin:
        raise ConfigError("'opencode_bin' must be a non-empty string")


def load_config(path):
    """Return defaults merged with an optional JSON config file.

    Precedence (handled by the caller): defaults < config file < CLI flags.
    """
    config = dict(DEFAULTS)
    if path:
        if not os.path.exists(path):
            raise ConfigError(f"config file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"cannot read config file: {exc}")
        if not isinstance(data, dict):
            raise ConfigError("config file must contain a JSON object")
        for key in CONFIG_KEYS:
            if key in data:
                config[key] = data[key]
    validate_config(config)
    return config


def load_sessions(db_path):
    """Union of ``session`` and ``session_v2`` (dict keyed by id). Read-only."""
    sessions = {}
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        for table in ("session", "session_v2"):
            try:
                rows = con.execute(
                    f"SELECT id, directory, title, time_updated FROM {table}"
                ).fetchall()
            except sqlite3.Error as exc:
                print(f"WARN: table {table} not readable: {exc}", flush=True)
                continue
            for sid, directory, title, time_updated in rows:
                entry = sessions.get(sid)
                if entry is None:
                    sessions[sid] = {
                        "id": sid,
                        "directory": directory,
                        "title": title,
                        "time_updated": time_updated,
                    }
                else:
                    # Fill gaps from the second table.
                    if entry["directory"] is None and directory is not None:
                        entry["directory"] = directory
                    if entry["title"] is None and title is not None:
                        entry["title"] = title
                    if entry["time_updated"] is None and time_updated is not None:
                        entry["time_updated"] = time_updated
    finally:
        con.close()
    return sessions


def short_title(title):
    if not title:
        return ""
    text = " ".join(str(title).split())
    if len(text) > TITLE_MAX:
        text = text[: TITLE_MAX - 1] + "..."
    return text


def format_table(rows):
    headers = ("ID", "AGE(D)", "PROTECTED", "DIRECTORY", "TITLE")
    table = []
    for r in rows:
        table.append(
            (
                r["id"],
                f"{r['age_days']:.1f}",
                "yes" if r["protected"] else "no",
                r["directory"] or "",
                short_title(r["title"]),
            )
        )
    widths = [len(h) for h in headers]
    for row in table:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in table:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def delete_session(binary, session_id):
    """Delete one session through the official CLI. Returns (ok, output)."""
    try:
        proc = subprocess.run(
            [binary, "session", "delete", session_id],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"invocation failed: {exc}"
    output = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0
    return ok, output.strip()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Delete old OpenCode sessions (dry-run by default)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually delete sessions (without this flag only a report is printed).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="age threshold in days; overrides the config file.",
    )
    parser.add_argument(
        "--protect",
        action="append",
        default=None,
        metavar="PATH",
        help="protected directory prefix (repeatable); overrides the config file.",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="path to a JSON configuration file.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        merged = dict(config)
        if args.days is not None:
            merged["days"] = args.days
        if args.protect is not None:
            merged["protect_paths"] = args.protect
        validate_config(merged)
    except ConfigError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 1

    days = merged["days"]
    db_path = os.path.expanduser(merged["db_path"])
    protected_roots = [
        root for root in (normalize(p) for p in merged["protect_paths"]) if root
    ]

    if not os.path.exists(db_path):
        print(f"ERROR: database not found: {db_path}", flush=True)
        return 1

    binary = None
    if args.apply:
        binary = resolve_binary(merged["opencode_bin"])
        if binary is None:
            print(
                "ERROR: opencode binary not found on PATH: "
                f"{merged['opencode_bin']}",
                flush=True,
            )
            return 1

    try:
        sessions = load_sessions(db_path)
    except sqlite3.Error as exc:
        print(f"ERROR: cannot read SQLite database: {exc}", flush=True)
        return 1

    cutoff = now_ms() - int(days * MS_PER_DAY)
    old = []
    for entry in sessions.values():
        ts = entry["time_updated"]
        if ts is None or ts >= cutoff:
            continue
        old.append(
            {
                "id": entry["id"],
                "directory": entry["directory"],
                "title": entry["title"],
                "time_updated": ts,
                "age_days": (now_ms() - ts) / MS_PER_DAY,
                "protected": is_protected(entry["directory"], protected_roots),
            }
        )
    old.sort(key=lambda r: r["time_updated"])

    candidates = [r for r in old if not r["protected"]]
    protected = [r for r in old if r["protected"]]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{LOG_PREFIX} mode={mode} days={days} db={db_path}", flush=True)
    print(f"{LOG_PREFIX} protected paths: {merged['protect_paths']}", flush=True)
    print(
        f"{LOG_PREFIX} sessions total={len(sessions)} older_than_{days}d={len(old)} "
        f"candidates={len(candidates)} protected={len(protected)}",
        flush=True,
    )
    if old:
        print(format_table(old), flush=True)
    else:
        print(f"{LOG_PREFIX} no sessions older than threshold.", flush=True)

    if not args.apply:
        print(
            f"{LOG_PREFIX} dry-run finished - nothing deleted. "
            "Run with --apply to delete.",
            flush=True,
        )
        return 0

    failures = 0
    deleted = 0
    not_found = 0
    for r in candidates:
        sid = r["id"]
        ok, output = delete_session(binary, sid)
        if is_not_found(output):
            not_found += 1
            print(
                f"{LOG_PREFIX} session not found (skipped): {sid}",
                flush=True,
            )
        elif ok:
            deleted += 1
            print(f"{LOG_PREFIX} deleted: {sid}", flush=True)
        else:
            failures += 1
            print(
                f"{LOG_PREFIX} delete failed: {sid}: {output}",
                flush=True,
            )
        if output:
            print(f"{LOG_PREFIX}   cli: {output}", flush=True)

    print(
        f"{LOG_PREFIX} done: deleted={deleted} failed={failures} "
        f"not_found={not_found} protected/skipped={len(protected)}",
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
