#!/usr/bin/env python3
"""Publish a staging directory to GitHub: create, configure, push, release, verify.

Design rules this script enforces:

* **Dry-run by default.** Every mutating subcommand prints the exact API call it
  would make and does nothing until ``--apply`` is given.
* **No token on disk or on a command line.** API calls go through ``urllib``;
  ``git push`` gets a throwaway ``GIT_ASKPASS`` helper. Nothing is written into
  ``.git/config``.
* **Verification is a separate step.** ``verify`` compares the *published*
  repository with the staging tree and re-runs the privacy audit on a fresh
  clone, because "I pushed it" is not evidence that the public artifact is clean.

Subcommands
-----------
``whoami``     token identity, scopes and remaining rate limit
``create``     create the repository (no-op if it already exists)
``configure``  description, homepage, topics, features, vulnerability alerts
``push``       set the remote and push the branch and tags
``release``    create a release with notes from a file or generated
``verify``     compare remote vs local, re-audit the published clone
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
    EXIT_BLOCKED,
    GITHUB_API,
    HttpFailure,
    default_redactor,
    fail,
    git,
    git_credential,
    git_identity,
    github_headers,
    http_json,
    info,
    ok,
    publish_home,
    resolve_token,
    step,
    token_source,
    warn,
    write_json,
)

GITHUB_ASKPASS_USER = "x-access-token"


class GitHub:
    """A thin, redacting GitHub REST client."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.headers = github_headers(token)
        self.redactor = default_redactor()

    def call(self, path: str, *, method: str = "GET", payload: object | None = None,
             expect: tuple[int, ...] = (200, 201, 204)) -> tuple[int, object]:
        """Call the REST API; ``path`` is relative to ``https://api.github.com``."""
        url = path if path.startswith("http") else f"{GITHUB_API}{path}"
        return http_json(url, method=method, headers=self.headers, payload=payload,
                         expect=expect, redactor=self.redactor)

    def get(self, path: str, *, expect: tuple[int, ...] = (200,)) -> object:
        return self.call(path, expect=expect)[1]

    def user(self) -> dict:
        body = self.get("/user")
        if not isinstance(body, dict):
            raise SystemExit(f"unexpected /user response: {body}")
        return body

    def repo(self, full_name: str) -> dict | None:
        """Return the repository or ``None`` when it does not exist."""
        try:
            body = self.get(f"/repos/{full_name}")
        except HttpFailure as error:
            if error.status == 404:
                return None
            raise
        return body if isinstance(body, dict) else None


def client() -> tuple[GitHub, str]:
    """Return ``(client, login)`` for the resolved GITHUB_TOKEN."""
    token = resolve_token("GITHUB_TOKEN")
    assert token is not None
    api = GitHub(token)
    return api, str(api.user().get("login"))


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------


def cmd_whoami(args: argparse.Namespace) -> int:
    """Show token identity, scopes and rate limit."""
    token = resolve_token("GITHUB_TOKEN")
    assert token is not None
    api = GitHub(token)
    user = api.user()
    ok(f"github: {user.get('login')} ({user.get('name') or 'no display name'}, {user.get('type')})")
    info(f"token source: {token_source('GITHUB_TOKEN')}")
    try:
        body = api.get("/rate_limit")
        core = (body or {}).get("resources", {}).get("core", {}) if isinstance(body, dict) else {}
        if core:
            info(f"rate limit: {core.get('remaining')}/{core.get('limit')} remaining for core API")
    except HttpFailure as error:
        warn(f"rate limit check failed: {error}")
    info("required scopes for this pipeline: 'repo' (create/push/configure, private included) and "
         "'workflow' when the push contains .github/workflows/*")
    return EXIT_OK


def ensure_repo(api: GitHub, owner: str, name: str, args: argparse.Namespace) -> bool:
    """Create the repository when absent. Returns ``True`` when it created one."""
    existing = api.repo(f"{owner}/{name}")
    if existing is not None:
        info(f"repository {owner}/{name} already exists (private={existing.get('private')})")
        return False

    payload = {
        "name": name,
        "description": args.description or "",
        "homepage": args.homepage or "",
        "private": bool(args.private),
        "has_issues": True,
        "has_projects": False,
        "has_wiki": bool(args.wiki),
        "has_discussions": bool(args.discussions),
        "auto_init": False,
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": True,
        "delete_branch_on_merge": True,
    }
    if not args.apply:
        info("[dry-run] POST /user/repos")
        info(json.dumps(payload, indent=2))
        return False
    status, body = api.call("/user/repos", method="POST", payload=payload, expect=(201, 422))
    if status == 422:
        warn(f"GitHub refused creation (422): {body}")
        return False
    ok(f"created https://github.com/{owner}/{name} (private={bool(args.private)})")
    # Topics and description are set in a second call: the create payload does
    # not accept topics.
    if args.topics:
        set_topics(api, owner, name, args.topics)
    return True


def set_topics(api: GitHub, owner: str, name: str, topics: list[str]) -> None:
    """Replace the repository's topic list."""
    cleaned = sorted({topic.strip().lower().replace(" ", "-") for topic in topics if topic.strip()})
    if not cleaned:
        return
    try:
        body = api.call(f"/repos/{owner}/{name}/topics", method="PUT",
                        payload={"names": cleaned}, expect=(200,))
        applied = body[1]
        shown = applied.get("names") if isinstance(applied, dict) else cleaned
        ok(f"topics: {', '.join(shown or cleaned)}")
    except HttpFailure as error:
        warn(f"could not set topics: {error}")


def cmd_create(args: argparse.Namespace) -> int:
    """Create the GitHub repository (idempotent)."""
    api, login = client()
    owner = args.owner or login
    created = ensure_repo(api, owner, args.repo, args)
    if not args.apply:
        info("[dry-run] nothing was created; re-run with --apply")
        return EXIT_OK
    if not created:
        # Already present: still apply the topics the plan asked for, because
        # `create` is the step the pipeline runs unconditionally.
        if args.topics:
            set_topics(api, owner, args.repo, args.topics)
        else:
            info("nothing to do (already present)")
    return EXIT_OK


def cmd_configure(args: argparse.Namespace) -> int:
    """Apply description, homepage, topics and feature switches."""
    api, login = client()
    owner = args.owner or login
    full = f"{owner}/{args.repo}"
    repository = api.repo(full)
    if repository is None:
        fail(f"{full} does not exist — create it first")
        return EXIT_ERROR

    payload: dict[str, object] = {
        "has_issues": True,
        "has_discussions": bool(args.discussions),
        "has_wiki": bool(args.wiki),
        "allow_squash_merge": True,
        "delete_branch_on_merge": True,
    }
    if args.description is not None:
        payload["description"] = args.description
    if args.homepage is not None:
        payload["homepage"] = args.homepage
    if args.default_branch:
        payload["default_branch"] = args.default_branch

    if not args.apply:
        info(f"[dry-run] PATCH /repos/{full}")
        info(json.dumps(payload, indent=2))
        if args.topics:
            info(f"[dry-run] PUT /repos/{full}/topics {sorted(set(args.topics))}")
        info("[dry-run] PUT /repos/{repo}/vulnerability-alerts")
        return EXIT_OK

    api.call(f"/repos/{full}", method="PATCH", payload=payload)
    ok(f"configured {full}")
    if args.topics:
        set_topics(api, owner, args.repo, args.topics)
    try:
        api.call(f"/repos/{full}/vulnerability-alerts", method="PUT", expect=(204, 200))
        ok("vulnerability alerts enabled")
    except HttpFailure as error:
        warn(f"could not enable vulnerability alerts (fine for a plain public repo): {error}")
    return EXIT_OK


def cmd_push(args: argparse.Namespace) -> int:
    """Push the staging tree to GitHub over an askpass-authenticated remote."""
    api, login = client()
    owner = args.owner or login
    directory = Path(args.dir).expanduser().resolve()
    if not (directory / ".git").is_dir():
        fail(f"{directory} is not a git repository — export it first")
        return EXIT_ERROR

    branch = args.branch or git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=directory,
                                check=False).stdout.strip() or "main"
    remote = f"https://github.com/{owner}/{args.repo}.git"

    if args.apply:
        repository = api.repo(f"{owner}/{args.repo}")
        if repository is None:
            fail(f"{owner}/{args.repo} does not exist — run `create --apply` first")
            return EXIT_ERROR

    info(f"branch: {branch}")
    info(f"remote: {remote} (credentials supplied via a throwaway askpass helper)")
    if not args.apply:
        info("[dry-run] git remote add|set-url github <remote>")
        info(f"[dry-run] git push -u github {branch}" + (" (--force)" if args.force else ""))
        if args.tags:
            info("[dry-run] git push github --tags")
        return EXIT_OK

    if git(["remote"], cwd=directory, check=False).stdout.split().count("github"):
        git(["remote", "set-url", "github", remote], cwd=directory)
    else:
        git(["remote", "add", "github", remote], cwd=directory)

    token = resolve_token("GITHUB_TOKEN")
    assert token is not None
    with git_credential(GITHUB_ASKPASS_USER, token) as env:
        push_args = ["push", "-u", "github", branch]
        if args.force:
            push_args.insert(1, "--force")
        git(push_args, cwd=directory, env=env, timeout=1800)
        ok(f"pushed {branch}")
        if args.tags:
            git(["push", "github", "--tags"], cwd=directory, env=env, timeout=900)
            ok("pushed tags")
    return EXIT_OK


def cmd_release(args: argparse.Namespace) -> int:
    """Create a release, with notes from a file or generated by GitHub."""
    api, login = client()
    owner = args.owner or login
    full = f"{owner}/{args.repo}"
    payload: dict[str, object] = {
        "tag_name": args.tag,
        "name": args.name or args.tag,
        "draft": bool(args.draft),
        "prerelease": bool(args.prerelease),
        "generate_release_notes": bool(args.generate_notes),
    }
    if args.notes:
        notes = Path(args.notes).expanduser()
        if not notes.is_file():
            fail(f"notes file not found: {notes}")
            return EXIT_ERROR
        payload["body"] = notes.read_text(encoding="utf-8")
    if not args.apply:
        info(f"[dry-run] POST /repos/{full}/releases")
        info(json.dumps({key: (value[:120] + '…' if isinstance(value, str) and len(value) > 120 else value)
                         for key, value in payload.items()}, indent=2, ensure_ascii=False))
        return EXIT_OK
    status, body = api.call(f"/repos/{full}/releases", method="POST", payload=payload, expect=(201, 422))
    if status == 422:
        warn(f"release not created (422 — the tag may already have a release): {body}")
        return EXIT_ERROR
    url = body.get("html_url") if isinstance(body, dict) else ""
    ok(f"release {args.tag} created: {url}")
    return EXIT_OK


def _local_paths(directory: Path) -> list[str]:
    """Tracked file paths in the staging tree."""
    listed = git(["ls-files"], cwd=directory, check=False).stdout.splitlines()
    return sorted(path.strip() for path in listed if path.strip())


def _remote_paths(api: GitHub, full: str, branch: str) -> list[str] | None:
    """Paths present in the published branch, or ``None`` when the tree is empty."""
    repository = api.repo(full)
    if repository is None:
        return None
    branch_info = repository.get("default_branch") or branch
    try:
        body = api.get(f"/repos/{full}/git/trees/{branch_info}?recursive=1")
    except HttpFailure as error:
        if error.status in {404, 409}:  # empty repository
            return []
        raise
    if not isinstance(body, dict):
        return []
    return sorted(entry["path"] for entry in body.get("tree", []) if entry.get("type") == "blob")


def _readme_images(text: str) -> list[str]:
    """Image targets referenced from Markdown, excluding absolute URLs."""
    import re

    targets: list[str] = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", text):
        target = match.group(1)
        if not target.startswith(("http://", "https://", "data:")):
            targets.append(target.lstrip("./"))
    for match in re.finditer(r"<img[^>]+src=[\"']([^\"']+)[\"']", text):
        target = match.group(1)
        if not target.startswith(("http://", "https://", "data:")):
            targets.append(target.lstrip("./"))
    return sorted(set(targets))


def _materialize_via_api(api: GitHub, full: str, branch: str, dest: Path) -> int:
    """Write the published tree to ``dest`` using only the REST API.

    Needed when git transport to github.com is unavailable — a mirror rewrite in
    the user's global git config (``url.<mirror>.insteadOf``), or a network that
    blocks the git endpoint while leaving ``api.github.com`` reachable. The audit
    must still run against the *published* bytes, so reconstructing them from
    ``git/blobs`` beats skipping the check and calling it verified.
    """
    body = api.get(f"/repos/{full}/git/trees/{branch}?recursive=1")
    written = 0
    for entry in (body or {}).get("tree", []):
        if entry.get("type") != "blob":
            continue
        path = entry["path"]
        blob = api.get(f"/repos/{full}/git/blobs/{entry['sha']}")
        raw = base64.b64decode((blob or {}).get("content") or "")
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.get("mode") == "120000":
            if target.exists() or target.is_symlink():
                target.unlink()
            os.symlink(raw.decode("utf-8"), target)
        else:
            target.write_bytes(raw)
        written += 1
    return written


def cmd_verify(args: argparse.Namespace) -> int:
    """Compare the published repository with the staging tree, then re-audit it."""
    api, login = client()
    owner = args.owner or login
    full = f"{owner}/{args.repo}"
    directory = Path(args.dir).expanduser().resolve() if args.dir else (publish_home() / args.repo)

    step(f"verify {full}")
    repository = api.repo(full)
    if repository is None:
        fail(f"{full} not found on GitHub")
        return EXIT_ERROR

    checks: list[tuple[str, str, str]] = []  # (status, item, detail)
    add = checks.append

    branch = repository.get("default_branch") or args.branch
    add(("ok", "default branch", str(branch)))
    add(("ok" if repository.get("description") else "missing", "description",
         str(repository.get("description") or "empty — add a keyword-rich description")))
    add(("ok" if repository.get("homepage") else "info", "homepage",
         str(repository.get("homepage") or "not set (optional)")))
    topics = repository.get("topics") or []
    add(("ok" if len(topics) >= 5 else "missing", "topics",
         ", ".join(topics) or "none — 8-15 topics drive discoverability"))
    license_info = repository.get("license") or {}
    add(("ok" if license_info.get("spdx_id") not in {None, "NOASSERTION"} else "missing",
         "license detected by GitHub", str(license_info.get("spdx_id") or "none")))
    add(("ok" if repository.get("private") == bool(args.expect_private) else "warn",
         "visibility", "private" if repository.get("private") else "public"))

    remote = _remote_paths(api, full, branch) if branch else None
    if directory.is_dir() and remote is not None:
        local = _local_paths(directory)
        missing = sorted(set(local) - set(remote))
        extra = sorted(set(remote) - set(local))
        add(("ok" if not missing and not extra else "warn", "file tree",
             f"{len(remote)} file(s) published, {len(local)} local"
             + (f"; missing on GitHub: {', '.join(missing[:8])}" if missing else "")
             + (f"; only on GitHub: {', '.join(extra[:8])}" if extra else "")))
        for name in ("README.md", "README.zh-CN.md"):
            present = name in remote
            add(("ok" if present else "missing", f"{name} published",
                 "present" if present else "not published — the bilingual policy requires both"))
            path = directory / name
            if path.is_file():
                images = _readme_images(path.read_text(encoding="utf-8", errors="replace"))
                broken = [target for target in images if target not in remote]
                add(("ok" if not broken else "missing", f"{name} images",
                     f"{len(images)} referenced, all present" if not broken
                     else f"not published: {', '.join(broken[:8])}"))
        add(("ok" if not repository.get("stargazers_count") == 0 else "info", "engagement",
             f"stars={repository.get('stargazers_count')} forks={repository.get('forks_count')} "
             f"watchers={repository.get('subscribers_count')}"))
    elif remote is None:
        add(("missing", "published tree", "repository has no commits yet"))
    else:
        warn("no local staging directory given — skipping the file-tree comparison")

    if args.reaudit:
        clone_to = Path(tempfile.mkdtemp(prefix="dsh-verify-"))
        token = resolve_token("GITHUB_TOKEN")
        assert token is not None
        step("re-audit a fresh clone of the published repository")
        try:
            try:
                with git_credential(GITHUB_ASKPASS_USER, token) as env:
                    git(["clone", "--quiet", "--depth", "50",
                         f"https://github.com/{full}.git", str(clone_to / "repo")], env=env,
                        timeout=900)
            except Exception as error:  # noqa: BLE001 - any transport failure falls back
                warn(f"git clone unavailable ({str(error).splitlines()[0][:90]}) — "
                     f"reconstructing the published tree through the REST API instead")
                written = _materialize_via_api(api, full, branch or "main", clone_to / "repo")
                add(("info", "published-tree transport",
                     f"git transport blocked; rebuilt {written} file(s) from the API"))
            audit = Path(__file__).resolve().parent / "privacy_audit.py"
            report = Path(args.report_dir).expanduser() if args.report_dir else clone_to
            argv = [sys.executable, str(audit), str(clone_to / "repo"),
                    "--report", str(report / "privacy-report-published.md"),
                    "--json", str(report / "privacy-report-published.json"),
                    "--quiet"]
            # The re-audit must judge the published tree by the same rules the
            # local audit used, including any deliberate suppression: without
            # this, a repository that legitimately allowed a documented example
            # could never pass its own verification.
            if args.audit_config:
                argv += ["--config", str(Path(args.audit_config).expanduser())]
            for name in (args.name or []):
                argv += ["--names", name]
            run = subprocess.run(argv, capture_output=True, text=True, check=False)
            redactor = default_redactor()
            output = redactor((run.stdout or "") + (run.stderr or "")).strip()
            # One line per check: keep the scanner's own verdict, not its log.
            last = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "")
            if run.returncode == 0:
                add(("ok", "published-tree privacy audit", last or "clean"))
            elif run.returncode == 3:
                add(("blocked", "published-tree privacy audit",
                     "the PUBLIC tree has findings — rotate credentials and rewrite the repository"))
                warn(output)
            else:
                add(("warn", "published-tree privacy audit",
                     f"scanner error ({run.returncode}): {last}"))
        except subprocess.SubprocessError as error:
            add(("warn", "published-tree privacy audit", f"clone failed: {error}"))
        finally:
            if not args.report_dir:
                shutil.rmtree(clone_to, ignore_errors=True)

    if args.json_path:
        write_json(args.json_path, {
            "repository": full,
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "default_branch": branch,
            "checks": [{"status": status, "item": item, "detail": detail}
                       for status, item, detail in checks],
        })

    blocked = False
    for status, item, detail in checks:
        marker = {"ok": "OK  ", "info": "INFO", "warn": "WARN", "missing": "MISS",
                  "blocked": "FAIL"}.get(status, status.upper()[:4])
        print(f"  {marker} {item:<34} {detail}")
        if status == "blocked":
            blocked = True

    if blocked:
        fail("verification found blocking problems in the published repository")
        return EXIT_BLOCKED
    if any(status in {"missing", "warn"} for status, _, _ in checks):
        warn("verification finished with items to fix")
    else:
        ok("verification passed")
    return EXIT_OK


def _git_head_files(directory: Path) -> list[tuple[str, str, bytes]]:
    """Return ``(path, mode, bytes)`` for every file in ``HEAD``.

    Reads the *commit* rather than the working tree, and refuses a dirty tree:
    what gets published has to be exactly what the audit scanned.
    """
    dirty = git(["status", "--porcelain"], cwd=directory, check=False).stdout.strip()
    if dirty:
        raise SystemExit(
            "refusing to publish a dirty working tree — commit or stash first:\n" + dirty)
    files: list[tuple[str, str, bytes]] = []
    for line in git(["ls-files", "-s"], cwd=directory, check=True).stdout.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        mode = meta.split()[0]
        target = directory / path
        if mode == "120000":                      # a symlink: the blob is its target path
            files.append((path, "120000", os.readlink(target).encode("utf-8")))
        elif mode == "100755":
            files.append((path, "100755", target.read_bytes()))
        else:
            files.append((path, "100644", target.read_bytes()))
    return files


def _bootstrap_empty_repo(api: GitHub, full: str, branch: str,
                         files: list[tuple[str, str, bytes]]) -> str:
    """Create the first commit of an empty repository through the Contents API.

    ``POST /git/trees`` answers **409 "Git Repository is empty."** until the
    repository has at least one commit, so an empty repository has to be seeded
    before the Git Data API will build anything. The caller later moves the
    branch to the real, parentless commit, which leaves this seed commit
    unreachable — it exists only to unlock the API.

    The seed uses a file that is part of the tree anyway (``.gitignore``), so
    even the unreachable commit contains nothing that is not published.
    """
    seed_path = next((path for path, _, _ in files if path == ".gitignore"),
                     next((path for path, _, _ in files if path.endswith(".gitignore")), None))
    if seed_path is None:
        seed_path = ".gitattributes"
    content = next(raw for path, _, raw in files if path == seed_path) if any(
        path == seed_path for path, _, _ in files) else b""
    body = api.call(f"/repos/{full}/contents/{seed_path}", method="PUT", payload={
        "message": "chore: seed the repository so the API can build the first tree",
        "content": base64.b64encode(content).decode("ascii"),
        "branch": branch,
    }, expect=(200, 201))[1]
    sha = body["commit"]["sha"]
    info(f"seeded {branch} at {sha[:10]} with {seed_path}")
    return sha


def cmd_push_api(args: argparse.Namespace) -> int:
    """Publish HEAD through the REST API, without using git transport at all.

    Needed whenever ``git push`` cannot reach GitHub: a mirror/proxy rewrite in
    the user's global git config (``url.<mirror>.insteadOf``), a network that
    blocks git-over-HTTPS, or a credential helper that eats the askpass. The
    Git Data API does the same job over ``api.github.com``, which is usually
    reachable even when the git endpoint is not.
    """
    api, login = client()
    owner = args.owner or login
    full = f"{owner}/{args.repo}"
    directory = Path(args.dir).expanduser().resolve() if args.dir else (publish_home() / args.repo)
    if not (directory / ".git").is_dir():
        fail(f"{directory} is not a git repository")
        return EXIT_ERROR

    files = _git_head_files(directory)
    if not files:
        fail("nothing to publish: HEAD has no files")
        return EXIT_ERROR
    total = sum(len(raw) for _, _, raw in files)
    branch = args.branch or git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=directory,
                                check=False).stdout.strip() or "main"
    name, email = git_identity(directory)
    message = args.message or git(["log", "-1", "--format=%B"], cwd=directory,
                                  check=False).stdout.strip() or "Publish"
    committed_at = git(["log", "-1", "--format=%aI"], cwd=directory, check=False).stdout.strip()

    info(f"{len(files)} file(s), {total / 1024:.0f} KiB, branch '{branch}', author {name} <{email}>")
    if not args.apply:
        info(f"[dry-run] POST /repos/{full}/git/blobs   × {len(files)}")
        info(f"[dry-run] POST /repos/{full}/git/trees   (1 tree, {len(files)} entries)")
        info(f"[dry-run] POST /repos/{full}/git/commits "
             f"(parent: the current {branch} head when the branch already exists)")
        info(f"[dry-run] POST|PATCH /repos/{full}/git/refs/heads/{branch}")
        info("[dry-run] nothing was pushed; re-run with --apply")
        return EXIT_OK

    repository = api.repo(full)
    if repository is None:
        fail(f"{full} does not exist — run `create --apply` first")
        return EXIT_ERROR

    # Resolve the branch FIRST: an empty repository answers 409 to `POST /git/trees`
    # ("Git Repository is empty."), so it must be seeded before any tree is built.
    parent: str | None = None
    try:
        parent = api.get(f"/repos/{full}/git/ref/heads/{branch}")["object"]["sha"]
        info(f"existing {branch} at {parent[:10]} — appending a commit")
    except HttpFailure as error:
        if error.status not in (404, 409):
            raise
        info(f"{branch} does not exist yet")

    seeded = False
    if parent is None:
        parent = _bootstrap_empty_repo(api, full, branch, files)
        seeded = True

    blobs: dict[str, str] = {}
    for index, (path, _mode, raw) in enumerate(files, start=1):
        payload = {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"}
        body = api.call(f"/repos/{full}/git/blobs", method="POST", payload=payload, expect=(201,))[1]
        blobs[path] = body["sha"]
        if index % 10 == 0 or index == len(files):
            info(f"  uploaded {index}/{len(files)} blob(s)")

    tree_body = api.call(
        f"/repos/{full}/git/trees", method="POST",
        payload={"tree": [{"path": path, "mode": mode, "type": "blob", "sha": blobs[path]}
                          for path, mode, _ in files]},
        expect=(201,))[1]
    ok(f"tree {tree_body['sha'][:10]} ({len(files)} entries)")


    commit_payload: dict[str, object] = {
        "message": message,
        "tree": tree_body["sha"],
        "author": {"name": name, "email": email},
        "committer": {"name": name, "email": email},
        # A seeded repository produces one clean-room commit with no parent; an
        # existing branch simply gets a child commit.
        "parents": [] if seeded else ([parent] if parent else []),
    }
    if committed_at:
        commit_payload["author"]["date"] = committed_at      # type: ignore[index]
        commit_payload["committer"]["date"] = committed_at   # type: ignore[index]
    commit = api.call(f"/repos/{full}/git/commits", method="POST", payload=commit_payload,
                      expect=(201,))[1]
    ok(f"commit {commit['sha'][:10]}")

    api.call(f"/repos/{full}/git/refs/heads/{branch}", method="PATCH",
             payload={"sha": commit["sha"], "force": bool(args.force) or seeded})
    ok(f"refs/heads/{branch} -> {commit['sha'][:10]}"
       + (" (single clean-room commit; the seed commit is now unreachable)" if seeded else ""))

    if repository.get("default_branch") != branch:
        api.call(f"/repos/{full}", method="PATCH", payload={"default_branch": branch})
        ok(f"default branch set to {branch}")
    info(f"https://github.com/{full}/commit/{commit['sha']}")
    return EXIT_OK


def cmd_state(args: argparse.Namespace) -> int:
    """Print a one-screen summary of a GitHub repository's settings."""
    api, login = client()
    full = f"{args.owner or login}/{args.repo}"
    repository = api.repo(full)
    if repository is None:
        fail(f"{full} not found")
        return EXIT_ERROR
    payload = {
        "full_name": repository.get("full_name"),
        "private": repository.get("private"),
        "description": repository.get("description"),
        "homepage": repository.get("homepage"),
        "topics": repository.get("topics"),
        "default_branch": repository.get("default_branch"),
        "license": (repository.get("license") or {}).get("spdx_id"),
        "stars": repository.get("stargazers_count"),
        "forks": repository.get("forks_count"),
        "watchers": repository.get("subscribers_count"),
        "open_issues": repository.get("open_issues_count"),
        "has_discussions": repository.get("has_discussions"),
        "pushed_at": repository.get("pushed_at"),
        "html_url": repository.get("html_url"),
    }
    info(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.json_path:
        write_json(args.json_path, payload)
    return EXIT_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github_publish.py",
        description="Publish a staging directory to GitHub. Dry-run unless --apply is given.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    whoami = sub.add_parser("whoami", help="token identity and scopes")
    whoami.set_defaults(func=cmd_whoami)

    def add_repo_target(target: argparse.ArgumentParser) -> None:
        target.add_argument("--repo", required=True, help="repository name on GitHub")
        target.add_argument("--owner", help="owner (default: the token's login)")

    create = sub.add_parser("create", help="create the repository")
    add_repo_target(create)
    create.add_argument("--description")
    create.add_argument("--homepage")
    create.add_argument("--topics", nargs="*", default=[])
    create.add_argument("--private", action="store_true", help="create it private (default public)")
    create.add_argument("--wiki", action="store_true")
    create.add_argument("--discussions", action="store_true")
    create.add_argument("--apply", action="store_true")
    create.set_defaults(func=cmd_create)

    configure = sub.add_parser("configure", help="set description, homepage, topics, features")
    add_repo_target(configure)
    configure.add_argument("--description")
    configure.add_argument("--homepage")
    configure.add_argument("--topics", nargs="*", default=[])
    configure.add_argument("--default-branch")
    configure.add_argument("--wiki", action="store_true")
    configure.add_argument("--discussions", action="store_true")
    configure.add_argument("--apply", action="store_true")
    configure.set_defaults(func=cmd_configure)

    push = sub.add_parser("push", help="push the staging tree")
    add_repo_target(push)
    push.add_argument("--dir", help="staging repository (default: <publish home>/<repo>)")
    push.add_argument("--branch", help="branch to push (default: the checked-out branch)")
    push.add_argument("--tags", action="store_true", help="also push tags")
    push.add_argument("--force", action="store_true")
    push.add_argument("--apply", action="store_true")
    push.set_defaults(func=cmd_push)

    release = sub.add_parser("release", help="create a release")
    add_repo_target(release)
    release.add_argument("--tag", required=True)
    release.add_argument("--name")
    release.add_argument("--notes", help="Markdown file with the release notes")
    release.add_argument("--generate-notes", action="store_true")
    release.add_argument("--draft", action="store_true")
    release.add_argument("--prerelease", action="store_true")
    release.add_argument("--apply", action="store_true")
    release.set_defaults(func=cmd_release)

    verify = sub.add_parser("verify", help="compare remote with local and re-audit the clone")
    add_repo_target(verify)
    verify.add_argument("--dir", help="staging repository to compare against")
    verify.add_argument("--branch", default="main")
    verify.add_argument("--expect-private", action="store_true")
    verify.add_argument("--reaudit", action="store_true", default=True,
                        help="clone the published repository and re-run the privacy audit (default on)")
    verify.add_argument("--no-reaudit", dest="reaudit", action="store_false")
    verify.add_argument("--report-dir", help="keep the published-tree audit reports here")
    verify.add_argument("--audit-config",
                        help="the audit config the local scan used (publish-plan.json or "
                             "publish-audit.json); forwarded to the published-tree re-audit")
    verify.add_argument("--name", action="append",
                        help="private name to hunt for in the published tree (repeatable)")
    verify.add_argument("--json", dest="json_path")
    verify.set_defaults(func=cmd_verify)

    push_api = sub.add_parser(
        "push-api",
        help="publish HEAD through the REST API (use when git transport is blocked or rewritten)")
    add_repo_target(push_api)
    push_api.add_argument("--dir", help="repository to publish (default: <publish home>/<repo>)")
    push_api.add_argument("--branch", help="branch to write (default: the checked-out branch)")
    push_api.add_argument("--message", help="commit message (default: HEAD's message)")
    push_api.add_argument("--force", action="store_true",
                          help="move an existing branch ref even when it is not a fast-forward")
    push_api.add_argument("--apply", action="store_true")
    push_api.set_defaults(func=cmd_push_api)

    state = sub.add_parser("state", help="summarise a repository's settings")
    add_repo_target(state)
    state.add_argument("--json", dest="json_path")
    state.set_defaults(func=cmd_state)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except HttpFailure as error:
        fail(str(error))
        return EXIT_ERROR
    except RuntimeError as error:
        fail(str(error))
        return EXIT_ERROR


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(EXIT_ERROR)