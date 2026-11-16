"""Tools of the coding agent.

All tools only work inside one repository folder (root).
Paths that lead outside this folder are rejected.
By default, tests run in an isolated Docker container (sandbox).
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

# Control characters (except tab and newline) appear when the model mangles special characters such as €.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

SANDBOX_IMAGE = "coding-agent-sandbox"
SANDBOX_DIR = Path(__file__).resolve().parent.parent / "sandbox"


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def ensure_sandbox_image() -> None:
    """Builds the sandbox image if it does not exist yet."""
    if not docker_available():
        raise RuntimeError("Docker is not reachable. Start Docker Desktop or use --no-sandbox.")
    if subprocess.run(["docker", "image", "inspect", SANDBOX_IMAGE], capture_output=True).returncode != 0:
        print(f"Building sandbox image '{SANDBOX_IMAGE}' (one time only) ...")
        subprocess.run(["docker", "build", "-q", "-t", SANDBOX_IMAGE, str(SANDBOX_DIR)], check=True)


def sandbox_command(root: Path, name: str, args: list[str]) -> list[str]:
    # On Linux the host's file permissions also apply inside the container: with the host's own user ID the
    # sandbox can read the repository but has no root privileges. Docker Desktop (Windows/macOS) does not need this.
    user = []
    if hasattr(os, "getuid") and os.getuid() != 0:
        user = ["--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp"]
    return [
        "docker", "run", "--rm", "--name", name, *user,
        "--network", "none",                     # no internet
        "--memory", "512m", "--cpus", "1", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp",        # read-only file system, only /tmp is writable
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--mount", f"type=bind,source={root},target=/repo,readonly",
        SANDBOX_IMAGE, "python", *args,
    ]


def tests_green(output: str) -> bool:
    """Result of run_tests: did all executed tests pass?"""
    return output.startswith("Exit code: 0")


def resolve_path(root: Path, path: str) -> Path:
    full = (root / path).resolve()
    if not full.is_relative_to(root):
        raise ToolException(f"Error: path is outside the repository: {path}")
    return full


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... [{len(text) - limit} characters truncated] ...\n" + text[-half:]


def iter_files(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def is_test_file(rel: str) -> bool:
    """rel: path relative to the repository with / as separator."""
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py" or "/tests/" in f"/{rel}"


# Checks whether a path may be written: None = allowed, otherwise the reason for the rejection.
WritePolicy = Callable[[str], str | None]


def make_tools(root: Path, sandbox: bool = True, can_write: WritePolicy | None = None) -> list[BaseTool]:
    root = root.resolve()
    # Parallel tool calls run in threads. Without a lock, simultaneous changes
    # to the same file would overwrite each other (read -> change -> write).
    write_lock = threading.Lock()
    # Initial state of the repository, so that show_changes can show all changes so far.
    snapshot = {p.relative_to(root).as_posix(): read_text(p) for p in iter_files(root)}

    def check_writable(file: Path, text: str) -> None:
        rel = file.relative_to(root).as_posix()
        if can_write and (reason := can_write(rel)):
            raise ToolException(f"Error: {rel} must not be changed. {reason}")
        if match := CONTROL_CHARS.search(text):
            raise ToolException(f"Error: the text contains the forbidden control character {match.group()!r}. "
                                "Nothing was written. Check special characters such as € and write the text again.")

    @tool
    def list_files(directory: str = ".") -> str:
        """Lists all files in a folder of the repository recursively."""
        base = resolve_path(root, directory)
        if not base.is_dir():
            raise ToolException(f"Error: {directory} is not a folder.")
        files = [p.relative_to(root).as_posix() for p in iter_files(base)]
        return truncate("\n".join(files) or "(empty)")

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Reads a file with line numbers. Optionally only the lines start_line to end_line."""
        file = resolve_path(root, path)
        if not file.is_file():
            raise ToolException(f"Error: file {path} does not exist.")
        lines = read_text(file).splitlines()
        end = end_line or len(lines)
        numbered = [f"{i:>4}  {line}" for i, line in enumerate(lines[start_line - 1:end], start_line)]
        return truncate("\n".join(numbered) or "(empty file)")

    @tool
    def search_code(pattern: str, file_glob: str = "*") -> str:
        """Searches all files (optionally filtered, e.g. '*.py') for a regular expression."""
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ToolException(f"Error: invalid regular expression: {e}") from None
        hits = []
        for file in iter_files(root):
            if not file.match(file_glob):
                continue
            for number, line in enumerate(read_text(file).splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{file.relative_to(root).as_posix()}:{number}: {line.strip()}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + f"\n... (more than {MAX_SEARCH_HITS} hits)"
        return "\n".join(hits) or "No hits."

    @tool
    def write_file(path: str, content: str) -> str:
        """Creates a new file (or completely overwrites it) with the given content."""
        file = resolve_path(root, path)
        check_writable(file, content)
        with write_lock:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        return f"{path} written ({len(content.splitlines())} lines)."

    @tool
    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Replaces exactly one occurrence of old_text with new_text in a file.

        old_text must occur exactly (including indentation) and uniquely in the file,
        without the line numbers that read_file puts in front.
        """
        file = resolve_path(root, path)
        check_writable(file, new_text)
        with write_lock:
            if not file.is_file():
                raise ToolException(f"Error: file {path} does not exist.")
            content = read_text(file)
            count = content.count(old_text)
            if count == 0:
                raise ToolException("Error: old_text was not found. Read the file again and copy "
                                    "the text exactly, but without the line numbers at the start of each line.")
            if count > 1:
                raise ToolException(f"Error: old_text occurs {count} times. "
                                    "Include more surrounding lines so that it is unique.")
            file.write_text(content.replace(old_text, new_text), encoding="utf-8")
        return f"{path} changed."

    @tool
    def run_tests(target: str = "") -> str:
        """Runs the tests with pytest. Optionally only one file or one test (e.g. 'test_x.py::test_y')."""
        args = ["-m", "pytest", "-q", "-p", "no:cacheprovider"]
        if target:
            resolve_path(root, target.split("::")[0])
            args.append(target)
        # Do not pass secrets such as OPENAI_API_KEY on to the executed code.
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
            raise ToolException(f"Error: tests aborted after {TEST_TIMEOUT_SECONDS} seconds.") from None
        return truncate(f"Exit code: {result.returncode}\n{result.stdout}{result.stderr}")

    @tool
    def show_changes() -> str:
        """Shows all changes compared to the initial state of the repository as a diff."""
        diffs = []
        for file in iter_files(root):
            rel = file.relative_to(root).as_posix()
            old = snapshot.get(rel, "").splitlines(keepends=True)
            new = read_text(file).splitlines(keepends=True)
            diffs.extend(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}"))
        return truncate("".join(diffs) or "No changes.")

    tools = [list_files, read_file, search_code, write_file, edit_file, run_tests, show_changes]
    # A ToolException is returned to the agent as a message with status="error" instead of aborting the run.
    for t in tools:
        t.handle_tool_error = True
    return tools
