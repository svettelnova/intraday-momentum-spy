"""
Download market data for an intraday momentum backtest on SPY.

Outputs (in ./data):
  spy_30min.csv  - SPY 30-minute bars from Alpaca (SIP feed, raw prices, regular hours only)
  spy_daily.csv  - SPY daily OHLC + adj_close from yfinance
  vix_daily.csv  - ^VIX daily OHLC from yfinance

Usage:
  export ALPACA_API_KEY=...  ALPACA_SECRET_KEY=...
  python get_data.py
"""

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SYMBOL = "SPY"
INTRADAY_START = date(2016, 1, 4)
DAILY_START = date(2015, 12, 1)  # one extra month for rolling windows
TZ = "America/New_York"
BAR_MINUTES = 30
DATA_DIR = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_env_file(path=Path(__file__).resolve().parent / ".env"):
    """
    Load KEY=value lines from a .env file next to this script into the
    environment, so the keys don't have to be exported in the terminal.
    Values in .env take priority over anything set in the terminal.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ[name.strip()] = value.strip()


def get_alpaca_keys():
    """Read Alpaca credentials from .env or the environment; stop if missing."""
    load_env_file()
    # Strip stray spaces/newlines and quotes (straight or curly) from copy-pasting.
    junk = " \t\r\n\"'\u201c\u201d\u2018\u2019"
    key = os.environ.get("ALPACA_API_KEY", "").strip(junk)
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip(junk)
    if not key or not secret:
        sys.exit(
            "ERROR: ALPACA_API_KEY and/or ALPACA_SECRET_KEY are not set.\n"
            "Put them in a file named .env next to get_data.py:\n"
            "  ALPACA_API_KEY=your_key\n"
            "  ALPACA_SECRET_KEY=your_secret\n"
            "or export them in the terminal:\n"
            "  export ALPACA_API_KEY='your_key'\n"
            "  export ALPACA_SECRET_KEY='your_secret'"
        )
    return key, secret


def get_market_calendar(key, secret, start, end):
    """
    Get the official market calendar (open/close time per trading day) from Alpaca.

    We need this because SIP bars include pre- and after-market trades: on an
    early-close day (13:00) Alpaca still returns bars for 13:00-15:30, but those
    are after-hours bars and must be dropped.

    Keys are either paper or live keys, so we try both endpoints.
    Returns a DataFrame with columns: date, open, close (naive New York times).
    """
    req = GetCalendarRequest(start=start, end=end)
    last_error = None
    for paper in (True, False):
        try:
            days = TradingClient(key, secret, paper=paper).get_calendar(req)
            return pd.DataFrame(
                {"date": [d.date for d in days],
                 "open": [d.open for d in days],
                 "close": [d.close for d in days]}
            )
        except Exception as e:  # wrong endpoint for these keys -> try the other one
            last_error = e
    if "401" in str(last_error):
        sys.exit(
            "ERROR: Alpaca rejected the API keys (401 Unauthorized).\n"
            f"  ALPACA_API_KEY: {len(key)} chars, starts with '{key[:2]}' (expected ~26 chars, 'PK' or 'AK')\n"
            f"  ALPACA_SECRET_KEY: {len(secret)} chars (expected ~44)\n"
            "Check for typos, and make sure key and secret belong to the same, current pair\n"
            "(regenerating keys in the Alpaca dashboard invalidates the old ones)."
        )
    sys.exit(f"ERROR: could not load the Alpaca market calendar: {last_error}")


def last_full_trading_day(calendar):
    """
    The last trading day whose session has fully ended (plus a 20-minute margin,
    because the free plan only allows SIP data older than 15 minutes).
    """
    now_ny = pd.Timestamp.now(tz=TZ).tz_localize(None)
    finished = calendar[calendar["close"] + timedelta(minutes=20) <= now_ny]
    return finished["date"].iloc[-1]


# ---------------------------------------------------------------------------
# 1) SPY 30-minute bars from Alpaca
# ---------------------------------------------------------------------------
def download_spy_30min(key, secret):
    """Download SPY 30-min bars year by year, keep regular hours, save CSV."""
    calendar = get_market_calendar(key, secret, INTRADAY_START, date.today())
    end_day = last_full_trading_day(calendar)
    calendar = calendar[calendar["date"] <= end_day]
    print(f"Alpaca: downloading {SYMBOL} 30-min bars {INTRADAY_START} -> {end_day}")

    client = StockHistoricalDataClient(key, secret)
    frames = []

    # One request per calendar year keeps each request small (rate limits).
    for year in range(INTRADAY_START.year, end_day.year + 1):
        start = max(INTRADAY_START, date(year, 1, 1))
        end = min(end_day, date(year, 12, 31))
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOL,
            timeframe=TimeFrame(BAR_MINUTES, TimeFrameUnit.Minute),
            # Request in New York time so the year boundaries are clean.
            start=pd.Timestamp(datetime.combine(start, time(0, 0)), tz=TZ).to_pydatetime(),
            end=pd.Timestamp(datetime.combine(end, time(23, 59)), tz=TZ).to_pydatetime(),
            feed=DataFeed.SIP,
            adjustment=Adjustment.RAW,
        )
        df = client.get_stock_bars(req).df  # MultiIndex (symbol, timestamp); the SDK handles paging
        print(f"  {year}: {len(df):6d} bars (incl. extended hours)")
        frames.append(df)

    bars = pd.concat(frames).reset_index()

    # Alpaca timestamps are UTC bar START times -> convert to New York time.
    bars["bar_start"] = pd.to_datetime(bars["timestamp"], utc=True).dt.tz_convert(TZ)
    bars["bar_end"] = bars["bar_start"] + pd.Timedelta(minutes=BAR_MINUTES)
    bars["date"] = bars["bar_start"].dt.date

    # Attach each day's official open/close from the calendar.
    cal = calendar.copy()
    cal["open"] = cal["open"].dt.tz_localize(TZ)
    cal["close"] = cal["close"].dt.tz_localize(TZ)
    bars = bars.merge(cal.rename(columns={"open": "mkt_open", "close": "mkt_close"}),
                      on="date", how="inner")  # inner join also drops non-trading days

    # Regular trading hours only: bar starts at/after the open and ends at/before
    # the close. On normal days that is bars starting 09:30 ... 15:30 (13 bars).
    rth = (bars["bar_start"] >= bars["mkt_open"]) & (bars["bar_end"] <= bars["mkt_close"])
    bars = bars[rth].copy()

    # Early close = official close before 16:00 (e.g. 13:00 half days).
    bars["early_close"] = bars["mkt_close"].dt.time < time(16, 0)

    cols = ["date", "bar_start", "bar_end", "open", "high", "low", "close",
            "volume", "vwap", "trade_count", "early_close"]
    bars = bars[cols].sort_values("bar_start").reset_index(drop=True)

    DATA_DIR.mkdir(exist_ok=True)
    bars.to_csv(DATA_DIR / "spy_30min.csv", index=False)
    print(f"  saved {len(bars)} bars -> {DATA_DIR / 'spy_30min.csv'}")
    return bars


# ---------------------------------------------------------------------------
# 2) Daily data from yfinance
# ---------------------------------------------------------------------------
def download_daily(ticker, with_adj_close):
    """Download daily OHLC (raw, not adjusted) from yfinance."""
    # auto_adjust=False -> Open/High/Low/Close are the traded prices
    # (split-adjusted only; SPY has had no splits) and 'Adj Close' is separate.
    df = yf.Ticker(ticker).history(start=DAILY_START.isoformat(), auto_adjust=False,
                                   interval="1d")
    if df.empty:
        sys.exit(f"ERROR: yfinance returned no data for {ticker}")

    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Adj Close": "adj_close"})
    cols = ["open", "high", "low", "close"] + (["adj_close"] if with_adj_close else [])
    df = df[cols]
    df.insert(0, "date", df.index.date)  # drop the timezone/time part
    # Drop today's row if the session is still running (it would be a partial bar).
    if df["date"].iloc[-1] == date.today() and pd.Timestamp.now(tz=TZ).time() < time(16, 30):
        df = df.iloc[:-1]
    return df.reset_index(drop=True)


def download_spy_daily():
    print(f"yfinance: downloading {SYMBOL} daily from {DAILY_START}")
    df = download_daily(SYMBOL, with_adj_close=True)
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(DATA_DIR / "spy_daily.csv", index=False)
    print(f"  saved {len(df)} rows -> {DATA_DIR / 'spy_daily.csv'}")
    return df


def download_vix_daily():
    print(f"yfinance: downloading ^VIX daily from {DAILY_START}")
    df = download_daily("^VIX", with_adj_close=False)
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(DATA_DIR / "vix_daily.csv", index=False)
    print(f"  saved {len(df)} rows -> {DATA_DIR / 'vix_daily.csv'}")
    return df


# ---------------------------------------------------------------------------
# 3) Quick checks
# ---------------------------------------------------------------------------
def check_data(bars, spy_daily, vix_daily):
    """Print basic sanity checks for the three datasets."""
    print("\n" + "=" * 70 + "\nDATA CHECKS\n" + "=" * 70)

    # --- Date range and number of trading days -----------------------------
    print("\nDate range / trading days:")
    for name, df in [("spy_30min", bars), ("spy_daily", spy_daily), ("vix_daily", vix_daily)]:
        print(f"  {name:10s} {df['date'].min()} -> {df['date'].max()}   "
              f"{df['date'].nunique()} days, {len(df)} rows")

    # --- Days without 13 bars ---------------------------------------------
    per_day = bars.groupby("date").agg(n_bars=("close", "size"),
                                       early_close=("early_close", "first"))
    odd = per_day[per_day["n_bars"] != 13]
    print(f"\nDays in spy_30min without 13 bars: {len(odd)} "
          f"({int(odd['early_close'].sum())} are early closes)")
    for d, row in odd.iterrows():
        tag = "early close (expected)" if row["early_close"] else "UNEXPECTED"
        print(f"  {d}  {row['n_bars']:2d} bars  {tag}")

    # --- Missing values and duplicates --------------------------------------
    print("\nMissing values:")
    for name, df in [("spy_30min", bars), ("spy_daily", spy_daily), ("vix_daily", vix_daily)]:
        na = df.isna().sum()
        na = na[na > 0]
        print(f"  {name:10s} " + ("none" if na.empty else na.to_dict().__str__()))

    print("\nDuplicates:")
    print(f"  spy_30min duplicate bar_start: {bars['bar_start'].duplicated().sum()}")
    print(f"  spy_daily duplicate dates:     {spy_daily['date'].duplicated().sum()}")
    print(f"  vix_daily duplicate dates:     {vix_daily['date'].duplicated().sum()}")

    # --- Trading days present in one SPY file but not the other --------------
    intraday_days = set(bars["date"])
    daily_days = set(spy_daily.loc[spy_daily["date"] >= bars["date"].min(), "date"])
    daily_days = {d for d in daily_days if d <= bars["date"].max()}
    print(f"\nDays in spy_daily missing from spy_30min: {sorted(daily_days - intraday_days)}")
    print(f"Days in spy_30min missing from spy_daily: {sorted(intraday_days - daily_days)}")

    # --- Compare intraday first open / last close with daily open / close ----
    first_last = bars.groupby("date").agg(first_open=("open", "first"),
                                          last_close=("close", "last"))
    cmp = first_last.join(spy_daily.set_index("date")[["open", "close"]], how="inner")
    cmp["open_diff_pct"] = (cmp["first_open"] / cmp["open"] - 1) * 100
    cmp["close_diff_pct"] = (cmp["last_close"] / cmp["close"] - 1) * 100

    print(f"\nAlpaca 30-min vs yfinance daily ({len(cmp)} common days):")
    for col, label in [("open_diff_pct", "first open vs daily open"),
                       ("close_diff_pct", "last close vs daily close")]:
        absdiff = cmp[col].abs()
        print(f"  {label:27s} median |diff| = {absdiff.median():.4f}%   "
              f"max |diff| = {absdiff.max():.4f}% (on {absdiff.idxmax()})")

    big = cmp[(cmp["open_diff_pct"].abs() > 0.2) | (cmp["close_diff_pct"].abs() > 0.2)]
    print(f"\nDays with |diff| > 0.2%: {len(big)}")
    if not big.empty:
        print(big[["first_open", "open", "open_diff_pct",
                   "last_close", "close", "close_diff_pct"]].round(4).to_string())


# ---------------------------------------------------------------------------
def main():
    key, secret = get_alpaca_keys()  # check keys first, before any downloading
    bars = download_spy_30min(key, secret)
    spy_daily = download_spy_daily()
    vix_daily = download_vix_daily()
    check_data(bars, spy_daily, vix_daily)


if __name__ == "__main__":
    main()
