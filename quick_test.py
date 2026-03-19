"""
Quick test runner - tests strategies with mock data
Useful for quick validation and stress testing
"""

import json
from collections import deque
from datetime import datetime


# Copy indicator functions from backtest
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


def sma(data, period):
    if len(data) < period:
        return sum(data) / len(data) if data else 0
    return sum(data[-period:]) / period


def generate_mock_data(num_candles=500, start_price=43000, volatility=0.02):
    """Generate mock OHLCV data for testing"""
    import random
    random.seed(42)  # For reproducibility
    
    klines = []
    current_price = start_price
    
    for i in range(num_candles):
        # Random price movement with volatility
        change_percent = random.gauss(0, volatility)  # Normal distribution
        open_price = current_price
        close_price = current_price * (1 + change_percent)
        
        # High and low for the candle
        high = max(open_price, close_price) * (1 + abs(random.gauss(0, volatility/2)))
        low = min(open_price, close_price) * (1 - abs(random.gauss(0, volatility/2)))
        
        volume = random.uniform(100, 1000)
        
        # Binance format: [time, open, high, low, close, volume, close_time, quote_volume, trades, taker_buy_base, taker_buy_quote, ignore]
        kline = [
            i * 60000,  # Open time (milliseconds)
            str(open_price),
            str(high),
            str(low),
            str(close_price),
            str(volume),
            i * 60000 + 59999,  # Close time
            str(volume * close_price),
            100,  # Number of trades
            str(volume / 2),  # Taker buy base asset
            str((volume / 2) * close_price),  # Taker buy quote asset
            "0"  # Ignore
        ]
        
        klines.append(kline)
        current_price = close_price
    
    return klines


def predict_rsi_ema(closes):
    """RSI + EMA strategy"""
    if len(closes) < 20 or not all(isinstance(c, (int, float)) for c in closes[-20:]):
        return "Hold"
    ema5 = ema(closes[-20:], 5)
    ema10 = ema(closes[-20:], 10)
    rsi_val = rsi(closes[-20:], 14)
    if ema5 > ema10 and rsi_val > 50:
        return "Up"
    else:
        return "Down"


def predict_bb(closes):
    """Bollinger Bands strategy"""
    if len(closes) < 20:
        return "Hold"
    
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
    
    lower, mid, upper = bollinger_bands(closes[-20:])
    last = closes[-1]
    prev = closes[-2]
    if prev < lower and last > prev:
        return "Up"
    if prev > upper and last < prev:
        return "Down"
    return "Up" if last > mid else "Down"


def predict_macd(closes):
    """MACD strategy"""
    if len(closes) < 30:
        return "Hold"
    
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
    
    macd_line, signal = macd_indicator(closes[-30:])
    return "Up" if macd_line > signal else "Down"


def run_quick_test():
    """Run quick backtest with mock data"""
    
    print("\n" + "="*70)
    print("QUICK BACKTEST WITH MOCK DATA")
    print("="*70)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")
    
    # Generate mock data
    print("Generating mock price data (500 candles)...")
    klines = generate_mock_data(500, start_price=43000, volatility=0.01)
    print(f"Generated data from ${float(klines[0][4]):.2f} to ${float(klines[-1][4]):.2f}\n")
    
    # Run backtests
    strategies = [
        ("RSI + EMA", predict_rsi_ema),
        ("Bollinger Bands", predict_bb),
        ("MACD", predict_macd)
    ]
    
    results = {}
    
    for strategy_name, predict_func in strategies:
        print(f"Testing {strategy_name}...", end=" ")
        
        closes = deque(maxlen=200)
        opens = deque(maxlen=200)
        
        # Initialize with first 100 candles
        for k in klines[:100]:
            opens.append(float(k[1]))
            closes.append(float(k[4]))
        
        initial_balance = 500.0
        wallet_usd = initial_balance
        wallet_btc = 0.0
        safe_wallet = 0.0
        fee_rate = 0.001
        position = False
        buy_price = 0.0
        btc_amount = 0.0
        trade_percent = 0.1
        
        trades = []
        
        # Run through rest of candles
        for idx, k in enumerate(klines[100:], start=100):
            opens.append(float(k[1]))
            closes.append(float(k[4]))
            
            current_price = float(k[4])
            prediction = predict_func(list(closes))
            
            if prediction == "Up" and not position:
                usd_to_use = wallet_usd * trade_percent
                if usd_to_use > 0:
                    btc_to_buy = usd_to_use / current_price * (1 - fee_rate)
                    wallet_usd -= usd_to_use
                    wallet_btc += btc_to_buy
                    position = True
                    buy_price = current_price
                    btc_amount = btc_to_buy
                    trades.append(('BUY', current_price, btc_to_buy))
            
            elif prediction == "Down" and position:
                usd_from_sell = btc_amount * current_price * (1 - fee_rate)
                profit = usd_from_sell - (btc_amount * buy_price)
                wallet_usd += usd_from_sell
                if profit > 0:
                    half_profit = profit / 2
                    safe_wallet += half_profit
                    wallet_usd -= half_profit
                wallet_btc -= btc_amount
                trades.append(('SELL', current_price, btc_amount, profit))
                position = False
                btc_amount = 0
        
        # Calculate final balance
        final_price = float(klines[-1][4])
        total_balance = wallet_usd + (wallet_btc * final_price) + safe_wallet
        total_return = ((total_balance - initial_balance) / initial_balance) * 100
        
        sell_trades = [t for t in trades if t[0] == 'SELL']
        profitable = sum(1 for t in sell_trades if t[3] > 0)
        
        results[strategy_name] = {
            'balance': total_balance,
            'return': total_return,
            'trades': len(trades),
            'win_rate': (profitable / len(sell_trades) * 100) if sell_trades else 0,
            'profitable_trades': profitable
        }
        
        print(f"✓")
    
    # Print results
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70 + "\n")
    
    print(f"{'Strategy':<20} {'Final Balance':<18} {'Return':<12} {'Win Rate':<12} {'Trades':<8}")
    print("-" * 70)
    
    for strategy_name in ["RSI + EMA", "Bollinger Bands", "MACD"]:
        result = results[strategy_name]
        print(f"{strategy_name:<20} ${result['balance']:>12.2f}{'':<3} "
              f"{result['return']:>6.2f}%{'':<4} {result['win_rate']:>6.2f}%{'':<4} "
              f"{result['trades']:>4}")
    
    print("\n" + "="*70 + "\n")
    print("✓ Quick test completed successfully!")
    print("\nTo test with REAL historical Binance data:")
    print("  Run: python backtest.py")
    print("\nTo test a specific date range:")
    print("  Modify backtest.py and change the start_time parameter")
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    run_quick_test()
