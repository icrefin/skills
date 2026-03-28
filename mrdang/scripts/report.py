"""Report generation and saving for MR Dang stock analysis."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any


def get_reports_dir() -> Path:
    """Get the reports directory path.

    Returns:
        Path to reports directory
    """
    # Default to ~/reports/mrdang/
    reports_dir = Path.home() / "reports" / "mrdang"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def generate_report_filename(stock_name: str, ts_code: str) -> str:
    """Generate a filename for the report.

    Args:
        stock_name: Stock name
        ts_code: Tushare stock code

    Returns:
        Filename string
    """
    date_str = datetime.now().strftime("%Y%m%d")
    # Clean stock name for filename
    safe_name = "".join(c for c in stock_name if c.isalnum() or c in "._-")
    return f"{safe_name}_{ts_code.split('.')[0]}_{date_str}.md"


def format_value(value: Any, default: str = "N/A") -> str:
    """Format a value for display.

    Args:
        value: Value to format
        default: Default string if value is None

    Returns:
        Formatted string
    """
    if value is None:
        return default
    if isinstance(value, float):
        if abs(value) >= 1e8:
            return f"{value / 1e8:.2f}亿"
        elif abs(value) >= 1e4:
            return f"{value / 1e4:.2f}万"
        else:
            return f"{value:.2f}"
    return str(value)


def generate_report(
    stock_name: str,
    ts_code: str,
    industry: str,
    data: dict[str, Any],
    search_results: dict[str, list[dict[str, Any]]],
    scores: dict[str, Any],
    screening: dict[str, str],
    checklist: dict[str, str],
    conclusion: str,
) -> str:
    """Generate the full markdown report.

    Args:
        stock_name: Stock name
        ts_code: Tushare stock code
        industry: Industry classification
        data: Stock data from Tushare
        search_results: Search results from Tavily
        scores: Scoring results
        screening: Screening results
        checklist: Checklist verification results
        conclusion: Final conclusion

    Returns:
        Markdown report string
    """
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Extract data
    basic = data.get("basic", {})
    daily = data.get("daily_basic", {})
    financial = data.get("financial", {})
    dividend = data.get("dividend", {})
    price_pos = data.get("price_position", {})

    # Build report
    lines = [
        f"# MR Dang 选股打分报告",
        "",
        f"【标的】{stock_name}（{ts_code}）",
        f"【行业归类】{industry}",
        f"【分析日期】{date_str}",
        "",
        "---",
        "",
        "## 一、基础筛查结果",
        "",
        "| 筛查项 | 结果 | 说明 |",
        "|--------|------|------|",
    ]

    # Add screening results
    for item, result in screening.items():
        status = "✅ 通过" if result == "通过" else "❌ 淘汰"
        lines.append(f"| {item} | {status} | |")

    screening_passed = all(r == "通过" for r in screening.values())
    screening_conclusion = "✅ 全部通过" if screening_passed else f"❌ 淘汰（原因：{[k for k, v in screening.items() if v != '通过'][0]}）"
    lines.extend([
        "",
        f"**筛查结论**：{screening_conclusion}",
        "",
        "---",
        "",
        "## 二、核心数据概览",
        "",
        "### 估值指标",
        "| 指标 | 数值 | 说明 |",
        "|------|------|------|",
        f"| PE(TTM) | {format_value(daily.get('pe_ttm'))} | |",
        f"| PB | {format_value(daily.get('pb'))} | |",
        f"| 总市值 | {format_value(daily.get('total_mv'))} | |",
        f"| 流通市值 | {format_value(daily.get('circ_mv'))} | |",
        "",
        "### 财务指标",
        "| 指标 | 数值 | 说明 |",
        "|------|------|------|",
        f"| 股息率(TTM) | {format_value(daily.get('dv_ratio'))}% | |",
        f"| 资产负债率 | {format_value(financial.get('debt_to_assets'))}% | |",
        f"| ROE | {format_value(financial.get('roe'))}% | |",
        f"| 经营现金流/股 | {format_value(financial.get('ocfps'))} | |",
        "",
        "### 分红历史",
        "| 指标 | 数值 | 说明 |",
        "|------|------|------|",
        f"| 近3年分红次数 | {dividend.get('dividend_count', 0)} | |",
        f"| 分红稳定性 | {dividend.get('dividend_stability', 'N/A')} | |",
        "",
    ])

    # Add price position
    if price_pos:
        lines.extend([
            "### 股价位置",
            "| 指标 | 数值 | 说明 |",
            "|------|------|------|",
            f"| 最新收盘价 | {format_value(price_pos.get('latest_close'))} | |",
            f"| 52周高点 | {format_value(price_pos.get('high_52w'))} | |",
            f"| 52周低点 | {format_value(price_pos.get('low_52w'))} | |",
            f"| 价格分位 | {format_value(price_pos.get('price_position_pct'))}% | {price_pos.get('position_level', '')} |",
            "",
        ])

    # Add business info from search
    lines.extend([
        "### 业务概况",
        f"- **主营业务**：{search_results.get('business_summary', 'N/A')}",
        f"- **行业地位**：{search_results.get('position_summary', 'N/A')}",
        "",
        "---",
        "",
        "## 三、维度打分明细",
        "",
        "| 维度 | 得分 | 满分 | 评分依据 |",
        "|------|------|------|----------|",
    ])

    # Add scores
    total_score = 0
    max_score = 0
    for dim, info in scores.items():
        score = info.get("score", 0)
        max_s = info.get("max", 0)
        reason = info.get("reason", "")
        total_score += score
        max_score += max_s
        lines.append(f"| {dim} | {score} | {max_s} | {reason} |")

    # Determine rating
    if total_score >= 80:
        rating = "⭐⭐⭐⭐⭐ 优秀"
        suggestion = "重点关注、可建仓"
    elif total_score >= 60:
        rating = "⭐⭐⭐⭐ 良好"
        suggestion = "可分批买入"
    elif total_score >= 40:
        rating = "⭐⭐⭐ 一般"
        suggestion = "谨慎观察"
    elif total_score >= 20:
        rating = "⭐⭐ 较差"
        suggestion = "建议回避"
    else:
        rating = "⭐ 极差"
        suggestion = "直接排除"

    lines.extend([
        "",
        f"**总分：{total_score} / {max_score}**",
        f"**评级：{rating}**",
        "",
        "---",
        "",
        "## 四、操作建议",
        "",
        suggestion,
        "",
        "---",
        "",
        "## 五、买入前清单核验",
        "",
        "| 清单项 | 状态 | 说明 |",
        "|--------|------|------|",
    ])

    # Add checklist
    passed_count = 0
    for item, status in checklist.items():
        status_icon = "✅ 达标" if status == "达标" else "⚠️ 存疑" if status == "存疑" else "❌ 不达标"
        lines.append(f"| {item} | {status_icon} | |")
        if status == "达标":
            passed_count += 1

    lines.extend([
        "",
        f"**达标项：{passed_count} / {len(checklist)}**",
        "",
        "---",
        "",
        "## 六、综合结论",
        "",
        conclusion,
        "",
        "---",
        "",
        "**风险提示**：本报告基于公开数据分析，不构成投资建议。投资有风险，入市需谨慎。",
        "",
    ])

    return "\n".join(lines)


def save_report(
    stock_name: str,
    ts_code: str,
    industry: str,
    data: dict[str, Any],
    search_results: dict[str, list[dict[str, Any]]],
    scores: dict[str, Any],
    screening: dict[str, str],
    checklist: dict[str, str],
    conclusion: str,
    output_dir: str | Path | None = None,
) -> Path:
    """Generate and save the report to disk.

    Args:
        stock_name: Stock name
        ts_code: Tushare stock code
        industry: Industry classification
        data: Stock data from Tushare
        search_results: Search results from Tavily
        scores: Scoring results
        screening: Screening results
        checklist: Checklist verification results
        conclusion: Final conclusion
        output_dir: Output directory (defaults to ~/reports/mrdang/)

    Returns:
        Path to saved report file
    """
    # Determine output directory
    if output_dir is None:
        output_dir = get_reports_dir()
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Generate report content
    content = generate_report(
        stock_name=stock_name,
        ts_code=ts_code,
        industry=industry,
        data=data,
        search_results=search_results,
        scores=scores,
        screening=screening,
        checklist=checklist,
        conclusion=conclusion,
    )

    # Generate filename and save
    filename = generate_report_filename(stock_name, ts_code)
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


if __name__ == "__main__":
    # Test report generation
    print("Testing report generation...")

    test_data = {
        "basic": {"name": "招商银行", "area": "深圳", "industry": "银行"},
        "daily_basic": {"pe_ttm": 6.62, "pb": 0.93, "total_mv": 99467071.0, "circ_mv": 81360556.0, "dv_ratio": 5.07},
        "financial": {"debt_to_assets": 90.2, "roe": 12.02, "ocfps": 17.9},
        "dividend": {"dividend_count": 2, "dividend_stability": "基本稳定"},
        "price_position": {"latest_close": 39.44, "high_52w": 48.55, "low_52w": 37.31, "price_position_pct": 19.0, "position_level": "接近历史低位"},
    }

    test_scores = {
        "生产资料属性": {"score": 19, "max": 20, "reason": "银行属于重资产行业"},
        "股息率": {"score": 20, "max": 20, "reason": "5.07% ≥ 5%"},
        "估值": {"score": 15, "max": 15, "reason": "PE 6.62 ≤ 10"},
        "行业竞争位置": {"score": 9, "max": 10, "reason": "股份制银行龙头"},
        "地域因素": {"score": 9, "max": 10, "reason": "深圳，经济发达"},
        "流动性与财务安全": {"score": 5, "max": 5, "reason": "万亿市值，财务健康"},
        "逻辑清晰度": {"score": 5, "max": 5, "reason": "逻辑清晰"},
    }

    test_screening = {
        "题材股筛查": "通过",
        "高估值筛查": "通过",
        "产能过剩筛查": "通过",
        "增发圈钱筛查": "通过",
        "逻辑复杂度筛查": "通过",
    }

    test_checklist = {
        "三句话逻辑": "达标",
        "生产资料属性": "达标",
        "股息率≥3%": "达标",
        "PE≤20": "达标",
        "股价不在高位": "达标",
        "不依赖短期财报": "达标",
        "独立判断": "达标",
        "跌30%敢加仓": "存疑",
        "无更优替代": "存疑",
        "明确持有周期": "存疑",
    }

    filepath = save_report(
        stock_name="招商银行",
        ts_code="600036.SH",
        industry="银行",
        data=test_data,
        search_results={"business_summary": "零售银行龙头", "position_summary": "股份制银行第一"},
        scores=test_scores,
        screening=test_screening,
        checklist=test_checklist,
        conclusion="适合长期持有",
    )

    print(f"Report saved to: {filepath}")
