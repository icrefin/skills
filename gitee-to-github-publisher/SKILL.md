---
name: gitee-to-github-publisher
description: Publish selected Gitee repositories on GitHub as a polished, bilingual, privacy-audited open-source release. Use when the user wants to publish, mirror, migrate, import or re-release a repo from gitee.com to github.com, or asks to make a README bilingual (English plus Chinese), add screenshots, badges, topics or a star call-to-action, audit a repo for leaked secrets/IP/credentials/company names before it goes public, check license compatibility of dependencies, add CONTRIBUTING/SECURITY/issue templates or CI, or verify that a repository was published correctly and the public artifact is clean.
---

# Publishing Gitee repositories to GitHub

Publishing turns a private working repository into a permanent public record.
Two facts drive every rule below:

- **It is one-way.** GitHub forks, caches and third-party mirrors copy content
  within minutes. "I deleted it" is not a fix; rotating a credential is.
- **The local tree is not the artifact.** What matters is the tree a stranger
  clones, so the last step is always a re-audit of a fresh clone.

Four gates stand between a repository and the public: the **privacy audit**, the
**license check**, the explicit **`--apply`** on every GitHub write, and the
**published-tree verification**. Do not skip a gate because the repository "looks
small" or "is obviously harmless".

## Non-negotiables

1. **Bilingual by default.** Every published repo gets `README.md` (English) and
   `README.zh-CN.md` (Chinese), each linking to the other. If the source has one
   language, write the other — translate faithfully, never summarise. If it has
   neither, create both.
2. **Screenshots.** Add product shots when the project has any visible surface.
   Capture fresh, empty-data sessions and check them for leaked paths, hostnames,
   usernames and serials before committing.
3. **Tokens come from the environment.** `GITEE_TOKEN` and `GITHUB_TOKEN` only.
   Never inline a token in a URL, `.git/config`, a file, or a command argument.
   See `references/gitee-github-api.md` for why, and for how to resolve tokens
   that an interactive shell exports but a tool shell cannot see.
4. **Audit before you publish, in private.** Replace every credential, IP,
   hostname, personal name, company name and vendor license artifact with a
   placeholder, and say in the README that they are placeholders. A leak in the
   Chinese README is as public as a leak in the English one.
5. **Promote like a real project.** Topics, a keyword-rich description, badges,
   screenshots, a star call-to-action, community health files and a first release.
6. **License compliance is a gate, not a note.** The project's outbound license
   must be compatible with every dependency, upstream clones keep their upstream
   license and get attribution, and `CONTRIBUTING.md` states the inbound=outbound
   rule.
7. **Say what you did not verify.** End every run with the explicit list of open
   items and unknowns.

## Quick start (one repository)

```bash
export DSH_PUBLISH_HOME="${DSH_PUBLISH_HOME:-$HOME/.dsh/publish}"
SKILL="$HOME/.dsh/skills/gitee-to-github-publisher"
R=example-tool

# 0. tokens + inventory
python3 "$SKILL/scripts/gitee_repo.py" whoami
python3 "$SKILL/scripts/gitee_repo.py" inspect <owner>/$R --json "$DSH_PUBLISH_HOME/audit/inspect-$R.json"

# 1. export (squash = publish one clean commit; the original clone is kept)
python3 "$SKILL/scripts/gitee_repo.py" export <owner>/$R --dest "$DSH_PUBLISH_HOME" \
    --history squash --author "$(git config user.name) <$(git config user.email)>"

# 2-3. bilingual README + screenshots  (see references/bilingual-readme.md)
#      fill the placeholders, drop images in docs/images/, then:
uv run --with pillow python3 "$SKILL/scripts/optimize_images.py" "$DSH_PUBLISH_HOME/$R/docs/images" \
    --width 1600 --max-kb 500 --report "$DSH_PUBLISH_HOME/audit/images.md"

# 4. PRIVACY GATE  (exit 3 blocks)
python3 "$SKILL/scripts/privacy_audit.py" "$DSH_PUBLISH_HOME/$R" \
    --report "$DSH_PUBLISH_HOME/audit/privacy-report.md" \
    --json   "$DSH_PUBLISH_HOME/audit/privacy-report.json"

# 5. LICENSE GATE  (exit 3 blocks)
python3 "$SKILL/scripts/license_check.py" "$DSH_PUBLISH_HOME/$R" \
    --report "$DSH_PUBLISH_HOME/audit/license-report.md" \
    --json   "$DSH_PUBLISH_HOME/audit/license-report.json"

# 6. promotion + community files (references/promotion.md has the placement table)

# 7. dry-run first, then apply
python3 "$SKILL/scripts/github_publish.py" create --repo $R --description "<EN, <=160 chars>" --topics <topic...>
python3 "$SKILL/scripts/github_publish.py" create --repo $R --description "<EN, <=160 chars>" --topics <topic...> --apply
python3 "$SKILL/scripts/github_publish.py" push --repo $R --dir "$DSH_PUBLISH_HOME/$R" --tags --apply
python3 "$SKILL/scripts/github_publish.py" configure --repo $R --topics <topic...> --apply

# 8. VERIFY GATE  (clones the published repo and re-audits it)
python3 "$SKILL/scripts/github_publish.py" verify --repo $R --dir "$DSH_PUBLISH_HOME/$R" \
    --report-dir "$DSH_PUBLISH_HOME/audit" --json "$DSH_PUBLISH_HOME/audit/verify-$R.json"

# 9. report for the human
python3 "$SKILL/scripts/publish_report.py" "$DSH_PUBLISH_HOME" --repo $R \
    --out "$DSH_PUBLISH_HOME/audit/report-$R.html"
```

## The phases

| # | Phase | Gate | Detail |
| --- | --- | --- | --- |
| 0 | Plan and confirm what goes public | — | `references/pipeline.md` |
| 1 | Export from Gitee (read-only) | — | `references/pipeline.md` |
| 2 | Bilingual README and docs | — | `references/bilingual-readme.md` |
| 3 | Screenshots, optimized and stripped | — | `references/promotion.md` |
| 4 | Privacy audit | **exit 3 blocks** | `references/privacy-audit.md` |
| 5 | License and contribution compliance | **exit 3 blocks** | `references/license-compliance.md` |
| 6 | Promotion and community health | — | `references/promotion.md` |
| 7 | Create and push | needs `--apply` | `references/gitee-github-api.md` |
| 8 | Verify the published artifact | **exit 3 blocks** | `references/pipeline.md` |
| 9 | HTML report and hand-off | — | this file |

Read `references/pipeline.md` before starting a batch: it holds the
`publish-plan.json` schema, the ordering rationale (content first, *then* audit —
new README text and screenshots can carry new leaks) and the per-phase commands.

## Scripts

Standard-library Python 3, except the image optimizer which needs Pillow
(`uv run --with pillow`). They share `_common.py` for token resolution, output
redaction and the git askpass helper. Exit codes: `0` ok, `1` error, `2` usage,
`3` blocked.

| Script | What it does | Mutates |
| --- | --- | --- |
| `scripts/gitee_repo.py` | `whoami`, `list`, `inspect`, `readme`, `export` (`--history preserve\|squash`) | Gitee: never. Disk: yes |
| `scripts/privacy_audit.py` | scans the tree, file names, `.git/config`, history, commit identities and the live token values | no |
| `scripts/license_check.py` | outbound license, dependency inventory and verdicts, provenance, paperwork | no |
| `scripts/github_publish.py` | `whoami`, `create`, `configure`, `push`, `push-api`, `release`, `verify`, `state` | GitHub: only with `--apply` |
| `scripts/optimize_images.py` | resize/compress screenshots, strip EXIF/GPS | images (in place or `--out`) |
| `scripts/publish_report.py` | one light-theme HTML report with the gates and the open items | no |

Run any script with `--help` for its full flag set. `publish_report.py --lang zh`
renders the report in Chinese (the default follows `$REPORT_LANG`/`$LC_ALL`/`$LANG`);
`verify --audit-config <plan>` forwards the local scan's suppressions to the
published-tree re-audit, which is what lets a deliberately-allowed finding pass
verification instead of reappearing as a blocker.

## Assets to copy into the target repository

Substitute every `{{PLACEHOLDER}}` (`{{OWNER}}`, `{{REPO}}`, `{{FULL_NAME}}`,
`{{AUTHOR}}`, `{{EMAIL}}`, `{{YEAR}}`, `{{LICENSE}}`, `{{DESC_EN}}`,
`{{DESC_ZH}}`, `{{TAGLINE_EN}}`, `{{TAGLINE_ZH}}`, `{{HOMEPAGE}}`,
`{{DEFAULT_BRANCH}}`, `{{GITEE_URL}}`, `{{DEMO_URL}}`, `{{TOPIC_LIST}}`,
`{{SCREENSHOT_1}}`, `{{SCREENSHOT_2}}`, `{{UV_VERSION}}`) before committing —
`grep -rn '{{' .` in the target repository must come back empty.

Substitute **by that list**, never with a broad `{{...}}` regex: GitHub Actions
expressions (`${{ github.ref }}`, `${{ matrix.os }}`) use the same braces, and the
uppercase-snake convention is what keeps the two apart. `grep -rn '\${{' .` should
still show the workflow expressions after substitution.

| Asset | Destination |
| --- | --- |
| `assets/readme/README.en.md.tmpl` | `README.md` |
| `assets/readme/README.zh-CN.md.tmpl` | `README.zh-CN.md` |
| `assets/readme/badges.md` | snippet bank (badges, switcher, star CTA) — not copied wholesale |
| `assets/community/CONTRIBUTING.md` | `.github/CONTRIBUTING.md` (or the repository root) |
| `assets/community/SECURITY.md` | `.github/SECURITY.md` |
| `assets/community/CODE_OF_CONDUCT.md` | `.github/CODE_OF_CONDUCT.md` |
| `assets/community/PULL_REQUEST_TEMPLATE.md` | `.github/PULL_REQUEST_TEMPLATE.md` |
| `assets/community/ISSUE_TEMPLATE/*.yml` | `.github/ISSUE_TEMPLATE/` |
| `assets/community/CITATION.cff` | repository **root** (not `.github/`); academic projects only |
| `assets/community/PLACEHOLDER-NOTICE.md` | paste into both READMEs when the repository was sanitized |
| `assets/github/workflows/ci.yml` | `.github/workflows/ci.yml` — delete the job you do not need |

The community files link to each other with relative paths that assume they all
live in `.github/`; keep them together or fix the links.

## Reacting to a gate

| Result | Action |
| --- | --- |
| Privacy exit `3` | Fix every `critical`/`high`, decide every `medium`. Rotate first, then fix the tree, then decide history. Re-run. Never suppress without recording the reason. |
| License exit `3` | No outbound license → choose one. `incompatible` dependency → relicense or replace it. Vendor license artifact → remove it from the tree **and** from history. |
| Verify `blocked` | The public tree has findings. Rotate, rewrite history, force-push, then ask GitHub Support to purge cached views; assume forks keep the old object. |
| Verify `missing` | A required file never arrived: usually one of the two READMEs, an image referenced but never committed, or topics/description the plan expected. |

## Common failure modes

- **"The token is set but the script says it is missing."** On this machine the
  tokens are exported by an interactive shell while tool shells start
  non-interactive; `resolve_token()` falls back to `zsh -ic` for exactly that
  reason. `python3 scripts/gitee_repo.py whoami` prints the source it used.
- **Squash lost the tags.** Expected: a clean-room history has no upstream tags.
  Do not invent them.
- **Push rejected for a workflow file.** The token lacks the `workflow` scope.
  Fix the token; do not delete the CI file to make the push succeed.
- **`git push` cannot reach GitHub at all.** A mirror in the user's global git
  config (`url.https://<mirror>/https://github.com/.insteadOf https://github.com/`)
  silently reroutes the remote — mirrors are usually read-only, so the push dies
  with "No anonymous write access" even though the token is fine. Check
  `git config --global --get-regexp '^url\.'`, then publish over the API instead:
  `github_publish.py push-api --repo <name> --dir <staging> --apply`. It needs
  nothing but `api.github.com`, which is often reachable when the git endpoint is
  not. Never delete the user's global config to make a push work.
- **`409 Git Repository is empty.`** The Git Data API refuses to build a tree in a
  repository with no commits. `push-api` seeds one commit through the Contents API
  and then moves the branch to the real parentless commit, so the published history
  is still a single clean-room commit; the seed is left unreachable.
- **A finding looks wrong.** Prefer a narrow `# audit:allow <rule>` on that line,
  or an `allow` entry in the plan's `audit` block with a written reason, over
  lowering a severity for the whole repository.
- **The translated README reads like a translation.** Rewrite it as prose in the
  target language; `references/bilingual-readme.md` has the register and
  vocabulary guidance.
- **A screenshot shows a terminal with a token in the scrollback.** That is a
  `critical` leak no text scanner can see. Re-capture with a clean session.

## Batch publishing

Publish one repository at a time, each with its own audit reports and its own
verification. A blocking finding in repo 3 must not stop the report for repos 1
and 2 — nor silently publish them. Keep one `publish-plan.json` per batch, record
each outcome, and finish with a summary of which repositories are public, which
are blocked, and why.

## Out of scope

This skill publishes the user's own repositories and mirrors. It does not copy
someone else's repository without its license, scrape Gitee for other people's
code, automate the GitHub web UI, or make a repository public without an explicit
instruction that names the repository.