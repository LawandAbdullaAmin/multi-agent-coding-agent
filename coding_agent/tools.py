"""Werkzeuge des Coding-Agenten.

Alle Werkzeuge arbeiten nur innerhalb eines Repository-Ordners (root).
Pfade, die aus diesem Ordner herausführen, werden abgelehnt.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import BaseTool, tool

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
MAX_OUTPUT_CHARS = 8000
MAX_SEARCH_HITS = 100
TEST_TIMEOUT_SECONDS = 120


def resolve_path(root: Path, path: str) -> Path:
    full = (root / path).resolve()
    if not full.is_relative_to(root):
        raise ValueError(f"Pfad liegt außerhalb des Repositorys: {path}")
    return full


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... [{len(text) - limit} Zeichen gekürzt] ...\n" + text[-half:]


def iter_files(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def make_tools(root: Path) -> list[BaseTool]:
    root = root.resolve()

    @tool
    def list_files(directory: str = ".") -> str:
        """Listet alle Dateien in einem Ordner des Repositorys rekursiv auf."""
        base = resolve_path(root, directory)
        if not base.is_dir():
            return f"Fehler: {directory} ist kein Ordner."
        files = [p.relative_to(root).as_posix() for p in iter_files(base)]
        return truncate("\n".join(files) or "(leer)")

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Liest eine Datei mit Zeilennummern. Optional nur die Zeilen start_line bis end_line."""
        file = resolve_path(root, path)
        if not file.is_file():
            return f"Fehler: Datei {path} existiert nicht."
        lines = read_text(file).splitlines()
        end = end_line or len(lines)
        numbered = [f"{i:>4}  {line}" for i, line in enumerate(lines[start_line - 1:end], start_line)]
        return truncate("\n".join(numbered) or "(leere Datei)")

    @tool
    def search_code(pattern: str, file_glob: str = "*") -> str:
        """Durchsucht alle Dateien (optional gefiltert, z. B. '*.py') nach einem regulären Ausdruck."""
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Fehler: ungültiger regulärer Ausdruck: {e}"
        hits = []
        for file in iter_files(root):
            if not file.match(file_glob):
                continue
            for number, line in enumerate(read_text(file).splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{file.relative_to(root).as_posix()}:{number}: {line.strip()}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + f"\n... (mehr als {MAX_SEARCH_HITS} Treffer)"
        return "\n".join(hits) or "Keine Treffer."

    @tool
    def write_file(path: str, content: str) -> str:
        """Erstellt eine neue Datei (oder überschreibt sie komplett) mit dem angegebenen Inhalt."""
        file = resolve_path(root, path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return f"{path} geschrieben ({len(content.splitlines())} Zeilen)."

    @tool
    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Ersetzt in einer Datei genau eine Stelle old_text durch new_text.

        old_text muss exakt (inkl. Einrückung) und eindeutig in der Datei vorkommen.
        """
        file = resolve_path(root, path)
        if not file.is_file():
            return f"Fehler: Datei {path} existiert nicht."
        content = read_text(file)
        count = content.count(old_text)
        if count == 0:
            return "Fehler: old_text wurde nicht gefunden. Lies die Datei erneut und kopiere den Text exakt."
        if count > 1:
            return f"Fehler: old_text kommt {count}-mal vor. Nimm mehr umgebende Zeilen dazu, damit er eindeutig ist."
        file.write_text(content.replace(old_text, new_text), encoding="utf-8")
        return f"{path} geändert."

    @tool
    def run_tests(target: str = "") -> str:
        """Führt die Tests mit pytest aus. Optional nur eine Datei oder einen Test (z. B. 'test_x.py::test_y')."""
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if target:
            resolve_path(root, target.split("::")[0])
            cmd.append(target)
        # Geheimnisse wie OPENAI_API_KEY nicht an den ausgeführten Code weitergeben.
        env = {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in SECRET_MARKERS)}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            result = subprocess.run(
                cmd, cwd=root, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=TEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"Fehler: Tests nach {TEST_TIMEOUT_SECONDS} Sekunden abgebrochen."
        return truncate(f"Exit-Code: {result.returncode}\n{result.stdout}{result.stderr}")

    return [list_files, read_file, search_code, write_file, edit_file, run_tests]
