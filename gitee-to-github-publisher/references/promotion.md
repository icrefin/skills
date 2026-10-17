# Repository promotion reference (README badges, topics, releases, outreach)

Operational checklist for taking a sanitized repository that already exists on GitHub
(`{{FULL_NAME}}`) and making it discoverable and creditable. Every snippet is
copy-pasteable; replace `{{...}}` placeholders first. Nothing here requires paid tools.

## 1. README badge catalog

Put badges in one block, directly under the H1 and the one-line description: five to eight
maximum, `?style=flat-square` throughout. A wall of fifteen is noise.

| Badge | Markdown |
| --- | --- |
| License | `[![License](https://img.shields.io/github/license/{{OWNER}}/{{REPO}}?style=flat-square)](LICENSE)` |
| Language | `[![Language](https://img.shields.io/github/languages/top/{{OWNER}}/{{REPO}}?style=flat-square)](#)` |
| Release | `[![Release](https://img.shields.io/github/v/release/{{OWNER}}/{{REPO}}?style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/releases)` |
| CI | `[![CI](https://img.shields.io/github/actions/workflow/status/{{OWNER}}/{{REPO}}/ci.yml?branch={{DEFAULT_BRANCH}}&style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/actions/workflows/ci.yml)` |
| Last commit | `[![Last commit](https://img.shields.io/github/last-commit/{{OWNER}}/{{REPO}}?style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/commits/{{DEFAULT_BRANCH}})` |
| Stars | `[![Stars](https://img.shields.io/github/stars/{{OWNER}}/{{REPO}}?style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/stargazers)` |
| PRs welcome | `[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](CONTRIBUTING.md)` |
| Platform | `![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20Windows-blue?style=flat-square)` |

Paste-ready block (edit the platform line, delete what you cannot support):

```markdown
[![License](https://img.shields.io/github/license/{{OWNER}}/{{REPO}}?style=flat-square)](LICENSE)
[![Release](https://img.shields.io/github/v/release/{{OWNER}}/{{REPO}}?style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/{{OWNER}}/{{REPO}}/ci.yml?branch={{DEFAULT_BRANCH}}&style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/actions/workflows/ci.yml)
[![Last commit](https://img.shields.io/github/last-commit/{{OWNER}}/{{REPO}}?style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/commits/{{DEFAULT_BRANCH}})
[![Stars](https://img.shields.io/github/stars/{{OWNER}}/{{REPO}}?style=flat-square)](https://github.com/{{OWNER}}/{{REPO}}/stargazers)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](CONTRIBUTING.md)
![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macOS%20%7C%20Windows-blue?style=flat-square)
```

Extra badges, only when the underlying fact exists:

| Badge | Markdown |
| --- | --- |
| PyPI version | `[![PyPI](https://img.shields.io/pypi/v/{{REPO}}?style=flat-square)](https://pypi.org/project/{{REPO}}/)` |
| npm version | `[![npm](https://img.shields.io/npm/v/{{REPO}}?style=flat-square)](https://www.npmjs.com/package/{{REPO}})` |
| Downloads | `![Downloads](https://img.shields.io/github/downloads/{{OWNER}}/{{REPO}}/total?style=flat-square)` |
| Issues | `![Issues](https://img.shields.io/github/issues/{{OWNER}}/{{REPO}}?style=flat-square)` |
| Contributors | `![Contributors](https://img.shields.io/github/contributors/{{OWNER}}/{{REPO}}?style=flat-square)` |
| Docs | `[![Docs](https://img.shields.io/badge/docs-{{HOMEPAGE}}-informational?style=flat-square)]({{HOMEPAGE}})` |

Star-history chart (an image, not a badge; only add it once you have real stars):

```markdown
[![Star History Chart](https://api.star-history.com/svg?repos={{OWNER}}/{{REPO}}&type=Date)](https://star-history.com/#{{OWNER}}/{{REPO}}&Date)
```

Badge hygiene: the CI badge must point at the real workflow file name (`ci.yml`) — a broken
badge is worse than none. Static badges use the three-segment form
`.../badge/<label>-<message>-<color>` (`-` between segments, `_` for spaces, `%20` for dashes).

## 2. Description, homepage, topics

**Description** (the field next to the repo name): keyword-rich, ≤160 characters, no
marketing adjectives or emoji, front-loading the searchable nouns and the differentiator.

| Bad | Why |
| --- | --- |
| `An awesome project 🚀` | No keyword, no category, ranks for nothing |
| `{{REPO}}` | Repeats the name, says nothing about function |
| `Publish a Gitee repository to GitHub: sanitize, add community files, rewrite links, push with CI and badges.` | Names the action, the platforms, and the deliverables — matches real queries |

Chinese description (use it in the Gitee mirror and the Chinese README half):
`把 Gitee 仓库发布到 GitHub：脱敏、补齐社区文件、重写链接、推送并带上 CI 与徽章。`

**Homepage**: set it to the strongest single URL you control — docs site, demo, or the
package page. Never leave it pointing at the GitHub repo itself. If you have no docs
site yet, use the Chinese mirror or leave it empty; a dead link is worse.

**Topics**: 8–15, lowercase, hyphenated, ordered by importance. They are the strongest
on-site discovery signal after the description.

| Slot | Rule | Examples |
| --- | --- | --- |
| 1–2 Language / runtime | The exact technology | `python`, `typescript` |
| 3 Ecosystem tooling | Framework or package manager | `uv`, `pnpm`, `cli` |
| 4–6 Category | What kind of tool it is, using words people search | `migration`, `git`, `devtools` |
| 7–9 Domain keywords | The problem it solves | `repository-management`, `github-actions` |
| 10–12 Integrations | Platforms and providers it talks to | `gitee`, `github-api` |
| 13–15 Audience / qualities | Only if honest | `open-source`, `bilingual`, `self-hosted` |

Reject topics that are irrelevant, already implied by the language, or that no one
browses. Cap at 15 — GitHub silently drops extras.

```bash
# Simplest path (mutually exclusive with the API call below for the same field):
gh repo edit {{OWNER}}/{{REPO}} \
  --description "Publish a Gitee repository to GitHub: sanitize, add community files, rewrite links, push with CI and badges." \
  --homepage "{{HOMEPAGE}}" \
  --add-topic python --add-topic git --add-topic migration --add-topic github-actions

# Replace the whole topic list (PUT), useful for keeping it identical across mirrors:
gh api -X PUT repos/{{OWNER}}/{{REPO}}/topics \
  -f names[]=python -f names[]=cli -f names[]=git -f names[]=migration \
  -f names[]=github-actions -f names[]=gitee -f names[]=devtools
```

## 3. Social preview image (1280×640)

When the repo link is shared on X, Slack, Discord, or WeChat, GitHub renders the social
preview card. Upload yours in **Settings → General → Social preview → Upload image**.
Requirements: PNG or JPG, ≥640×320, 1280×640 recommended, ≤1 MB. Design for the thumbnail:
one readable title, the tool logos, and your handle in a corner, kept inside the central 80%.

There is no stable public API for uploading it: `PATCH /repos/{owner}/{repo}` has no social
preview field, and the web upload endpoint is internal and unsupported. Upload it by hand.

Generate the PNG from a vector or HTML source, then check it at 320 px wide:

```bash
# Option A: hand-written SVG -> PNG (rsvg-convert, from librsvg)
rsvg-convert -w 1280 -h 640 social-preview.svg -o social-preview.png

# Option A': resvg (crisper text, respects fontconfig)
resvg --width 1280 --height 640 social-preview.svg social-preview.png

# Option B: HTML/CSS template -> PNG via headless Chromium (best fonts and gradients)
npx playwright screenshot --viewport-size=1280,640 --wait-for-timeout=800 \
  social-preview.html social-preview.png
```

SVG skeleton to start from (swap the title and colors, keep the 1280×640 viewBox):

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640">
  <rect width="1280" height="640" fill="#0d1117"/>
  <text x="80" y="300" font-family="Inter, Helvetica, sans-serif" font-size="86"
        font-weight="700" fill="#ffffff">{{REPO}}</text>
  <text x="80" y="380" font-family="Inter, Helvetica, sans-serif" font-size="36"
        fill="#8b949e">{{DESC_EN}}</text>
  <text x="80" y="560" font-family="Inter, Helvetica, sans-serif" font-size="30"
        fill="#58a6ff">github.com/{{FULL_NAME}}</text>
</svg>
```

Commit the source (`social-preview.svg` or `.html`) so the card is reproducible; the PNG
itself lives only in the GitHub settings, not in the repository.

## 4. Star call-to-action (copy bank)

Ask once, in plain language, near a point where the reader has just seen value. A second
ask immediately below is fine; a banner every section is not.

| Position | Why it works |
| --- | --- |
| Top, right after the badges | Seen by everyone, including people who will not scroll |
| After the features / demo section | The reader has just understood the value |
| Bottom, immediately before `## License` | Catches the reader who read everything |

English:

- "If this project helps you, please consider giving it a ⭐ star — it helps others find it."
- "Found this useful? A star costs nothing and helps the project get discovered."
- "If {{REPO}} saved you time, star it so the next person finds it faster."
- "Stars are how small projects survive. If this one earned yours, tap ⭐ above."

中文：

- "如果这个项目对你有帮助，欢迎点一个 ⭐ Star，让更多人看到它。"
- "觉得好用的话，顺手点个 Star 就是最大的支持。"
- "如果 {{REPO}} 帮你省下了时间，欢迎 Star 一下，让下一个人更快找到它。"
- "点 Star 不花钱，但能让这个项目被更多人发现。"

Rules: put the CTA in a blockquote or plain paragraph, never in an image, never in the first
line, and never as a fake issue or PR. Do not ask for stars in other people's repositories,
and attach it to release notes at most once. Translate it in the Chinese half of the README.

## 5. Community health files and what GitHub does with them

Community files are read by GitHub only from the repository root, `.github/`, or `docs/`. Put
them under `.github/` so the root stays clean. Rows marked *template* ship with this skill.

| File | Location | What GitHub surfaces |
| --- | --- | --- |
| `README.md` | root (or `.github/`) | Repo landing page; the only file people reliably read |
| `LICENSE` / `LICENSE.md` | root | License label on the repo page; `github/license` badge |
| `CONTRIBUTING.md` *(template)* | `.github/` | "Contributing" link on new issues and PRs, and on the repo's Community tab |
| `CODE_OF_CONDUCT.md` *(template)* | `.github/` | "Code of conduct" link in the Community tab; required by some awesome-lists |
| `SECURITY.md` *(template)* | `.github/` | "Report a vulnerability" button under Security, plus a private advisory flow |
| `SUPPORT.md` | `.github/` | "Support" resource link in the Community tab |
| `GOVERNANCE.md`, `MAINTAINERS.md` | `.github/` or root | Not surfaced by GitHub, but read by contributors |
| `PULL_REQUEST_TEMPLATE.md` *(template)* | `.github/` | Pre-fills every new PR body |
| `ISSUE_TEMPLATE/*.yml` *(templates)* | `.github/ISSUE_TEMPLATE/` | The structured issue chooser; fields become labels and required input |
| `ISSUE_TEMPLATE/config.yml` *(template)* | `.github/ISSUE_TEMPLATE/` | Disables blank issues, adds contact links |
| `CITATION.cff` *(template)* | root | Adds a "Cite this repository" button — only if the software is citable |
| `CHANGELOG.md` | root | Not surfaced, but linked from releases by convention |
| `.github/FUNDING.yml` | `.github/` | Sponsor button (needs a real funding account) |
| `CODEOWNERS` | `.github/`, root, or `docs/` | Auto-requests reviewers on PRs |

Check the result at `https://github.com/{{OWNER}}/{{REPO}}/community` — GitHub scores the
checklist there. A five-of-five Community Profile is the difference between a repository
that looks maintained and one that looks abandoned.

## 6. Releases, tags, and CHANGELOG

Tag with annotated semver tags; releases are what people watch and what badges read.

```bash
# 1. Land everything, then tag an annotated release (vMAJOR.MINOR.PATCH).
git switch {{DEFAULT_BRANCH}} && git pull --ff-only
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0

# 2. Create the release with GitHub's generated notes (PR titles since the last tag).
gh release create v0.1.0 --title "v0.1.0" --generate-notes

# 3. Pre-release for testing; `latest` is never moved to a prerelease.
gh release create v0.2.0-rc.1 --prerelease --generate-notes

# 4. Attach build artifacts and checksums.
gh release upload v0.1.0 dist/*.whl dist/*.tar.gz
```

Auto-generated notes come from merged PR titles, categories from
`.github/release.yml` labels. Point people at the real notes, not at raw commits.

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
semantic versioning. One entry per release, newest first, grouped under the standard
headings. Write it for users, not for git log.

```markdown
# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - {{YEAR}}-01-01

### Added
- Initial public release.

### Fixed
- Correct the CI badge branch.

[Unreleased]: https://github.com/{{OWNER}}/{{REPO}}/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/{{OWNER}}/{{REPO}}/releases/tag/v0.1.0
```

Standard headings, in this order: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`,
`Security`. Rule: the first public release is `0.1.0`, never `1.0.0` unless you are
committing to a stable API. Automate the changelog with `git-cliff`, `release-drafter`, or
`commit-and-tag-version` if you follow Conventional Commits — GitHub does not require any
particular commit convention.

## 7. Outreach channels that actually work

Ranked by effort-to-return for a small tool. Do one channel per week, and only after the
repository has a README, license, CI, and at least one release — a half-finished repo gets
one look. In every channel: disclose that you are the author.

| Channel | How to use it | Expected effect |
| --- | --- | --- |
| Awesome-lists | Find the list, read its `CONTRIBUTING.md`, open one PR adding your line to the right section, in alphabetical order, with a one-sentence reason | Steady trickle of qualified visitors for years |
| Reddit `r/opensource` | Post a short "I built X to solve Y" text post; answer questions same day | Modest, engaged traffic |
| Reddit `r/programming` | Only if genuinely substantial; heavy moderation, strict self-promo rules | Rare but large spikes |
| Hacker News `Show HN` | Title `Show HN: {{REPO}} – <what it does>`; post Tuesday–Thursday, 08:00–10:00 US Eastern; reply to every comment | Highest variance; often zero, occasionally thousands |
| V2EX `分享创造` | Post in Chinese, describe the problem and the tradeoffs, respond in-thread | Best Chinese developer reach after 知乎 |
| 掘金 / 知乎 | A technical article that teaches the problem, with the repo linked at the end — not an announcement | Long-tail search traffic in Chinese |
| X / Twitter | One post with the social preview image and the one-line pitch; pin it | Small unless you already have followers |
| dev.to / Medium | Write the build story with real code and pitfalls | SEO plus a place to link the repo |

Anti-spam rules, all of them mandatory:

- Read each community's self-promotion policy first; many ban link-dropping outright.
- Disclose that you are the author in the first sentence.
- Post once per community per release worth talking about. No cross-posting the same
  text into five subreddits in ten minutes.
- Never ask for upvotes, stars, or HN votes, and never use vote rings — it is detected
  and it costs you the account.
- Reply to criticism with a fix or a clear explanation, not a defense.
- Contribute to the community before you ask it for attention.

## 8. Promotion checklist

Copy this into the release tracking issue and close it when every box is ticked.

- [ ] `README.md` opens with the one-line description, badges, and a 30-second quickstart
- [ ] README is bilingual: English first, then a `---`-separated Chinese half, both equivalent
- [ ] Placeholder notice is at the top of the README; every `<YOUR_API_KEY>`, `192.0.2.10`, `you@example.com`, and `Example Corp` is meant to be replaced
- [ ] `LICENSE` exists, its copyright line reads `Copyright (c) {{YEAR}} {{AUTHOR}}`, and the identifier matches the `{{LICENSE}}` value used in badges and `CITATION.cff`
- [ ] CI is green on `{{DEFAULT_BRANCH}}` and the CI badge points at `ci.yml`
- [ ] Repository description is ≤160 characters and keyword-rich; homepage is a real URL
- [ ] 8–15 topics set, lowercase, no junk topics
- [ ] Social preview 1280×640 PNG uploaded in Settings → General (source committed)
- [ ] Community files present: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, PR template, issue forms
- [ ] Community profile page shows no missing files
- [ ] First release tagged (`v0.1.0`) with generated notes, and `CHANGELOG.md` seeded
- [ ] Star CTA appears in at most two places, in both languages
- [ ] No secrets, tokens, private keys, IPs, or personal data anywhere: `git log -p` scanned, not just the working tree
- [ ] Mirror on Gitee updated and cross-linked, with the Chinese half of the README leading there
- [ ] One awesome-list PR opened (correct section, alphabetical, respects their rules)
- [ ] One community post written and answered — author disclosed, no vote solicitation
- [ ] Analytics checked after two weeks; the channel that worked gets the next post
