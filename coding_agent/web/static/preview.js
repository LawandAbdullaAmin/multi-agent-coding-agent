// Simulated run for the free preview of the interface (no server, no model).
// Each entry: [time in ms, event as sent by the server]. The run is labeled as "Preview (simulated)".

const TASK = "Implement the function roman_to_int in roman.py so that all tests pass.";

const DIFF = `--- a/roman.py
+++ b/roman.py
@@ -1,10 +1,22 @@
 """Roman numerals."""
+
+VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


 def roman_to_int(text: str) -> int:
-    raise NotImplementedError
+    if not text or any(char not in VALUES for char in text):
+        raise ValueError(f"Invalid Roman numeral: {text!r}")
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
  [700, { type: "dispatch", agent: "explorer", text: "Investigate roman.py and the tests. Which requirements do the task and the docstring describe?" }],
  [1500, stats(0.0004, 1900)],
  [2300, { type: "action", agent: "explorer", text: "Gets an overview of the project" }],
  [3000, { type: "action", agent: "explorer", text: "Reads roman.py" }],
  [3500, { type: "action", agent: "explorer", text: "Reads test_roman.py" }],
  [4200, stats(0.0007, 3400)],
  [5200, { type: "report", agent: "explorer", model: "gpt-4.1-mini", text: "**roman_to_int** is not implemented yet (`NotImplementedError`).\n\nRequirements according to the docstring:\n- allowed characters: I, V, X, L, C, D, M\n- `ValueError` for other characters **or empty text**" }],
  [6600, { type: "dispatch", agent: "test_writer", text: "Write tests for all requirements from the docstring, including the empty text." }],
  [7800, { type: "action", agent: "test_writer", text: "Reads roman.py" }],
  [8600, { type: "action", agent: "test_writer", text: "Writes test_spec_roman.py" }],
  [9400, { type: "action", agent: "test_writer", text: "Runs all tests" }],
  [10300, { type: "observation", agent: "test_writer", text: "9 of 14 tests failed", ok: false }],
  [10800, stats(0.0042, 6100)],
  [11800, { type: "report", agent: "test_writer", model: "gpt-4.1", text: "8 new tests in `test_spec_roman.py`, each backed by a quote from the docstring. As expected, they fail as long as the function is missing." }],
  [13200, { type: "dispatch", agent: "developer", text: "Implement roman_to_int according to the docstring: subtraction rule and ValueError for invalid input." }],
  [14400, { type: "action", agent: "developer", text: "Reads roman.py" }],
  [15300, { type: "action", agent: "developer", text: "Edits roman.py" }],
  [16000, stats(0.0009, 4300)],
  [17000, { type: "report", agent: "developer", model: "gpt-4.1-mini", text: "Implemented roman_to_int: value table, subtraction rule (IV, IX, XL …) and `ValueError` for empty or invalid input." }],
  [18400, { type: "dispatch", agent: "tester", text: "Run all tests and report the result." }],
  [19400, { type: "action", agent: "tester", text: "Runs all tests" }],
  [20500, { type: "observation", agent: "tester", text: "14 tests passed", ok: true }],
  [21300, { type: "report", agent: "tester", model: "gpt-4.1-mini", text: "All 14 tests pass." }],
  [22600, { type: "dispatch", agent: "reviewer", text: "Check the changes completely against the task and the docstring." }],
  [23600, { type: "action", agent: "reviewer", text: "Reviews all changes" }],
  [24300, { type: "action", agent: "reviewer", text: "Runs all tests" }],
  [25100, { type: "observation", agent: "reviewer", text: "14 tests passed", ok: true }],
  [25600, stats(0.0051, 5200)],
  [26600, { type: "report", agent: "reviewer", model: "gpt-4.1", approved: true, text: "Approved: yes. All requirements from the task and docstring are implemented, and the new tests are backed by quotes." }],
  [28000, { type: "dispatch", agent: "finish", text: "roman_to_int is implemented and verified with 14 tests, including the error cases from the docstring." }],
  [30500, { type: "review", summary: "roman_to_int is implemented and verified with 14 tests, including the error cases from the docstring.",
    tests_passed: true, diff: DIFF,
    files: [{ path: "roman.py", new: false, added: 14, removed: 1 }, { path: "test_spec_roman.py", new: true, added: 38, removed: 0 }] }],
];
