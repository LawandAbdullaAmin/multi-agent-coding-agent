# Coding-Agent

Ein autonomer Coding-Agent mit LangGraph. Er erkundet ein Repository, führt die Tests aus,
findet die Fehlerursache, ändert den Code und prüft seine Änderung, bis alle Tests grün sind.

## Architektur

### Team-Modus (Standard): Supervisor mit Fach-Agenten

```
                 +--> explorer  --+
START -> supervisor --> developer --+--> supervisor --> ... --> END
                 +--> tester    --+
```

Der **Supervisor** ist ein eigener LangGraph-Knoten. Er liest die Berichte der Fach-Agenten und
entscheidet per strukturierter Ausgabe, wer als Nächstes arbeitet und mit welchem Auftrag.
Die **Fach-Agenten** sind mit `create_agent` gebaut und bekommen nur die Werkzeuge ihrer Rolle:

| Agent | Werkzeuge | Rolle |
|---|---|---|
| explorer | `list_files`, `read_file`, `search_code` | Code untersuchen, Fehlerursachen finden |
| developer | `read_file`, `search_code`, `edit_file`, `write_file` | Code ändern |
| tester | `run_tests`, `read_file` | Tests ausführen und berichten |

Ob die Tests am Ende bestehen, entscheidet nicht das Modell, sondern das tatsächliche Ergebnis
des letzten Testlaufs (`tests_passed`).

**Human-in-the-loop:** Wenn der Supervisor fertig ist, pausiert der Graph im Knoten `review`
(`interrupt`, Zustand gesichert durch einen Checkpointer). Der Mensch sieht den Diff und kann

- **freigeben**: Die Änderungen werden aus der Arbeitskopie ins Repository übernommen,
- **verwerfen**: Das Repository bleibt unverändert,
- **Feedback geben**: Der Graph läuft mit dem Feedback weiter zum Supervisor, das Team arbeitet nach
  und legt das Ergebnis erneut zur Freigabe vor.

```
supervisor --(finish)--> review --(freigeben / verwerfen)--> END
    ^                       |
    +------(Feedback)-------+
```

**Persistente Läufe:** Jeder Lauf hat eine Lauf-ID. Der Zustand des Graphen wird nach jedem Schritt
in einer SQLite-Datenbank gespeichert (`.runs/checkpoints.sqlite`, `thread_id` = Lauf-ID).
Wird ein Lauf unterbrochen (Fenster geschlossen, Strg+C, Absturz), läuft er mit `--resume`
am letzten gespeicherten Schritt weiter. Wartet er auf die Freigabe, geht es direkt dort weiter.

### Single-Modus: ein Agent (ReAct-Schleife)

```
START -> agent --(Werkzeugaufrufe)--> tools
           ^                            |
           +----------------------------+
         agent --(fertig / Schrittlimit)--> END
```

### Werkzeuge

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
- Parallele Dateiänderungen sind durch eine Sperre geschützt (keine verlorenen Änderungen).
- Der Agent arbeitet auf einer Kopie unter `workspaces/` und zeigt am Ende einen Diff.
- Vom Agenten geschriebener Code läuft nur in einem Docker-Container ([sandbox/Dockerfile](sandbox/Dockerfile)):
  kein Netzwerk, schreibgeschütztes Dateisystem, eigener Nutzer ohne Root-Rechte,
  Limits für RAM (512 MB), CPU und Prozesse, keine API-Schlüssel in der Umgebung.

## Starten

```
# einmalig: .env.example nach .env kopieren und OPENAI_API_KEY eintragen
pip install -r requirements.txt

python -m coding_agent --repo examples/calculator
python -m coding_agent --repo examples/calculator --mode single
python -m coding_agent --repo <pfad> "Eigene Aufgabe"
python -m coding_agent --repo <pfad> --auto-approve   # ohne Freigabe, z. B. für Evaluationen
python -m coding_agent --resume <lauf-id>             # unterbrochenen Lauf fortsetzen
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
- [x] Phase 2b: Mehrere Agenten mit Supervisor
- [x] Phase 3a: Human-in-the-loop (Freigabe, Verwerfen, Feedback-Schleife)
- [x] Phase 3b: Persistentes Checkpointing (Läufe später fortsetzen)
- [ ] Phase 3c: LangSmith-Tracing
- [ ] Phase 4: Evaluation auf SWE-bench Lite
