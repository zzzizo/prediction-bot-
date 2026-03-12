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


def bollinger_bands(closes, period=20, num_std=2):
    if len(closes) < period:
        return 0, 0, 0
    window = closes[-period:]
    mean = sma(window, period)
    variance = sum((x - mean) ** 2 for x in window) / period
    std = variance ** 0.5
    upper = mean + num_std * std
    lower = mean - num_std * std
    return lower, mean, upper


def predict(closes):
    # use 20-period bollinger bands
    if len(closes) < 20 or not all(isinstance(c, (int, float)) for c in closes[-20:]):
        return "Hold"
    lower, mid, upper = bollinger_bands(closes[-20:])
    last = closes[-1]
    prev = closes[-2]
    # simple rule: if price bounces off lower band -> up, if price rejected at upper -> down
    if prev < lower and last > prev:
        return "Up"
    if prev > upper and last < prev:
        return "Down"
    # fallback to band centre crossing
    return "Up" if last > mid else "Down"


symbol = 'BTCUSDT'
closes = deque(maxlen=200)
opens = deque(maxlen=200)

# seed
initial_data = get_klines(symbol, limit=100)
for k in initial_data:
    opens.append(float(k[1]))
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
    new_close = float(latest_k[4])
    if new_close != last_close:
        opens.append(new_open)
        closes.append(new_close)
        last_close = new_close
        next_pred = predict(list(closes))
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
