# MR Dang 价值选股打分助手

根据 MR Dang 投资体系，对 A 股上市公司进行**标准化风险筛查 + 多维度打分 + 投资评级**的 Claude Code 技能。

## 功能特点

- 🔄 **自动化数据获取**: 通过 Tushare API 自动获取财务、估值、分红数据
- 🔍 **智能信息搜索**: 使用 Tavily API 搜索公司业务、行业地位、风险信息
- 📊 **标准化评分体系**: 8维度打分，总分100分，自动评级
- 📝 **报告自动保存**: 生成的分析报告自动保存到 `~/reports/mrdang/`

## 核心规则

1. **一票否决**: 股息率＜2% 直接淘汰
2. **及格线**: ≥60 分可进入深度研究
3. **核心逻辑**: 以排除风险为主，不追求完美公司
4. **适用行业**: 银行、资源、化工/制造、公用事业、其他传统行业

## 安装

### 1. 复制技能到 Claude Code 技能目录

```bash
cp -r mrdang ~/.claude/skills/
```

### 2. 安装 Python 依赖

```bash
cd mrdang/scripts
pip install tushare requests pandas
```

或使用 uv:

```bash
uv pip install tushare requests pandas
```

### 3. 配置环境变量

```bash
# Tushare API Token (必需)
export TUSHARE_TOKEN="your_tushare_token"

# Tavily API Key (必需)
export TAVILY_API_KEY="your_tavily_api_key"
```

获取 API 密钥:
- Tushare: https://tushare.pro/register
- Tavily: https://tavily.com/

## 使用方法

### 触发方式

在 Claude Code 中输入以下命令：

```
MR Dang 选股 招商银行
MR Dang 打分 中国神华
帮我用 MR Dang 体系分析 600028
```

### 直接调用 Python 函数

```python
from scripts.data import search_stock, get_all_data
from scripts.search import search_company_info
from scripts.report import save_report

# 搜索股票
result = search_stock("招商银行")
ts_code = result.iloc[0]["ts_code"]

# 获取所有数据
data = get_all_data(ts_code)

# 搜索公司信息
search_results = search_company_info("招商银行", "银行")

# 保存报告
filepath = save_report(
    stock_name="招商银行",
    ts_code=ts_code,
    industry="银行",
    data=data,
    search_results=search_results,
    scores={...},
    screening={...},
    checklist={...},
    conclusion="综合结论",
)
```

## 评分体系

### 8维度打分（总分100）

| 维度 | 满分 | 说明 |
|------|------|------|
| 生产资料属性 | 20 | 资源/银行/重资产得分高 |
| 股息率 | 20 | ≥5%满分，＜2%淘汰 |
| 估值 | 15 | PE≤10满分 |
| 资源/成本优势 | 15 | 仅资源/制造启用 |
| 行业竞争位置 | 10 | 龙头得分高 |
| 地域因素 | 10 | 仅银行/区域股启用 |
| 流动性与财务安全 | 5 | 市值/负债/现金流 |
| 逻辑清晰度 | 5 | 业务复杂度 |

### 评级标准

| 分数 | 评级 | 建议 |
|------|------|------|
| 80-100 | ⭐⭐⭐⭐⭐ | 重点关注、可建仓 |
| 60-79 | ⭐⭐⭐⭐ | 可分批买入 |
| 40-59 | ⭐⭐⭐ | 谨慎观察 |
| 20-39 | ⭐⭐ | 建议回避 |
| 0-19 | ⭐ | 直接排除 |

## 文件结构

```
mrdang/
├── SKILL.md          # Claude Code 技能定义
├── README.md         # 本文档
└── scripts/          # Python 脚本
    ├── __init__.py   # 包导出
    ├── data.py       # Tushare 数据获取
    ├── search.py     # Tavily 网络搜索
    └── report.py     # 报告生成与保存
```

## API 函数

### data.py - 数据获取

| 函数 | 说明 |
|------|------|
| `search_stock(keyword)` | 搜索股票代码 |
| `get_stock_basic(ts_code)` | 获取股票基础信息 |
| `get_daily_basic(ts_code)` | 获取 PE/PB/市值等 |
| `get_financial_indicator(ts_code)` | 获取财务指标 |
| `get_dividend_info(ts_code)` | 获取分红信息 |
| `get_price_position(ts_code)` | 计算股价位置 |
| `get_all_data(ts_code)` | 获取所有数据 |

### search.py - 网络搜索

| 函数 | 说明 |
|------|------|
| `tavily_search(query)` | Tavily API 搜索 |
| `search_company_info(name, industry)` | 搜索公司全面信息 |
| `extract_search_content(results)` | 提取搜索摘要 |

### report.py - 报告生成

| 函数 | 说明 |
|------|------|
| `generate_report(...)` | 生成报告内容 |
| `save_report(...)` | 保存报告到磁盘 |
| `get_reports_dir()` | 获取报告目录 |

## 输出示例

报告自动保存至 `~/reports/mrdang/招商银行_600036_20260328.md`

```markdown
# MR Dang 选股打分报告

【标的】招商银行（600036.SH）
【行业归类】银行
【分析日期】2026-03-28

## 一、基础筛查结果
✅ 全部通过

## 二、核心数据概览
- PE(TTM): 6.62
- PB: 0.93
- 股息率: 5.07%
- ROE: 12.02%

## 三、维度打分明细
**总分：82 / 100**
**评级：⭐⭐⭐⭐⭐ 优秀**

## 四、操作建议
重点关注，可考虑建仓
```

## 风险提示

本工具基于公开数据分析，不构成投资建议。投资有风险，入市需谨慎。

## 更新日志

### v1.0.0 (2026-03-28)
- 初始版本
- 支持 Tushare 数据获取
- 支持 Tavily 网络搜索
- 支持 8 维度评分
- 支持报告自动保存

## License

MIT
