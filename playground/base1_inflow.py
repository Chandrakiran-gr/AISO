"""
base1_inflow.py - Bootstrap and live-update base1.csv with OHLCV data.

On startup: backfills all missing data until DB is current, then updates as fast as possible.
Sources: yfinance (daily, long history), TwelveData (1-min, live + recent).
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from twelvedata import TDClient

# --- config ---
PLAYGROUND = Path(__file__).resolve().parent
BASE_FILE = PLAYGROUND / "base1.csv"
TWELVEDATA_KEY = "56f8cc6641af45ef8a2655f3c94701a1"  # from peper_trader_4
REQUESTS_PER_MIN = 8  # TwelveData free tier
SLEEP_BETWEEN_REQUESTS = 60 / REQUESTS_PER_MIN
MAX_DAILY_YEARS = 15   # how far back for daily (stay under 10GB)
MAX_1MIN_DAYS = 30     # how far back for 1-min from TwelveData
INTERVAL = "1min"      # live bars are 1-min
DAILY_INTERVAL = "1day"


def get_ticker_list() -> list[str]:
    """Fetch S&P 500 tickers from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url)
        df = tables[0]
        symbols = df["Symbol"].astype(str).str.strip().tolist()
        # yfinance uses '-' instead of '.' for classes
        symbols = [s.replace(".", "-") for s in symbols if s and s != "nan"]
        return symbols
    except Exception as e:
        print(f"Failed to fetch S&P 500 list: {e}")
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SPY"]  # fallback


def load_base() -> pd.DataFrame:
    """Load base1.csv or return empty DataFrame with correct columns."""
    if BASE_FILE.exists():
        df = pd.read_csv(BASE_FILE)
        return df
    return pd.DataFrame(columns=[
        "symbol", "interval", "datetime", "open", "high", "low", "close", "volume"
    ])


def save_base(df: pd.DataFrame) -> None:
    """Save DataFrame to base1.csv."""
    df = df.drop_duplicates(subset=["symbol", "interval", "datetime"], keep="last")
    df = df.sort_values(["symbol", "interval", "datetime"]).reset_index(drop=True)
    df.to_csv(BASE_FILE, index=False)


def bootstrap_daily(tickers: list[str]) -> pd.DataFrame:
    """Download daily history from yfinance (max years back)."""
    print("Bootstrap daily from yfinance...")
    end = datetime.now()
    start = end - timedelta(days=MAX_DAILY_YEARS * 365)
    period = "max" if MAX_DAILY_YEARS >= 20 else f"{MAX_DAILY_YEARS}y"
    data = yf.download(
        tickers,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False,
    )
    rows = []
    if len(tickers) == 1:
        data = {tickers[0]: data}
    elif "Close" in data.columns and isinstance(data.columns, pd.MultiIndex):
        # multi-ticker
        for sym in data.columns.get_level_values(0).unique():
            try:
                sub = data[sym].copy()
                if sub is None or sub.empty:
                    continue
                sub = sub.dropna(how="all")
                sub["symbol"] = sym
                sub["interval"] = DAILY_INTERVAL
                sub["datetime"] = sub.index.astype(str)
                sub = sub.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
                for col in ["open", "high", "low", "close", "volume"]:
                    if col not in sub.columns:
                        sub[col] = None
                rows.append(sub[["symbol", "interval", "datetime", "open", "high", "low", "close", "volume"]])
            except Exception as e:
                print(f"  skip {sym}: {e}")
    else:
        for sym in tickers:
            try:
                sub = data[sym] if sym in data else data.xs(sym, axis=1, level=0)
                if sub is None or sub.empty:
                    continue
                sub = sub.dropna(how="all").copy()
                sub["symbol"] = sym
                sub["interval"] = DAILY_INTERVAL
                sub["datetime"] = sub.index.astype(str)
                for old, new in [("Open", "open"), ("High", "high"), ("Low", "low"), ("Close", "close"), ("Volume", "volume")]:
                    if old in sub.columns:
                        sub = sub.rename(columns={old: new})
                for col in ["open", "high", "low", "close", "volume"]:
                    if col not in sub.columns:
                        sub[col] = None
                rows.append(sub[["symbol", "interval", "datetime", "open", "high", "low", "close", "volume"]])
            except Exception as e:
                print(f"  skip {sym}: {e}")
    if not rows:
        return pd.DataFrame(columns=["symbol", "interval", "datetime", "open", "high", "low", "close", "volume"])
    out = pd.concat(rows, ignore_index=True)
    return out


def fetch_twelvedata_1min(ticker: str, outputsize: int = 5000) -> pd.DataFrame | None:
    """Fetch 1-min bars from TwelveData."""
    td = TDClient(apikey=TWELVEDATA_KEY)
    try:
        ts = td.time_series(symbol=ticker, interval="1min", outputsize=outputsize)
        df = ts.as_pandas()
        if df.empty or "close" not in df.columns:
            return None
        df = df.reset_index()
        df = df.rename(columns={"datetime": "datetime"})
        if "datetime" not in df.columns and df.index.name == "datetime":
            df["datetime"] = df.index.astype(str)
        df["symbol"] = ticker
        df["interval"] = INTERVAL
        for c in ["open", "high", "low", "close", "volume"]:
            if c not in df.columns and c.capitalize() in df.columns:
                df[c] = df[c.capitalize()]
        keep = [c for c in ["symbol", "interval", "datetime", "open", "high", "low", "close", "volume"] if c in df.columns]
        return df[keep]
    except Exception as e:
        print(f"  TwelveData {ticker}: {e}")
        return None


def bootstrap_1min(tickers: list[str]) -> pd.DataFrame:
    """Download recent 1-min history from TwelveData (rate limited)."""
    print("Bootstrap 1-min from TwelveData (rate limited)...")
    rows = []
    for i, ticker in enumerate(tickers):
        df = fetch_twelvedata_1min(ticker, outputsize=5000)
        if df is not None and not df.empty:
            rows.append(df)
        if (i + 1) % REQUESTS_PER_MIN == 0:
            time.sleep(60)
        else:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
    if not rows:
        return pd.DataFrame(columns=["symbol", "interval", "datetime", "open", "high", "low", "close", "volume"])
    return pd.concat(rows, ignore_index=True)


def backfill_1min(base: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Backfill 1-min from last stored bar to now."""
    print("Backfilling 1-min gaps...")
    existing = base[base["interval"] == INTERVAL]
    appended = []
    for i, ticker in enumerate(tickers):
        sub = existing[existing["symbol"] == ticker]
        last_ts = None
        if not sub.empty:
            last_dt = pd.to_datetime(sub["datetime"].max())
            last_ts = last_dt
        df = fetch_twelvedata_1min(ticker, outputsize=5000)
        if df is None or df.empty:
            if (i + 1) % REQUESTS_PER_MIN == 0:
                time.sleep(60)
            else:
                time.sleep(SLEEP_BETWEEN_REQUESTS)
            continue
        df["dt"] = pd.to_datetime(df["datetime"])
        if last_ts is not None:
            df = df[df["dt"] > last_ts]
        if not df.empty:
            appended.append(df.drop(columns=["dt"]))
        if (i + 1) % REQUESTS_PER_MIN == 0:
            time.sleep(60)
        else:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
    if not appended:
        return base
    new_rows = pd.concat(appended, ignore_index=True)
    keep = [c for c in new_rows.columns if c in ["symbol", "interval", "datetime", "open", "high", "low", "close", "volume"]]
    new_rows = new_rows[keep]
    base = pd.concat([base, new_rows], ignore_index=True)
    return base


def live_update(base: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Fetch latest 1-min bar for each ticker and append."""
    rows = []
    for i, ticker in enumerate(tickers):
        df = fetch_twelvedata_1min(ticker, outputsize=2)
        if df is not None and not df.empty:
            rows.append(df.iloc[[-1]])
        if (i + 1) % REQUESTS_PER_MIN == 0:
            time.sleep(60)
        else:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
    if not rows:
        return base
    new_rows = pd.concat(rows, ignore_index=True)
    return pd.concat([base, new_rows], ignore_index=True)


def main():
    print("base1_inflow starting...")
    tickers = get_ticker_list()
    print(f"Tickers: {len(tickers)}")

    base = load_base()
    is_empty = base.empty

    # Phase 1: Bootstrap
    if is_empty or base[base["interval"] == DAILY_INTERVAL].empty:
        daily_df = bootstrap_daily(tickers)
        if not daily_df.empty:
            base = pd.concat([base, daily_df], ignore_index=True)
            save_base(base)
            print(f"Saved {len(daily_df)} daily rows")

    if is_empty or base[base["interval"] == INTERVAL].empty:
        min_df = bootstrap_1min(tickers)
        if not min_df.empty:
            base = load_base()
            base = pd.concat([base, min_df], ignore_index=True)
            save_base(base)
            print(f"Saved {len(min_df)} 1-min rows")

    # Phase 2: Backfill until current
    base = load_base()
    base = backfill_1min(base, tickers)
    save_base(base)

    # Phase 3: Live loop - update as fast as allowed
    print("Live updates (Ctrl+C to stop)...")
    while True:
        base = load_base()
        base = live_update(base, tickers)
        save_base(base)
        print(f"Updated at {datetime.now().isoformat()}")
        time.sleep(60)  # wait for next minute bar


if __name__ == "__main__":
    main()
