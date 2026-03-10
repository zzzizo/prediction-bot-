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
            response.raise_for_status()  # Raises for 4xx/5xx errors
            data = response.json()
            if not isinstance(data, list) or not all(isinstance(k, list) and len(k) == 12 for k in data):
                raise ValueError("Invalid kline data format")
            return data
        except (RequestException, ValueError) as e:
            if attempt == retries - 1:
                raise e
            time.sleep(2 ** attempt)  # Exponential backoff
    return []

def ema(data, period):
    if len(data) < period:
        return data[-1] if data else 0
    multiplier = 2 / (period + 1)
    ema_values = [sum(data[:period]) / period]
    for price in data[period:]:
        ema_values.append((price * multiplier) + (ema_values[-1] * (1 - multiplier)))
    return ema_values[-1]

def rsi(data, period=14):
    if len(data) < period + 1:
        return 50
    gains = []
    losses = []
    for i in range(1, len(data)):
        change = data[i] - data[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi_val = 100 - (100 / (1 + rs))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_val = 100
        else:
            rs = avg_gain / avg_loss
            rsi_val = 100 - (100 / (1 + rs))
    return rsi_val

def predict(closes):
    if len(closes) < 20 or not all(isinstance(c, (int, float)) for c in closes[-20:]):
        return "Hold"  # Or skip trading
    ema5 = ema(closes[-20:], 5)
    ema10 = ema(closes[-20:], 10)
    rsi_val = rsi(closes[-20:], 14)
    if ema5 > ema10 and rsi_val > 50:
        return "Up"
    else:
        return "Down"

symbol = 'BTCUSDT'
closes = deque(maxlen=200)
opens = deque(maxlen=200)

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
        # Sell logic with stop-loss/take-profit
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