"""
TwelveData Connect
------------------
How to connect a script to TwelveData (stock/crypto/forex data API).

Docs: https://twelvedata.com/docs
API Reference: https://twelvedata.com/docs#api-reference
"""

import os

# -----------------------------------------------------------------------------
# 1. GET AN API KEY
# -----------------------------------------------------------------------------
# - Sign up: https://twelvedata.com/
# - Free tier: 8 API calls/min, 800/day
# - Copy your key from the dashboard

# -----------------------------------------------------------------------------
# 2. STORE KEY SECURELY (don't hardcode)
# -----------------------------------------------------------------------------
API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "YOUR_KEY_HERE")
# Set in terminal:  set TWELVE_DATA_API_KEY=your_key_here  (Windows)
# Or in .env file (use python-dotenv)

# -----------------------------------------------------------------------------
# 3. CONNECT USING THE OFFICIAL SDK (recommended)
# -----------------------------------------------------------------------------
# Install:  pip install twelvedata

from twelvedata import TDClient

td = TDClient(apikey=API_KEY)

# Example: fetch time-series for AAPL, 15-min bars
ts = td.time_series(
    symbol="AAPL",
    interval="15min",
    outputsize=30,
)
df = ts.as_pandas()  # returns pandas DataFrame with open, high, low, close, volume
print(df.head())

# -----------------------------------------------------------------------------
# 4. ALTERNATIVE: RAW HTTP REQUESTS (no SDK)
# -----------------------------------------------------------------------------
# import requests
# url = f"https://api.twelvedata.com/time_series?symbol=AAPL&interval=15min&outputsize=30&apikey={API_KEY}"
# r = requests.get(url)
# data = r.json()

# -----------------------------------------------------------------------------
# 5. COMMON PARAMETERS
# -----------------------------------------------------------------------------
# symbol     : "AAPL", "BTC/USD", "EUR/USD", etc.
# interval   : "1min", "5min", "15min", "30min", "1h", "4h", "1day"
# outputsize : 1–5000 (or "compact" ~100, "full" for daily)
# start_date : "2020-01-01" (optional)
# end_date   : "2020-12-31" (optional)

# -----------------------------------------------------------------------------
# 6. RATE LIMITS (free tier)
# -----------------------------------------------------------------------------
# 8 calls/minute, 800/day. Add delays between requests to avoid 429 errors.
