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

**Tracing (optional):** Mit `LANGSMITH_TRACING=true` und `LANGSMITH_API_KEY` in der `.env` wird jeder Lauf
in LangSmith aufgezeichnet: jeder Supervisor-Entscheid, jeder Modell- und Werkzeugaufruf der Fach-Agenten,
mit Tokens, Kosten und Dauer. Die Traces sind nach Lauf-ID und Modus filterbar.

Docker Desktop muss laufen. Das Sandbox-Image wird beim ersten Start automatisch gebaut.
Ohne Docker: `--no-sandbox` (Tests laufen dann lokal, nur für vertrauenswürdigen Code).

## Evaluation

Eigener Benchmark mit 10 Aufgaben in [benchmark/tasks/](benchmark/tasks/), von Off-by-one-Fehlern über
Fehler in einer anderen als der getesteten Datei bis zu einer Feature-Anfrage im Stil eines Issues.

- **Versteckte Tests:** Bewertet wird zusätzlich mit Tests aus `hidden/`, die der Agent nie sieht.
- **Schutz gegen Schummeln:** Bewertet wird immer mit den Original-Tests. Verändert der Agent Tests, wird das markiert.
- **Geprüfter Benchmark:** Ein Test stellt sicher, dass jede Aufgabe anfangs fehlschlägt und mit der
  Musterlösung aus `solution/` besteht.

```
python -m coding_agent.evaluate --repeats 3
```

**Ergebnis** (`gpt-4.1-mini`, 10 Aufgaben × 3 Wiederholungen, [Bericht](benchmark/results/20261031-153014.md)):

| Modus | Gelöst | Ø Dauer | Ø Tokens | Ø Kosten pro Aufgabe |
|---|---|---|---|---|
| Team (Supervisor + 3 Fach-Agenten) | **25/30 (83 %)** | 33 s | 22.293 | $0,0125 |
| Einzel-Agent | 23/30 (77 %) | 15 s | 21.786 | $0,0100 |

Beobachtungen:

- Das Team löst etwas mehr Aufgaben, braucht aber gut doppelt so lange und kostet rund 25 % mehr.
  Bei 30 Läufen pro Modus ist der Unterschied von 2 Aufgaben noch kein belastbarer Beleg.
- Das Team ist **zuverlässiger**: Bei leichten und mittleren Aufgaben löst es jede in 3 von 3 Läufen,
  der Einzel-Agent scheitert dort gelegentlich (bank_account, roman, shopping_cart).
- **Gemeinsamer Schwachpunkt:** Bei `leap_year` beheben beide Modi den getesteten Fehler, übersehen aber
  einen zweiten, der nur in der Dokumentation beschrieben ist (0/3). Die Agenten hören auf, sobald die
  sichtbaren Tests grün sind, statt die Spezifikation vollständig umzusetzen.
- Die Feature-Anfrage (`duration`) ist für beide Modi die schwierigste lösbare Aufgabe (1/3 bzw. 2/3).

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
- [x] Phase 3c: LangSmith-Tracing
- [x] Phase 4a: Eigener Benchmark mit versteckten Tests, Team gegen Einzel-Agent
- [ ] Phase 4b: Evaluation auf SWE-bench Lite
