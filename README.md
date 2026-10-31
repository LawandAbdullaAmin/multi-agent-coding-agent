# Coding-Agent

Ein autonomer Coding-Agent mit LangGraph. Er erkundet ein Repository, führt die Tests aus,
findet die Fehlerursache, ändert den Code und prüft seine Änderung, bis alle Tests grün sind.

## Architektur (Phase 1)

```
START -> agent --(Werkzeugaufrufe)--> tools
           ^                            |
           +----------------------------+
         agent --(fertig / Schrittlimit)--> END
```

| Werkzeug | Zweck |
|---|---|
| `list_files` | Dateien im Repository auflisten |
| `read_file` | Datei mit Zeilennummern lesen |
| `search_code` | Regex-Suche im Code |
| `edit_file` | Gezielte, eindeutige Textersetzung |
| `write_file` | Neue Datei anlegen |
| `run_tests` | `pytest` ausführen (mit Zeitlimit, ohne API-Schlüssel in der Umgebung) |

Sicherheit: Alle Werkzeuge sind auf den Repository-Ordner beschränkt. Standardmäßig arbeitet
der Agent auf einer Kopie unter `workspaces/` und zeigt am Ende einen Diff.

## Starten

```
# einmalig: .env.example nach .env kopieren und OPENAI_API_KEY eintragen
pip install -r requirements.txt

python -m coding_agent --repo examples/calculator
python -m coding_agent --repo <pfad> "Eigene Aufgabe"
```

## Tests

```
python -m pytest tests
```

## Roadmap

- [x] Phase 1: Einzelner Agent mit Werkzeugen (ReAct-Schleife)
- [ ] Phase 2: Mehrere Agenten mit Supervisor, Docker-Sandbox
- [ ] Phase 3: Human-in-the-loop, Checkpointing, LangSmith-Tracing
- [ ] Phase 4: Evaluation auf SWE-bench Lite
