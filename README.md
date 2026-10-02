# opencode-session-cleaner

A small, portable, stdlib-only utility that deletes **old OpenCode sessions**
based on their last activity timestamp (`time_updated`), optionally keeping
sessions that live under protected directory prefixes.

It is designed to be safe by default: it never touches the OpenCode SQLite
database with write statements and it does not delete anything unless you
explicitly pass `--apply`.

## Safety model

- **Read-only database access.** The database is opened with SQLite's
  `mode=ro` URI. This tool never issues `DELETE`, `UPDATE`, `VACUUM`, or any
  other write statement against it.
- **Deletion via the official CLI only.** Sessions are removed sequentially
  with `opencode session delete <id>`, where `opencode` is resolved from your
  `PATH` via `shutil.which`. No direct database mutation.
- **Dry-run is the default.** Without `--apply`, the tool prints a report and
  exits without deleting anything.
- **Neutral defaults.** No directory is protected by default. Add your own
  protected paths explicitly via `--protect` or a config file.

## Requirements

- Python 3 (standard library only; no third-party packages).
- The `opencode` CLI available on your `PATH` when running with `--apply`.

## Configuration

Defaults:

| Key            | Default                                    |
|----------------|--------------------------------------------|
| `days`         | `30`                                       |
| `protect_paths`| `[]` (nothing protected)                   |
| `db_path`      | `~/.local/share/opencode/opencode.db`      |
| `opencode_bin` | `opencode` (resolved via `PATH`)           |

Copy `config.example.json` and adjust it:

```json
{
  "days": 30,
  "protect_paths": [],
  "db_path": "~/.local/share/opencode/opencode.db",
  "opencode_bin": "opencode"
}
```

Precedence: **defaults < config file < CLI flags**.

CLI flags:

- `--days N` — age threshold in days.
- `--protect PATH` — protected directory prefix, repeatable. Sessions whose
  stored `directory` equals or is nested under `PATH` are never candidates.
- `--config PATH` — path to a JSON config file.
- `--apply` — actually delete candidates (without it: dry-run report).

## Usage

Dry-run (report only, nothing is deleted):

```bash
python3 opencode_session_cleaner.py
python3 opencode_session_cleaner.py --days 14 --protect /path/to/keep
python3 opencode_session_cleaner.py --config config.json
```

Delete for real (only after reviewing a dry-run report):

```bash
python3 opencode_session_cleaner.py --apply
```

### Exit codes

| Code | Meaning                                                              |
|------|----------------------------------------------------------------------|
| `0`  | Success (including "session not found" skips and dry-run)            |
| `1`  | Real error: missing/unreadable database, missing binary (with `--apply`), delete failure, invalid config |
| `2`  | `argparse` usage error                                               |

## systemd --user timer (optional)

`systemd/` contains generic unit templates. The service runs the script as a
plain dry-run report; the timer triggers it weekly.

1. Adjust the clone location in the service file. The placeholder
   `<PATH-TO-REPO>` in `ExecStart` must be replaced with the real path
   (relative to `%h`, your home directory):

   ```ini
   [Service]
   ExecStart=/usr/bin/python3 %h/<PATH-TO-REPO>/opencode_session_cleaner.py
   ```

   Example: if the repo lives at `~/code/opencode-session-cleaner`, use
   `%h/code/opencode-session-cleaner/opencode_session_cleaner.py`.

2. Copy the units and reload:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp systemd/opencode-session-cleaner.service ~/.config/systemd/user/
   cp systemd/opencode-session-cleaner.timer ~/.config/systemd/user/
   systemctl --user daemon-reload
   ```

3. Optional sanity check before enabling:

   ```bash
   systemd-analyze --user verify ~/.config/systemd/user/opencode-session-cleaner.service
   ```

4. Enable the timer (nothing here is enabled automatically):

   ```bash
   systemctl --user enable --now opencode-session-cleaner.timer
   systemctl --user start opencode-session-cleaner.service   # one dry-run now
   journalctl --user -u opencode-session-cleaner.service -n 100
   ```

### Enabling actual deletion (drop-in)

The shipped service intentionally calls the script **without** `--apply`, so the
timer only produces journal reports. To enable deletions, add a drop-in:

```bash
systemctl --user edit opencode-session-cleaner.service
```

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 %h/<PATH-TO-REPO>/opencode_session_cleaner.py --apply
```

Then `systemctl --user daemon-reload`. Recommended before doing this: review
the dry-run report, then delete one verified old session manually with
`opencode session delete <id>`, and only then switch to `--apply`.

## Backups

Deletion is permanent (SQLite has no trash can). Before the first `--apply`,
consider exporting sessions you may want to keep:

```bash
opencode export <sessionID>
```

## Snapshots

`opencode session delete` does not immediately remove associated snapshot
objects. A separate snapshot garbage collector runs independently, and
leftover snapshot diffs may become orphaned. Snapshot handling is intentionally
**not** part of this tool.

## Limitations

- The "session not found" detection relies on a case-insensitive substring
  match against the CLI output. A localized CLI message could change this
  behavior; such a case is treated as a delete failure (exit code `1`), never
  as a silent success.
- The database schema is read as a union of the `session` and `session_v2`
  tables. If a table is missing or unreadable, a warning is printed and the
  other table is used.

## Contributing

Please do **not** paste real session IDs, session titles, directory paths, or
database dumps into issues or pull requests. Use anonymized examples only.

## Tests

```bash
python3 -m unittest discover tests
```

The tests use a temporary SQLite fixture and mock `subprocess.run`; they never
delete real sessions.

## License

MIT — see [LICENSE](LICENSE).
