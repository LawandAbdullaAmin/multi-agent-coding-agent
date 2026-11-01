"""Werkzeuge des Coding-Agenten.

Alle Werkzeuge arbeiten nur innerhalb eines Repository-Ordners (root).
Pfade, die aus diesem Ordner herausführen, werden abgelehnt.
Tests laufen standardmäßig in einem isolierten Docker-Container (Sandbox).
"""

import difflib
import os
import re
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from langchain_core.tools import BaseTool, ToolException, tool

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
MAX_OUTPUT_CHARS = 8000
MAX_SEARCH_HITS = 100
TEST_TIMEOUT_SECONDS = 120

# Steuerzeichen (außer Tab und Zeilenumbruch) entstehen, wenn das Modell Sonderzeichen wie € verstümmelt.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

SANDBOX_IMAGE = "coding-agent-sandbox"
SANDBOX_DIR = Path(__file__).resolve().parent.parent / "sandbox"


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def ensure_sandbox_image() -> None:
    """Baut das Sandbox-Image, falls es noch nicht existiert."""
    if not docker_available():
        raise RuntimeError("Docker ist nicht erreichbar. Starte Docker Desktop oder nutze --no-sandbox.")
    if subprocess.run(["docker", "image", "inspect", SANDBOX_IMAGE], capture_output=True).returncode != 0:
        print(f"Baue Sandbox-Image '{SANDBOX_IMAGE}' (einmalig) ...")
        subprocess.run(["docker", "build", "-q", "-t", SANDBOX_IMAGE, str(SANDBOX_DIR)], check=True)


def sandbox_command(root: Path, name: str, args: list[str]) -> list[str]:
    # Unter Linux gelten die Dateirechte des Hosts auch im Container: Mit der eigenen Nutzer-ID darf die
    # Sandbox das Repository lesen, bleibt aber ohne Root-Rechte. Docker Desktop (Windows/macOS) braucht das nicht.
    user = ["--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp"] if hasattr(os, "getuid") and os.getuid() != 0 else []
    return [
        "docker", "run", "--rm", "--name", name, *user,
        "--network", "none",                     # kein Internet
        "--memory", "512m", "--cpus", "1", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp",        # Dateisystem schreibgeschützt, nur /tmp beschreibbar
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--mount", f"type=bind,source={root},target=/repo,readonly",
        SANDBOX_IMAGE, "python", *args,
    ]


def resolve_path(root: Path, path: str) -> Path:
    full = (root / path).resolve()
    if not full.is_relative_to(root):
        raise ToolException(f"Fehler: Pfad liegt außerhalb des Repositorys: {path}")
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


def is_test_file(rel: str) -> bool:
    """rel: Pfad relativ zum Repository mit / als Trenner."""
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py" or "/tests/" in f"/{rel}"


# Prüft, ob ein Pfad geschrieben werden darf: None = erlaubt, sonst der Grund für die Ablehnung.
WritePolicy = Callable[[str], str | None]


def make_tools(root: Path, sandbox: bool = True, can_write: WritePolicy | None = None) -> list[BaseTool]:
    root = root.resolve()
    # Parallele Werkzeugaufrufe laufen in Threads. Ohne Sperre würden sich gleichzeitige
    # Änderungen an derselben Datei gegenseitig überschreiben (lesen -> ändern -> schreiben).
    write_lock = threading.Lock()
    # Ausgangsstand des Repositorys, damit show_changes alle bisherigen Änderungen zeigen kann.
    snapshot = {p.relative_to(root).as_posix(): read_text(p) for p in iter_files(root)}

    def check_writable(file: Path, text: str) -> None:
        rel = file.relative_to(root).as_posix()
        if can_write and (reason := can_write(rel)):
            raise ToolException(f"Fehler: {rel} darf nicht geändert werden. {reason}")
        if match := CONTROL_CHARS.search(text):
            raise ToolException(f"Fehler: Der Text enthält das unzulässige Steuerzeichen {match.group()!r}. "
                                "Nichts wurde geschrieben. Prüfe Sonderzeichen wie € und schreibe den Text erneut.")

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
        check_writable(file, content)
        with write_lock:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        return f"{path} geschrieben ({len(content.splitlines())} Zeilen)."

    @tool
    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Ersetzt in einer Datei genau eine Stelle old_text durch new_text.

        old_text muss exakt (inkl. Einrückung) und eindeutig in der Datei vorkommen,
        ohne die Zeilennummern, die read_file voranstellt.
        """
        file = resolve_path(root, path)
        check_writable(file, new_text)
        with write_lock:
            if not file.is_file():
                return f"Fehler: Datei {path} existiert nicht."
            content = read_text(file)
            count = content.count(old_text)
            if count == 0:
                return ("Fehler: old_text wurde nicht gefunden. Lies die Datei erneut und kopiere den Text exakt, "
                        "aber ohne die Zeilennummern am Zeilenanfang.")
            if count > 1:
                return f"Fehler: old_text kommt {count}-mal vor. Nimm mehr umgebende Zeilen dazu, damit er eindeutig ist."
            file.write_text(content.replace(old_text, new_text), encoding="utf-8")
        return f"{path} geändert."

    @tool
    def run_tests(target: str = "") -> str:
        """Führt die Tests mit pytest aus. Optional nur eine Datei oder einen Test (z. B. 'test_x.py::test_y')."""
        args = ["-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if target:
            resolve_path(root, target.split("::")[0])
            args.append(target)
        # Geheimnisse wie OPENAI_API_KEY nicht an den ausgeführten Code weitergeben.
        env = {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in SECRET_MARKERS)}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        name = f"coding-agent-{uuid.uuid4().hex[:8]}"
        cmd = sandbox_command(root, name, args) if sandbox else [sys.executable, *args]
        try:
            result = subprocess.run(
                cmd, cwd=root, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=TEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            if sandbox:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            return f"Fehler: Tests nach {TEST_TIMEOUT_SECONDS} Sekunden abgebrochen."
        return truncate(f"Exit-Code: {result.returncode}\n{result.stdout}{result.stderr}")

    @tool
    def show_changes() -> str:
        """Zeigt alle Änderungen gegenüber dem Ausgangsstand des Repositorys als Diff."""
        diffs = []
        for file in iter_files(root):
            rel = file.relative_to(root).as_posix()
            old = snapshot.get(rel, "").splitlines(keepends=True)
            new = read_text(file).splitlines(keepends=True)
            diffs.extend(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}"))
        return truncate("".join(diffs) or "Keine Änderungen.")

    tools = [list_files, read_file, search_code, write_file, edit_file, run_tests, show_changes]
    # ToolException wird als Nachricht an den Agenten zurückgegeben, statt den Lauf abzubrechen.
    for t in tools:
        t.handle_tool_error = True
    return tools
