# Tokens and APIs (Gitee v5, GitHub REST v3, git over HTTPS)

Everything this skill does travels one of three ways: Gitee API v5 (read),
GitHub REST v3 (read + write), or `git` over HTTPS. This document is the exact
surface, the token rules, and the failure modes worth recognising.

## Tokens

| Variable | Used for | Where it lives on this machine |
| --- | --- | --- |
| `GITEE_TOKEN` | reading repositories and metadata from gitee.com | `~/scripts/keys.zsh` (`export GITEE_TOKEN=...`) |
| `GITHUB_TOKEN` | creating and configuring repositories on github.com | `~/scripts/keys.zsh` |

`_common.resolve_token()` looks in this order and never prints the value:

1. the process environment (`$GITHUB_TOKEN`, `$GITEE_TOKEN`);
2. `~/.config/dsh/publish.env`, `~/.dsh/publish.env`, `~/scripts/keys.zsh`,
   `~/.env` — parsed as plain `export NAME=value` lines, **not sourced**;
3. an interactive login shell (`zsh -ic 'printf %s "$GITHUB_TOKEN"'`).

Step 3 exists because the tokens are often exported from an interactive shell's
rc file (for example `~/.zshrc`), which only interactive shells read: a tool
shell that runs `bash -c` sees nothing while `zsh -lic` sees everything. If a
script reports a token as missing but your terminal has it, that is why.
`token_source()` reports
which of the three answered, so a run is always explainable.

Required GitHub token scopes (verify with
`python3 scripts/github_publish.py whoami`):

- `repo` — create repositories, push, read the tree, manage topics and releases
  (this covers private repositories too);
- `workflow` — required when the push contains `.github/workflows/*`. Without it
  GitHub rejects the push with `refusing to allow a Personal Access Token to
  create or update workflow`.

A fine-grained token needs: *Administration* (write) to create repositories,
*Contents* (write) to push, *Metadata* (read), *Workflows* (write) if CI files
are included.

GitHub OAuth scopes are only visible in the `x-oauth-scopes` response header of a
classic-token request; `whoami` prints the expected scopes instead of guessing.

## Where the token must never go

| Anti-pattern | Why it is wrong |
| --- | --- |
| `git remote add origin https://user:TOKEN@github.com/...` | The token is written to `.git/config` and to the reflog, and leaks into any later `git remote -v`. |
| `curl "https://api.github.com/...?access_token=$TOKEN"` | The token appears in the process argument list (`ps aux`) and in shell history. |
| `git config credential.helper store` | Writes the token to `~/.git-credentials` in plain text, forever. |
| `echo "$TOKEN"` in a script that is `set -x`'d | Ends up in CI logs. |
| A token in a `.env` inside the repository | The next `git add -A` publishes it. |

The two supported patterns:

- **API**: `urllib` inside the Python process, with the token in an
  `Authorization: Bearer` header (GitHub) or an `access_token` query parameter
  (Gitee). It never becomes an argument, so `ps` cannot see it;
- **git**: a throwaway `GIT_ASKPASS` script written to a mode-`0600` temp file by
  `git_credential()`, used for one command and deleted in a `finally`. Set
  `GIT_TERMINAL_PROMPT=0` so a missing credential fails instead of hanging.

`_common.default_redactor()` is seeded with every resolvable token value and is
applied to all captured subprocess output and error messages, plus a
credential-in-URL pattern and `gh[pousr]_...` shapes. `run(..., redact=False)`
exists only for the scanner's own read path, where hiding the evidence would
produce a false all-clear; it is forbidden with `check=True`.

## Gitee API v5

Base `https://gitee.com/api/v5`. Authentication is
`?access_token=<token>`. Rate limit for an authenticated user: 5000 calls/hour
(Gitee documents 1000/hour for anonymous access).

| Purpose | Endpoint |
| --- | --- |
| identity | `GET /user` |
| repository list | `GET /user/repos?per_page=100&page=N&sort=updated&direction=desc&visibility=all\|public\|private` |
| one repository | `GET /repos/{owner}/{repo}` |
| README | `GET /repos/{owner}/{repo}/readme` → `{name, content}` with base64 content |
| clone | `https://gitee.com/{owner}/{repo}.git` with askpass username `oauth2` |

Notes learned the hard way:

- `license` comes back **either** as a string **or** as an object with
  `spdx_id`/`name` depending on the repository — handle both (the user's own
  inventory contains both shapes).
- `language` is frequently `null` for small or polyglot repositories; do not
  treat it as a signal.
- Gitee's README endpoint answers `404` when there is no README rather than
  returning an empty body.
- Private repositories require the token to own them; a token for another user
  returns `404`, not `403`.

## GitHub REST v3

Base `https://api.github.com`, header
`X-GitHub-Api-Version: 2022-11-28`, `Accept: application/vnd.github+json`.

| Purpose | Endpoint |
| --- | --- |
| identity | `GET /user` |
| rate limit | `GET /rate_limit` |
| create repository | `POST /user/repos` (also accepts `POST /orgs/{org}/repos`) |
| update settings | `PATCH /repos/{owner}/{repo}` |
| topics | `PUT /repos/{owner}/{repo}/topics` with `{"names": [...]}` (replaces the list) |
| vulnerability alerts | `PUT /repos/{owner}/{repo}/vulnerability-alerts` |
| file tree | `GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1` |
| release | `POST /repos/{owner}/{repo}/releases` |
| release notes | body field `generate_release_notes: true` |

Error codes to expect:

| Status | Meaning here | Reaction |
| --- | --- | --- |
| `401` | token invalid or revoked | re-issue the token |
| `403` | missing scope, or rate limited | check `x-oauth-scopes`; wait for reset |
| `404` on a private path | the token cannot see it (not necessarily absent) | check the token's repository access |
| `409` on `git/trees` | empty repository (no commits) | push first |
| `422` on create | name taken, reserved, or invalid | treat as "already exists" and continue |
| `422` on release | tag already has a release | edit the existing release instead |

`POST /user/repos` does **not** accept `topics` — `create` therefore makes a
second call to `PUT /topics`. It also does not accept a license template unless
`auto_init` is true; this pipeline pushes its own tree, so `auto_init` stays
false and the license comes from the committed `LICENSE` file.

Unauthenticated GitHub limit is 60 requests/hour per IP; an authenticated token
gets 5000/hour, which is far beyond what this pipeline needs.

## When `git push` cannot reach GitHub

Two failures look like credential problems but are not, and both were hit for
real while publishing `icrefin/dsh-notify-push`:

| Symptom | Cause | Fix |
| --- | --- | --- |
| `remote: No anonymous write access` / the URL in the error is not github.com | a mirror rewrite in the user's **global** git config: `url.https://gh-proxy.org/https://github.com/.insteadOf https://github.com/`. Mirrors accelerate *cloning* and are usually read-only. | `github_publish.py push-api`, or push with an overridden config. Never edit the user's global config. |
| `Could not resolve host` / TLS timeout on `github.com`, while `api.github.com` answers 200 | the network blocks the git endpoint | `push-api` |

`push-api` publishes `HEAD` through the Git Data API, with no git transport:

```
POST /repos/{owner}/{repo}/git/blobs      × N   (base64, one per file)
POST /repos/{owner}/{repo}/git/trees            (one tree, no base_tree)
POST /repos/{owner}/{repo}/git/commits          (parents: the current head, or none)
PATCH /repos/{owner}/{repo}/git/refs/heads/{b}  (force only when re-publishing)
```

Three details that are not obvious:

- **An empty repository rejects trees.** `POST /git/trees` answers
  `409 Git Repository is empty.` until the repository has at least one commit. The
  script seeds one commit with `PUT /contents/.gitignore` (a file that is in the
  tree anyway), then moves the branch to the real, parentless commit — the
  published history is still one clean-room commit and the seed is unreachable.
- **It reads `HEAD`, not the working tree**, and refuses to run on a dirty tree:
  what gets published must be exactly what was audited.
- **Modes are preserved** (`100644` / `100755` / `120000` for symlinks), so an
  executable script does not silently lose its bit.

Reconstructing a published tree for the re-audit uses the same transport:
`GET /git/trees/{branch}?recursive=1` plus `GET /git/blobs/{sha}` per file —
`github_publish.py verify` falls back to that automatically when a clone fails,
because an unverifiable publish is not a finished publish.

## Transient failures are expected

On a constrained network a single `SSLEOFError` mid-publish is normal, so
`http_json` retries transport failures (and 5xx/429) with a short backoff before
giving up. The retries are safe by design: a replayed blob or commit becomes an
orphan object, and a replayed `create`/`release` answers `422`, which the callers
already treat as "already exists". A `4xx` is never retried — it is an answer.

## Things with no stable public API

| Task | Workaround |
| --- | --- |
| Uploading the 1280×640 **social preview** image | Settings → Social preview, by hand. An undocumented endpoint exists and is not worth depending on. |
| Pushing a repository into an organisation that requires SSO | Authorise the token for the organisation in the browser first. |
| Enabling GitHub Sponsors | Web onboarding only. |
| Changing a repository's *name* via a "rename + redirect" friendly path | `PATCH /repos/{owner}/{repo}` with `name`; the old URL keeps redirecting. |

## Dry-run contract

Every mutating subcommand of `github_publish.py` prints the request it would make
and exits without `--apply`. Reviewing the printed payload is the cheapest way to
catch a wrong owner, a wrong visibility, or a description with a leaked internal
detail — before anything is public.