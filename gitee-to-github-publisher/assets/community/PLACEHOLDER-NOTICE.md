<!--
  PLACEHOLDER-NOTICE.md — paste-ready README snippet, not a file to ship as-is.
  Place the blockquote below near the TOP of the README, after the title and badges,
  before the feature list, so readers see it before they copy any example.
  本文件是一段可直接粘贴到 README 的提示块，本身不需要作为文件发布。
  请把下面的引用块放在 README 顶部（标题与徽章之后、功能列表之前），
  让读者在复制任何示例之前就能看到它。
  Everything inside the blockquotes is English + 中文; keep both halves.
-->

# Placeholder notice / 占位符说明

## English (copy this blockquote into README.md)

> **⚠️ Placeholders ahead.** This repository was sanitized before publication. Every value
> that looks like a credential, host, or organization is a **placeholder** and must be
> replaced with your own before use: `<YOUR_API_KEY>`, `192.0.2.10`, `you@example.com`,
> `Example Corp`, `https://example.com`. Nothing here connects to a live service, and no
> real key, account, or internal address is included.
>
> Start from the `*.example` files (for example `.env.example`) and copy them to their real
> names; never commit the result. If you find a value that is *not* an obvious placeholder,
> please report it privately — see [SECURITY.md](SECURITY.md).

## 中文（把下面的引用块复制到 README.md）

> **⚠️ 请注意占位符。** 本仓库在发布前已做脱敏处理。所有看起来像凭据、主机或组织的值
> 都是**占位符**，使用前必须替换为你自己的内容：`<YOUR_API_KEY>`、`192.0.2.10`、
> `you@example.com`、`Example Corp`、`https://example.com`。仓库中没有任何东西会连接真实
> 服务，也不包含任何真实密钥、账号或内网地址。
>
> 请从 `*.example` 文件（例如 `.env.example`）开始，复制成真实文件名后再填写；切勿提交
> 填写后的文件。如果你发现某个值**并非**明显的占位符，请私下报告 —— 见 [SECURITY.md](SECURITY.md)。

---

## Which files to check / 需要检查哪些文件

Replace placeholders in every one of these before you run or publish anything:

| Location / 位置 | What to look for / 需要替换什么 |
| --- | --- |
| `.env.example` | Every `<YOUR_API_KEY>`, `CHANGE_ME`, and empty secret value / 所有 `<YOUR_API_KEY>`、`CHANGE_ME` 与空的密钥值 |
| Config samples / 配置样例 | `config.example.yaml`, `*.sample.toml`, `settings.example.json` — hosts, ports, accounts, URLs |
| `docker-compose.example.yml`, `Dockerfile` | Image names, registry hosts, volumes, `192.0.2.10` style addresses |
| `docs/` and code comments / 文档与代码注释 | Example commands, curl snippets, screenshots, example email addresses |
| CI workflows / CI 工作流 | `.github/workflows/*.yml` — secret names (not values), deploy targets, cron URLs |
| README and other Markdown / README 及其他 Markdown | Badges pointing at `{{OWNER}}/{{REPO}}`, clone URLs, demo links |

## Checklist before publishing / 发布前检查清单

- [ ] `grep -rnE "192\.0\.2\.10|you@example\.com|Example Corp|<YOUR_" .` returns only intentional placeholders / 只返回有意的占位符
- [ ] No `.env`, `*.pem`, `*.key`, `id_rsa`, or credential JSON is tracked: `git ls-files | grep -Ei '\.env$|\.pem$|\.key$|credential'` / 没有跟踪任何凭据文件
- [ ] Commit history scanned for secrets (a deleted secret is still in history) / 已扫描提交历史（删除过的密钥仍留在历史中）
- [ ] `.gitignore` covers `.env`, build output, caches, and editor state / `.gitignore` 已覆盖 `.env`、构建产物、缓存与编辑器状态