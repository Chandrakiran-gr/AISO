from ib_insync import *
from twelvedata import TDClient
import time 
import pandas as pd 
import numpy as np 
import os
from datetime import datetime, time as dt_time  # rename the class to avoid conflict
import time  # this is the module you use for time.sleep() etc.
import pytz
import math


api_key = "56f8cc6641af45ef8a2655f3c94701a1"

freqency = 15 # controlls  how long betwene each main loop run 
interval = "15min"  # controlls how far back the indecators look 

file = "C:/Users/aidan/Documents/trader/my_data3.csv"



#meow 


def stockprice(ticker):
    td = TDClient(apikey=api_key)

    # Get the most recent 1-minute candle (or any short interval)
    ts = td.time_series(symbol=ticker, interval='1min', outputsize=1)
    df = ts.as_pandas()

    # Get the latest close price
    price = float(df["close"].iloc[0])

    # Print for confirmation
    print("\n— Latest Price for", ticker, ":", price)
    return price


def is_market_open():
    ny_tz = pytz.timezone("America/New_York")
    now = datetime.now(ny_tz)

    # Check weekday (Monday=0 to Friday=4)
    if now.weekday() >= 5:
        return False

    market_open = dt_time(9, 30)
    market_close = dt_time(16, 0)

    current_time = now.time()

    return market_open <= current_time <= market_close


def pdread(row, column, filename):
    # Load the DataFrame
    df = pd.read_csv(filename)

    # Use the last row if "auto" is passed
    if row == "auto":
        row = len(df) - 1  # index of the last row

    if row == "auto2":
        row = len(df) - 2  #

    # Return the value at the specified row and column
    return df.iloc[row, column]


def pdwright(arr, filename):
    # Check if file exists
    if os.path.exists(filename):
        df = pd.read_csv(filename)
        # Calculate the next index number (first column)
        next_index = df.iloc[-1, 0] + 1 if not df.empty else 0
    else:
        # If file doesn't exist, create an empty DataFrame
        next_index = 0
        df = pd.DataFrame(columns=['index'] + [f'col{i}' for i in range(len(arr))])

    # Prepend the index number to the row
    full_row = [next_index] + arr

    # Convert to DataFrame with same columns
    new_row = pd.DataFrame([full_row], columns=df.columns)

    # Append and save
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(filename, index=False)


def get_indicators(ticker, interval):
    """
    Fetch close price, MACD(12,26,9), and RSI(14) for the given ticker.
    Uses only pandas/numpy; 1 TwelveData credit.

    Parameters
    ----------
    ticker : str
        e.g. "AAPL"
    interval : str
        TwelveData interval, e.g. "15min", "1h", "1day"

    Returns
    -------
    list[float]
        [close_price, macd, macd_signal, rsi]
    """

    # Choose candle history depth: ~3× longest period (26) but at least 80
    interval_map = {
        "1min": 400,   # ~6.5 h
        "5min": 300,   # ~25 h
        "15min": 200,  # ~2 days
        "30min": 160,  # ~3 days
        "1h": 120,     # ~5 days
        "4h": 90,      # ~15 days
        "1day": 90     # ~4 months
    }
    candles = interval_map.get(interval, 120)

    td = TDClient(apikey=api_key)
    ts = td.time_series(symbol=ticker, interval=interval, outputsize=candles)
    df = ts.as_pandas()

    if df.empty or "close" not in df:
        raise ValueError(f"No price data returned for {ticker}")

    df.sort_index(inplace=True)

    # ── MACD 12/26/9 ────────────────────────────────────────────────
    ema_fast = df["close"].ewm(span=12, adjust=False).mean()
    ema_slow = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    # ── RSI 14 ──────────────────────────────────────────────────────
    delta = df["close"].diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain, index=df.index).ewm(alpha=1/14, adjust=False).mean()
    avg_loss = pd.Series(loss, index=df.index).ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # Attach calculated columns
    df["macd"] = macd
    df["macd_signal"] = macd_signal
    df["rsi"] = rsi

    # Keep only rows where all indicators are valid
    valid = df.dropna(subset=["macd", "macd_signal", "rsi"])
    if valid.empty:
        raise ValueError(f"Not enough data to compute indicators for {ticker}")

    latest = valid.iloc[-1]

    return [float(latest["close"]), float(latest["macd"]), float(latest["macd_signal"]), float(latest["rsi"])]




def IBKRtrade(ticker, amount_usd):

    # Connect to TWS or IB Gateway
    ib = IB()
    ib.connect('127.0.0.1', 7496, clientId=1)  # TWS = 7497, IB Gateway = 4001


    if not ib.isConnected():
        print("Not connected to IBKR")
        return

    # Define the stock
    contract = Stock(ticker, 'SMART', 'USD')
    ib.qualifyContracts(contract)

    # Get latest closing price (no subscription required)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True,
        formatDate=1
    )

    if not bars:
        print(f"Failed to get historical price for {ticker}")
        return

    price = bars[-1].close
    if price <= 0 or price != price:  # catches invalid/NaN price
        print(f"Invalid closing price for {ticker}")
        return

    # Calculate number of whole shares
    shares = int(abs(amount_usd) // price)
    if shares == 0:
        print("Amount too small to buy/sell at least 1 share")
        return

    # Decide action
    action = 'BUY' if amount_usd > 0 else 'SELL'
    order = MarketOrder(action, shares)
    trade = ib.placeOrder(contract, order)

    print(f"{action}ING {shares} shares of {ticker} at approx. ${price:.2f}")
    return trade

# Example usage
#IBKRtrade(ticker, 0)


def compute_allocation_weight(price, macd, macd_signal, rsi ):  
    # === Tunable Parameters ===
    # Indicator weightings (must sum to 1.0)
    alpha = 0.34  # Weight of RSI
    beta  = 0.33  # Weight of MACD trend (macd / price)
    gamma = 0.33  # Weight of MACD momentum (macd - signal)

    # Scaling factors
    k1 = 5        # MACD trend sensitivity
    k2 = 10       # MACD momentum sensitivity
    lamb = 2      # Logistic steepness (higher = sharper transitions)

    # === Normalized Inputs ===
    r = (rsi - 50) / 50                          # RSI normalization
    m1 = math.tanh(k1 * macd / price)            # MACD trend normalized
    m2 = math.tanh(k2 * (macd - macd_signal) / price)  # MACD crossover signal

    # === Weighted Score ===
    score = alpha * r + beta * m1 + gamma * m2

    # === Logistic Mapping to [0, 1] ===
    weight = 1 / (1 + math.exp(-lamb * score))

    return weight


def compute_cash_weight(avg_score, max_cash=0.25):
    """
    avg_score: float between 0 and 1 (average of all stock allocation scores)
    max_cash: maximum fraction of portfolio to hold in cash
    """
    avg_score = max(0, min(1, avg_score))  # clamp just in case
    return max_cash * (1 - avg_score)


def papertrade(ticker, amount_usd):
    global arr
    global cash 

    for i in range(3):
        if arr[i][0] == ticker:
            print("trying to buy " + str(amount_usd) + "  of  " + str(ticker) + " | ~"  + str( amount_usd / arr[i][2] ) + "  shares")
            if amount_usd > 0:
                

                if cash - amount_usd > 0:

                    arr[i][1] = arr[i][1] + ((amount_usd  - (amount_usd % arr[i][2]))/arr[i][2])

                    print(str((amount_usd  - (amount_usd % arr[i][2]))/arr[i][2]) + "  shares bought")
                    cash = cash - amount_usd + (amount_usd % arr[i][2])

                else:
                


                    print("not enought cash")

            if amount_usd < 0:
                if arr[i][1] >= (abs(amount_usd) - (abs(amount_usd) % arr[i][2]))/arr[i][2]:

                    arr[i][1] = arr[i][1] - (abs(amount_usd) - (abs(amount_usd) % arr[i][2]))/arr[i][2]

                    print(str((abs(amount_usd) - (abs(amount_usd) % arr[i][2]))/arr[i][2]) + "  shares sold")

                    cash = cash + (abs(amount_usd) - (abs(amount_usd) % arr[i][2]))

                else:
                    print("not enought shares owned to sell")


def save():
    global arr 
    global cash 

    pdwright([arr[0][0],arr[1][0],arr[2][0],arr[0][1],arr[1][1],arr[2][1],arr[0][2],arr[1][2],arr[2][2],cash,time.time()],file)



#weights arr

Warr = [0,0,0,0]

#indecators arr
Iarr = [[0,0,0,0],[0,0,0,0],[0,0,0,0]]


#main values arr 
#'ticker',shares owned,value of each share 
arr = [["",0,0],["",0,0],["",0,0]]


cash = pdread("auto",10,file)


for i in range(3):

    arr[i][0] = pdread("auto",i + 1,file)

    arr[i][1] = pdread("auto",i + 4,file)
    
    arr[i][2] = pdread("auto",i + 7,file)



active = True 

while active:

    #waits until the next time the data drops 
    print("waiting " + str((60 * (freqency + 1)) - (time.time() % (60 * freqency))) + " seconds")
    time.sleep((60 * (freqency + 1)) - (time.time() % (60 * freqency)))

    avg_score = 0

    if is_market_open():

        print("HI")

        #get indecators and price data  
        for i in range(3):
            I = get_indicators(arr[i][0], interval)
            for j in range(4):
                Iarr[i][j] = I[j]

        #update stock prices 

            arr[i][2] = Iarr[i][0]
        
        #calculate weights 
            w = compute_allocation_weight(Iarr[i][0], Iarr[i][1], Iarr[i][2], Iarr[i][3] )
            Warr[i] = w

            avg_score = avg_score + w

        avg_score = avg_score/3
        
        Warr[3] = compute_cash_weight(avg_score, max_cash=0.25)

        #calculate equedy allocations based on weights
        
        equity = 0

        for i in range(3):
            equity = equity + arr[i][1] * arr[i][2]

        equity = equity + cash        

        total_weights = 0

        for i in range(4):
            total_weights = total_weights + Warr[i]

        #cualculate order 
        t1_amount = equity * Warr[0]/total_weights
        t2_amount = equity * Warr[1]/total_weights
        t3_amount = equity * Warr[2]/total_weights
        cash_amount = equity * Warr[3]/total_weights

        #place trades

        papertrade(arr[0][0],t1_amount - (arr[0][1] * arr[0][2]))
        papertrade(arr[1][0],t2_amount - (arr[1][1] * arr[1][2]))
        papertrade(arr[2][0],t3_amount - (arr[2][1] * arr[2][2]))

        #IBKRtrade(arr[0][0],t1_amount - (arr[0][1] * arr[0][2]))
        #IBKRtrade(arr[1][0],t2_amount - (arr[1][1] * arr[1][2]))
        #IBKRtrade(arr[2][0],t3_amount - (arr[2][1] * arr[2][2]))

        #save
        save()


    else:
        print("NYSE closed--hold")
        
    
    time.sleep(1)
    active = True








