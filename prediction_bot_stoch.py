import requests
import time
import logging
from collections import deque
from requests.exceptions import RequestException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_klines(symbol, interval='1m', limit=100, retries=3):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or not all(isinstance(k, list) and len(k) == 12 for k in data):
                raise ValueError("Invalid kline data format")
            return data
        except (RequestException, ValueError) as e:
            if attempt == retries - 1:
                raise e
            time.sleep(2 ** attempt)
    return []


def sma(data, period):
    if len(data) < period:
        return sum(data) / len(data) if data else 0
    return sum(data[-period:]) / period


def stochastic(closes, lows, highs, period=14, smoothing=3):
    k_pct = None
    if len(closes) < period or len(lows) < period or len(highs) < period:
        return 50, 50
    recent_closes = list(closes)[-period:]
    recent_lows = list(lows)[-period:]
    recent_highs = list(highs)[-period:]
    lowest_low = min(recent_lows)
    highest_high = max(recent_highs)
    last_close = recent_closes[-1]
    if highest_high == lowest_low:
        k_pct = 50
    else:
        k_pct = (last_close - lowest_low) / (highest_high - lowest_low) * 100
    # %D is sma of %K values
    # compute history of %K for smoothing
    k_history = []
    for i in range(period, len(closes)):
        window_closes = list(closes)[i-period+1:i+1]
        window_lows = list(lows)[i-period+1:i+1]
        window_highs = list(highs)[i-period+1:i+1]
        ll = min(window_lows)
        hh = max(window_highs)
        if hh == ll:
            k_val = 50
        else:
            k_val = (window_closes[-1] - ll) / (hh - ll) * 100
        k_history.append(k_val)
    k_history.append(k_pct)
    d_val = sma(k_history, smoothing)
    return k_pct, d_val


def predict(closes, lows, highs):
    if len(closes) < 20 or len(lows) < 20 or len(highs) < 20:
        return "Hold"
    k, d = stochastic(closes, lows, highs)
    return "Up" if k > d else "Down"


symbol = 'BTCUSDT'
closes = deque(maxlen=200)
lows = deque(maxlen=200)
highs = deque(maxlen=200)
opens = deque(maxlen=200)

# seed the deque with historical data
initial_data = get_klines(symbol, limit=100)
for k in initial_data:
    opens.append(float(k[1]))
    lows.append(float(k[3]))
    highs.append(float(k[2]))
    closes.append(float(k[4]))

last_close = closes[-1]

wallet_usd = 500.0
wallet_btc = 0.0
safe_wallet = 0.0
fee_rate = 0.001
position = False
buy_price = 0.0
btc_amount = 0.0
trade_percent = 0.1

while True:
    latest_data = get_klines(symbol, limit=1)
    latest_k = latest_data[0]
    new_open = float(latest_k[1])
    new_high = float(latest_k[2])
    new_low = float(latest_k[3])
    new_close = float(latest_k[4])
    if new_close != last_close:
        opens.append(new_open)
        highs.append(new_high)
        lows.append(new_low)
        closes.append(new_close)
        last_close = new_close
        next_pred = predict(closes, lows, highs)
        live_pred = "Up" if closes[-1] > closes[-2] else "Down"
        logging.info(f"Live prediction: {live_pred}")
        logging.info(f"Next candle prediction: {next_pred}")
        current_price = closes[-1]
        if next_pred == "Up" and not position:
            usd_to_use = wallet_usd * trade_percent
            if usd_to_use > 0:
                btc_to_buy = usd_to_use / current_price * (1 - fee_rate)
                wallet_usd -= usd_to_use
                wallet_btc += btc_to_buy
                position = True
                buy_price = current_price
                btc_amount = btc_to_buy
        elif next_pred == "Down" and position:
            usd_from_sell = btc_amount * current_price * (1 - fee_rate)
            wallet_usd += usd_from_sell
            profit = usd_from_sell - (btc_amount * buy_price)
            if profit > 0:
                half_profit = profit / 2
                safe_wallet += half_profit
                wallet_usd -= half_profit
            wallet_btc -= btc_amount
            position = False
            btc_amount = 0
        direction = "Up" if closes[-1] > opens[-1] else "Down"
        logging.info(f"Candle direction: {direction}")
        logging.info(f"Wallet USD: {wallet_usd:.2f}, BTC: {wallet_btc:.6f}, Safe: {safe_wallet:.2f}")
    if position and (current_price <= buy_price * 0.98 or current_price >= buy_price * 1.05):
        usd_from_sell = btc_amount * current_price * (1 - fee_rate)
        wallet_usd += usd_from_sell
        profit = usd_from_sell - (btc_amount * buy_price)
        if profit > 0:
            half_profit = profit / 2
            safe_wallet += half_profit
            wallet_usd -= half_profit
        wallet_btc -= btc_amount
        position = False
        btc_amount = 0
    time.sleep(60)
