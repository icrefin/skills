# zcode-session-import

把 **ZCode（Z.ai）** 与 **opencode** 的聊天记录导入 **DeepSeek Harness（DSH）**，转成 DSH **原生、可继续对话**的会话：导入后的会话会出现在 DSH 会话列表里，能直接接着聊，而不是只能看的静态转录。

同时也是一个 **DSH v4 会话日志（`session.v4.jsonl.zstd`）格式参考 + 校验器**：需要手写、检查或修复会话文件时，用 `references/` 里的格式说明和 `scripts/validate_session_log.mjs`。

## 功能特点

- 🔒 **只读源库**：ZCode / opencode 的 SQLite 一律以只读方式打开，源数据零改动
- 🔁 **幂等**：会话 id 由源会话 id 经 UUIDv5 推导，重复运行自动跳过已导入的会话
- ✅ **自校验**：写出的每个文件都先过转换器内置的快速校验，再用 **DSH 自己的读取器**复核
- 🖼️ **附件搬运**：引用的图片会被解码、校验魔数后放进 DSH 的 content-addressed 附件库
- 🧩 **两种来源**：`zcode_to_dsh_import.py`（ZCode）+ `opencode_to_dsh_import.py`（opencode v2）

## 环境要求

- Python 3.10+（脚本只用标准库，无需 `pip install`）
- `zstd` 命令行工具；没有时回退到 Node 24 的 `zlib`
- Node.js（仅用于 `validate_session_log.mjs` 复核，以及上面的 zstd 回退）

## 安装

复制技能目录到 Claude Code 或 DeepSeek Harness 的技能目录：

```bash
cp -r zcode-session-import ~/.claude/skills/
# 或
cp -r zcode-session-import ~/.dsh/skills/
```

## 使用方法

技能会在 DSH / Claude Code 里由对话触发，例如「把 ZCode 里的会话导进 DSH」。
也可以直接跑脚本：

### 1. 先试运行（dry run）

只把日志暂存到本地目录，不碰 `~/.dsh`：

```bash
python3 scripts/zcode_to_dsh_import.py --workspace "$PWD" --out ./.zcode-import-stage
```

### 2. 复核暂存结果

```bash
node scripts/validate_session_log.mjs ./.zcode-import-stage/<dir>/<session>/session.v4.jsonl.zstd
```

### 3. 正式写入

`--apply` 会写入 `$DSH_HOME`（默认 `~/.dsh`）并登记到 `workspace.json`：

```bash
python3 scripts/zcode_to_dsh_import.py --workspace "$PWD" --apply
```

### 常用参数

| 参数 | 说明 |
|------|------|
| `--list` | 只列出匹配到的会话，不写任何文件 |
| `--include-subdirs` | 连源工具从子目录运行的会话一起导入 |
| `--session <id>` | 只导入指定会话，可重复 |
| `--force` | 重写已有日志，始终保留带时间戳的备份 |
| `--overwrite-continued` | 见下方警告，慎用 |
| `--no-attachments` | 跳过图片附件 |
| `--db` / `--dsh-home` / `--artifacts` | 自定义源库、DSH home、附件目录 |

默认源库位置：ZCode `~/.zcode/cli/db/db.sqlite`，opencode `~/.local/share/opencode/opencode.db`。

### 导入 opencode 会话

```bash
python3 scripts/opencode_to_dsh_import.py --workspace "$PWD" --out ./_oc_import
python3 scripts/opencode_to_dsh_import.py --workspace "$PWD" --apply
```

它复用 ZCode 导入器的 DSH 侧机制（Zstandard 分帧、自校验、workspace 登记、system prompt 引用），只替换来源侧的翻译，因此同样是只读 + 幂等。

## ⚠️ 不要重写 DSH 已经续聊过的会话

重跑导入是幂等的——已存在的日志会被跳过。危险的是 `--force`：如果用户之后在 DSH 里打开过该会话并继续发言，DSH 已经往日志里追加了实时事件，覆盖会毁掉它们；而且运行中的 Harness 手里有自己的 next-sequence 计数器，下一条消息会写在它的计数位置而不是文件末尾，会话从此永久读不了：

```
stored log is corrupt: Error: corrupt session log: invalid committed event at
line 943: released v2 row 942 has seq gap (expected 942, got 960)
```

转换器会比对现有日志：若现有文件正好是「我们将写的内容 + 额外实时事件」，会直接拒绝（`REFUSED (continued in DSH, +N live event(s))`），`--force` 也覆盖不了。`--overwrite-continued` 只在 **DSH 已关闭**时才对，且仍会安静丢掉用户的消息——更好的做法是别碰那个会话，或导入成一个新会话。

同理：**会话还活着时不要删除或改写它引用的附件对象**，Harness 内存里的投影仍指向旧 id，下一轮会以 `Attachment object is missing.` 失败。

## 导入之后要跟用户说清楚

日志文件和 `workspace.json` 登记是立刻生效的，但**运行中的 DSH 服务把会话列表放在内存里**，在 GUI 重载之前看不到新会话；还是没有就重启 DSH app。

## 文件结构

```
zcode-session-import/
├── SKILL.md                              # 技能定义（触发条件 + 硬性规则）
├── README.md                             # 本文档
├── references/
│   └── dsh-session-format-v4.md          # DSH v4 会话格式与 ZCode→DSH 字段映射
└── scripts/
    ├── zcode_to_dsh_import.py            # ZCode SQLite → DSH 会话日志
    ├── opencode_to_dsh_import.py         # opencode v2 SQLite → DSH 会话日志
    └── validate_session_log.mjs          # 用 DSH 自带读取器复核日志
```

## 校验器

`validate_session_log.mjs` 从已安装的 `app.asar` 里取出 DSH 真正的编解码器，调用 `restoreReleasedV4Artifact` 验证文件：

```bash
node scripts/validate_session_log.mjs ~/.dsh/sessions/<dir>/<session>/session.v4.jsonl.zstd
node scripts/validate_session_log.mjs $(ls ~/.dsh/sessions/<dir>/*/session.v4.jsonl.zstd)
```

输出 `OK`，或 Harness 会抛出的那个确切的 `SessionFormatError`。自写的检查不够用——曾有导入通过了人工照抄的全部规则，仍被 Harness 拒收，所以这一步是收尾必做项。

默认从 macOS 安装路径 `/Applications/DeepSeek Harness.app/Contents/Resources/app.asar` 取编解码器；装在别处时用 `--asar PATH` 指定。

## DSH 升级后

格式规则是从安装的 Harness bundle 里读出来的。DSH 升级后，先按 `references/dsh-session-format-v4.md` 第 1 节列出的路径与函数名重读一遍，再信任本技能。

## 更新日志

### v1.0.0 (2026-10-17)
- 初始发布：ZCode 会话导入、opencode 会话导入、v4 格式参考与校验器

## 许可证

MIT License