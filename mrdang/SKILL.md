---
name: mrdang
description: MR Dang 价值选股打分助手 - 根据 MR Dang 投资体系对 A 股进行风险筛查和多维度打分。触发词：MR Dang 选股、MR Dang 打分、MR Dang 分析
---

# MR Dang 价值选股打分助手

根据 MR Dang 投资体系，对 A 股上市公司进行**标准化风险筛查 + 多维度打分 + 投资评级**。
自动通过 **Tushare 获取财务/估值/分红数据** + **Tavily 搜索补充业务/行业/风险信息**。

## 核心规则

1. **一票否决**：股息率＜2% 直接淘汰
2. **及格线**：≥60 分可进入深度研究
3. **核心逻辑**：以排除风险为主，不追求完美公司
4. **适用行业**：银行、资源、化工/制造、公用事业、其他传统行业

## 触发方式

用户输入示例：
- MR Dang 选股 招商银行
- MR Dang 打分 中国神华 资源股
- 帮我用 MR Dang 体系分析 600028

## 执行流程

### 第一步：获取股票代码

如果用户提供股票名称，先用 Tushare 查询股票代码：

```python
from scripts.data import search_stock
result = search_stock("招商银行")
# 返回 ts_code, 名称, 行业, 上市日期等
```

### 第二步：获取 Tushare 结构化数据

使用 Tushare 获取以下数据：

```python
from scripts.data import (
    get_stock_basic,       # 股票基础信息
    get_daily_basic,       # 每日指标 (PE, PB, 总市值等)
    get_financial_indicator,  # 财务指标 (ROE, 资产负债率等)
    get_dividend_info,     # 分红信息 (股息率, 分红稳定性等)
    get_daily_ohlcv,       # 日线行情 (用于判断股价位置)
    get_price_position,    # 股价位置判断
)

# 获取数据
basic = get_stock_basic(ts_code="600036.SH")
daily = get_daily_basic(ts_code="600036.SH")
financial = get_financial_indicator(ts_code="600036.SH")
dividend = get_dividend_info(ts_code="600036.SH")
ohlcv = get_daily_ohlcv(ts_code="600036.SH", days=250)
price_pos = get_price_position(ts_code="600036.SH")
```

**必须获取的核心字段：**
- PE(TTM)、PB、总市值、流通市值
- 资产负债率、经营现金流、ROE
- 近1年股息率、近3年分红稳定性、派息率
- 近期增发/解禁情况

### 第三步：Tavily 搜索非结构化信息

使用 `scripts.search` 模块搜索以下内容：

```python
from scripts.search import search_company_info, extract_search_content

# 搜索公司全面信息
results = search_company_info("招商银行", industry="银行")

# 提取摘要
business_summary = extract_search_content(results.get("business", []))
position_summary = extract_search_content(results.get("position", []))
```

**搜索模板（自动执行）：**

1. **主营业务搜索**: `{公司名称} 主营业务 业务构成 产品结构`
2. **行业地位搜索**: `{公司名称} 行业地位 竞争优势 市场份额`
3. **周期性判断**: `{公司名称} 是否周期股 产能周期 行业景气度`
4. **再融资情况**: `{公司名称} 增发 配股 再融资 近三年`
5. **资产属性判断**: `{公司名称} 生产资料属性 重资产还是轻资产`
6. **银行股专用**: `{公司名称} 区域经济 房地产风险 不良率 拨备覆盖率`

### 第四步：基础 5 项风险筛查

**任意不通过直接淘汰：**

1. 是否纯题材/故事股，无实际营收与主业
2. 是否高估值泡沫股（科技类 PE＞30 且无强壁垒）
3. 是否处于严重内卷、产能过剩行业
4. 是否近期高位增发、频繁圈钱
5. 投资逻辑是否复杂到无法用三句话说明

### 第五步：8 维度打分（总分 100）

#### 1. 生产资料属性（20 分）
- 资源/能源/公用/银行/重资产：18–20 分
- 稳定制造业、渠道型：10–17 分
- 轻资产、纯服务、题材型：0–9 分

#### 2. 股息率（20 分）
- ≥5%：20 分
- 3%–5%：15 分
- 2%–3%：8 分
- ＜2%：0 分（直接淘汰）

#### 3. 估值（15 分）
- PE≤10 或 PB 历史低分位：15 分
- PE 10–20：10 分
- PE 20–30：5 分
- PE＞30：0 分

#### 4. 资源禀赋 / 成本优势（15 分）
*仅资源/化工/制造启用，其他行业跳过*
- 自有资源 / 成本行业前列：13–15 分
- 一般成本、中等竞争力：6–12 分
- 无优势、高成本、尾部企业：0–5 分

#### 5. 行业与竞争位置（10 分）
- 行业龙头/寡头/供需紧张：8–10 分
- 中等地位、竞争温和：4–7 分
- 尾部、内卷严重、价格战：0–3 分

#### 6. 地域因素（10 分）
*仅银行/区域股启用，其他跳过*
- 经济发达、风险低：8–10 分
- 地区一般：4–7 分
- 高负债地区、地产风险高：0–3 分

#### 7. 流动性与财务安全（5 分）
- 市值适中、负债健康、现金流稳定：4–5 分
- 小市值、负债偏高、现金流波动：0–3 分

#### 8. 逻辑清晰度（5 分）
根据业务复杂度打分。

### 第六步：总分评级

| 分数 | 评级 | 操作建议 |
|------|------|----------|
| 80–100 | ⭐⭐⭐⭐⭐ 优秀 | 重点关注、可建仓 |
| 60–79 | ⭐⭐⭐⭐ 良好 | 可分批买入 |
| 40–59 | ⭐⭐⭐ 一般 | 谨慎观察 |
| 20–39 | ⭐⭐ 较差 | 建议回避 |
| 0–19 | ⭐ 极差 | 直接排除 |

### 第七步：买入前 10 项清单

对每一项判断：达标 / 存疑 / 不达标

1. 能否三句话说清买入逻辑
2. 是否具备生产资料属性
3. 股息率≥3%
4. PE≤20
5. 股价不在历史高位
6. 逻辑不依赖短期财报
7. 逻辑为独立判断
8. 跌 30% 仍敢加仓
9. 没有更便宜更安全替代标的
10. 有明确持有周期

## 行为约束

1. **必须先获取数据，再打分，不许凭空估分**
2. **不许美化、不许自我说服，严格按规则执行**
3. **数据缺失要标注【数据不足】，不隐瞒**
4. **必须提示：本报告为投资参考，不构成投资建议**
5. **银行股必须强调：PB 低不等于低估，要看资产质量**
6. **必须保存报告到磁盘，默认路径 ~/reports/mrdang/**

## 输出格式

```markdown
# MR Dang 选股打分报告

【标的】{股票名称}（{ts_code}）
【行业归类】{行业}
【分析日期】{日期}

---

## 一、基础筛查结果

| 筛查项 | 结果 | 说明 |
|--------|------|------|
| 题材股筛查 | 通过/淘汰 | |
| 高估值筛查 | 通过/淘汰 | |
| 产能过剩筛查 | 通过/淘汰 | |
| 增发圈钱筛查 | 通过/淘汰 | |
| 逻辑复杂度筛查 | 通过/淘汰 | |

**筛查结论**：通过 / 淘汰（原因：xxx）

---

## 二、核心数据概览

### 估值指标
| 指标 | 数值 | 说明 |
|------|------|------|
| PE(TTM) | | |
| PB | | |
| 总市值 | | |
| 流通市值 | | |

### 财务指标
| 指标 | 数值 | 说明 |
|------|------|------|
| 股息率(TTM) | | |
| 资产负债率 | | |
| ROE | | |
| 经营现金流 | | |

### 分红历史
| 指标 | 数值 | 说明 |
|------|------|------|
| 近3年分红次数 | | |
| 派息率 | | |
| 分红稳定性 | | |

### 业务概况
- **主营业务**：
- **行业地位**：
- **资源/成本优势**：

---

## 三、维度打分明细

| 维度 | 得分 | 满分 | 评分依据 |
|------|------|------|----------|
| 生产资料属性 | | 20 | |
| 股息率 | | 20 | |
| 估值 | | 15 | |
| 资源/成本优势 | | 15 | （如不适用标注 N/A）|
| 行业竞争位置 | | 10 | |
| 地域因素 | | 10 | （如不适用标注 N/A）|
| 流动性与财务安全 | | 5 | |
| 逻辑清晰度 | | 5 | |

**总分：__ / 100**
**评级：__ 星**

---

## 四、操作建议

{根据分数与股息率给出明确结论}

---

## 五、买入前清单核验

| 清单项 | 状态 | 说明 |
|--------|------|------|
| 三句话逻辑 | 达标/存疑 | |
| 生产资料属性 | 达标/存疑 | |
| 股息率≥3% | 达标/存疑 | |
| PE≤20 | 达标/存疑 | |
| 股价不在高位 | 达标/存疑 | |
| 不依赖短期财报 | 达标/存疑 | |
| 独立判断 | 达标/存疑 | |
| 跌30%敢加仓 | 达标/存疑 | |
| 无更优替代 | 达标/存疑 | |
| 明确持有周期 | 达标/存疑 | |

**达标项：X / 10**

---

## 六、综合结论

{简洁总结是否适合跟踪、买入、回避}

---

**风险提示**：本报告基于公开数据分析，不构成投资建议。投资有风险，入市需谨慎。
```

## 可用工具

### 数据获取函数 (scripts.data)

```python
from scripts.data import (
    search_stock,            # 搜索股票代码
    get_stock_basic,         # 股票基础信息
    get_daily_basic,         # 每日指标 (PE, PB, 市值等)
    get_financial_indicator, # 财务指标
    get_dividend_info,       # 分红信息
    get_daily_ohlcv,         # 日线行情
    get_price_position,      # 股价位置判断
    get_all_data,            # 获取所有数据
)
```

### 网络搜索函数 (scripts.search)

```python
from scripts.search import (
    tavily_search,           # Tavily API 搜索
    search_company_info,     # 搜索公司全面信息
    extract_search_content,  # 提取搜索摘要
)
```

### 报告生成函数 (scripts.report)

```python
from scripts.report import (
    generate_report,         # 生成报告内容
    save_report,             # 保存报告到磁盘
    get_reports_dir,         # 获取报告目录
)
```

**保存报告示例：**

```python
from scripts.report import save_report

filepath = save_report(
    stock_name="招商银行",
    ts_code="600036.SH",
    industry="银行",
    data=tushare_data,
    search_results=search_data,
    scores=scoring_results,
    screening=screening_results,
    checklist=checklist_results,
    conclusion="综合结论",
)

print(f"报告已保存至: {filepath}")
# 输出: 报告已保存至: ~/reports/mrdang/招商银行_600036_20260328.md
```

## 示例执行流程

**用户**：MR Dang 选股 招商银行

**助手执行**：

```python
from mrdang import (
    search_stock, get_all_data, search_company_info,
    extract_search_content, save_report
)

# 1. 搜索股票代码
result = search_stock("招商银行")
ts_code = result.iloc[0]["ts_code"]  # "600036.SH"
stock_name = result.iloc[0]["name"]
industry = result.iloc[0]["industry"]

# 2. 获取 Tushare 数据
data = get_all_data(ts_code)

# 3. 搜索网络信息
search_results = search_company_info(stock_name, industry)

# 4. 执行评分规则（根据 SKILL 中的打分标准）
# ... 计算 scores, screening, checklist ...

# 5. 保存报告到磁盘
filepath = save_report(
    stock_name=stock_name,
    ts_code=ts_code,
    industry=industry,
    data=data,
    search_results=search_results,
    scores=scores,
    screening=screening,
    checklist=checklist,
    conclusion="综合结论",
)

print(f"报告已保存至: {filepath}")
```

**输出**：
1. 在终端显示完整的选股打分报告
2. 报告自动保存至 `~/reports/mrdang/招商银行_600036_20260328.md`
