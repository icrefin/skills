# Claude Code Skills Collection

A collection of custom skills for Claude Code, designed to enhance AI-assisted workflows with domain-specific knowledge and tools.

## What are Claude Code Skills?

Claude Code Skills are modular capabilities that extend Claude's abilities with specialized knowledge, tools, and workflows. Each skill is a self-contained package that can be easily installed and used in Claude Code sessions.

## Available Skills

| Skill | Description | Status |
|-------|-------------|--------|
| [mrdang](./mrdang/) | MR Dang 价值选股打分助手 - A股价值投资分析工具 | ✅ Active |

## Installation

Skills are installed by copying the skill folder to `~/.claude/skills/`:

```bash
# Clone the repository
git clone https://github.com/icrefin/skills.git
cd skills

# Install a skill
cp -r <skill-name> ~/.claude/skills/
```

### Installing the mrdang skill

```bash
cp -r mrdang ~/.claude/skills/
```

## Skill Structure

Each skill follows a standard structure:

```
<skill-name>/
├── SKILL.md          # Skill definition (required)
├── README.md         # Documentation (required)
└── scripts/          # Python/scripts (optional)
    ├── __init__.py
    └── *.py
```

## Creating a New Skill

1. Create a new folder with the skill name
2. Add `SKILL.md` with frontmatter:
   ```markdown
   ---
   name: skill-name
   description: Brief description of the skill
   ---

   # Skill content...
   ```
3. Add `README.md` with usage documentation
4. Add any supporting scripts in `scripts/`

## Requirements

- Claude Code CLI
- Python 3.10+ (for skills with Python scripts)
- Required API keys (specified in each skill's README)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add your skill following the standard structure
4. Submit a pull request

## License

MIT License - See [LICENSE](LICENSE) for details.

## Links

- [Claude Code Documentation](https://docs.anthropic.com/claude-code)
- [Skill Development Guide](https://docs.anthropic.com/claude-code/skills)
