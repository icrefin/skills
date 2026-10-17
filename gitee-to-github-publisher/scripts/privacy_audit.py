#!/usr/bin/env python3
"""Blocking privacy / IP audit for a repository about to become public.

Publishing a private Gitee repository on GitHub is a one-way door: a secret that
reaches a public GitHub object may already be scraped by the time you delete it.
This scanner is therefore deliberately paranoid and deliberately *deterministic*
— the pattern catalog is data, not judgement, so the same tree always yields the
same verdict.

What it scans
-------------
* every git-tracked text file, plus untracked-but-not-ignored files;
* file names (a tracked ``id_rsa`` is a finding even if its content is opaque);
* ``.git/config`` and remote URLs for inline credentials;
* commit author/committer identities across all reachable history;
* every commit identity in history, plus (default ``auto``) the history's
  patches for credential-shaped strings that a later commit deleted — deletion
  does not unpublish. ``auto`` bounds the patch walk to the newest
  :data:`PATCH_SCAN_CAP` commits and reports when it did;``on`` walks all of them;
* the live ``GITHUB_TOKEN``/``GITEE_TOKEN`` values themselves, anywhere.

Verdict
-------
``critical`` or ``high`` findings make the repository **unpublishable as-is**
(exit :data:`EXIT_BLOCKED`). ``medium`` findings are for human review; ``low``
and ``info`` never block.

Usage
-----
    python3 scripts/privacy_audit.py REPO_DIR \
        --report REPO_DIR/../audit/privacy-report.md \
        --json   REPO_DIR/../audit/privacy-report.json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    Redactor,
    default_redactor,
    fail,
    git,
    info,
    ok,
    read_json,
    resolve_token,
    step,
    warn,
    write_json,
)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
BLOCKING = {"critical", "high"}

MAX_FILE_BYTES = 4 * 1024 * 1024

#: How many commits the history *patch* scan walks in ``--history auto``. The
#: identity scan is never capped; this bound only limits the expensive
#: ``git log -p`` walk on a very long history, and the report says when it bit.
PATCH_SCAN_CAP = 2000
SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",
    ".next",
    "site-packages",
}

#: Values that are obviously already placeholders — never a finding.
PLACEHOLDER_HINT = re.compile(
    r"<[^>]*>|\{\{|\$\{|%[sd]|"
    r"your[_ -]?|example|placeholder|changeme|change_me|redacted|"
    r"xxx+|yyy+|zzz+|\*\*\*|\.\.\.|dummy|sample|fake|"
    r"getenv|environ|process\.env|System\.getenv|os\.Getenv|secrets\.|vault|1password|op://|"
    r"\bnull\b|\bnone\b|\bnil\b|\btrue\b|\bfalse\b",
    re.I,
)

#: Documentation / reserved ranges that are safe to publish.
SAFE_IPV4 = re.compile(
    r"^(?:127\.|0\.|255\.255\.255\.255$|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|"
    r"10\.0\.2\.|1\.2\.3\.4$|8\.8\.8\.8$|1\.1\.1\.1$)"
)
SAFE_MAC = re.compile(r"(?i)^(00:00:5e:00:53:|ff:ff:ff:ff:ff:ff$|00:00:00:00:00:00$|de:ad:be:ef)")
SAFE_EMAIL_DOMAIN = re.compile(r"(?i)@(example\.(com|org|net)|.*\.example|localhost|users\.noreply\.github\.com)$")
SAFE_PATH_USER = {"you", "user", "username", "yourname", "example", "runner", "me", "someone"}

#: Non-public IPv4 space — already reported by the dedicated rule, so the
#: generic "public IPv4" rule must not repeat it.
NON_PUBLIC_IPV4 = re.compile(
    r"^(?:10\.|127\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|169\.254\.|0\.|"
    r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)"
)

#: ``# audit:allow <rule-id|all>`` — on the finding's line, or the line above it.
ALLOW_COMMENT = re.compile(r"audit[:-]allow\s+([A-Za-z0-9_*, -]+)")


def suppression_for(line: str, previous: str) -> set[str] | None:
    """Return the suppressed rule ids for a line, or ``None`` for none."""
    for source in (line, previous):
        match = ALLOW_COMMENT.search(source or "")
        if match:
            return {token.strip() for token in match.group(1).replace(",", " ").split()}
    return None


def suppressed_by(allow: set[str] | None, rule_id: str) -> bool:
    """Whether a suppression set covers a rule."""
    if allow is None:
        return False
    return "all" in allow or "*" in allow or rule_id in allow


# --------------------------------------------------------------------------
# Rule model
# --------------------------------------------------------------------------


@dataclass
class Rule:
    """One audit rule: a category, a severity, and how to recognise it."""

    id: str
    severity: str
    category: str
    summary: str
    pattern: str | None = None
    filename_glob: tuple[str, ...] = ()
    placeholder: str = "<REDACTED>"
    remediation: str = ""
    #: Require one of these words on the same line (cuts false positives).
    context: str | None = None

    def compiled(self) -> re.Pattern[str] | None:
        if self.pattern is None:
            return None
        return re.compile(self.pattern)


def _r(*args, **kwargs) -> Rule:
    return Rule(*args, **kwargs)


#: The catalog. Order is presentation order inside a severity band.
RULES: tuple[Rule, ...] = (
    # ---------------- credentials that are unambiguous secrets -------------
    _r("secret-private-key-block", "critical", "credential",
       "PEM/OpenSSH private key material",
       pattern=r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
       placeholder="<YOUR_PRIVATE_KEY>",
       remediation="Remove the key from the working tree and from git history, then rotate it. "
                   "Never publish key material; document how to generate a fresh key instead."),
    _r("secret-github-token", "critical", "credential",
       "GitHub personal access token",
       pattern=r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
       placeholder="<YOUR_GITHUB_TOKEN>",
       remediation="Revoke the token on GitHub, then replace it with an environment variable reference."),
    _r("secret-github-fine-grained", "critical", "credential",
       "GitHub fine-grained token",
       pattern=r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
       placeholder="<YOUR_GITHUB_TOKEN>",
       remediation="Revoke the token on GitHub, then replace it with an environment variable reference."),
    _r("secret-aws-access-key", "critical", "credential",
       "AWS access key id",
       pattern=r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
       placeholder="<YOUR_AWS_ACCESS_KEY_ID>",
       remediation="Deactivate the key in IAM, then reference it from the environment."),
    _r("secret-aws-secret", "critical", "credential",
       "AWS secret access key",
       pattern=r"(?i)aws_?secret_?access_?key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40}",
       placeholder="<YOUR_AWS_SECRET_ACCESS_KEY>",
       remediation="Rotate the keypair immediately."),
    _r("secret-openai-style", "critical", "credential",
       "LLM/SaaS API key (sk- style)",
       pattern=r"\bsk-(?:ant-|proj-|live-)?[A-Za-z0-9_-]{24,}\b",
       placeholder="<YOUR_API_KEY>",
       remediation="Revoke it at the provider and load it from the environment."),
    _r("secret-google-api-key", "critical", "credential",
       "Google API key",
       pattern=r"\bAIza[0-9A-Za-z_-]{35}\b",
       placeholder="<YOUR_GOOGLE_API_KEY>",
       remediation="Restrict or delete the key in Google Cloud Console."),
    _r("secret-slack-token", "critical", "credential",
       "Slack token",
       pattern=r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b",
       placeholder="<YOUR_SLACK_TOKEN>",
       remediation="Revoke the app token."),
    _r("secret-jwt", "critical", "credential",
       "JSON Web Token",
       pattern=r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
       placeholder="<YOUR_JWT>",
       remediation="Tokens are usually short-lived, but a long-lived one must be revoked."),
    _r("secret-credential-in-url", "critical", "credential",
       "Credentials embedded in a URL",
       pattern=r"https?://[^/\s:@\"']+:[^/\s@\"']+@",
       placeholder="https://user:<YOUR_PASSWORD>@host/",
       remediation="Strip the credential; use a token from the environment and an askpass helper."),
    _r("secret-live-token", "critical", "credential",
       "The live GITHUB_TOKEN/GITEE_TOKEN value appears in the tree",
       pattern=None,  # injected at runtime from the resolved tokens
       placeholder="<YOUR_TOKEN>",
       remediation="Remove it, rotate the token, and rebuild history if it was ever committed."),
    _r("secret-flexlm-license", "critical", "legal",
       "FlexLM / EDA license string (INCREMENT, SERVER hostid, LM_LICENSE_FILE)",
       pattern=r"(?im)^\s*(?:INCREMENT|FEATURE)\s+\S+\s+\S+\s+\d+(?:\.\d+)?\s+\S+.*$"
               r"|^\s*SERVER\s+\S+\s+[0-9a-fA-F]{12}\s+\d+\s*$"
               r"|\b(?:LM|SNPSLMD|CDS_LIC|MGLS|SALT|VCS|VERDI)_LICENSE_FILE\s*[=:]\s*\S*"
               r"|\bHOSTID\s*[=:]\s*\S*",
       placeholder="<YOUR_LICENSE_SERVER>",
       remediation="Vendor license files and license-server identifiers must never be published; "
                   "they are licensed to a specific party and reveal internal infrastructure."),
    _r("secret-eda-license-artifact", "high", "legal",
       "EDA license-manager artifact (lmutil/lmgrd/snpslmd/ck=)",
       pattern=r"(?i)\b(?:lmutil|lmgrd|snpslmd|cdslmd|mgcld|saltd|elmd)\b|\bcksum\s*=\s*[A-Za-z0-9]+|\bck\s*=\s*[0-9a-f]{8,}",
       placeholder="<YOUR_LICENSE_COMMAND>",
       remediation="Replace with a neutral description; do not ship the invocation or its output."),
    _r("secret-generic-assignment", "high", "credential",
       "Hard-coded secret in an assignment",
       pattern=r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
               r"private[_-]?key|client[_-]?secret|auth[_-]?token|bearer)\b\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']",
       placeholder="<YOUR_API_KEY> / <YOUR_PASSWORD>",
       remediation="Read the value from the environment (or a secret manager) and provide a "
                   "committed `.env.example` with placeholders."),
    _r("secret-hex-with-context", "high", "credential",
       "Long hex blob next to a key/token/license/hostid word",
       pattern=r"(?i)(?:key|token|secret|license|licence|hostid|serial|sn)\b[^\n]{0,40}\b[0-9a-fA-F]{16,64}\b",
       placeholder="<YOUR_KEY>",
       remediation="Confirm the value and parameterise it if it is a real credential."),
    _r("secret-gitee-token-inline", "high", "credential",
       "Gitee access token in an inline query string",
       pattern=r"(?i)[?&]access_token=[0-9a-fA-F]{20,}",
       placeholder="<YOUR_GITEE_TOKEN>",
       remediation="Revoke the token; read it from the environment."),

    # ---------------- personal / organisational information ----------------
    _r("pii-home-path", "high", "identity",
       "Absolute path exposing a user or machine name",
       pattern=r"(?:/Users/|/home/|(?:[A-Za-z]:\\Users\\))([A-Za-z0-9._-]+)",
       placeholder="/home/you/  ·  /Users/you/  ·  C:\\Users\\you\\",
       remediation="Rewrite absolute paths as `~`, `$HOME`, a relative path, or a documented "
                   "`<YOUR_WORKSPACE>` placeholder."),
    _r("net-private-ipv4", "high", "network",
       "Private / link-local / CGNAT IPv4 address",
       pattern=r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|"
               r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|169\.254\.\d{1,3}\.\d{1,3}|"
               r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b",
       placeholder="192.0.2.10  (RFC 5737 documentation range)",
       remediation="Replace with a documentation address or a hostname placeholder."),
    _r("net-private-ipv6", "high", "network",
       "Unique-local / link-local IPv6 address",
       pattern=r"\b(?:f[cd][0-9a-f]{2}:|fe80:)[0-9a-f:]+\b",
       placeholder="2001:db8::1  (RFC 3849 documentation range)",
       remediation="Replace with the documentation prefix."),
    _r("net-internal-host", "high", "network",
       "Internal hostname or private TLD",
       # `.test` / `.invalid` / `.example` / `.localhost` are deliberately NOT in
       # this list: RFC 2606/6761 reserve them for documentation and testing, so
       # they are the placeholder forms this skill recommends. Flagging them made
       # the rule fire on ordinary code — `i.test(url)`, `api.test()` — while
       # catching nothing real.
       pattern=r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:local|internal|intranet|lan|corp|home|"
               r"localdomain|localnet|home\.arpa)\b",
       placeholder="host.example.com",
       remediation="Replace with a placeholder hostname; keep real infrastructure out of public docs."),
    _r("net-unc-path", "high", "network",
       "Windows UNC / network share path",
       pattern=r"\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9._$-]+",
       placeholder="\\\\server\\share",
       remediation="Replace with a local relative path."),
    _r("net-mac-address", "medium", "network",
       "MAC address (often a hardware lock identifier)",
       pattern=r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b|\b(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}\b",
       placeholder="00:00:5E:00:53:00  (RFC 7042 documentation MAC)",
       remediation="Hardware identifiers are personal data in some jurisdictions and are used as "
                   "license locks — replace them."),
    _r("pii-chinese-id", "high", "identity",
       "Chinese resident ID number (checksum-valid)",
       pattern=None,  # validated by code, not a bare regex
       placeholder="<YOUR_ID_NUMBER>",
       remediation="Never publish identity documents or their numbers."),
    _r("pii-chinese-phone", "medium", "identity",
       "Chinese mobile number",
       pattern=r"(?<!\d)1[3-9]\d{9}(?!\d)",
       placeholder="+86 138 0000 0000",
       remediation="Confirm whether this is a real number; use a placeholder if it is."),
    _r("pii-intl-phone", "medium", "identity",
       "International phone number",
       pattern=r"(?<![\d-])\+\d{1,3}[\s-]?(?:\(?\d{1,4}\)?[\s-]?){2,4}\d{2,4}(?![\d-])",
       placeholder="+1 555 010 0000",
       remediation="Confirm whether this is a real number; use a placeholder if it is."),
    _r("pii-email", "medium", "identity",
       "Email address",
       pattern=r"\b[A-Za-z][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b",
       placeholder="you@example.com",
       remediation="Decide per occurrence: attribution in LICENSE/AUTHORS is intentional, an email "
                   "in a script or an issue template is usually a leak."),
    _r("pii-company-marker", "medium", "identity",
       "Confidentiality marker",
       pattern=r"(?i)\b(?:confidential|proprietary and confidential|internal use only|do not distribute|"
               r"company confidential|trade secret)\b|版权所有|内部资料|内部使用|机密|严禁外传|仅供内部",
       placeholder="(remove the marker)",
       remediation="Remove the marker and the material it protects; check whether the surrounding "
                   "content is publishable at all."),
    _r("pii-copyright-holder", "info", "identity",
       "Copyright holder named in a source file or LICENSE",
       pattern=r"(?i)copyright\s*(?:\(c\)|©)?\s*\d{4}(?:\s*-\s*\d{4})?\s+([A-Z][^\n,;]{2,60})",
       placeholder="Copyright (c) 2026 Your Name",
       remediation="Confirm the holder is the one you intend to publish under, and that an "
                   "employer's name appears only where you are allowed to use it."),
    _r("net-public-ipv4", "medium", "network",
       "Public IPv4 address",
       pattern=r"\b(?:[1-9]\d{0,2})\.(?:\d{1,3})\.(?:\d{1,3})\.(?:\d{1,3})\b",
       placeholder="203.0.113.10  (RFC 5737 documentation range)",
       remediation="A public address may be your own server or a customer's; replace it with a "
                   "documentation address unless it is an intentional, public endpoint."),
    _r("net-ssh-target", "medium", "network",
       "Concrete SSH target",
       pattern=r"\bssh\s+(?:-[A-Za-z]+\s+)*[a-z0-9._-]+@(?!example\.|github\.com|gitee\.com|gitlab\.com)[a-z0-9.-]+",
       placeholder="ssh user@host.example.com",
       remediation="Replace the host and user."),
    _r("pii-absolute-volume-path", "low", "identity",
       "Machine-specific mount or drive path",
       pattern=r"(?m)(?:^|[\s\"'(])(?:/mnt/[A-Za-z0-9._-]+|/data/[A-Za-z0-9._-]+|[D-Z]:\\\\)",
       placeholder="/path/to/data",
       remediation="Replace with a documented relative or configurable path."),

    # ---------------- file / repository hygiene ---------------------------
    _r("file-private-key", "critical", "file",
       "Private key or keystore file",
       filename_glob=("id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.pem", "*.key", "*.p12",
                      "*.pfx", "*.jks", "*.keystore", "*.ppk", "*.asc", "*.gpg"),
       placeholder="<YOUR_PRIVATE_KEY_FILE>",
       remediation="Delete the file (and its history) and rotate the credential."),
    _r("file-env", "high", "file",
       "Real environment / dotenv file",
       filename_glob=(".env", ".env.*", "*.env", "env.local", ".envrc"),
       placeholder=".env.example",
       remediation="Keep only a committed `.env.example` with placeholders."),
    _r("file-secret-store", "high", "file",
       "Secret store or credential dump",
       filename_glob=("*secret*", "*credential*", "*token*", "*password*", "*.kdbx", "*_rsa",
                      "known_hosts", "*.netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials"),
       placeholder="<YOUR_SECRETS>",
       remediation="Move the file out of the repository; reference the values from the environment."),
    _r("file-eda-license", "critical", "legal",
       "Vendor license file",
       filename_glob=("*.lic", "*.flexlm", "license.dat", "licfile*", "*_license.dat", "*.v2c",
                      "lmutil*", "lmgrd*", "snpslmd*", "cdslmd*", "*.scl"),
       placeholder="<YOUR_LICENSE_FILE>",
       remediation="Vendor licenses are non-redistributable; remove the file from tree and history."),
    _r("file-archive-or-binary", "low", "file",
       "Archive or compiled artifact committed to the tree",
       filename_glob=("*.zip", "*.tar.gz", "*.tgz", "*.7z", "*.rar", "*.exe", "*.dll", "*.so",
                      "*.dylib", "*.jar", "*.whl", "*.bin", "*.img", "*.iso"),
       placeholder="<YOUR_ARTIFACT>",
       remediation="Ship sources and a build script; use a release asset for binaries. A committed "
                   "binary can hide credentials that a text scan cannot see."),
)


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def _validate_catalog() -> None:
    """Fail loudly at import time if a rule pattern is malformed.

    A silently skipped rule is worse than a crash: the audit would report
    "clear" for a repository it never actually checked.
    """
    for rule in RULES:
        if rule.pattern is None:
            if rule.filename_glob or rule.id in {"secret-live-token", "pii-chinese-id"}:
                continue  # handled by a file-name match or by dedicated code
            raise RuntimeError(f"rule {rule.id} has neither a pattern nor a file-name glob")
        rule.compiled()  # raises re.error on a malformed pattern
        if rule.severity not in SEVERITY_ORDER:
            raise RuntimeError(f"rule {rule.id} has unknown severity {rule.severity!r}")


_validate_catalog()


@dataclass
class Finding:
    """One located problem."""

    rule: str
    severity: str
    category: str
    summary: str
    path: str
    line: int = 0
    snippet: str = ""
    placeholder: str = ""
    remediation: str = ""
    note: str = ""

    def sort_key(self) -> tuple:
        return (SEVERITY_ORDER.get(self.severity, 9), self.path, self.line, self.rule)


@dataclass
class ScanStats:
    """Bookkeeping so the report can prove what was actually covered."""

    files_scanned: int = 0
    files_skipped: int = 0
    bytes_scanned: int = 0
    history_commits: int = 0
    history_mode: str = "off"
    skipped_paths: list[str] = field(default_factory=list)


def mask(value: str, *, keep: int = 4) -> str:
    """Return a partially masked rendering of a matched secret."""
    value = value.strip()
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * min(len(value) - keep, 24)} (len {len(value)})"


def is_placeholder(value: str) -> bool:
    """Whether a matched value is already a placeholder or an env lookup."""
    text = value.strip().strip("\"'")
    if not text:
        return True
    if len(text) < 6:
        return True
    return bool(PLACEHOLDER_HINT.search(text))


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class AuditConfig:
    """Tunables, merged from ``publish-audit.json`` and the CLI."""

    extra_names: list[str] = field(default_factory=list)
    allow_emails: list[str] = field(default_factory=list)
    allow_paths: list[list[str]] = field(default_factory=list)  # [rule, glob, reason]
    exclude: list[str] = field(default_factory=list)
    severity_override: dict[str, str] = field(default_factory=dict)

    def allowed(self, rule: str, path: str) -> bool:
        for entry in self.allow_paths:
            if len(entry) >= 2 and entry[0] in (rule, "*") and fnmatch.fnmatch(path, entry[1]):
                return True
        return False

    def excluded(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.exclude)

    def severity_of(self, rule: Rule) -> str:
        return self.severity_override.get(rule.id, rule.severity)


def load_config(path: str | None) -> AuditConfig:
    """Load an optional ``publish-audit.json`` — or a whole ``publish-plan.json``.

    Both shapes work: a bare audit document, or a publish plan whose audit block
    sits under ``"audit"``. The nested block wins over the top level, so a plan
    can carry its own overrides.
    """
    config = AuditConfig()
    if not path:
        return config
    document = read_json(path)
    if not isinstance(document, dict):
        warn(f"ignoring unreadable audit config: {path}")
        return config
    if isinstance(document.get("audit"), dict):
        document = {**document, **document["audit"]}
    config.extra_names = [str(item) for item in document.get("names", [])]
    config.allow_emails = [str(item).lower() for item in document.get("allow_emails", [])]
    config.allow_paths = [list(item) for item in document.get("allow", [])]
    config.exclude = [str(item) for item in document.get("exclude", [])]
    config.severity_override = {str(k): str(v) for k, v in document.get("severity_overrides", {}).items()}
    return config


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------


def tracked_files(repo: Path, *, include_untracked: bool = True) -> tuple[list[str], list[str]]:
    """Return ``(tracked, untracked_not_ignored)`` paths relative to ``repo``."""
    tracked = git(["ls-files", "-z"], cwd=repo, check=False).stdout.split("\0")
    tracked = [name for name in tracked if name]
    others: list[str] = []
    if include_untracked:
        raw = git(["ls-files", "-z", "--others", "--exclude-standard"], cwd=repo, check=False).stdout
        others = [name for name in raw.split("\0") if name]
    return tracked, others


def iter_text(path: Path) -> str | None:
    """Return the file's text, or ``None`` when it is binary or too large."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _zh_id_valid(candidate: str) -> bool:
    """Validate a Chinese ID number with the ISO 7064 MOD 11-2 checksum."""
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    checks = "10X98765432"
    if len(candidate) != 18:
        return False
    try:
        total = sum(int(candidate[i]) * weights[i] for i in range(17))
    except ValueError:
        return False
    return checks[total % 11] == candidate[17].upper()


def scan_content(
    repo: Path,
    relpath: str,
    config: AuditConfig,
    *,
    extra_rules: tuple[Rule, ...] = (),
    origin: str = "worktree",
) -> list[Finding]:
    """Scan one file's text and name; return its findings."""
    findings: list[Finding] = []
    base = Path(relpath).name

    for rule in (*RULES, *extra_rules):
        if rule.filename_glob and any(fnmatch.fnmatch(base, glob) for glob in rule.filename_glob):
            if config.allowed(rule.id, relpath):
                continue
            # `.env.example` and friends are the recommended replacement.
            if rule.id == "file-env" and re.search(r"(?i)(example|sample|template|dist)", base):
                continue
            findings.append(
                Finding(
                    rule=rule.id,
                    severity=config.severity_of(rule),
                    category=rule.category,
                    summary=rule.summary,
                    path=relpath,
                    snippet=mask(base, keep=2),
                    placeholder=rule.placeholder,
                    remediation=rule.remediation,
                    note=f"{origin}: file name matches `{rule.filename_glob[0]}`",
                )
            )

    text = iter_text(repo / relpath)
    if text is None:
        return findings

    lines = text.splitlines()
    for rule in (*RULES, *extra_rules):
        if rule.id in {"file-private-key", "file-env", "file-secret-store", "file-eda-license",
                       "file-archive-or-binary"}:
            continue
        if config.allowed(rule.id, relpath):
            continue
        context = re.compile(rule.context, re.I) if rule.context else None

        if rule.id == "pii-chinese-id":
            for number in range(len(lines)):
                for match in re.finditer(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}\d{4}\d{3}[\dXx](?!\d)", lines[number]):
                    if not _zh_id_valid(match.group(0)):
                        continue
                    findings.append(
                        Finding(rule.id, config.severity_of(rule), rule.category, rule.summary,
                                relpath, number + 1, mask(match.group(0)), rule.placeholder, rule.remediation)
                    )
            continue

        pattern = rule.compiled()
        if pattern is None:
            continue
        for number, line in enumerate(lines, start=1):
            previous = lines[number - 2] if number >= 2 else ""
            if suppressed_by(suppression_for(line, previous), rule.id):
                continue
            # A FlexLM match already proves the line is vendor license material;
            # a second rule for the same line is noise, not signal.
            if rule.id == "secret-eda-license-artifact" and any(
                other.rule == "secret-flexlm-license" and other.line == number for other in findings
            ):
                continue
            for match in pattern.finditer(line):
                captured = match.group(1) if match.groups() else match.group(0)
                if is_placeholder(captured):
                    continue
                if rule.id == "pii-email" and SAFE_EMAIL_DOMAIN.search(captured):
                    continue
                if rule.id == "pii-email" and captured.lower() in config.allow_emails:
                    continue
                if rule.id == "net-public-ipv4":
                    if SAFE_IPV4.match(captured) or NON_PUBLIC_IPV4.match(captured):
                        continue
                    if re.search(r"(?i)\b(?:version|v|release|build|sha|rev)\s*$", line[: match.start()]):
                        continue
                if rule.id == "net-mac-address" and SAFE_MAC.match(captured):
                    continue
                if rule.id == "pii-home-path" and captured.lower() in SAFE_PATH_USER:
                    continue
                if rule.id == "net-internal-host" and captured.lower().endswith(".example"):
                    continue
                if context and not context.search(line):
                    continue
                findings.append(
                    Finding(
                        rule=rule.id,
                        severity=config.severity_of(rule),
                        category=rule.category,
                        summary=rule.summary,
                        path=relpath,
                        line=number,
                        snippet=mask(captured),
                        placeholder=rule.placeholder,
                        remediation=rule.remediation,
                    )
                )
                break  # one finding per rule per line keeps the report readable
    return findings


def scan_extras(repo: Path, config: AuditConfig, redactor: Redactor) -> list[Finding]:
    """Checks that are not line-pattern checks: live tokens, names, git config."""
    findings: list[Finding] = []
    tracked, others = tracked_files(repo)

    # 1. The live tokens themselves.
    live = [value for value in (
        resolve_token("GITHUB_TOKEN", required=False),
        resolve_token("GITEE_TOKEN", required=False),
    ) if value]
    if live:
        for relpath in [*tracked, *others]:
            text = iter_text(repo / relpath)
            if text is None:
                continue
            for value in live:
                if value and value in text:
                    findings.append(
                        Finding(
                            "secret-live-token", "critical", "credential",
                            "Live API token committed in the tree", relpath, 0,
                            mask(value),
                            "<YOUR_TOKEN>",
                            "Remove it, rotate the token, and rewrite history if it was committed.",
                        )
                    )

    # 2. Inline credentials in git config / submodule URLs.
    for relpath in (".git/config", ".gitmodules"):
        candidate = repo / relpath
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        if re.search(r"https?://[^/\s:@]+:[^/\s@]+@", text):
            findings.append(
                Finding(
                    "secret-credential-in-url", "critical", "credential",
                    "Credential embedded in a git remote URL", relpath, 0,
                    redactor(re.search(r"https?://[^/\s:@]+:[^/\s@]+@", text).group(0)),  # type: ignore[union-attr]
                    "https://user:<YOUR_TOKEN>@host/",
                    "Rewrite the remote without credentials and use an askpass helper.",
                )
            )

    # 3. Operator-supplied personal / company names.
    for name in config.extra_names:
        if len(name.strip()) < 3:
            continue
        pattern = re.compile(re.escape(name.strip()), re.I)
        for relpath in [*tracked, *others]:
            text = iter_text(repo / relpath)
            if text is None:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line) and "audit:allow" not in line:
                    findings.append(
                        Finding(
                            "pii-named-entity", "high", "identity",
                            "Operator-supplied name or company appears in the tree",
                            relpath, number, mask(name, keep=2),
                            "<YOUR_ORGANISATION> / Your Name",
                            "Replace with a generic name unless the mention is intentional attribution.",
                        )
                    )
                    break
    return findings


def scan_history(repo: Path, config: AuditConfig, mode: str, redactor: Redactor) -> tuple[list[Finding], int, str]:
    """Scan reachable history for credential-shaped content and identities."""
    findings: list[Finding] = []
    if mode == "off" or not (repo / ".git").exists():
        return findings, 0, "off"

    commits = git(["rev-list", "--all", "--count"], cwd=repo, check=False).stdout.strip()
    count = int(commits) if commits.isdigit() else 0

    # Identities: a personal or employer email in every commit is a real leak
    # that no working-tree edit can remove.
    # NOTE: `redact=False` — this analysis must see the raw patch text; the
    # redactor would otherwise hide exactly the token shapes we hunt for.
    # Every finding below is masked via mask() before it is rendered.
    identity = git(["log", "--all", "--format=%an <%ae>|%cn <%ce>"], cwd=repo, check=False,
                   redact=False).stdout
    seen: dict[str, int] = {}
    for line in identity.splitlines():
        for entry in line.split("|"):
            entry = entry.strip()
            if entry:
                seen[entry] = seen.get(entry, 0) + 1
    for entry, occurrences in sorted(seen.items(), key=lambda item: -item[1]):
        match = re.search(r"<([^>]+)>", entry)
        if not match:
            continue
        address = match.group(1)
        if SAFE_EMAIL_DOMAIN.search("@" + address.split("@")[-1]) or address.endswith("noreply.github.com"):
            continue
        if address.lower() in config.allow_emails:
            continue
        if address.endswith("users.noreply.github.com") or "noreply" in address:
            continue
        findings.append(
            Finding(
                "history-commit-identity", "medium", "identity",
                "Commit identity appears across history",
                ".git (history)", 0, f"{entry} × {occurrences}",
                "Your Name <you@example.com>",
                "History preserves every author email. If you do not want it public, publish a "
                "squashed/clean-room history or rewrite identities with git-filter-repo.",
            )
        )

    # Patches: catch secrets that were committed and later deleted.
    high_patterns = [rule for rule in RULES if rule.severity == "critical" and rule.compiled()]
    # The patch scan is expensive, so `auto` bounds it on a large history and
    # says so; `on` walks every commit. The identity scan above is deliberately
    # never capped — an author email from the first commit is exactly the leak a
    # bounded scan would miss.
    cap = 0 if mode == "on" else (PATCH_SCAN_CAP if count > PATCH_SCAN_CAP else 0)
    args = ["log", "--all", "-p", "--no-color", "--format=%H %h %s", "-U0"]
    if cap:
        args.insert(2, f"-n{cap}")
    done = git(args, cwd=repo, check=False, redact=False)
    current = ""
    hits: dict[str, set[str]] = {}
    for line in done.stdout.splitlines():
        if re.fullmatch(r"[0-9a-f]{40} [0-9a-f]{7,} .*", line):
            current = line.split()[1]
            continue
        for rule in high_patterns:
            pattern = rule.compiled()
            if pattern is None:
                continue
            if pattern.search(line):
                hits.setdefault(rule.id, set()).add(current)
    for rule_id, shas in hits.items():
        rule = next(item for item in RULES if item.id == rule_id)
        findings.append(
            Finding(
                rule_id, "high", rule.category,
                f"{rule.summary} — present in history patches",
                ".git (history)", 0,
                f"{len(shas)} commit(s): {', '.join(sorted(shas)[:5])}",
                rule.placeholder,
                "A deleted file is still published by history. Publish a clean-room (squashed) "
                "history, or rewrite with git-filter-repo plus a mandatory credential rotation.",
            )
        )
    if cap:
        label = f"auto (newest {cap} of {count} commits)"
    elif mode == "on":
        label = f"on (all {count} commits)"
    else:
        label = f"auto (all {count} commits)"
    return findings, count, label


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

PLACEHOLDER_TABLE = (
    ("API key / token", "<YOUR_API_KEY>, <YOUR_TOKEN>, <YOUR_GITHUB_TOKEN>"),
    ("Password", "<YOUR_PASSWORD>"),
    ("Private key", "<YOUR_PRIVATE_KEY> (and rotate the real one)"),
    ("Email", "you@example.com"),
    ("Personal / company name", "Your Name, Example Corp, 示例公司"),
    ("Private IPv4", "192.0.2.10 (RFC 5737)"),
    ("Public IP / server", "203.0.113.10 or your-server.example.com"),
    ("IPv6", "2001:db8::1 (RFC 3849)"),
    ("Hostname", "host.example.com"),
    ("MAC address", "00:00:5E:00:53:00 (RFC 7042)"),
    ("Home directory", "~  ·  /home/you/  ·  <YOUR_WORKSPACE>"),
    ("Phone", "+1 555 010 0000  ·  +86 138 0000 0000"),
    ("National ID", "<YOUR_ID_NUMBER>"),
    ("License server / EDA license", "<YOUR_LICENSE_SERVER>"),
    ("Serial / hostid", "<YOUR_SERIAL>"),
)


def render_report(
    repo: Path,
    findings: list[Finding],
    stats: ScanStats,
    config: AuditConfig,
    *,
    redactor: Redactor,
) -> str:
    """Render the Markdown audit report."""
    ordered = sorted(findings, key=Finding.sort_key)
    counts: dict[str, int] = {}
    for finding in ordered:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    blocking = [f for f in ordered if f.severity in BLOCKING]

    out: list[str] = []
    out.append(f"# Privacy & IP audit — {repo.name}\n")
    out.append("> **Do not commit this file.** It enumerates the sensitive values it found so you "
               "can fix them; keep it in the staging directory (outside the repository) or in a "
               "git-ignored `audit/` folder.\n")
    out.append(f"Verdict: **{'BLOCKED' if blocking else 'CLEAR TO PROCEED'}**")
    out.append("")
    out.append("| severity | findings |")
    out.append("| --- | --- |")
    for severity in ("critical", "high", "medium", "low", "info"):
        out.append(f"| {severity} | {counts.get(severity, 0)} |")
    out.append("")
    out.append(
        f"Coverage: {stats.files_scanned} text file(s), {stats.bytes_scanned / 1024:.0f} KiB scanned; "
        f"{stats.files_skipped} skipped (binary or >4 MiB); history mode "
        f"**{stats.history_mode}**."
    )
    out.append("")

    if not ordered:
        out.append("No findings. Re-run after every content change — the audit is only valid for "
                   "the exact tree it scanned.\n")
        return "\n".join(out)

    out.append("## Findings\n")
    for severity in ("critical", "high", "medium", "low", "info"):
        group = [f for f in ordered if f.severity == severity]
        if not group:
            continue
        out.append(f"### {severity.upper()} ({len(group)})\n")
        out.append("| rule | location | matched (masked) | fix |")
        out.append("| --- | --- | --- | --- |")
        for finding in group:
            location = finding.path + (f":{finding.line}" if finding.line else "")
            fix = (finding.placeholder or "").replace("|", "\\|")
            out.append(f"| `{finding.rule}` | `{location}` | `{finding.snippet}` | {fix} |")
        out.append("")
        for finding in group:
            if finding.remediation:
                out.append(f"- **{finding.rule}** — {finding.remediation}")
                if finding.note:
                    out.append(f"  - {finding.note}")
        out.append("")

    out.append("## Placeholder conventions\n")
    out.append("| what | use this instead |")
    out.append("| --- | --- |")
    for label, value in PLACEHOLDER_TABLE:
        out.append(f"| {label} | `{value}` |")
    out.append("")

    out.append("## Remediation order (do not skip the rewrite step)\n")
    out.append("1. **Rotate first.** A leaked credential is compromised the moment it is public. "
               "Revoke/rotate it before deciding how to remove it.")
    out.append("2. **Fix the working tree.** Delete files that must not ship (vendor licenses, keys, "
               "`.env`) and replace values with the placeholders above.")
    out.append("3. **Check history.** If a finding names a commit in the history section, a clean "
               "working tree is not enough: publish a squashed (clean-room) history, or rewrite with "
               "`git filter-repo --replace-text` and force-push to Gitee too.")
    out.append("4. **Tell the reader.** Add the placeholder notice to the README so a user knows "
               "which values are theirs to fill in (see `assets/community/PLACEHOLDER-NOTICE.md`).")
    out.append("5. **Re-run this audit on the tree you are about to push**, and then again on the "
               "published repository.")
    out.append("")

    if any(f.category == "legal" for f in ordered):
        out.append("## Legal findings need a human decision\n")
        out.append("Vendor license material (FlexLM/EDA) and vendor binaries are not yours to "
                   "publish, even when they sit in your own repository. Remove them and describe "
                   "the workflow instead of shipping the artifact. See "
                   "`references/license-compliance.md`.\n")

    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="privacy_audit.py",
        description="Blocking privacy/IP audit before publishing a repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 clear to proceed (or only review items), 1 error, 3 blocked.",
    )
    parser.add_argument("repo", help="repository working tree to scan")
    parser.add_argument("--config", help="JSON config: names, allow_emails, allow, exclude, severity_overrides")
    parser.add_argument("--names", action="append", default=[],
                        help="personal or company name to treat as a leak (repeatable)")
    parser.add_argument("--exclude", action="append", default=[],
                        help="path glob to skip entirely (repeatable)")
    parser.add_argument("--history", choices=("auto", "on", "off"), default="auto",
                        help="history scanning: 'auto' (default) always checks identities and scans "
                         "patches for the newest 2000 commits; 'on' scans every commit's "
                         "patches; 'off' skips history entirely")
    parser.add_argument("--report", help="write a Markdown report here")
    parser.add_argument("--json", dest="json_path", help="write machine-readable findings here")
    parser.add_argument("--quiet", action="store_true", help="only print the verdict line")
    parser.add_argument("--max-per-rule", type=int, default=50,
                        help="cap findings per rule in the console summary (report is uncapped)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        fail(f"not a directory: {repo}")
        return EXIT_USAGE

    config = load_config(args.config)
    config.extra_names.extend(args.names)
    config.exclude.extend(args.exclude)
    redactor = default_redactor()

    step(f"Privacy audit — {repo}")
    tracked, others = tracked_files(repo)
    candidates = [*tracked, *others]
    if not candidates:
        warn("no git-tracked files found; scanning the filesystem instead")
        candidates = [
            str(path.relative_to(repo))
            for path in sorted(repo.rglob("*"))
            if path.is_file() and not any(part in SKIP_DIRS for part in path.parts)
        ]

    stats = ScanStats()
    findings: list[Finding] = []
    for relpath in candidates:
        if any(part in SKIP_DIRS for part in Path(relpath).parts):
            stats.files_skipped += 1
            stats.skipped_paths.append(relpath)
            continue
        if config.excluded(relpath):
            stats.files_skipped += 1
            stats.skipped_paths.append(relpath)
            continue
        path = repo / relpath
        text = iter_text(path)
        if text is None:
            stats.files_skipped += 1
            stats.skipped_paths.append(relpath)
            # A binary with a sensitive name is still a finding.
            findings.extend(scan_content(repo, relpath, config, origin="name-only"))
            continue
        stats.files_scanned += 1
        stats.bytes_scanned += len(text.encode("utf-8", errors="replace"))
        findings.extend(scan_content(repo, relpath, config))

    findings.extend(scan_extras(repo, config, redactor))

    history_findings, commits, mode_used = scan_history(repo, config, args.history, redactor)
    findings.extend(history_findings)
    stats.history_commits = commits
    stats.history_mode = mode_used

    # One finding per (rule, path, line) — history patches can duplicate.
    unique: dict[tuple, Finding] = {}
    for finding in findings:
        unique.setdefault((finding.rule, finding.path, finding.line, finding.snippet), finding)
    findings = list(unique.values())

    report = render_report(repo, findings, stats, config, redactor=redactor)
    if args.report:
        target = Path(args.report).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
        info(f"report: {target}")
    if args.json_path:
        payload = {
            "repo": str(repo),
            "verdict": "blocked" if any(f.severity in BLOCKING for f in findings) else "clear",
            "coverage": {
                "files_scanned": stats.files_scanned,
                "files_skipped": stats.files_skipped,
                "bytes_scanned": stats.bytes_scanned,
                "history_mode": stats.history_mode,
                "history_commits": stats.history_commits,
            },
            "counts": {severity: sum(1 for f in findings if f.severity == severity)
                       for severity in ("critical", "high", "medium", "low", "info")},
            "findings": [f.__dict__ for f in sorted(findings, key=Finding.sort_key)],
        }
        write_json(args.json_path, payload)

    blocking = [f for f in findings if f.severity in BLOCKING]
    review = [f for f in findings if f.severity not in BLOCKING]

    if not args.quiet:
        for severity in ("critical", "high", "medium"):
            group = [f for f in findings if f.severity == severity]
            for finding in group[: args.max_per_rule]:
                location = finding.path + (f":{finding.line}" if finding.line else "")
                print(f"  [{severity:<8}] {finding.rule:<28} {location}  {finding.snippet}")
            if len(group) > args.max_per_rule:
                info(f"  … {len(group) - args.max_per_rule} more {severity} finding(s) in the report")

    info(f"scanned {stats.files_scanned} file(s); history={stats.history_mode}")
    if blocking:
        fail(f"{len(blocking)} blocking finding(s) — the repository is NOT publishable as-is")
        return EXIT_BLOCKED
    if review:
        warn(f"{len(review)} review item(s) — decide each one, then re-run")
    else:
        ok("no privacy findings")
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(EXIT_ERROR)