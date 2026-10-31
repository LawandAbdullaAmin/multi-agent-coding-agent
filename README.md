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
| `run_tests` | `pytest` in der Docker-Sandbox ausführen (mit Zeitlimit) |

## Sicherheit

- Alle Werkzeuge sind auf den Repository-Ordner beschränkt.
- Der Agent arbeitet auf einer Kopie unter `workspaces/` und zeigt am Ende einen Diff.
- Vom Agenten geschriebener Code läuft nur in einem Docker-Container ([sandbox/Dockerfile](sandbox/Dockerfile)):
  kein Netzwerk, schreibgeschütztes Dateisystem, eigener Nutzer ohne Root-Rechte,
  Limits für RAM (512 MB), CPU und Prozesse, keine API-Schlüssel in der Umgebung.

## Starten

```
# einmalig: .env.example nach .env kopieren und OPENAI_API_KEY eintragen
pip install -r requirements.txt

python -m coding_agent --repo examples/calculator
python -m coding_agent --repo <pfad> "Eigene Aufgabe"
```

Docker Desktop muss laufen. Das Sandbox-Image wird beim ersten Start automatisch gebaut.
Ohne Docker: `--no-sandbox` (Tests laufen dann lokal, nur für vertrauenswürdigen Code).

## Tests

```
python -m pytest tests
```

## Roadmap

- [x] Phase 1: Einzelner Agent mit Werkzeugen (ReAct-Schleife)
- [x] Phase 2a: Docker-Sandbox für die Code-Ausführung
- [ ] Phase 2b: Mehrere Agenten mit Supervisor
- [ ] Phase 3: Human-in-the-loop, Checkpointing, LangSmith-Tracing
- [ ] Phase 4: Evaluation auf SWE-bench Lite
