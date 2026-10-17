# Bilingual READMEs (English + Chinese)

The rule for this pipeline: **every published repository has a `README.md` in
English and a `README.zh-CN.md` in Chinese**, each linking to the other. GitHub's
audience is global and the source repositories are Chinese-origin, so both halves
earn their place — but they must stay *parallel*, not drift into two different
documents.

## File naming and which one is primary

| Situation | Action |
| --- | --- |
| Gitee has a Chinese `README.md` | Move its content to `README.zh-CN.md`; author the English `README.md` (English is the GitHub default). |
| Gitee has an English `README.md` | Keep it as `README.md`; author `README.zh-CN.md`. |
| Gitee has both (any names) | Normalise to `README.md` (en) + `README.zh-CN.md` (zh); keep the other file as a redirect stub only if something already links to it. |
| Gitee has no README | Create both from `assets/readme/README.en.md.tmpl` and `assets/readme/README.zh-CN.md.tmpl`. |
| The project is Chinese-first by design (a Chinese-only audience, e.g. a 政策/教学 tool) | English still goes in `README.md`, but the **Chinese content is authoritative** — say so in a line at the top of both ("本文档以中文为准 / The Chinese version is authoritative"). |

Use `.zh-CN.md` (not `.zh.md`, not `中文.md`): GitHub renders the region subtag
and the extension is a convention people recognise. `README.en.md` appears only
when a repository's Chinese README must stay as `README.md` for existing links —
in that case the English file is `README.en.md` and the switcher mirrors
accordingly.

## The switcher

Put it on line 2 or 3, under the title:

```markdown
**English** | [简体中文](README.zh-CN.md)
```

```markdown
[English](README.md) | **简体中文**
```

Rules: the active language is bold and unlinked; the other language is a relative
link; no flags (they imply a country, not a language); no language selector
graphics.

## Parallel structure

Both files must have the same **section skeleton** — same count, same order, same
purpose — because a reader who switches languages should land in the same place.

| # | English heading | Chinese heading |
| --- | --- | --- |
| 1 | Title + tagline | 标题 + 一句话简介 |
| 2 | Badges | 徽章 |
| 3 | Features / Why this exists | 功能特性 |
| 4 | Screenshots | 截图 |
| 5 | Requirements | 环境要求 |
| 6 | Installation | 安装 |
| 7 | Quick start | 快速开始 |
| 8 | Usage / Configuration | 使用说明 / 配置 |
| 9 | FAQ / Troubleshooting | 常见问题 |
| 10 | Roadmap | 路线图 |
| 11 | License | 许可证 |
| 12 | Star CTA + footer | 求 Star + 页脚 |

**Byte-identical between languages:** every fenced code block, every shell
command, every file path, every image path, every badge URL, every version
number, every table that is pure data. **Translated:** prose, headings, table
headers, image alt text and captions, bullet labels.

**Deliberately absent from the skeleton.** Do not add a *Contributing*, a
*Project structure* / *Layout*, or a *Verification* section to either README — this is a
standing preference, not an oversight:

- **Contributing** lives in `CONTRIBUTING.md` (plus `SECURITY.md` and
  `CODE_OF_CONDUCT.md`); the README links the repository's Community tab implicitly and
  does not need to restate the rules.
- **Layout / Project structure** duplicates what the file tree already shows and goes
  stale as soon as a directory moves.
- **Verification** is the project's own development narrative. It belongs in the commit
  history, `CONTRIBUTING.md`, or a `docs/` page — not in a README that a newcomer reads
  to decide whether to use the thing.

If a repository genuinely needs one of them, put it in `docs/` and link it from the
README's FAQ rather than inlining a section.

Do not add a section to one language only. If a section genuinely does not apply
in one language (rare), keep the heading with a one-line note rather than
deleting it.

## Translation quality bar

A machine-translated README reads as *foreign documentation* and costs
credibility. Write Chinese technical prose the way Chinese developers write it:

- Keep established technical nouns in English: `Docker`, `Kubernetes`, `Python`,
  `API`, `CLI`, `token`, `PR`, `bug`, `build`, `cache`, `pipeline`.
- Do not translate code identifiers, flags, environment variables or brand names.
- Prefer the verb the ecosystem uses: 安装 (install), 编译/构建 (build), 部署
  (deploy), 调试 (debug), 运行 (run), 配置 (configure), 依赖 (dependency),
  仓库 (repository), 分支 (branch), 提交 (commit/PR).
- Use 您 only in a formal product README; 你 is normal in open-source prose.
- Avoid calques ("这是一个非常强大的工具，它可以…") — lead with what it does:
  "把 A 转成 B 的命令行工具。" 
- Keep sentence-final punctuation as full-width （）and 、 for Chinese; keep ASCII
  parentheses inside code.
- Numbers and units: `1.6 GB`, `128 MB` stay ASCII.

## Placeholders and privacy

A placeholder notice is mandatory when the repository was sanitized. Paste the
blockquote from `assets/community/PLACEHOLDER-NOTICE.md` into **both** READMEs,
near the top (after the intro, before Requirements), and list the same files in
both languages:

```markdown
> **Note**: This repository was sanitized before publication. Values such as
> `<YOUR_API_KEY>`, `192.0.2.10`, `you@example.com` and `Example Corp` are
> **placeholders** — replace them with your own before running anything.
```

```markdown
> **注意**：本仓库在发布前已做脱敏处理。`<YOUR_API_KEY>`、`192.0.2.10`、
> `you@example.com`、`Example Corp` 等均为**占位符**，请在使用前替换为你自己的配置。
```

Never leave a real hostname, path, username or email in either language — a leak
in the Chinese file is just as public as one in the English file. The privacy
audit scans both.

## Mirror and attribution

For a Gitee-first project, add a short provenance line near the top:

```markdown
> This repository is the GitHub mirror of [gitee.com/<owner>/<repo>](https://gitee.com/<owner>/<repo>).
> Issues and pull requests are welcome here; the Gitee repository stays the primary development home.
```

```markdown
> 本仓库是 [gitee.com/<owner>/<repo>](https://gitee.com/<owner>/<repo>) 的 GitHub 镜像。
> 欢迎在此提交 issue 和 PR；主仓库仍在 Gitee。
```

If the project was cloned or forked from a third party, the attribution section is
not optional — see `references/license-compliance.md`.

## Verify before publishing

```bash
# both files exist and have the same heading count
grep -c '^#' README.md README.zh-CN.md
# the switcher is present in both
grep -l 'README.md' README.md README.zh-CN.md
# no section exists in only one language: eyeball the two heading lists
grep '^#' README.md > /tmp/en.txt; grep '^#' README.zh-CN.md > /tmp/zh.txt; wc -l /tmp/en.txt /tmp/zh.txt
```

`github_publish.py verify` fails the repository when either README is missing from
the published tree, and a dangling image reference is reported per file, so a
README that references `docs/images/foo.png` without committing it is caught
before the user ever sees it.