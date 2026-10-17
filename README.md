# 个人技能库

个人收集的Skill，用于增强 AI 辅助工作流。

## 可用技能

| 技能 | 描述 | 状态 |
|------|------|------|
| [mrdang](./mrdang/) | MR Dang 价值选股打分助手 - A股价值投资分析工具 | ✅ 可用 |
| [show-me-arch](./show-me-arch/) | 可视化解释助手 - 选最小视图讲清楚，需要架构图时用 Archify 渲染并嵌入 HTML 页面 | ✅ 可用 |
| [zcode-session-import](./zcode-session-import/) | 会话导入助手 - 把 ZCode / opencode 聊天记录转成 DSH 原生可续聊会话，附 v4 日志格式参考与校验器 | ✅ 可用 |

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

也可以装到 DeepSeek Harness：

```bash
cp -r show-me-arch ~/.dsh/skills/
cp -r zcode-session-import ~/.dsh/skills/
```

## 环境要求

- Python 3.10+（带 Python 脚本的技能需要）
- Node.js 18+（show-me-arch 需要；无第三方依赖，无需 `npm install`）
- 各技能所需的 API 密钥（详见各技能的 README）
- `zcode-session-import` 额外需要 `zstd` 命令行工具（缺失时回退到 Node 24 的 `zlib`）

## 许可证

MIT License
