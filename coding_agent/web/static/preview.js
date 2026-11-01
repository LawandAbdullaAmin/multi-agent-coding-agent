// Simulierter Lauf für die kostenlose Vorschau der Oberfläche (kein Server, kein Modell).
// Jeder Eintrag: [Zeitpunkt in ms, Ereignis wie vom Server]. Der Lauf ist als "Vorschau (simuliert)" gekennzeichnet.

const TASK = "Implementiere die Funktion roman_to_int in roman.py, sodass alle Tests erfolgreich durchlaufen.";

const DIFF = `--- a/roman.py
+++ b/roman.py
@@ -1,10 +1,22 @@
 """Römische Zahlen."""
+
+VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


 def roman_to_int(text: str) -> int:
-    raise NotImplementedError
+    if not text or any(char not in VALUES for char in text):
+        raise ValueError(f"Ungültige römische Zahl: {text!r}")
+    total = 0
+    for i, char in enumerate(text):
+        value = VALUES[char]
+        if i + 1 < len(text) and VALUES[text[i + 1]] > value:
+            total -= value
+        else:
+            total += value
+    return total`;

let cost = 0, tokens = 0;
const stats = (addCost, addTokens) => {
  cost += addCost;
  tokens += addTokens;
  return { type: "stats", cost: Number(cost.toFixed(5)), tokens };
};

export const PREVIEW_EVENTS = [
  [0, { type: "run", project: "roman", task: TASK, preview: true }],
  [700, { type: "dispatch", agent: "explorer", text: "Untersuche roman.py und die Tests. Welche Anforderungen beschreiben Aufgabe und Docstring?" }],
  [1500, stats(0.0004, 1900)],
  [2300, { type: "action", agent: "explorer", text: "Verschafft sich einen Überblick über das Projekt" }],
  [3000, { type: "action", agent: "explorer", text: "Liest roman.py" }],
  [3500, { type: "action", agent: "explorer", text: "Liest test_roman.py" }],
  [4200, stats(0.0007, 3400)],
  [5200, { type: "report", agent: "explorer", model: "gpt-4.1-mini", text: "**roman_to_int** ist noch nicht implementiert (`NotImplementedError`).\n\nAnforderungen laut Docstring:\n- erlaubte Zeichen: I, V, X, L, C, D, M\n- `ValueError` bei anderen Zeichen **oder leerem Text**" }],
  [6600, { type: "dispatch", agent: "test_writer", text: "Schreibe Tests für alle Anforderungen aus dem Docstring, auch für den leeren Text." }],
  [7800, { type: "action", agent: "test_writer", text: "Liest roman.py" }],
  [8600, { type: "action", agent: "test_writer", text: "Schreibt test_spec_roman.py" }],
  [9400, { type: "action", agent: "test_writer", text: "Führt alle Tests aus" }],
  [10300, { type: "observation", agent: "test_writer", text: "9 von 14 Tests fehlgeschlagen", ok: false }],
  [10800, stats(0.0042, 6100)],
  [11800, { type: "report", agent: "test_writer", model: "gpt-4.1", text: "8 neue Tests in `test_spec_roman.py`, jeder mit Zitat aus dem Docstring als Beleg. Sie schlagen erwartungsgemäß fehl, solange die Funktion fehlt." }],
  [13200, { type: "dispatch", agent: "developer", text: "Implementiere roman_to_int nach dem Docstring: Subtraktionsregel und ValueError bei ungültiger Eingabe." }],
  [14400, { type: "action", agent: "developer", text: "Liest roman.py" }],
  [15300, { type: "action", agent: "developer", text: "Ändert roman.py" }],
  [16000, stats(0.0009, 4300)],
  [17000, { type: "report", agent: "developer", model: "gpt-4.1-mini", text: "roman_to_int implementiert: Werte-Tabelle, Subtraktionsregel (IV, IX, XL …) und `ValueError` bei leeren oder ungültigen Eingaben." }],
  [18400, { type: "dispatch", agent: "tester", text: "Führe alle Tests aus und berichte das Ergebnis." }],
  [19400, { type: "action", agent: "tester", text: "Führt alle Tests aus" }],
  [20500, { type: "observation", agent: "tester", text: "14 Tests bestanden", ok: true }],
  [21300, { type: "report", agent: "tester", model: "gpt-4.1-mini", text: "Alle 14 Tests bestehen." }],
  [22600, { type: "dispatch", agent: "reviewer", text: "Prüfe die Änderungen vollständig gegen Aufgabe und Docstring." }],
  [23600, { type: "action", agent: "reviewer", text: "Prüft alle Änderungen" }],
  [24300, { type: "action", agent: "reviewer", text: "Führt alle Tests aus" }],
  [25100, { type: "observation", agent: "reviewer", text: "14 Tests bestanden", ok: true }],
  [25600, stats(0.0051, 5200)],
  [26600, { type: "report", agent: "reviewer", model: "gpt-4.1", approved: true, text: "Freigegeben: ja. Alle Anforderungen aus Aufgabe und Docstring sind umgesetzt, die neuen Tests sind durch Zitate belegt." }],
  [28000, { type: "dispatch", agent: "finish", text: "roman_to_int ist implementiert und mit 14 Tests verifiziert, inklusive Fehlerfällen aus dem Docstring." }],
  [30500, { type: "review", summary: "roman_to_int ist implementiert und mit 14 Tests verifiziert, inklusive Fehlerfällen aus dem Docstring.",
    tests_passed: true, diff: DIFF,
    files: [{ path: "roman.py", new: false, added: 14, removed: 1 }, { path: "test_spec_roman.py", new: true, added: 38, removed: 0 }] }],
];
