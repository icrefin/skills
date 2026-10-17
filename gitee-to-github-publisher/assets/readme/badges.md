<!--
  badges.md — snippet bank for a repository that is about to be published.
  NOT copied wholesale: pick the blocks you need, replace every {{...}} placeholder,
  and paste them into README.md (English) and README.zh-CN.md (Chinese).

  Rule: whatever you paste into one language must also appear in the other, with the
  same badge URLs, the same commands and the same image paths. Only the prose, the
  headings, the alt text and the captions change language.

  Freshly created repositories have no badge data yet: shields.io renders "no status"
  for the license and CI badges, "0" for stars and an error for the release badge
  until the repository actually has a LICENSE file, a release/tag, a CI run and a
  star. See the table at the bottom before adding a badge — and delete the badges
  whose data does not exist yet. An empty "no status" row costs more credibility
  than a missing badge.
-->

# Badge, switcher and star-CTA snippets

## 1. Badge row — one line

<!-- Paste under the title and the language switcher. Replace {{FULL_NAME}} and
     {{DEFAULT_BRANCH}} first. Delete badges from the right as needed. -->

[![License](https://img.shields.io/github/license/{{FULL_NAME}}?style=flat-square&label=license)](LICENSE) [![Release](https://img.shields.io/github/v/release/{{FULL_NAME}}?style=flat-square&display_name=tag&sort=semver)](https://github.com/{{FULL_NAME}}/releases) [![CI](https://img.shields.io/github/actions/workflow/status/{{FULL_NAME}}/ci.yml?style=flat-square&label=CI&branch={{DEFAULT_BRANCH}})](https://github.com/{{FULL_NAME}}/actions) [![Last commit](https://img.shields.io/github/last-commit/{{FULL_NAME}}?style=flat-square&branch={{DEFAULT_BRANCH}})](https://github.com/{{FULL_NAME}}/commits/{{DEFAULT_BRANCH}}) [![Stars](https://img.shields.io/github/stars/{{FULL_NAME}}?style=flat-square&logo=github&label=stars)](https://github.com/{{FULL_NAME}}/stargazers) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](CONTRIBUTING.md) ![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-555?style=flat-square) ![Language](https://img.shields.io/badge/Language-Python%203.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)

## 2. Badge row — one badge per line

<!-- Same badges, one per line: easier to diff and review. Markdown still renders
     them on a single line, so the result looks identical to §1. -->

[![License](https://img.shields.io/github/license/{{FULL_NAME}}?style=flat-square&label=license)](LICENSE)
[![Release](https://img.shields.io/github/v/release/{{FULL_NAME}}?style=flat-square&display_name=tag&sort=semver)](https://github.com/{{FULL_NAME}}/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/{{FULL_NAME}}/ci.yml?style=flat-square&label=CI&branch={{DEFAULT_BRANCH}})](https://github.com/{{FULL_NAME}}/actions)
[![Last commit](https://img.shields.io/github/last-commit/{{FULL_NAME}}?style=flat-square&branch={{DEFAULT_BRANCH}})](https://github.com/{{FULL_NAME}}/commits/{{DEFAULT_BRANCH}})
[![Stars](https://img.shields.io/github/stars/{{FULL_NAME}}?style=flat-square&logo=github&label=stars)](https://github.com/{{FULL_NAME}}/stargazers)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](CONTRIBUTING.md)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-555?style=flat-square)
![Language](https://img.shields.io/badge/Language-Python%203.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)

## 3. Language switcher

<!-- Line 2 or 3 of the README, right under the title. The active language is bold and
     NOT a link; the other language is a relative link. No flag icons: a flag is a
     country, not a language.

     Which file is "the other" depends on which language is primary:
       README.md (English primary)   → the other file is README.zh-CN.md
       README.md (Chinese primary)   → the other file is README.en.md
     Keep the pair consistent: both files must point at each other's real name. -->

<!-- In README.md, English primary -->
**English** | [中文](README.zh-CN.md)

<!-- In README.zh-CN.md, Chinese primary -->
[English](README.md) | **中文**

<!-- Alternative pair when the Chinese README has to stay at README.md -->
[English](README.en.md) | **中文**

<!-- ...and in README.en.md -->
**English** | [中文](README.md)

## 4. Star CTA — English (subtle → direct)

<!-- One line near the end of the README. Pick one; never stack them. -->

**1 · subtle** — If you find this useful, a ⭐ is always appreciated.

**2 · gentle** — If {{REPO}} saves you time, a star helps other people find it.

**3 · direct** — **Star this repo** if you want to follow along — it takes one click and makes the project easier to find.

**4 · with a next step** — Found this useful? Consider starring the repo, and [open an issue](https://github.com/{{FULL_NAME}}/issues) if something is missing.

**5 · explicit** — ⭐ If {{REPO}} is useful to you, please [star it](https://github.com/{{FULL_NAME}}/stargazers). It costs nothing and helps a lot.

**6 · strongest** — **[Star {{FULL_NAME}}](https://github.com/{{FULL_NAME}}/stargazers)** to support the project. A star is the cheapest way to keep it maintained.

## 5. Star CTA — 中文（由含蓄到直接）

<!-- 放在 README 末尾附近，选一条即可，不要叠加。 -->

**1 · 含蓄** —— 如果这个项目对你有用，欢迎点个 ⭐。

**2 · 温和** —— 如果 {{REPO}} 帮你省了时间，点个 Star 能让更多人找到它。

**3 · 直接** —— **给个 Star** 关注后续更新 —— 一次点击，就能让项目更容易被搜到。

**4 · 带下一步** —— 用得顺手的话欢迎 star；缺什么功能也可以直接[提 issue](https://github.com/{{FULL_NAME}}/issues)。

**5 · 明确** —— ⭐ 如果 {{REPO}} 对你有用，欢迎[点个 Star](https://github.com/{{FULL_NAME}}/stargazers)，不花什么成本，但对项目帮助很大。

**6 · 最直接** —— **[给 {{FULL_NAME}} 点个 Star](https://github.com/{{FULL_NAME}}/stargazers)** 支持这个项目 —— 一个 Star 就是持续维护的动力。

## 6. Screenshots block

<!-- Plain markdown: what both README templates ship with. Keep the image paths and
     the two file names identical in both languages; translate only alt text and
     captions. The files live in docs/images/ so the links survive the clone. -->

![Main window](docs/images/{{SCREENSHOT_1}})
*Figure 1 — the main window running with the sample configuration.*

![Result output](docs/images/{{SCREENSHOT_2}})
*Figure 2 — a successful run.*

<!-- Centered HTML variant with a fixed width. Use it when a plain image looks
     unbalanced on a wide screen; 800 px matches most README layouts. -->

<p align="center">
  <img src="docs/images/{{SCREENSHOT_1}}" alt="Main window" width="800">
  <br>
  <em>Figure 1 — the main window running with the sample configuration.</em>
</p>

<p align="center">
  <img src="docs/images/{{SCREENSHOT_2}}" alt="Result output" width="800">
  <br>
  <em>Figure 2 — a successful run.</em>
</p>

<!-- Screenshots are the easiest place to leak: capture an empty demo session, then
     check paths, hostnames, usernames, tokens and serial numbers. Redact or blur
     anything private before committing the image. -->

## 7. End-of-README footer

<!-- After the License section. Delete any link that does not apply. -->

---

<p align="center">
  <a href="https://github.com/{{FULL_NAME}}/stargazers">⭐ Star</a> ·
  <a href="https://github.com/{{FULL_NAME}}/fork">🍴 Fork</a> ·
  <a href="https://github.com/{{FULL_NAME}}/issues">🐛 Issues</a> ·
  <a href="{{GITEE_URL}}">Gitee 镜像 / Gitee mirror</a>
</p>

## 8. Which badge, when

| Badge | Include when | Renders as junk until then |
| --- | --- | --- |
| License | a `LICENSE` file sits at the repository root | "no status" / license not found |
| Release | at least one release or tag is published | an error instead of a version |
| CI | `.github/workflows/ci.yml` has run once on `{{DEFAULT_BRANCH}}` | "no status" |
| Last commit | always — GitHub computes it from the branch | never |
| Stars | the repository has at least one star | `0` |
| PRs welcome | `CONTRIBUTING.md` exists | never (static badge) |
| Platform / Language | the supported matrix is decided, not guessed | never (static badge) |
| Star History chart | the repository has history and a few stars | an empty chart |

## 9. Verify what you pasted

```bash
grep -c '^#' README.md README.zh-CN.md              # same heading count in both languages
grep -c 'img.shields.io' README.md README.zh-CN.md  # same badge count in both languages
grep -o 'docs/images/[^)]*' README.md README.zh-CN.md | sort -u   # image paths in use
ls docs/images/                                     # every referenced image is committed
```
