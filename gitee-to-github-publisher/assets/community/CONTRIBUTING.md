# Contributing to {{FULL_NAME}}

<!-- Template: install this file at .github/CONTRIBUTING.md (or CONTRIBUTING.md in the
     repository root). Replace every {{...}} placeholder before committing. -->

Thanks for taking the time to contribute. This document covers the repository
**{{REPO}}** owned by `{{OWNER}}`.

## Ways to contribute

- Report a bug using the *Bug report* issue form.
- Request a feature using the *Feature request* issue form.
- Improve documentation, examples, or translations.
- Send a pull request that fixes or implements something on the issue tracker.

If you plan a large change, open an issue first so we can agree on the design
before you write the implementation.

## Before you start

1. Search existing issues and pull requests to avoid duplicates.
2. Read the [Code of Conduct](CODE_OF_CONDUCT.md).
3. Check the README for supported versions and prerequisites.

## Development setup

```bash
git clone https://github.com/{{OWNER}}/{{REPO}}.git
cd {{REPO}}
git switch {{DEFAULT_BRANCH}}

# Python project
uv sync
uv run pytest

# Node project
corepack enable
pnpm install
pnpm test
```

Run the full test suite plus the formatter and linter before opening a pull request.

## Branch and commit conventions

- Branch from `{{DEFAULT_BRANCH}}`; keep one topic per branch (`fix/...`, `feat/...`, `docs/...`).
- Keep commits small and focused.
- Write imperative, scoped commit messages, e.g. `fix(parser): reject empty input`.
- Rebase onto the latest `{{DEFAULT_BRANCH}}` before requesting review; avoid merge commits inside the PR branch.

## Pull requests

Every pull request must:

- Explain **what** changed and **why**.
- Link the issue it closes (`Closes #123`).
- Pass CI.
- Update documentation whenever user-facing text or behavior changes — including both
  language halves of a bilingual README.
- Contain no secrets, tokens, private keys, internal hostnames, or personal data.
- State the license of any newly added dependency and confirm it is compatible with
  this project's `{{LICENSE}}` license.

Use the repository's pull request template. Do not delete checklist items without
explaining why.

## Reporting bugs

A useful bug report contains:

- The version, commit SHA, or release tag you tested.
- Operating system and runtime version.
- Exact reproduction steps, expected result, and actual result.
- Logs with secrets and personal data removed.

Report security vulnerabilities privately — see [SECURITY.md](SECURITY.md). Never open
a public issue for a vulnerability.

## Coding style

- Match the style of the surrounding code; do not reformat unrelated files.
- Add or update tests for behavior changes.
- Keep public APIs documented.
- Prefer clear names over comments that restate the code.
- Do not add a dependency for something the standard library already does.

## Review process

Maintainers review pull requests as time allows. Expect at least one round of
feedback. Address comments with follow-up commits or a rebase, then re-request review.
A pull request inactive for 60 days without response may be closed.

## License

By contributing, you agree that your contributions are licensed under the `{{LICENSE}}`
license of this repository. Do not paste code you cannot license under these terms.

## Questions

Open a discussion, or email the maintainer at `{{EMAIL}}` (placeholder — replace it with
your own address).

---

# 为 {{FULL_NAME}} 贡献

<!-- 模板：本文件应放在 .github/CONTRIBUTING.md（或仓库根目录的 CONTRIBUTING.md）。
     提交前请替换所有 {{...}} 占位符。 -->

感谢你抽出时间参与贡献。本文适用于 `{{OWNER}}` 名下的仓库 **{{REPO}}**。

## 贡献方式

- 用 *Bug report* 表单报告问题。
- 用 *Feature request* 表单提出需求。
- 改进文档、示例或翻译。
- 提交 pull request，修复或实现 issue 中的事项。

如果改动较大，请先开 issue 讨论设计，以免实现在错误的方向上白费功夫。

## 开始之前

1. 先搜索已有的 issue 和 pull request，避免重复。
2. 阅读[行为准则](CODE_OF_CONDUCT.md)。
3. 查看 README 中说明的支持版本与前置条件。

## 开发环境

```bash
git clone https://github.com/{{OWNER}}/{{REPO}}.git
cd {{REPO}}
git switch {{DEFAULT_BRANCH}}

# Python 项目
uv sync
uv run pytest

# Node 项目
corepack enable
pnpm install
pnpm test
```

提 pull request 之前，请跑通完整测试以及格式化与静态检查。

## 分支与提交规范

- 从 `{{DEFAULT_BRANCH}}` 拉分支，一个分支只做一件事（`fix/...`、`feat/...`、`docs/...`）。
- 提交粒度尽量小。
- 提交信息用祈使句并带范围，例如 `fix(parser): reject empty input`。
- 请求评审前先 rebase 到最新的 `{{DEFAULT_BRANCH}}`；PR 分支内避免合并提交。

## Pull request 要求

每个 pull request 必须：

- 说明改了**什么**、**为什么**改。
- 关联对应 issue（`Closes #123`）。
- 通过 CI。
- 当用户可见文案或行为变化时更新文档，包括双语 README 的两种语言部分。
- 不含任何密钥、令牌、私钥、内网主机名或个人数据。
- 说明新增依赖的许可证，并确认与本项目的 `{{LICENSE}}` 许可证兼容。

请使用仓库的 pull request 模板；不要在没有说明理由的情况下删除检查项。

## 报告 bug

一份有效的 bug 报告应包含：

- 你测试的版本号、commit SHA 或发布标签。
- 操作系统与运行时版本。
- 精确的复现步骤、期望结果与实际结果。
- 去除密钥与个人信息后的日志。

安全漏洞请私下报告，见 [SECURITY.md](SECURITY.md)。切勿为漏洞开公开 issue。

## 代码风格

- 与周边代码风格保持一致；不要顺手重排无关文件。
- 行为变更需要新增或更新测试。
- 公开 API 必须有文档。
- 命名要清晰，避免复述代码的注释。
- 标准库已能实现的功能，不要新增依赖。

## 评审流程

维护者会在时间允许时评审 pull request，通常至少有一轮反馈。请通过后续提交响应意见，
或推送 rebase 后重新请求评审。超过 60 天无回应的 pull request 可能被关闭。

## 许可证

参与贡献即表示你同意自己的贡献按本仓库的 `{{LICENSE}}` 许可证授权。
请勿粘贴你无权按此条款授权的代码。

## 疑问

请开 discussion，或发邮件到 `{{EMAIL}}`（占位符，请替换为你自己的地址）。