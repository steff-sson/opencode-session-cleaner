# AGENTS.md

## Zweck

`opencode_session_cleaner.py` löscht alte OpenCode-Sessions, deren letzte
Aktivität (`time_updated`) älter als eine konfigurierbare Anzahl Tage ist.
Optionale geschützte Verzeichnis-Präfixe werden übersprungen.

## Regeln

- **Python stdlib-only.** Keine externen Abhängigkeiten.
- **Keine SQL-Schreiboperationen.** Die SQLite-DB wird ausschließlich
  read-only (`mode=ro`) geöffnet. Kein `DELETE`/`UPDATE`/`VACUUM`.
- **Löschung ausschließlich via `opencode session delete <id>`** (offizielle
  CLI, aufgelöst über `shutil.which`). Nie direkt in die DB schreiben.
- **Dry-run ist Default.** Gelöscht wird nur mit explizitem `--apply`.
- **Keine Snapshot-Bereinigung.** Dieses Tool löscht nur Sessions.
- **Keine personenbezogenen/lokalen Details** in Code, Tests oder Doku
  (keine Namen, Pfade, Hostnamen, Tokens).

## Tests

```bash
python3 -m py_compile opencode_session_cleaner.py
python3 -m unittest discover -s tests -v
```

Vor Änderungen Tests ausführen, danach Tests **plus** Privacy/Security-Audit.
