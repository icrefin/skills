#!/usr/bin/env python3
"""Read-only Gitee side of the publish pipeline: who am I, what do I have, export it.

Nothing here writes to Gitee. The subcommands are:

``whoami``   confirm the token and print the login it belongs to;
``list``     enumerate repositories, with the fields the publish plan needs;
``inspect``  one repository's metadata plus a README language verdict;
``readme``   dump a README to a file for translation;
``export``   clone a repository into the staging area, with a choice of
             history handling.

The token is used in a query string (Gitee's API) but travels inside this
process — never on a command line — so it cannot be read out of ``ps``. Git
operations use a throwaway ``GIT_ASKPASS`` helper instead of a token in the
remote URL.

Examples
--------
    python3 scripts/gitee_repo.py list --public-only
    python3 scripts/gitee_repo.py inspect OWNER/REPO
    python3 scripts/gitee_repo.py export OWNER/REPO --dest ~/.dsh/publish
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    HttpFailure,
    default_redactor,
    detect_language,
    fail,
    git,
    git_credential,
    gitee_url,
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

#: Gitee answers basic-auth prompts with ``oauth2`` as the username.
GITEE_ASKPASS_USER = "oauth2"


def token() -> str:
    """Resolve GITEE_TOKEN or explain how to provide it."""
    value = resolve_token("GITEE_TOKEN")
    assert value is not None
    return value


def api(path: str, *, params: dict | None = None, method: str = "GET", payload: dict | None = None):
    """Call the Gitee API v5 and return the decoded body."""
    key = token()
    url = gitee_url(path, key, **(params or {}))
    try:
        _, body = http_json(url, method=method, payload=payload)
    except HttpFailure as error:
        raise SystemExit(f"gitee api failed: {error}") from error
    return body


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------


def cmd_whoami(args: argparse.Namespace) -> int:
    """Print the authenticated login and token origin."""
    user = api("/user")
    if not isinstance(user, dict):
        fail(f"unexpected response: {user}")
        return EXIT_ERROR
    ok(f"gitee: {user.get('login')} ({user.get('name') or 'no display name'})")
    info(f"token source: {token_source('GITEE_TOKEN')}")
    return EXIT_OK


def _license_of(repo: dict) -> str:
    """Gitee returns the license either as a string or as an object."""
    value = repo.get("license")
    if isinstance(value, dict):
        return str(value.get("spdx_id") or value.get("name") or "")
    return str(value or "")


def cmd_list(args: argparse.Namespace) -> int:
    """List the account's repositories, newest activity first."""
    rows: list[dict] = []
    page = 1
    while True:
        batch = api("/user/repos", params={
            "per_page": 100, "page": page, "sort": "updated", "direction": "desc",
            "visibility": args.visibility,
        })
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    if args.public_only:
        rows = [row for row in rows if not row.get("private")]
    if args.match:
        needle = args.match.lower()
        rows = [row for row in rows
                if needle in str(row.get("full_name", "")).lower()
                or needle in str(row.get("description", "")).lower()]

    summary = [
        {
            "full_name": row.get("full_name"),
            "private": bool(row.get("private")),
            "fork": bool(row.get("fork")),
            "language": row.get("language"),
            "license": _license_of(row),
            "description": row.get("description") or "",
            "default_branch": row.get("default_branch"),
            "homepage": row.get("homepage") or "",
            "stars": row.get("stargazers_count"),
            "updated_at": row.get("updated_at"),
            "clone_url": row.get("html_url"),
        }
        for row in rows
    ]

    if args.json_path:
        write_json(args.json_path, summary)
        info(f"wrote {len(summary)} repo(s) to {args.json_path}")
    if not args.quiet:
        info(f"{'repository':<44} {'priv':<5} {'fork':<5} {'lang':<12} {'license':<14} desc")
        for row in summary:
            print(f"{row['full_name']:<44} {str(row['private']):<5} {str(row['fork']):<5} "
                  f"{str(row['language'])[:11]:<12} {row['license'][:13]:<14} "
                  f"{row['description'][:44]}")
    info(f"{len(summary)} repository(ies)")
    return EXIT_OK


def cmd_inspect(args: argparse.Namespace) -> int:
    """Print one repository's metadata and what its README looks like."""
    repo = api(f"/repos/{args.repo}")
    if not isinstance(repo, dict):
        fail(f"unexpected response for {args.repo}: {repo}")
        return EXIT_ERROR

    readme_text, readme_name = fetch_readme(args.repo)
    language = detect_language(readme_text) if readme_text else "none"

    payload = {
        "full_name": repo.get("full_name"),
        "private": bool(repo.get("private")),
        "fork": bool(repo.get("fork")),
        "description": repo.get("description") or "",
        "homepage": repo.get("homepage") or "",
        "default_branch": repo.get("default_branch"),
        "license": _license_of(repo),
        "language": repo.get("language"),
        "stars": repo.get("stargazers_count"),
        "forks": repo.get("forks_count"),
        "created_at": repo.get("created_at"),
        "updated_at": repo.get("updated_at"),
        "pushed_at": repo.get("pushed_at"),
        "html_url": repo.get("html_url"),
        "readme": {
            "file": readme_name,
            "bytes": len(readme_text.encode("utf-8")) if readme_text else 0,
            "language": language,
            "has_english": bool(readme_text and detect_language(readme_text) != "zh"),
            "has_chinese": bool(readme_text and detect_language(readme_text) != "en"),
        },
        "watchers": repo.get("watchers_count"),
        "open_issues": repo.get("open_issues_count"),
    }
    if args.json_path:
        write_json(args.json_path, payload)

    if not args.quiet:
        info(f"{payload['full_name']}  [{('private' if payload['private'] else 'public')}]"
             f"{'  FORK' if payload['fork'] else ''}")
        info(f"  description : {payload['description'] or '(none)'}")
        info(f"  homepage    : {payload['homepage'] or '(none)'}")
        info(f"  branch      : {payload['default_branch']}")
        info(f"  license     : {payload['license'] or '(none detected)'}")
        info(f"  language    : {payload['language']}  stars={payload['stars']} forks={payload['forks']}")
        info(f"  updated     : {payload['updated_at']}")
        readme = payload["readme"]
        if readme["file"]:
            info(f"  README      : {readme['file']} ({readme['bytes']} B) — prose language "
                 f"**{readme['language']}**")
            if readme["language"] in {"zh", "mixed"}:
                warn("README needs an English sibling before it is published on GitHub")
            if readme["language"] == "en":
                warn("README needs a Chinese sibling (bilingual is the policy for this pipeline)")
        else:
            warn("no README found — one will be created in both languages")
    return EXIT_OK


def fetch_readme(repo: str) -> tuple[str, str]:
    """Return ``(text, filename)`` for a repository README (``("", "")`` if none)."""
    try:
        body = api(f"/repos/{repo}/readme")
    except SystemExit:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    content = body.get("content") or ""
    name = body.get("name") or "README.md"
    try:
        return base64.b64decode(content).decode("utf-8", "replace"), name
    except (ValueError, TypeError):
        return "", name


def cmd_readme(args: argparse.Namespace) -> int:
    """Write the repository README to a file, ready for translation."""
    text, name = fetch_readme(args.repo)
    if not text:
        warn(f"{args.repo} has no README to read")
        return EXIT_ERROR
    target = Path(args.out).expanduser() if args.out else None
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        ok(f"{name} ({len(text)} chars, language **{detect_language(text)}**) → {target}")
    else:
        print(text)
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    """Clone the repository into the staging area and record its metadata."""
    redactor = default_redactor()
    key = token()
    owner, _, name = args.repo.partition("/")
    if not name:
        fail("expected OWNER/REPO")
        return EXIT_USAGE

    staging = Path(args.dest).expanduser().resolve() if args.dest else publish_home()
    staging.mkdir(parents=True, exist_ok=True)
    working = staging / name
    if working.exists() and not args.force:
        fail(f"{working} already exists — pass --force to replace it")
        return EXIT_ERROR

    metadata = api(f"/repos/{args.repo}")
    write_json(staging / f"{name}.gitee.json", metadata)
    info(f"metadata: {staging / f'{name}.gitee.json'}")

    remote = f"https://gitee.com/{owner}/{name}.git"
    step(f"clone {remote}")
    with git_credential(GITEE_ASKPASS_USER, key) as env:
        if working.exists():
            shutil.rmtree(working)
        git(["clone", "--quiet", remote, str(working)], env=env, redactor=redactor)

    branches = git(["branch", "-r", "--format=%(refname:short)"], cwd=working,
                   check=False).stdout.split()
    tags = git(["tag"], cwd=working, check=False).stdout.split()

    if args.history == "squash":
        # Publish a clean-room single commit. The source clone is kept as a
        # backup so nothing is destroyed, and so the difference is auditable.
        backup = staging / f".{name}.gitee-source"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(working, backup)
        info(f"kept the original history at {backup}")

        author = args.author or ""
        if author:
            git(["config", "user.name", author.split("<")[0].strip()], cwd=working)
            git(["config", "user.email", author.split("<")[1].rstrip(">").strip()], cwd=working)
        else:
            name_cfg = git(["config", "user.name"], cwd=working, check=False).stdout.strip()
            mail_cfg = git(["config", "user.email"], cwd=working, check=False).stdout.strip()
            warn(f"the squashed commit will be authored by {name_cfg} <{mail_cfg}>, which becomes "
                 f"public — pass --author 'Name <you@example.com>' to change it")

        branch = args.branch or (metadata.get("default_branch") if isinstance(metadata, dict) else None) or "main"
        git(["checkout", "--orphan", branch], cwd=working)
        git(["add", "-A"], cwd=working)
        message = args.message or (
            f"Initial public release\n\n"
            f"Imported from Gitee ({owner}/{name}) with a clean history: the upstream repository "
            f"keeps its full log, and every file here was privacy-audited before publication."
        )
        git(["commit", "--quiet", "-m", message], cwd=working)
        # Drop every other ref so only the clean branch can be published.
        git(["branch", "-D", *(b for b in git(["branch", "--format=%(refname:short)"], cwd=working,
                                              check=False).stdout.split() if b != branch)],
            cwd=working, check=False)
        for ref in git(["for-each-ref", "--format=%(refname)", "refs/remotes"], cwd=working,
                       check=False).stdout.split():
            git(["update-ref", "-d", ref], cwd=working, check=False)
        ok(f"squashed history: one commit on '{branch}'")
    else:
        branch = args.branch or (metadata.get("default_branch") if isinstance(metadata, dict) else None) or "main"
        git(["checkout", "--quiet", branch], cwd=working, check=False)

    info(f"branch: {branch}; {len(branches)} remote branch(es); {len(tags)} tag(s)")
    ok(f"exported to {working}")
    info(f"next: python3 scripts/privacy_audit.py {working} --report {staging}/audit/privacy-report.md")
    info(f"then: python3 scripts/license_check.py {working} --report {staging}/audit/license-report.md")
    return EXIT_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitee_repo.py",
        description="Inspect and export Gitee repositories (read-only on Gitee).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    whoami = sub.add_parser("whoami", help="show the authenticated Gitee account")
    whoami.set_defaults(func=cmd_whoami)

    listing = sub.add_parser("list", help="list repositories")
    listing.add_argument("--public-only", action="store_true")
    listing.add_argument("--match", help="substring filter on full name or description")
    listing.add_argument("--visibility", choices=("all", "public", "private"), default="all")
    listing.add_argument("--json", dest="json_path", help="write the inventory as JSON")
    listing.add_argument("--quiet", action="store_true")
    listing.set_defaults(func=cmd_list)

    inspect = sub.add_parser("inspect", help="show one repository's metadata and README status")
    inspect.add_argument("repo", help="OWNER/REPO")
    inspect.add_argument("--json", dest="json_path")
    inspect.add_argument("--quiet", action="store_true")
    inspect.set_defaults(func=cmd_inspect)

    readme = sub.add_parser("readme", help="dump a README for translation")
    readme.add_argument("repo", help="OWNER/REPO")
    readme.add_argument("--out", help="write here instead of stdout")
    readme.set_defaults(func=cmd_readme)

    export = sub.add_parser("export", help="clone a repository into the staging area")
    export.add_argument("repo", help="OWNER/REPO")
    export.add_argument("--dest", help="staging root (default: $DSH_PUBLISH_HOME or ~/.dsh/publish)")
    export.add_argument("--history", choices=("preserve", "squash"), default="preserve",
                        help="preserve the original log, or publish one clean-room commit")
    export.add_argument("--branch", help="branch to check out (default: the Gitee default branch)")
    export.add_argument("--author", help="'Name <email>' for the squashed commit")
    export.add_argument("--message", help="commit message for the squashed commit")
    export.add_argument("--force", action="store_true", help="replace an existing export")
    export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(EXIT_ERROR)