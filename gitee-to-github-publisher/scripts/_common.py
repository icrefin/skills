#!/usr/bin/env python3
"""Shared helpers for the gitee-to-github-publisher scripts.

Standard library only, on purpose: every script must run with a bare
``python3`` (or ``uv run python``) on a fresh machine.

Three rules this module exists to enforce:

1. **A token is never printed.**  ``redact()`` is applied to every subprocess
   stream and every error message this package emits, so a token can only leak
   through a place that bypasses these helpers.
2. **A token is never written to disk.**  Git gets its credential through a
   throwaway ``GIT_ASKPASS`` script (mode 0600, deleted in a ``finally``), so
   nothing lands in ``.git/config`` or a reflog.
3. **Nothing mutates by accident.**  Callers gate every write behind an
   explicit ``--apply``; this module only offers the plumbing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
GITEE_API = "https://gitee.com/api/v5"

#: Where exported repositories, audit reports and publish state live.
PUBLISH_HOME_ENV = "DSH_PUBLISH_HOME"


def publish_home() -> Path:
    """Return the staging root (``$DSH_PUBLISH_HOME`` or ``~/.dsh/publish``)."""
    override = os.environ.get(PUBLISH_HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / ".dsh" / "publish"


# --------------------------------------------------------------------------
# Token resolution — env first, then well-known local env files, then a
# login-shell fallback, because an exported-in-.zshrc token is invisible to a
# non-interactive tool shell.
# --------------------------------------------------------------------------

#: Files that may define ``export NAME=value`` lines. Only plain assignments
#: are read; the file is never sourced, so no side effect can run.
TOKEN_FILES = (
    "~/.config/dsh/publish.env",
    "~/.dsh/publish.env",
    "~/scripts/keys.zsh",
    "~/.env",
)

_TOKEN_ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class TokenError(RuntimeError):
    """Raised when a required token cannot be resolved."""


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _from_file(name: str) -> tuple[str, str] | None:
    for raw in TOKEN_FILES:
        path = Path(raw).expanduser()
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.split("#", 1)[0]
            match = _TOKEN_ASSIGN.match(line)
            if match and match.group(1) == name:
                value = _unquote(match.group(2))
                if value and not value.startswith("$"):
                    return value, str(path)
    return None


def _from_login_shell(name: str) -> tuple[str, str] | None:
    """Ask an interactive zsh/zsh-login shell, which sources rc files."""
    for argv in (["zsh", "-ic", f'printf %s "${name}"'], ["bash", "-lic", f'printf %s "${name}"']):
        if shutil.which(argv[0]) is None:
            continue
        try:
            done = subprocess.run(
                argv, capture_output=True, text=True, timeout=20, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        value = done.stdout.strip()
        # Interactive rc files may print banners; a token has no whitespace.
        if value and " " not in value and "\n" not in value and len(value) >= 8:
            return value, f"{argv[0]} -i"
    return None


def resolve_token(name: str, *, required: bool = True) -> str | None:
    """Resolve ``name`` (``GITHUB_TOKEN`` / ``GITEE_TOKEN``) without echoing it.

    Resolution order: process environment, then :data:`TOKEN_FILES`, then an
    interactive login shell. Call :func:`token_source` first when the origin
    matters for a report.
    """
    value = os.environ.get(name)
    if value:
        return value
    found = _from_file(name)
    if found:
        return found[0]
    found = _from_login_shell(name)
    if found:
        return found[0]
    if required:
        raise TokenError(
            f"{name} is not set. Export it, put 'export {name}=...' in one of "
            f"{', '.join(TOKEN_FILES)}, or rely on an interactive shell that already exports it."
        )
    return None


def token_source(name: str) -> str:
    """Return a human-readable description of where a token came from."""
    if os.environ.get(name):
        return "environment"
    found = _from_file(name)
    if found:
        return f"file {found[1]}"
    found = _from_login_shell(name)
    if found:
        return f"login shell ({found[1]})"
    return "missing"


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


@dataclass
class Redactor:
    """Replace secret values with a stable marker in any text we emit."""

    secrets: tuple[str, ...] = ()

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for secret in self.secrets:
            if secret and len(secret) >= 6:
                text = text.replace(secret, "<REDACTED>")
        # Defence in depth: catch credential-shaped strings we never resolved
        # (a token pasted into a config file, a URL with inline credentials).
        text = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1<REDACTED>@", text)
        text = re.sub(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", "<REDACTED-TOKEN>", text)
        return text


def default_redactor() -> Redactor:
    """A redactor seeded with every token this script family can resolve."""
    secrets: list[str] = []
    for name in ("GITHUB_TOKEN", "GITEE_TOKEN", "GH_TOKEN"):
        value = resolve_token(name, required=False)
        if value:
            secrets.append(value)
    return Redactor(tuple(secrets))


# --------------------------------------------------------------------------
# Subprocess plumbing
# --------------------------------------------------------------------------


class CommandError(RuntimeError):
    """A subprocess exited non-zero; ``stdout``/``stderr`` are pre-redacted."""

    def __init__(self, argv: list[str], code: int, stdout: str, stderr: str) -> None:
        self.argv = argv
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"command failed ({code}): {' '.join(argv)}\n{stderr.strip()}")


def run(
    argv: list[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    redactor: Redactor | None = None,
    redact: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, capture text output, redact it, and optionally raise.

    ``redact=False`` exists for read-only analysis paths that must *see* raw
    bytes — a secret scanner whose own output filter hides the evidence would
    report a false all-clear. Such callers must mask before rendering, and must
    never combine ``redact=False`` with ``check=True`` (a raised
    :class:`CommandError` would carry the raw text).
    """
    if not redact and check:
        raise ValueError("redact=False is only allowed with check=False")
    scrub = (redactor or default_redactor()) if redact else None
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        done = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=merged,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CommandError(argv, 127, "", f"{argv[0]}: not found") from exc
    if scrub is not None:
        done.stdout = scrub(done.stdout)  # type: ignore[assignment]
        done.stderr = scrub(done.stderr)  # type: ignore[assignment]
    if check and done.returncode != 0:
        raise CommandError(argv, done.returncode, done.stdout, done.stderr)  # type: ignore[arg-type]
    return done


def git(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    check: bool = True,
    redact: bool = True,
    **kwargs,
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>``; output is redacted unless ``redact=False``."""
    return run(["git", *args], cwd=cwd, check=check, redact=redact, **kwargs)


def git_identity(cwd: str | Path) -> tuple[str, str]:
    """Return ``(user.name, user.email)`` for a repo, with fallbacks."""
    name = git(["config", "user.name"], cwd=cwd, check=False).stdout.strip()
    email = git(["config", "user.email"], cwd=cwd, check=False).stdout.strip()
    return name or "Your Name", email or "you@example.com"


# --------------------------------------------------------------------------
# Askpass: hand git a credential without persisting it
# --------------------------------------------------------------------------

# The scripts below answer git's credential prompts from the environment. They
# live in a private temp file so the token never appears in ``ps`` output, in
# ``.git/config``, or in shell history.
_ASKPASS_TEMPLATE = """#!/bin/sh
# throwaway GIT_ASKPASS helper written by gitee-to-github-publisher
case "$1" in
  *[Uu]sername*) printf '%s' "$DSH_GIT_USERNAME" ;;
  *) printf '%s' "$DSH_GIT_PASSWORD" ;;
esac
"""


class git_credential:
    """Context manager yielding the environment for a token-authenticated git.

    Usage::

        with git_credential("x-access-token", token) as env:
            git(["push", "origin", "main"], cwd=repo, env=env)
    """

    def __init__(self, username: str, token: str) -> None:
        self.username = username
        self.token = token
        self._path: Path | None = None

    def __enter__(self) -> dict[str, str]:
        handle, raw = tempfile.mkstemp(prefix="dsh-askpass-", suffix=".sh")
        self._path = Path(raw)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(_ASKPASS_TEMPLATE)
        self._path.chmod(stat.S_IRWXU)
        env = {
            "DSH_GIT_USERNAME": self.username,
            "DSH_GIT_PASSWORD": self.token,
            "GIT_ASKPASS": str(self._path),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        return env

    def __exit__(self, *exc_info: object) -> None:
        if self._path is not None:
            self._path.unlink(missing_ok=True)
        return None


def authenticated_remote(host: str, owner: str, repo: str) -> str:
    """Return a credential-free HTTPS remote for ``host`` (github.com/gitee.com)."""
    return f"https://{host}/{owner}/{repo}.git"


# --------------------------------------------------------------------------
# HTTP — urllib only, so an API token never appears in a process argv
# --------------------------------------------------------------------------


class HttpFailure(RuntimeError):
    """An HTTP call failed; the message is redacted."""

    def __init__(self, status: int, message: str, body: object = None) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {message}")


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: object | None = None,
    timeout: int = 45,
    redactor: Redactor | None = None,
    expect: tuple[int, ...] = (200, 201, 204),
    attempts: int = 4,
) -> tuple[int, object]:
    """Perform a JSON request with ``urllib`` and return ``(status, decoded)``.

    Tokens go in headers (GitHub) or the URL (Gitee), never in a subprocess
    argument list. Any error message is redacted before it is raised.

    Transient transport failures are retried with a short backoff. On a
    constrained network — where a mirror/proxy sits in front of the API and TLS
    handshakes are reset at random — a single ``SSLEOFError`` is common enough
    that failing the whole publish on it would be wrong. Retries are safe for
    the calls this skill makes: a replayed blob or commit is an orphan object,
    and a replayed create/release answers 422, which the callers already treat
    as "already exists".
    """
    import ssl
    import urllib.error
    import urllib.request

    scrub = redactor or default_redactor()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    transient = (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, OSError)
    last: Exception | None = None

    for attempt in range(1, max(1, attempts) + 1):
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "gitee-to-github-publisher/1.0")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                status = response.status
            break
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            status = error.code
            # 5xx and throttling are worth another try; a 4xx is an answer.
            if status >= 500 or status == 429:
                last = HttpFailure(status, scrub(f"server error {status}"))
                if attempt < attempts:
                    time.sleep(attempt)
                    continue
            break
        except transient as error:
            # HTTPError is a subclass of URLError in some paths; re-raise only
            # after the loop so a genuine 4xx is never masked by a retry.
            last = error
            if attempt < attempts:
                time.sleep(attempt)
                continue
            reason = getattr(error, "reason", error)
            raise HttpFailure(0, scrub(f"network error after {attempt} attempt(s): {reason}")) from error

    else:  # pragma: no cover - the loop either breaks or raises
        raise HttpFailure(0, scrub(f"network error: {last}"))

    try:
        decoded: object = json.loads(body) if body.strip() else None
    except json.JSONDecodeError:
        decoded = scrub(body)

    if status not in expect:
        message = ""
        if isinstance(decoded, dict):
            message = str(decoded.get("message") or decoded.get("error") or "")
        raise HttpFailure(status, scrub(message or str(decoded)[:300]), decoded)
    return status, decoded


def github_headers(token: str) -> dict[str, str]:
    """Headers for the GitHub REST API v3."""
    return {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def gitee_url(path: str, token: str, **params: object) -> str:
    """Build a Gitee API v5 URL with the token as a query parameter."""
    import urllib.parse

    query = {key: str(value) for key, value in params.items() if value is not None}
    query["access_token"] = token
    return f"{GITEE_API}{path}?{urllib.parse.urlencode(query)}"


# --------------------------------------------------------------------------
# JSON and text I/O
# --------------------------------------------------------------------------


def write_json(path: str | Path, payload: object) -> Path:
    """Write ``payload`` as pretty UTF-8 JSON, creating parent directories."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def read_json(path: str | Path, default: object = None):
    """Read JSON, returning ``default`` when the file is absent or unparsable."""
    target = Path(path)
    if not target.is_file():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


# --------------------------------------------------------------------------
# Console output
# --------------------------------------------------------------------------

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(message: str) -> None:
    """Neutral progress line."""
    print(message, flush=True)


def ok(message: str) -> None:
    """Success line."""
    print(f"{_paint('32', 'OK')}   {message}", flush=True)


def warn(message: str) -> None:
    """Warning line."""
    print(f"{_paint('33', 'WARN')} {message}", flush=True)


def fail(message: str) -> None:
    """Failure line (does not exit)."""
    print(f"{_paint('31', 'FAIL')} {message}", flush=True)


def step(message: str) -> None:
    """Section heading."""
    print(f"\n{_paint('36', '==')} {message}", flush=True)


#: Exit codes shared by every script in this skill.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
#: The repository is not publishable as-is (privacy findings, license conflict).
EXIT_BLOCKED = 3


def die(message: str, code: int = EXIT_ERROR) -> "None":
    """Print a failure and exit with ``code``."""
    fail(message)
    raise SystemExit(code)


def require_tools(*names: str) -> None:
    """Exit unless every named executable is on PATH."""
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        die(f"missing required tool(s): {', '.join(missing)}")


# --------------------------------------------------------------------------
# Small text utilities shared by the audit and README steps
# --------------------------------------------------------------------------

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def cjk_ratio(text: str) -> float:
    """Fraction of non-space characters that are CJK ideographs."""
    stripped = [ch for ch in text if not ch.isspace()]
    if not stripped:
        return 0.0
    return len(_CJK.findall("".join(stripped))) / len(stripped)


def detect_language(text: str) -> str:
    """Classify prose as ``zh``, ``en`` or ``mixed`` by CJK ratio."""
    ratio = cjk_ratio(text)
    if ratio >= 0.15:
        return "zh" if ratio >= 0.35 else "mixed"
    return "en"


def slugify(text: str, *, fallback: str = "item") -> str:
    """Lowercase ASCII slug safe for a filename or a GitHub topic."""
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or fallback