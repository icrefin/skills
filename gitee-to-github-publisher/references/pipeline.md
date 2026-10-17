# The publish pipeline

Nine phases, four of them gates. Nothing is pushed to GitHub until phases 4, 5
and 8 pass. A repository is only "published" when phase 8 has re-audited the
**public artifact** — the local tree is not the artifact.

```
0 plan ─▶ 1 export ─▶ 2 README ─▶ 3 screenshots ─▶ [4 privacy GATE] ─▶ [5 license GATE]
                                                          │
                        [8 verify GATE] ◀─ 7 push ◀─ 6 promo ◀─┘
                                 │
                                 └─▶ 9 report
```

Staging layout (everything here is disposable; keep it out of git):

```
$DSH_PUBLISH_HOME/                 (default ~/.dsh/publish)
├── publish-plan.json              the machine-readable plan (phase 0)
├── audit/                         reports — never committed
│   ├── privacy-report.md/.json
│   ├── license-report.md/.json
│   ├── images.md
│   └── verify-<repo>.json
├── <repo>/                        the exported working tree that gets pushed
└── .<repo>.gitee-source/          untouched clone when history=squash
```

---

## Phase 0 — Plan, and get consent

Publishing is irreversible in practice. Before touching anything, write down
what will be published and confirm it with the user:

- **which repositories** (name them explicitly — "the ones that look interesting"
  is not a list);
- **visibility** (public by default; `--private` per repo);
- **history**: `preserve` (keep the real log — only for a repo that is already
  clean) or `squash` (one clean-room commit — the safe default for a **private**
  Gitee repo, because history is where old secrets live);
- **primary language** of the README (default English on GitHub);
- the **known private names** to hunt for: your name, employer, colleague names,
  company domains (`--names`).

Write `publish-plan.json`:

```json
{
  "defaults": {
    "visibility": "public",
    "history": "squash",
    "primary_language": "en",
    "topics": ["kubernetes", "cli", "python"]
  },
  "repos": [
    {
      "gitee": "OWNER/example-tool",
      "github": "example-tool",
      "description_en": "One-line, keyword-rich, <=160 chars.",
      "description_zh": "一句话中文描述。",
      "homepage": "https://example.com",
      "screenshots": "auto",
      "notes": "squash: the repo contains a 2019 license-server experiment"
    }
  ],
  "audit": {
    "names": ["Your Name", "Example Corp"],
    "allow_emails": ["you@example.com"],
    "allow": [["pii-email", "docs/credits.md", "upstream attribution, approved"]]
  }
}
```

Confirm the plan with the user before phase 1. For a batch of repos, publish one
at a time and keep the report per repo; a failure in repo 3 must not roll back
repos 1–2.

## Phase 1 — Export from Gitee (read-only)

```bash
python3 scripts/gitee_repo.py whoami
python3 scripts/gitee_repo.py list --match <filter> --json audit/gitee-inventory.json
python3 scripts/gitee_repo.py inspect <owner>/<repo> --json audit/inspect-<repo>.json
python3 scripts/gitee_repo.py readme  <owner>/<repo> --out audit/<repo>-readme.original.md
python3 scripts/gitee_repo.py export  <owner>/<repo> --dest "$DSH_PUBLISH_HOME" --history squash
```

`inspect` answers the questions phase 2 needs: does a README exist, and in which
language? Gitee metadata is written to `<staging>/<repo>.gitee.json` (outside the
tree, so it cannot leak).

`export --history squash` copies the original clone to `.<repo>.gitee-source`
first and then builds a single orphan commit — the linked working tree of a
public GitHub repo should not carry a private development log. Never delete the
backup until the user has confirmed the published repository looks right.

Record the source URL for the README footer
(`https://gitee.com/<owner>/<repo>`), because the GitHub repo is a mirror and
readers should be able to find the original.

## Phase 2 — Bilingual README and top-level docs

Read `references/bilingual-readme.md`. Summary of the policy:

- `README.md` is **English**; `README.zh-CN.md` is **Chinese**; both start with a
  switcher linking to the other.
- If the Gitee repo has only one language, **write the other one** — translate
  faithfully, do not summarise, and keep code blocks, commands, tables and image
  paths byte-identical between the two files.
- If there is no README at all, create both from
  `assets/readme/README.en.md.tmpl` and `assets/readme/README.zh-CN.md.tmpl`.
- Translate the *content*, not the *structure*: heading counts, badge rows and
  section order must match so the two files stay parallel.
- Also handle the small docs users actually read: `INSTALL*`, `QUICKSTART*`,
  `docs/*.md` (at minimum their titles and the language switcher). Do not
  machine-translate a 200-page manual — say what was translated and what was not.

Then fill the placeholders from the plan and delete the `<!-- -->` guidance
comments.

## Phase 3 — Screenshots

A repository without a picture gets no clicks; a repository with a picture of the
author's own machine gets a leak. Both matter.

- Reuse images already in the Gitee repo when they are real product shots.
- Generate what is missing — see `references/promotion.md` for capture recipes:
  a web UI via the built-in browser, a CLI via a resized terminal window, a chart
  via a small demo script. Capture a **fresh, empty-data** session, never your
  working state.
- Save to `docs/images/` with descriptive kebab-case names
  (`dashboard-overview.png`, `cli-scan-output.png`), reference them with alt
  text, and caption them in both READMEs.
- Optimize before committing:

```bash
uv run --with pillow python3 scripts/optimize_images.py docs/images \
    --width 1600 --max-kb 500 --report audit/images.md
```

- Before the audit gate: open every screenshot and look for window titles,
  usernames in prompts, hostnames, paths, tokens in a terminal scrollback, browser
  tabs, avatars, and EXIF/GPS. Blur or re-capture; then re-run the optimizer,
  which strips metadata.

## Phase 4 — Privacy audit (GATE)

```bash
python3 scripts/privacy_audit.py "$DSH_PUBLISH_HOME/<repo>" \
    --config "$DSH_PUBLISH_HOME/publish-plan.json" \
    --names "Your Name" --names "Example Corp" \
    --report "$DSH_PUBLISH_HOME/audit/privacy-report.md" \
    --json   "$DSH_PUBLISH_HOME/audit/privacy-report.json"
```

Exit `3` blocks. Fix every `critical`/`high` finding, decide every `medium` one,
and never suppress a finding without writing the reason into the plan's `allow`
list. Read `references/privacy-audit.md` for the rule catalog, the placeholder
conventions and the playbook (rotate → fix tree → decide history → re-run).

**A clean tree is not a clean repository.** If the report names commits, the
secret is still in history: either publish a `squash` history, or rewrite with
`git filter-repo` and force-push *both* remotes, and rotate anything that leaked.

## Phase 5 — License and contribution compliance (GATE)

```bash
python3 scripts/license_check.py "$DSH_PUBLISH_HOME/<repo>" \
    --report "$DSH_PUBLISH_HOME/audit/license-report.md" \
    --json   "$DSH_PUBLISH_HOME/audit/license-report.json"
```

Exit `3` blocks on an `incompatible` combination or a missing outbound license.
Read `references/license-compliance.md`. In short:

- no LICENSE → choose one (the report recommends, driven by the dependencies);
- a copyleft dependency under a permissive project → relicense or replace;
- an upstream clone → keep the upstream LICENSE **and** add an attribution
  section; never relicense somebody else's code;
- vendor license artifacts (FlexLM/EDA) → remove, they are not yours to publish;
- add `CONTRIBUTING.md` stating the inbound=outbound rule and the sign-off
  expectation.

Copy the templates from `assets/community/` (see the placement table in
`references/promotion.md`), then substitute the placeholders.

## Phase 6 — Promotion and community files

Read `references/promotion.md`. The minimum that makes a repository look alive:
topic list (8–15), a keyword-rich description, a homepage when one exists, a
badge row, screenshots, a star CTA, `CONTRIBUTING.md` + `SECURITY.md` +
`CODE_OF_CONDUCT.md` + issue/PR templates, a CI workflow, and a first release
tag with notes. Then — and only then — consider announcing it.

Do not add a badge whose data does not exist yet: `release`, `CI` and `stars`
badges read as broken until the repository actually has a release, a workflow
run and a star.

## Phase 7 — Create and push (mutation)

Dry-run first, always. `--apply` is the only thing that writes to GitHub.

```bash
# 1. create (idempotent: an existing repo is reported, not touched)
python3 scripts/github_publish.py create \
    --repo <repo> --description "<EN description>" --homepage "<url>" \
    --topics <topic...>                     # add --private if the plan says so
python3 scripts/github_publish.py create ... --apply

# 2. push the branch and tags
python3 scripts/github_publish.py push --repo <repo> --dir "$DSH_PUBLISH_HOME/<repo>" --tags
python3 scripts/github_publish.py push --repo <repo> --dir "$DSH_PUBLISH_HOME/<repo>" --tags --apply
#    if git cannot reach github.com (mirror rewrite, blocked git endpoint), use
#    the REST API instead — same result, no git transport:
python3 scripts/github_publish.py push-api --repo <repo> --dir "$DSH_PUBLISH_HOME/<repo>" --apply

# 3. configure after the first push (topics, features, vulnerability alerts)
python3 scripts/github_publish.py configure --repo <repo> --topics <topic...> --apply

# 4. first release
python3 scripts/github_publish.py release --repo <repo> --tag v1.0.0 \
    --name "v1.0.0" --generate-notes --apply
```

Notes that matter:

- The token never reaches `.git/config`: `push` installs a throwaway
  `GIT_ASKPASS` helper for the single command.
- A `squash` export has one branch and no tags; `--tags` then does nothing, which
  is correct — inventing tags that never existed upstream is misleading.
- If the push is rejected for a workflow file, the token lacks the `workflow`
  scope: fix the token rather than dropping the CI file.
- Never `--force` a repository that already has stars, forks or releases. If a
  clean-room re-publish is genuinely required, delete the GitHub repository with
  the user's explicit confirmation instead of force-pushing over it.

## Phase 8 — Verify the published artifact (GATE)

```bash
python3 scripts/github_publish.py verify --repo <repo> --dir "$DSH_PUBLISH_HOME/<repo>" \
    --audit-config "$DSH_PUBLISH_HOME/publish-plan.json" \
    --report-dir "$DSH_PUBLISH_HOME/audit" --json "$DSH_PUBLISH_HOME/audit/verify-<repo>.json"
```

`--audit-config` is not optional in practice: the re-audit must judge the published
tree by the same rules the local scan used. Without it, a finding you deliberately
allowed (a documented example hostname, say) comes back as a blocker and the
repository can never pass its own verification.

`verify` checks, against the **remote** state: default branch, description,
topics, GitHub's own license detection, visibility, the published file list
against the local one, the presence of **both** READMEs, that every README image
target actually exists in the repository, and — the important one — it clones the
published repository and re-runs the privacy audit on that clone.

If that re-audit is `blocked`: rotate the credential, rewrite history, force-push,
and then ask GitHub Support to purge cached views. Assume forks and the events
API may keep the old object; the only reliable remediation is rotation.

## Phase 9 — Report and hand off

```bash
python3 scripts/publish_report.py "$DSH_PUBLISH_HOME" --repo <repo> --out "$DSH_PUBLISH_HOME/audit/report-<repo>.html"
```

Then open the HTML report in the built-in browser to check it visually. The report
exists to make the remaining human decisions obvious: unresolved `medium`
findings, license questions, missing promotion items, and the "what you still
have to do" list (social preview image, homepage, announcement, upstream
attribution wording).

Finally, tell the user plainly:

- the GitHub URL and the visibility;
- which gates passed and which findings were accepted, with reasons;
- what was **not** verified (see "What the scanner cannot see" in
  `references/privacy-audit.md`);
- the mirror/attribution statement added to the README.