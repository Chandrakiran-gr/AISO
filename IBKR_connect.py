"""
IBKR Connect
------------
How to connect a script to Interactive Brokers (IBKR) for live/paper trading.

Requires: TWS (Trader Workstation) or IB Gateway running on your machine.
Docs: https://interactivebrokers.github.io/tws-api/
"""

import os

# -----------------------------------------------------------------------------
# 1. INSTALL ib_insync (easier than raw TWS API)
# -----------------------------------------------------------------------------
# pip install ib_insync
# Docs: https://ib-insync.readthedocs.io/

from ib_insync import IB, Stock, MarketOrder

# -----------------------------------------------------------------------------
# 2. START TWS OR IB GATEWAY
# -----------------------------------------------------------------------------
# - TWS: open Trader Workstation, enable "Enable ActiveX and Socket Clients"
#   in Edit > Global Configuration > API > Settings
# - IB Gateway: headless, good for servers
# - Paper: TWS paper = port 7497, Gateway paper = 4002
# - Live:  TWS live = port 7496, Gateway live = 4001

TWS_PAPER_PORT = 7497
TWS_LIVE_PORT = 7496
IB_GATEWAY_PAPER = 4002
IB_GATEWAY_LIVE = 4001

# -----------------------------------------------------------------------------
# 3. CONNECT
# -----------------------------------------------------------------------------
def connect_ibkr(port=TWS_PAPER_PORT, client_id=1):
    ib = IB()
    try:
        ib.connect("127.0.0.1", port, clientId=client_id)
        if ib.isConnected():
            print("Connected to IBKR")
            return ib
    except Exception as e:
        print(f"Connection failed: {e}")
        print("Is TWS/Gateway running? API enabled? Port correct?")
    return None

# Usage: ib = connect_ibkr(TWS_PAPER_PORT)

# -----------------------------------------------------------------------------
# 4. DEFINE CONTRACT AND PLACE ORDER (example)
# -----------------------------------------------------------------------------
contract = Stock("AAPL", "SMART", "USD")
ib.qualifyContracts(contract)

# Market order (example – don’t run blindly)
# order = MarketOrder("BUY", 1)   # 1 share
# trade = ib.placeOrder(contract, order)

# -----------------------------------------------------------------------------
# 5. GET MARKET DATA
# -----------------------------------------------------------------------------
# Historical bars:
# bars = ib.reqHistoricalData(contract, endDateTime='', durationStr='1 D',
#                             barSizeSetting='1 hour', whatToShow='TRADES',
#                             useRTH=True)
# Live ticker:
# ticker = ib.reqMktData(contract, '', False, False)
# ib.sleep(2)
# print(ticker.last)

# -----------------------------------------------------------------------------
# 6. DISCONNECT WHEN DONE
# -----------------------------------------------------------------------------
# ib.disconnect()
