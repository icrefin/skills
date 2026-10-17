# Privacy audit — the gate before publication

`scripts/privacy_audit.py` decides whether a repository may become public. This
document describes what the scanner actually implements: the catalog below is
generated from its `RULES` tuple, so ids, severities and categories match the code
exactly. Where the implementation is narrower than the intent, it says so.

## 1. Why this is a gate, not a report

Publishing is a **one-way door**: a secret that reaches a public GitHub object can be
scraped, forked and indexed before you notice, and deleting the commit does not
recall the copies. The scanner ends in a verdict, not a summary:

| Verdict | Severity of the findings | Exit code | What it means |
| --- | --- | --- | --- |
| **BLOCKED** | any `critical` or `high` | `3` | Do not publish. Rotate and fix, then re-run. |
| **CLEAR TO PROCEED** | only `medium` / `low` / `info` | `0` | Publishable, but `medium` is a human decision. |

`low` and `info` never block — they let the reviewer see the whole picture without
the scanner pretending to judge intent. `medium` is left to a person: whether an
email in a LICENSE file is attribution or a leak depends on context. Other codes:
`1` error, `2` usage (the path is not a directory). `--quiet` suppresses the
per-finding console lines only; the Markdown and JSON reports stay complete.

## 2. What is scanned

| Surface | How it is collected |
| --- | --- |
| Tracked files | `git ls-files -z` |
| Untracked, not ignored files | `git ls-files -z --others --exclude-standard` |
| File **names** | matched against the `filename_glob` rules (a tracked `id_rsa` is a finding even when its bytes are opaque) |
| `.git/config`, `.gitmodules` | read directly, for credentials in remote/submodule URLs |
| Commit identities | `git log --all --format=%an <%ae>\|%cn <%ce>` across all reachable history |
| History patches | `git log --all -p --no-color -U0`, searched for `critical` rule shapes only |
| Live token values | the resolved `GITHUB_TOKEN` and `GITEE_TOKEN` strings themselves, searched in every scanned file |

Contents are read only when a file is at most 4 MiB and has no NUL byte in its first
8192 bytes; larger or binary files count as skipped but their **names** are still
checked (the note marks that finding `name-only`). Skipped directories: `.git`,
`node_modules`, `vendor`, `dist`, `build`, `.venv`, `venv`, `__pycache__`,
`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `target`, `.next`, `site-packages`.
If `git ls-files` returns nothing, the scanner warns and walks the filesystem instead.

### The `--history` rule

| Mode | Behaviour |
| --- | --- |
| `--history auto` (default) | Identities always; the patch walk covers the newest `PATCH_SCAN_CAP` (2000) commits on a longer history. `history_mode` then reports which it was, e.g. `auto (newest 2000 of 8421 commits)` or `auto (all 12 commits)`. |
| `--history on` | Identities plus patches for **every** commit, however long the history. Reports `on (all N commits)`. |
| `--history off` | No identity or patch scan at all; the report shows `history_mode off`. |

The cap bounds only the expensive `git log -p` walk. The **identity** scan is never
capped, because an author email from the first commit is exactly the leak a bounded
scan would miss. `history_mode` is printed in the console summary, in the report's
coverage line and in the JSON's `coverage.history_mode`, so a capped run is always
visible rather than silently partial — if the history is the risk and it exceeds the
cap, re-run with `--history on`.

## 3. The rule catalog

Every row is one `Rule` in `RULES`; "placeholder" is the rule's own `placeholder`
field, the value the report tells you to write instead.

### credential (14 rules)

| rule id | severity | category | what it catches | placeholder to use instead |
| --- | --- | --- | --- | --- |
| `secret-private-key-block` | critical | credential | PEM / OpenSSH private key material (`-----BEGIN ... PRIVATE KEY-----`) | `<YOUR_PRIVATE_KEY>` |
| `secret-github-token` | critical | credential | GitHub personal access token (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`) | `<YOUR_GITHUB_TOKEN>` |
| `secret-github-fine-grained` | critical | credential | GitHub fine-grained token (`github_pat_…`) | `<YOUR_GITHUB_TOKEN>` |
| `secret-aws-access-key` | critical | credential | AWS access key id (`AKIA…` / `ASIA…`) | `<YOUR_AWS_ACCESS_KEY_ID>` |
| `secret-aws-secret` | critical | credential | AWS secret access key in an assignment | `<YOUR_AWS_SECRET_ACCESS_KEY>` |
| `secret-openai-style` | critical | credential | LLM / SaaS API key (`sk-…`, `sk-proj-…`, `sk-ant-…`, `sk-live-…`) | `<YOUR_API_KEY>` |
| `secret-google-api-key` | critical | credential | Google API key (`AIza…`) | `<YOUR_GOOGLE_API_KEY>` |
| `secret-slack-token` | critical | credential | Slack token (`xoxa-`, `xoxb-`, `xoxp-`, `xoxr-`, `xoxs-`) | `<YOUR_SLACK_TOKEN>` |
| `secret-jwt` | critical | credential | JSON Web Token (three `eyJ…` dot-separated segments) | `<YOUR_JWT>` |
| `secret-credential-in-url` | critical | credential | Credentials embedded in a URL (`https://user:pass@host`) | `https://user:<YOUR_PASSWORD>@host/` |
| `secret-live-token` | critical | credential | The live `GITHUB_TOKEN` / `GITEE_TOKEN` value appears in the tree (injected at runtime, no regex) | `<YOUR_TOKEN>` |
| `secret-generic-assignment` | high | credential | Hard-coded secret in an assignment (`password = "…"`, `api_key: "…"`) | `<YOUR_API_KEY>` / `<YOUR_PASSWORD>` |
| `secret-hex-with-context` | high | credential | A 16–64 character hex blob next to `key`/`token`/`license`/`hostid`/`serial`/`sn` | `<YOUR_KEY>` |
| `secret-gitee-token-inline` | high | credential | Gitee access token in an inline query string (`?access_token=…`) | `<YOUR_GITEE_TOKEN>` |

### legal (3 rules)

| rule id | severity | category | what it catches | placeholder to use instead |
| --- | --- | --- | --- | --- |
| `secret-flexlm-license` | critical | legal | FlexLM / EDA license text: `INCREMENT`/`FEATURE` lines, a `SERVER` line with a 12-hex-digit hostid, `*_LICENSE_FILE` variables, `HOSTID` | `<YOUR_LICENSE_SERVER>` |
| `secret-eda-license-artifact` | high | legal | EDA license-manager artifact: `lmutil`, `lmgrd`, `snpslmd`, `cdslmd`, `mgcld`, `saltd`, `elmd`, `cksum=`, `ck=<hex>` | `<YOUR_LICENSE_COMMAND>` |
| `file-eda-license` | critical | legal | Vendor license **file**: `*.lic`, `*.flexlm`, `license.dat`, `licfile*`, `*_license.dat`, `*.v2c`, `lmutil*`, `lmgrd*`, `snpslmd*`, `cdslmd*`, `*.scl` | `<YOUR_LICENSE_FILE>` |

### identity (8 rules)

| rule id | severity | category | what it catches | placeholder to use instead |
| --- | --- | --- | --- | --- |
| `pii-home-path` | high | identity | Absolute path exposing a user or machine name (`/Users/x`, `/home/x`, `C:\Users\x`) | `/home/you/` · `/Users/you/` · `C:\Users\you\` |
| `pii-chinese-id` | high | identity | Chinese resident ID number that passes the checksum (validated in code, not by a bare regex) | `<YOUR_ID_NUMBER>` |
| `pii-chinese-phone` | medium | identity | Chinese mobile number (`1[3-9]` + 9 digits) | `+86 138 0000 0000` |
| `pii-intl-phone` | medium | identity | International phone number (`+CC …`) | `+1 555 010 0000` |
| `pii-email` | medium | identity | Email address | `you@example.com` |
| `pii-company-marker` | medium | identity | Confidentiality marker: `confidential`, `internal use only`, `do not distribute`, `trade secret`, 版权所有, 内部资料, 内部使用, 机密, 严禁外传, 仅供内部 | *(remove the marker)* |
| `pii-copyright-holder` | info | identity | Copyright holder named in a source file or LICENSE | `Copyright (c) 2026 Your Name` |
| `pii-absolute-volume-path` | low | identity | Machine-specific mount or drive path (`/mnt/…`, `/data/…`, `D:\…`–`Z:\…`) | `/path/to/data` |

### network (7 rules)

| rule id | severity | category | what it catches | placeholder to use instead |
| --- | --- | --- | --- | --- |
| `net-private-ipv4` | high | network | RFC1918 (`10.`, `192.168.`, `172.16–31.`), link-local `169.254.`, CGNAT `100.64–127.` | `192.0.2.10` (RFC 5737 documentation range) |
| `net-private-ipv6` | high | network | Unique-local (`fc00::/7`) and link-local (`fe80::`) IPv6 | `2001:db8::1` (RFC 3849 documentation range) |
| `net-internal-host` | high | network | Internal hostname or private TLD (`.local`, `.internal`, `.intranet`, `.lan`, `.corp`, `.home`, `.localdomain`, `.localnet`, `.home.arpa`). RFC 2606/6761 names — `.test`, `.invalid`, `.example`, `.localhost` — are deliberately **not** matched: they are the placeholder forms this skill tells you to use, and matching them fired on ordinary code such as `i.test(url)` | `host.example.com` |
| `net-unc-path` | high | network | Windows UNC / network share path (`\\server\share`) | `\\server\share` |
| `net-mac-address` | medium | network | MAC address, colon- or dash-separated | `00:00:5E:00:53:00` (RFC 7042 documentation MAC) |
| `net-public-ipv4` | medium | network | Public IPv4 address | `203.0.113.10` (RFC 5737 documentation range) |
| `net-ssh-target` | medium | network | Concrete SSH target (`ssh user@host`), excluding `example.`, `github.com`, `gitee.com`, `gitlab.com` | `ssh user@host.example.com` |

### file (4 rules)

| rule id | severity | category | what it catches | placeholder to use instead |
| --- | --- | --- | --- | --- |
| `file-private-key` | critical | file | Private key or keystore file: `id_rsa*`, `id_dsa*`, `id_ecdsa*`, `id_ed25519*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `*.ppk`, `*.asc`, `*.gpg` | `<YOUR_PRIVATE_KEY_FILE>` |
| `file-env` | high | file | Real environment / dotenv file: `.env`, `.env.*`, `*.env`, `env.local`, `.envrc` (names containing `example`, `sample`, `template` or `dist` are exempt) | `.env.example` |
| `file-secret-store` | high | file | Secret store or credential dump: `*secret*`, `*credential*`, `*token*`, `*password*`, `*.kdbx`, `*_rsa`, `known_hosts`, `*.netrc`, `_netrc`, `.npmrc`, `.pypirc`, `.git-credentials` | `<YOUR_SECRETS>` |
| `file-archive-or-binary` | low | file | Archive or compiled artifact committed to the tree: `*.zip`, `*.tar.gz`, `*.tgz`, `*.7z`, `*.rar`, `*.exe`, `*.dll`, `*.so`, `*.dylib`, `*.jar`, `*.whl`, `*.bin`, `*.img`, `*.iso` | `<YOUR_ARTIFACT>` |

### Findings that are not `RULES` rows

| rule id | severity | category | produced by |
| --- | --- | --- | --- |
| `pii-named-entity` | high | identity | `--names` / the config's `names`: every file containing the operator-supplied name (one finding per file; names under 3 characters are ignored) |
| `history-commit-identity` | medium | identity | every distinct author/committer identity in history |
| *(a `critical` rule id)* | **high** | the rule's own category | a history patch matched a `critical` pattern; severity is forced to `high`, and the snippet lists up to five commit hashes |

### Why these

- **FlexLM / EDA license material** is not yours to redistribute: a vendor license is
  issued to a specific party, names internal infrastructure, and publishing it can
  breach a contract. `HOSTID` and `SERVER <host> <12-hex>` are license locks, not
  credentials — but they identify the machine the license was issued to.
- **MAC addresses** are usually a *hardware license lock* rather than a networking
  detail, and are personal data in some jurisdictions — hence `medium`.
- **Private IP space is split three ways** (RFC1918, CGNAT `100.64.0.0/10`,
  link-local `169.254.0.0/16`) because all three describe a real internal topology;
  IPv6 likewise for `fc00::/7` and `fe80::`.
- **The Chinese resident ID rule validates the ISO 7064 MOD 11-2 checksum** before
  reporting, so an arbitrary 18-digit number is not a finding — which keeps a `high`
  severity meaningful instead of noisy.
- **`audit:allow`** suppresses one true-but-harmless line without disabling a rule
  repository-wide (§4).
- **A deleted file still lives in history.** The patch scan exists for exactly that: a
  credential committed and later removed is still published by the history you push. A
  clean working tree is not a clean repository.

Allowlists that cut false positives: `127.`/`0.`/`255.255.255.255`, the three RFC 5737
documentation ranges, `10.0.2.`, `1.2.3.4`, `8.8.8.8`, `1.1.1.1`; the documentation
MAC prefixes `00:00:5e:00:53:`, `ff:ff:ff:ff:ff:ff`, `00:00:00:00:00:00`,
`de:ad:be:ef`; `@example.com|org|net`, `*.example`, `localhost`,
`users.noreply.github.com`; the home-path users `you`, `user`, `username`, `yourname`,
`example`, `runner`, `me`, `someone`; and any value that already looks like a
placeholder (under 6 characters, or containing `<…>`, `{{`, `${`, `your_`, `example`,
`changeme`, `redacted`, `xxx`, `dummy`, `sample`, `fake`, `getenv`, `environ`,
`process.env`, `vault`, `op://`, `null`, `none`, `nil`, `true`, `false`).

## 4. Suppressing a finding on purpose

**1. An inline comment.** `# audit:allow <rule-id>` on the finding's line or the line
directly above it suppresses that rule there; several ids may be listed, and `all` (or
`*`) covers every rule on the line:

```python
PUBLIC_ENDPOINT = "203.0.113.10"  # audit:allow net-public-ipv4
# audit:allow pii-email, pii-chinese-phone
CONTACT = "you@example.com"
```

This works for the **line-pattern rules only**. File-name rules, the live-token check,
the `.git/config` check, the `--names` search and every history finding ignore it —
suppress those with `allow` or `exclude`. (The `names` search is the exception: it
skips a line containing `audit:allow`.)

**2. `publish-audit.json`**, passed with `--config`:

| key | shape | effect |
| --- | --- | --- |
| `names` | `["Example Corp", "张三"]` | names treated as leaks by `pii-named-entity`; merged with `--names` |
| `allow_emails` | `["me@my-company.com"]` | addresses never reported by `pii-email` (case-insensitive) |
| `allow` | `[["pii-email", "LICENSE", "attribution"]]` | `[rule, glob, reason]`: skip files matching the glob for that rule. The rule may be `"*"`; the glob is matched with `fnmatch` against the repository-relative path. |
| `exclude` | `["docs/legacy/**"]` | skip matching paths entirely; counted as skipped, never scanned |
| `severity_overrides` | `{"pii-email": "info"}` | rewrite one rule's severity for this repository |

```json
{"allow_emails": ["maintainer@example.com"],
 "allow": [["pii-company-marker", "LICENSE", "verbatim upstream license text"]],
 "exclude": ["third_party/**"], "severity_overrides": {"pii-copyright-holder": "info"}}
```

```bash
python3 scripts/privacy_audit.py <repo> --config publish-audit.json \
    --report audit/privacy-report.md --json audit/privacy-report.json
```

**Suppression must be recorded, not silent.** The scanner stores each `allow` entry's
`reason` but never prints it, and `severity_overrides` leaves no trace in the report.
The audit trail is therefore yours: write the rule id, location, reason and approver
into the audit report (or a companion `audit/suppressions.md`) next to the scan it
belongs to. A report with fewer findings than the previous run, and no record of why,
is an unaudited report.

## 5. The remediation playbook

Rotating a credential is urgent; editing the tree is not.

1. **Rotate first.** A leaked credential is compromised the moment it is public.
   Revoke or rotate it at the provider *before* deciding how to remove it.
2. **Fix the working tree.** Delete what must not ship (vendor licenses, keys,
   `.env`, credential dumps) and replace values with the placeholders in §6; commit a
   `.env.example` instead of a real `.env`.
3. **Decide history.** If the report names history or a commit, a clean tree is not
   enough — publish a **clean-room history** or **rewrite** it:

   ```bash
   git checkout --orphan clean-room        # one commit, no upstream history
   git add -A && git commit -m "Publish example-tool"
   git filter-repo --replace-text replacements.txt   # or rewrite in place
   ```

   `--replace-text` takes one `literal==>replacement` per line. A rewrite means a
   force-push **and** a rotation — rewriting alone does not un-leak a value.
4. **Tell the reader.** Paste the notice from `assets/community/PLACEHOLDER-NOTICE.md`
   into both READMEs so a user knows which values are theirs to fill in.
5. **Re-run on the tree you are about to push**, then again on the published artifact
   (§8):

   ```bash
   python3 scripts/privacy_audit.py <repo> --report audit/privacy-report.md --json audit/privacy-report.json
   ```

The report enumerates the values it found, so keep it in the staging directory or a
git-ignored `audit/` folder — committing it would leak what it documents.

## 6. Placeholder conventions

The RFC-reserved ranges exist so an example is obviously an example.

| What | Use this instead |
| --- | --- |
| API key / token | `<YOUR_API_KEY>`, `<YOUR_TOKEN>`, `<YOUR_GITHUB_TOKEN>` |
| Password | `<YOUR_PASSWORD>` |
| Private key | `<YOUR_PRIVATE_KEY>` (and rotate the real one) |
| Email | `you@example.com` |
| Personal / company name | `Your Name`, `Example Corp`, `示例公司` |
| Private IPv4 | `192.0.2.10` (RFC 5737 `192.0.2.0/24`) |
| Public IP / server | `203.0.113.10` (RFC 5737 `203.0.113.0/24`) or `your-server.example.com` |
| IPv6 | `2001:db8::1` (RFC 3849 `2001:db8::/32`) |
| Hostname | `host.example.com` (and `198.51.100.0/24` for a second IPv4 example) |
| MAC address | `00:00:5E:00:53:00` (RFC 7042 `00:00:5E:00:53:xx`) |
| Home directory | `~` · `/home/you/` · `<YOUR_WORKSPACE>` |
| Phone | `+1 555 010 0000` · `+86 138 0000 0000` |
| National ID | `<YOUR_ID_NUMBER>` |
| License server / EDA license | `<YOUR_LICENSE_SERVER>` |
| Serial / hostid | `<YOUR_SERIAL>` |

Matched values are **masked** wherever the tool renders them: `mask()` keeps the first
four characters, replaces the rest with up to 24 asterisks and appends `(len N)`;
file-name findings keep two characters. The exception is a history identity, printed
as git records it (`Name <email> × N`) — that is the finding itself, so treat the
report as sensitive. Optimize and strip screenshots before committing them:

```bash
python3 scripts/optimize_images.py docs/images --report audit/images.md
```

## 7. What the scanner cannot see

The audit is a text scanner with a fixed catalog: it cannot read intent and does not
open binaries. It will not catch **text inside images** (a screenshot with a token,
hostname or username in the scrollback, or a UI shot showing a window title (窗口标题),
user name (用户名) or filesystem path (路径) — re-capture with a clean session, cropping
is not a fix); **content inside committed binaries and archives**
(`file-archive-or-binary` flags the file at `low`, but a `.zip`, `.jar`, `.whl`, `.bin`
or PDF can hide credentials no text scan reaches); **a value sensitive only in
context** (an internal codename, a customer list, a private repo name in a URL, a
build number that maps to a release); **data already published** (if the repository, a
fork, a mirror or a package index carries the value, a clean tree changes nothing and
only rotation helps); **a dependency's own metadata** (outside the scanned tree —
check the license report's inventory); and **anything an allowlist masks** (the safe
ranges in §3 are heuristics: a real production host inside a documentation range
passes silently).

| Extra manual check | Why |
| --- | --- |
| Open each committed binary / archive / PDF | the text scan does not go inside |
| Inspect every screenshot for 窗口标题 / 用户名 / 路径 and tokens in scrollback | the most common real leak |
| Check `docs/` and every other image folder, not just the README | images are added late and audited never |
| Check notebook outputs (`.ipynb`) | outputs embed paths, tokens, data frames and hostnames |
| Read the diff since the last audit | only the change is new, and only the change is unscanned |

## 8. The published-tree re-audit

**The local tree is not the artifact.** What a stranger clones can differ from what
you audited — a file left out of the commit, an image committed to another path, a
`.gitignore` that hid something locally but not in the published tree:

```bash
python3 scripts/github_publish.py verify --repo <owner>/<repo> --dir <staging-dir> \
    --report-dir audit --json audit/verify.json
```

`verify --reaudit` is **on by default** (`--no-reaudit` disables it). It clones the
published repository with `--depth 50`, runs the same scanner against the clone with
`--quiet`, and folds the result into the verification report:

| Result | Meaning | Action |
| --- | --- | --- |
| `ok` | the clone's audit exited `0` | done; archive the published-tree report |
| `blocked` | the clone's audit exited `3` — the **public** tree has findings | rotate, rewrite and force-push, then purge caches (below) |
| `warn` | the clone failed or the scanner errored | fix the tooling and re-run; this is not a pass |

`--depth 50` means that scan sees only the last 50 commits: a leak deeper in the
history will **not** appear here. If history depth is part of the risk, run the
scanner against a full clone yourself before trusting `ok`.

When the published-tree scan is `blocked`:

1. **Rotate** the credential — assume it was scraped the moment the push landed.
2. **Rewrite history** (`git filter-repo --replace-text`) and **force-push**.
3. **Ask GitHub Support to purge cached views**, and accept that you cannot fully undo
   it: **forks keep their own copy of the old object**, and the events API and
   third-party mirrors may retain it. Purging the default branch does not purge a fork.
4. **Re-run `verify`** and record the outcome. Only a fresh `ok` on a full clone
   closes the item.

Findings from the clone go to `privacy-report-published.md` /
`privacy-report-published.json` under `--report-dir`; without that flag the temporary
clone and its reports are deleted.