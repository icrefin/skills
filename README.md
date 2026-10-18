# 个人技能库

个人收集的Skills，用于增强 AI 辅助工作流。

## 可用技能

| 技能 | 描述 | 状态 |
|------|------|------|
| [mrdang](./mrdang/) | MR Dang 价值选股打分助手 - A股价值投资分析工具 | ✅ 可用 |
| [show-me-arch](./show-me-arch/) | 可视化解释助手 - 选最小视图讲清楚，需要架构图时用 Archify 渲染并嵌入 HTML 页面 | ✅ 可用 |
| [zcode-session-import](./zcode-session-import/) | 会话导入助手 - 把 ZCode / opencode 聊天记录转成 DSH 原生可续聊会话，附 v4 日志格式参考与校验器 | ✅ 可用 |
| [dsh-plugin-creator](./dsh-plugin-creator/) | DSH 插件开发助手 - 构建、验证并打包 DeepSeek Harness (dsh) 插件为可安装的 npm bundle，**兼容 DSH 0.2.1-rc.2** | ✅ 可用 |
| [gitee-to-github-publisher](./gitee-to-github-publisher/) | Gitee 仓库发布助手 - 脱敏并双语化后发布到 GitHub，内置隐私审计、许可证合规与发布后校验四道闸门 | ✅ 可用 |

## 版本与兼容性

本仓库按 **DSH 运行时版本** 打标签。技能大多与运行时无关，只有 `dsh-plugin-creator`
需要跟随 Harness 版本 —— 它内置的 UI 座位目录、模板清单与 peer 依赖都锚定在一个具体运行时上。

| 标签 | 对应 DSH 运行时 | 说明 |
|------|----------------|------|
| `dsh-0.2.1-rc.2` | **0.2.1-rc.2** | **当前版本。** `dsh-plugin-creator` 的座位目录已与 0.2.1-rc.2 运行时的实际座位逐条核对：76 个座位全部具名，两个已不存在的座位标为失效；模板在该运行时上 typecheck、build、test 全绿，构建无弃用告警 |
| `dsh-0.2.0-rc.2` | 0.2.0-rc.2 | 历史快照。`dsh-plugin-creator` 面向 0.2.0-rc.2 编写，座位目录取自该版本 |

```bash
# 取用与当前 Harness 匹配的快照
git clone --branch dsh-0.2.1-rc.2 https://github.com/icrefin/skills.git

# 或取用面向 0.2.0-rc.2 的历史快照
git clone --branch dsh-0.2.0-rc.2 https://github.com/icrefin/skills.git
```

> 除 `dsh-plugin-creator` 外，其余技能不随 DSH 运行时版本变化，任何标签下都可使用。

## 安装

将技能文件夹复制到 `~/.claude/skills/`：

```bash
# 克隆仓库
git clone https://github.com/icrefin/skills.git
cd skills

# 安装技能
cp -r <技能名称> ~/.claude/skills/
```

### 安装 mrdang 技能

```bash
cp -r mrdang ~/.claude/skills/
```

### 安装 show-me-arch 技能

```bash
cp -r show-me-arch ~/.claude/skills/
```

### 安装 zcode-session-import 技能

```bash
cp -r zcode-session-import ~/.claude/skills/
```

### 安装 dsh-plugin-creator 技能

```bash
# 该技能面向 DeepSeek Harness
cp -r dsh-plugin-creator ~/.dsh/skills/
```

### 安装 gitee-to-github-publisher 技能

```bash
cp -r gitee-to-github-publisher ~/.dsh/skills/
```

也可以装到 DeepSeek Harness：

```bash
cp -r show-me-arch ~/.dsh/skills/
cp -r zcode-session-import ~/.dsh/skills/
cp -r dsh-plugin-creator ~/.dsh/skills/
cp -r gitee-to-github-publisher ~/.dsh/skills/
```

## 环境要求

- Python 3.10+（带 Python 脚本的技能需要）
- Node.js 18+（show-me-arch 与 dsh-plugin-creator 需要；无第三方依赖，无需 `npm install`）
- 各技能所需的 API 密钥（详见各技能的 README）
- `zcode-session-import` 额外需要 `zstd` 命令行工具（缺失时回退到 Node 24 的 `zlib`）
- `gitee-to-github-publisher` 需要 `GITEE_TOKEN` 与 `GITHUB_TOKEN` 环境变量；截图压缩需 `uv run --with pillow`

## 许可证

MIT License
