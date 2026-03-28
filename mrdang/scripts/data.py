"""Tushare data fetching functions for MR Dang stock analysis."""

import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import tushare as ts

# Initialize Tushare with token from environment
_TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN")
if not _TUSHARE_TOKEN:
    raise ValueError("TUSHARE_TOKEN environment variable not set")

pro = ts.pro_api(_TUSHARE_TOKEN)


def search_stock(keyword: str) -> pd.DataFrame:
    """Search for stock by name or code.

    Args:
        keyword: Stock name or code to search

    Returns:
        DataFrame with columns: ts_code, name, area, industry, market, list_date
    """
    df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,area,industry,market,list_date")
    # Filter by keyword
    mask = df["name"].str.contains(keyword, case=False, na=False) | df["ts_code"].str.contains(
        keyword, case=False, na=False
    )
    result = df[mask]
    return result.reset_index(drop=True)


def get_stock_basic(ts_code: str) -> dict[str, Any]:
    """Get basic stock information.

    Args:
        ts_code: Tushare stock code (e.g., "600036.SH")

    Returns:
        Dictionary with basic stock info
    """
    df = pro.stock_basic(ts_code=ts_code, fields="ts_code,symbol,name,area,industry,market,list_date")
    if df.empty:
        return {"error": f"No data found for {ts_code}"}
    return df.iloc[0].to_dict()


def get_daily_basic(ts_code: str, trade_date: str | None = None) -> dict[str, Any]:
    """Get daily basic metrics (PE, PB, market cap, etc.).

    Args:
        ts_code: Tushare stock code
        trade_date: Trade date in format YYYYMMDD (defaults to latest)

    Returns:
        Dictionary with daily basic metrics
    """
    if trade_date is None:
        # Get latest trading date
        today = datetime.now()
        # Try last 10 days to find a trading day
        for i in range(10):
            check_date = (today - timedelta(days=i)).strftime("%Y%m%d")
            df = pro.daily_basic(ts_code=ts_code, trade_date=check_date)
            if not df.empty:
                break
    else:
        df = pro.daily_basic(ts_code=ts_code, trade_date=trade_date)

    if df.empty:
        return {"error": f"No daily basic data found for {ts_code}"}

    row = df.iloc[0]
    return {
        "ts_code": row.get("ts_code"),
        "trade_date": row.get("trade_date"),
        "close": row.get("close"),
        "turnover_rate": row.get("turnover_rate"),
        "turnover_rate_f": row.get("turnover_rate_f"),
        "volume_ratio": row.get("volume_ratio"),
        "pe": row.get("pe"),  # PE(TTM)
        "pe_ttm": row.get("pe_ttm"),
        "pb": row.get("pb"),
        "ps": row.get("ps"),
        "ps_ttm": row.get("ps_ttm"),
        "dv_ratio": row.get("dv_ratio"),  # Dividend yield (TTM) in %
        "dv_ttm": row.get("dv_ttm"),
        "total_mv": row.get("total_mv"),  # Total market value in 10k RMB
        "circ_mv": row.get("circ_mv"),  # Circulating market value in 10k RMB
        "free_share": row.get("free_share"),
        "total_share": row.get("total_share"),
    }


def get_financial_indicator(ts_code: str, periods: int = 4) -> pd.DataFrame:
    """Get financial indicators for recent periods.

    Args:
        ts_code: Tushare stock code
        periods: Number of recent periods to fetch

    Returns:
        DataFrame with financial indicators
    """
    df = pro.fina_indicator(ts_code=ts_code, fields=[
        "ts_code", "ann_date", "end_date", "roe", "roa", "debt_to_assets",
        "ocfps", "basic_eps", "dt_eps", "cfps", "ebit_of_gr", "op_yoy",
        "ebt_of_gr", "roa_yearly", "roe_dt", "roe_yearly", "cfps_yoy",
        "current_ratio", "quick_ratio", "grossprofit_margin", "profit_dedt",
    ])
    if df.empty:
        return pd.DataFrame()

    # Sort by end_date descending and take top periods
    df = df.sort_values("end_date", ascending=False).head(periods)
    return df.reset_index(drop=True)


def get_financial_indicator_summary(ts_code: str) -> dict[str, Any]:
    """Get latest financial indicator summary.

    Args:
        ts_code: Tushare stock code

    Returns:
        Dictionary with key financial metrics
    """
    df = get_financial_indicator(ts_code, periods=1)
    if df.empty:
        return {"error": f"No financial indicator data found for {ts_code}"}

    row = df.iloc[0]
    return {
        "ts_code": row.get("ts_code"),
        "end_date": row.get("end_date"),
        "roe": row.get("roe"),  # ROE (%)
        "roa": row.get("roa"),  # ROA (%)
        "debt_to_assets": row.get("debt_to_assets"),  # Debt to assets ratio (%)
        "ocfps": row.get("ocfps"),  # Operating cash flow per share
        "basic_eps": row.get("basic_eps"),  # Basic EPS
        "current_ratio": row.get("current_ratio"),  # Current ratio
        "quick_ratio": row.get("quick_ratio"),  # Quick ratio
        "grossprofit_margin": row.get("grossprofit_margin"),  # Gross profit margin (%)
    }


def get_dividend_info(ts_code: str, years: int = 3) -> dict[str, Any]:
    """Get dividend information for recent years.

    Args:
        ts_code: Tushare stock code
        years: Number of years to analyze

    Returns:
        Dictionary with dividend metrics
    """
    # Get dividend records
    df = pro.dividend(ts_code=ts_code, fields="ts_code,end_date,div_proc,stk_div,cash_div,record_date,ex_date,ann_date")

    if df.empty:
        return {
            "ts_code": ts_code,
            "dividend_count": 0,
            "avg_cash_div": 0,
            "dividend_stability": "无分红记录",
            "dividend_years": [],
        }

    # Filter for cash dividends (实施完成)
    cash_div_df = df[df["div_proc"] == "实施"].copy()
    cash_div_df = cash_div_df.sort_values("end_date", ascending=False)

    # Get recent years
    current_year = datetime.now().year
    recent_years = [str(current_year - i) for i in range(years)]

    # Count dividends per year
    yearly_div = {}
    for _, row in cash_div_df.iterrows():
        year = str(row["end_date"])[:4]
        if year in recent_years:
            if year not in yearly_div:
                yearly_div[year] = 0
            if pd.notna(row["cash_div"]) and row["cash_div"] > 0:
                yearly_div[year] += row["cash_div"]

    dividend_years = list(yearly_div.keys())
    dividend_count = len(dividend_years)
    avg_cash_div = sum(yearly_div.values()) / years if years > 0 else 0

    # Determine stability
    if dividend_count >= years:
        stability = "稳定分红"
    elif dividend_count >= years - 1:
        stability = "基本稳定"
    elif dividend_count > 0:
        stability = "分红不稳定"
    else:
        stability = "无分红记录"

    return {
        "ts_code": ts_code,
        "dividend_count": dividend_count,
        "years_analyzed": years,
        "avg_cash_div_per_10_shares": round(avg_cash_div, 2),
        "dividend_stability": stability,
        "dividend_years": dividend_years,
        "yearly_details": yearly_div,
    }


def get_daily_ohlcv(ts_code: str, days: int = 250) -> pd.DataFrame:
    """Get daily OHLCV data.

    Args:
        ts_code: Tushare stock code
        days: Number of trading days to fetch

    Returns:
        DataFrame with columns: trade_date, open, high, low, close, vol, amount
    """
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 1.5)).strftime("%Y%m%d")  # Buffer for non-trading days

    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

    if df.empty:
        return pd.DataFrame()

    # Sort by date ascending
    df = df.sort_values("trade_date").reset_index(drop=True)

    # Take last 'days' records
    if len(df) > days:
        df = df.tail(days).reset_index(drop=True)

    return df[["trade_date", "open", "high", "low", "close", "vol", "amount"]]


def get_price_position(ts_code: str, days: int = 250) -> dict[str, Any]:
    """Calculate price position relative to recent history.

    Args:
        ts_code: Tushare stock code
        days: Number of trading days for history

    Returns:
        Dictionary with price position metrics
    """
    df = get_daily_ohlcv(ts_code, days)

    if df.empty:
        return {"error": f"No price data found for {ts_code}"}

    latest_close = df.iloc[-1]["close"]
    high_52w = df["high"].max()
    low_52w = df["low"].min()
    avg_close = df["close"].mean()

    # Position relative to 52-week range (0-100%)
    price_position = (latest_close - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50

    # Distance from high
    distance_from_high = (high_52w - latest_close) / high_52w * 100

    # Determine position level
    if price_position >= 80:
        position_level = "接近历史高位"
    elif price_position >= 60:
        position_level = "偏高位置"
    elif price_position >= 40:
        position_level = "中等位置"
    elif price_position >= 20:
        position_level = "偏低位置"
    else:
        position_level = "接近历史低位"

    return {
        "ts_code": ts_code,
        "latest_close": latest_close,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "avg_close": round(avg_close, 2),
        "price_position_pct": round(price_position, 1),
        "distance_from_high_pct": round(distance_from_high, 1),
        "position_level": position_level,
    }


def get_all_data(ts_code: str) -> dict[str, Any]:
    """Get all relevant data for a stock.

    Args:
        ts_code: Tushare stock code

    Returns:
        Dictionary with all stock data
    """
    return {
        "basic": get_stock_basic(ts_code),
        "daily_basic": get_daily_basic(ts_code),
        "financial": get_financial_indicator_summary(ts_code),
        "dividend": get_dividend_info(ts_code),
        "price_position": get_price_position(ts_code),
    }


if __name__ == "__main__":
    # Test the functions
    print("Testing search_stock...")
    result = search_stock("招商银行")
    print(result)

    if not result.empty:
        ts_code = result.iloc[0]["ts_code"]
        print(f"\nTesting with ts_code: {ts_code}")

        print("\n--- Stock Basic ---")
        print(get_stock_basic(ts_code))

        print("\n--- Daily Basic ---")
        print(get_daily_basic(ts_code))

        print("\n--- Financial Indicator ---")
        print(get_financial_indicator_summary(ts_code))

        print("\n--- Dividend Info ---")
        print(get_dividend_info(ts_code))

        print("\n--- Price Position ---")
        print(get_price_position(ts_code))
