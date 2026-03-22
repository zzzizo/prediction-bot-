"""Debug script to see entry logic"""

import requests
from collections import deque
from datetime import datetime, timedelta

# Copy engine logic
class DebugEngine:
    def __init__(self):
        self.position = False
        self.buy_price = 0.0
        self.btc_amount = 0.0
        self.signal_strength = 0
        self.min_entry_strength = 1
        self.wallet_usd = 500.0
        self.trade_percent = 0.1
        self.fee_rate = 0.001
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.015
        self.trades = []
    
    def execute_trade(self, price, prediction, candle_index):
        """Execute trade based on prediction with risk management"""
        status = ""
        
        # Check if we should exit
        if self.position:
            current_pnl_pct = ((price - self.buy_price) / self.buy_price)
            if current_pnl_pct <= -self.stop_loss_pct:
                status = f"EXIT STOP_LOSS (-{current_pnl_pct*100:.1f}%)"
                self.position = False
                return status
            if current_pnl_pct >= self.take_profit_pct:
                status = f"EXIT TAKE_PROFIT (+{current_pnl_pct*100:.1f}%)"
                self.position = False
                return status
            if prediction == "Down":
                status = f"EXIT SIGNAL"
                self.position = False
                self.signal_strength = 0
            return status
        
        # Entry logic
        if prediction == "Up":
            self.signal_strength += 1
            if self.signal_strength >= self.min_entry_strength:
                usd_to_use = self.wallet_usd * self.trade_percent
                if usd_to_use >= 10:
                    btc_to_buy = usd_to_use / price * (1 - self.fee_rate)
                    self.position = True
                    self.buy_price = price
                    status = f"ENTRY [strength={self.signal_strength}]"
                    self.signal_strength = 0
                    self.trades.append({'price': price})
        else:
            self.signal_strength = 0
        
        return status

# Copy indicators
def ema(data, period):
    if len(data) < period:
        return data[-1] if data else 0
    multiplier = 2 / (period + 1)
    ema_values = [sum(data[:period]) / period]
    for price in data[period:]:
        ema_values.append((price * multiplier) + (ema_values[-1] * (1 - multiplier)))
    return ema_values[-1]

def sma(data, period):
    if len(data) < period:
        return sum(data) / len(data) if data else 0
    return sum(data[-period:]) / period

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

def macd_indicator(closes):
    if len(closes) < 26:
        return 0, 0
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = ema12 - ema26
    macd_history = []
    for i in range(len(closes) - 26, len(closes)):
        sub = closes[: i + 1]
        ema12_sub = ema(sub, 12)
        ema26_sub = ema(sub, 26)
        macd_history.append(ema12_sub - ema26_sub)
    signal_line = ema(macd_history, 9) if len(macd_history) >= 9 else macd_line
    return macd_line, signal_line

def predict_rsi_ema(closes):
    if len(closes) < 20 or not all(isinstance(c, (int, float)) for c in closes[-20:]):
        return "Hold"
    ema5 = ema(closes[-20:], 5)
    ema10 = ema(closes[-20:], 10)
    rsi_val = rsi(closes[-20:], 14)
    if ema5 > ema10 and rsi_val > 50:
        return "Up"
    else:
        return "Down"

# Fetch data
def get_klines_historical(symbol, interval='1m', start_time=None, end_time=None, limit=1000):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    if start_time:
        params['startTime'] = int(start_time.timestamp() * 1000)
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error: {e}")
        return []

# Main
start_time = datetime.now() - timedelta(days=7)
klines = get_klines_historical('BTCUSDT', interval='1m', start_time=start_time, limit=10080)

print(f"Fetched {len(klines)} candles\n")

engine = DebugEngine()
closes = deque(maxlen=200)

# Initialize
for k in klines[:100]:
    closes.append(float(k[4]))

print(f"\nFull trace (candles 100-350):")
print("Candle | Pred | Strength_Before | Strength_After | Position | Status")
print("-" * 70)

for idx, k in enumerate(klines[100:350], start=100):
    closes.append(float(k[4]))
    price = float(k[4])
    pred = predict_rsi_ema(list(closes))
    
    strength_before = engine.signal_strength
    status = engine.execute_trade(price, pred, idx)
    strength_after = engine.signal_strength
    
    if status or (idx > 110 and idx < 120) or (engine.position != (idx > 110)):
        print(f"{idx:3d}  | {pred:4s} | {strength_before:15d} | {strength_after:14d} | {engine.position} | {status}")


