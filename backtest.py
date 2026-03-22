"""
Backtesting framework for trading strategies
Tests strategies on historical Binance data and generates detailed reports
"""

import requests
import json
from collections import deque
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_klines_historical(symbol, interval='1m', start_time=None, end_time=None, limit=1000):
    """Fetch historical klines from Binance"""
    url = "https://api.binance.com/api/v3/klines"
    
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    
    if start_time:
        params['startTime'] = int(start_time.timestamp() * 1000)
    if end_time:
        params['endTime'] = int(end_time.timestamp() * 1000)
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching klines: {e}")
        return []


# ============ INDICATOR FUNCTIONS ============

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


def stochastic(closes, lows, highs, period=14, smoothing=3):
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


# ============ STRATEGY PREDICTION FUNCTIONS ============

def predict_rsi_ema(closes):
    """RSI + EMA strategy - Original with improved discipline"""
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
    """Bollinger Bands strategy - Original with risk management"""
    if len(closes) < 20 or not all(isinstance(c, (int, float)) for c in closes[-20:]):
        return "Hold"
    lower, mid, upper = bollinger_bands(closes[-20:])
    last = closes[-1]
    prev = closes[-2]
    if prev < lower and last > prev:
        return "Up"
    if prev > upper and last < prev:
        return "Down"
    return "Up" if last > mid else "Down"


def predict_macd(closes):
    """MACD strategy - Original with risk management"""
    if len(closes) < 30 or not all(isinstance(c, (int, float)) for c in closes[-30:]):
        return "Hold"
    macd_line, signal = macd_indicator(closes[-30:])
    return "Up" if macd_line > signal else "Down"


def predict_stoch(closes, lows, highs):
    """Stochastic strategy"""
    if len(closes) < 20 or len(lows) < 20 or len(highs) < 20:
        return "Hold"
    k, d = stochastic(closes, lows, highs)
    return "Up" if k > d else "Down"


# ============ BACKTEST ENGINE ============

class BacktestEngine:
    def __init__(self, symbol='BTCUSDT', initial_balance=500.0, trade_percent=0.1, fee_rate=0.001):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.trade_percent = trade_percent
        self.fee_rate = fee_rate
        
        self.wallet_usd = initial_balance
        self.wallet_btc = 0.0
        self.safe_wallet = 0.0
        
        self.position = False
        self.buy_price = 0.0
        self.btc_amount = 0.0
        
        # Risk management parameters
        self.stop_loss_pct = 0.005  # 0.5% stop loss
        self.take_profit_pct = 0.02  # 2% take profit target
        self.min_entry_strength = 4  # Require 4 consecutive signals for strong momentum
        
        self.trades = []
        self.balances_history = []
        self.predictions = []
        self.signal_strength = 0  # Track consecutive signals
        
    def execute_trade(self, price, prediction, candle_index):
        """Execute trade based on prediction with risk management"""
        
        # Check stop loss / take profit first if we have a position
        if self.position:
            current_pnl_pct = ((price - self.buy_price) / self.buy_price)
            
            # Stop loss exit
            if current_pnl_pct <= -self.stop_loss_pct:
                self._exit_position(price, candle_index, "STOP_LOSS")
                return
            
            # Take profit exit
            if current_pnl_pct >= self.take_profit_pct:
                self._exit_position(price, candle_index, "TAKE_PROFIT")
                return
            
            # Exit on strong bearish signal
            if prediction == "Down":
                self._exit_position(price, candle_index, "SIGNAL")
                self.signal_strength = 0
            return  # Don't process new entries if we have open position
        
        # Entry logic with signal confirmation (only when no position)
        if prediction == "Up":
            self.signal_strength += 1
            
            # Only enter after required signal confirmation
            if self.signal_strength >= self.min_entry_strength:
                usd_to_use = self.wallet_usd * self.trade_percent
                if usd_to_use >= 10:  # Minimum trade size to cover fees
                    btc_to_buy = usd_to_use / price * (1 - self.fee_rate)
                    self.wallet_usd -= usd_to_use
                    self.wallet_btc += btc_to_buy
                    self.position = True
                    self.buy_price = price
                    self.btc_amount = btc_to_buy
                    self.trades.append({
                        'type': 'BUY',
                        'price': price,
                        'amount': btc_to_buy,
                        'candle': candle_index,
                        'entry_strength': self.signal_strength
                    })
                    self.signal_strength = 0
        else:
            # Reset on any non-Up signal
            self.signal_strength = 0
    
    def _exit_position(self, price, candle_index, exit_reason):
        """Close position with proper accounting"""
        usd_from_sell = self.btc_amount * price * (1 - self.fee_rate)
        profit = usd_from_sell - (self.btc_amount * self.buy_price)
        pnl_percent = (profit / (self.btc_amount * self.buy_price)) * 100 if self.btc_amount > 0 else 0
        
        self.wallet_usd += usd_from_sell
        self.wallet_btc -= self.btc_amount
        
        # Lock in profits to safe wallet
        if profit > 0:
            half_profit = profit / 2
            self.safe_wallet += half_profit
            self.wallet_usd -= half_profit
        
        self.trades.append({
            'type': 'SELL',
            'price': price,
            'amount': self.btc_amount,
            'profit': profit,
            'pnl_percent': pnl_percent,
            'candle': candle_index,
            'exit_reason': exit_reason
        })
        
        self.position = False
        self.btc_amount = 0
    
    def get_total_balance(self, current_price):
        """Calculate total balance in USD"""
        return self.wallet_usd + (self.wallet_btc * current_price) + self.safe_wallet
    
    def get_stats(self, current_price):
        """Generate backtest statistics"""
        total_balance = self.get_total_balance(current_price)
        total_return = ((total_balance - self.initial_balance) / self.initial_balance) * 100
        
        buy_trades = [t for t in self.trades if t['type'] == 'BUY']
        sell_trades = [t for t in self.trades if t['type'] == 'SELL']
        
        profitable_trades = [t for t in sell_trades if t['profit'] > 0]
        losing_trades = [t for t in sell_trades if t['profit'] < 0]
        
        win_rate = (len(profitable_trades) / len(sell_trades) * 100) if sell_trades else 0
        total_profit = sum(t.get('profit', 0) for t in sell_trades)
        avg_profit = (total_profit / len(sell_trades)) if sell_trades else 0
        
        return {
            'total_balance': total_balance,
            'total_return_percent': total_return,
            'wallet_usd': self.wallet_usd,
            'wallet_btc': self.wallet_btc,
            'safe_wallet': self.safe_wallet,
            'total_trades': len(self.trades),
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'profitable_trades': len(profitable_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'total_profit': total_profit,
            'avg_profit_per_trade': avg_profit
        }


def run_backtest(strategy_name, klines, predict_func):
    """Run backtest for a strategy"""
    engine = BacktestEngine()
    
    closes = deque(maxlen=200)
    opens = deque(maxlen=200)
    lows = deque(maxlen=200)
    highs = deque(maxlen=200)
    
    # Initialize with first 100 candles
    for k in klines[:100]:
        opens.append(float(k[1]))
        lows.append(float(k[3]))
        highs.append(float(k[2]))
        closes.append(float(k[4]))
    
    # Run through rest of the klines
    for idx, k in enumerate(klines[100:], start=100):
        opens.append(float(k[1]))
        lows.append(float(k[3]))
        highs.append(float(k[2]))
        closes.append(float(k[4]))
        
        current_price = float(k[4])
        
        # Get prediction
        if strategy_name == "Stochastic":
            prediction = predict_func(closes, lows, highs)
        else:
            prediction = predict_func(list(closes))
        
        engine.predictions.append(prediction)
        
        # Execute trade
        if prediction != "Hold":
            engine.execute_trade(current_price, prediction, idx)
        
        # Record balance
        engine.balances_history.append({
            'candle': idx,
            'price': current_price,
            'balance': engine.get_total_balance(current_price)
        })
    
    return engine, engine.get_stats(float(klines[-1][4]))


# ============ MAIN BACKTESTING ============

def main():
    """Run backtests for all strategies"""
    
    print("\n" + "="*70)
    print("TRADING STRATEGY BACKTEST")
    print("="*70)
    print(f"Symbol: BTCUSDT")
    print(f"Initial Balance: $500.00")
    print(f"Trade Percent: 10%")
    print(f"Fee Rate: 0.1%")
    print("="*70 + "\n")
    
    # Fetch historical data (last 7 days of 5-minute candles)
    print("Fetching historical data from Binance...")
    start_time = datetime.now() - timedelta(days=7)
    klines = get_klines_historical('BTCUSDT', interval='5m', start_time=start_time, limit=2016)
    
    if not klines or len(klines) < 100:
        print("Error: Could not fetch sufficient historical data")
        return
    
    print(f"Fetched {len(klines)} candles\n")
    
    # Run backtests
    strategies = [
        ("RSI + EMA", predict_rsi_ema),
        ("Bollinger Bands", predict_bb),
        ("MACD", predict_macd)
    ]
    
    results = {}
    
    for strategy_name, predict_func in strategies:
        print(f"\nTesting {strategy_name}...")
        try:
            engine, stats = run_backtest(strategy_name, klines, predict_func)
            results[strategy_name] = {
                'engine': engine,
                'stats': stats
            }
        except Exception as e:
            print(f"  Error: {e}")
    
    # Print results
    print("\n" + "="*70)
    print("BACKTEST RESULTS")
    print("="*70 + "\n")
    
    for strategy_name, result in results.items():
        stats = result['stats']
        print(f"\n{strategy_name.upper()}")
        print("-" * 70)
        print(f"  Final Balance:        ${stats['total_balance']:.2f}")
        print(f"  Total Return:         {stats['total_return_percent']:.2f}%")
        print(f"  Wallet USD:           ${stats['wallet_usd']:.2f}")
        print(f"  Wallet BTC:           {stats['wallet_btc']:.6f}")
        print(f"  Safe Wallet:          ${stats['safe_wallet']:.2f}")
        print(f"  Total Trades:         {stats['total_trades']}")
        print(f"  Buy Trades:           {stats['buy_trades']}")
        print(f"  Sell Trades:          {stats['sell_trades']}")
        print(f"  Profitable Trades:    {stats['profitable_trades']}")
        print(f"  Losing Trades:        {stats['losing_trades']}")
        print(f"  Win Rate:             {stats['win_rate']:.2f}%")
        print(f"  Total Profit:         ${stats['total_profit']:.2f}")
        print(f"  Avg Profit/Trade:     ${stats['avg_profit_per_trade']:.2f}")
    
    # Summary comparison
    print("\n" + "="*70)
    print("STRATEGY COMPARISON")
    print("="*70)
    print(f"{'Strategy':<20} {'Return %':<15} {'Win Rate':<15} {'Trades':<10}")
    print("-" * 70)
    
    for strategy_name, result in sorted(results.items(), 
                                        key=lambda x: x[1]['stats']['total_return_percent'], 
                                        reverse=True):
        stats = result['stats']
        print(f"{strategy_name:<20} {stats['total_return_percent']:>6.2f}%{'':<8} "
              f"{stats['win_rate']:>6.2f}%{'':<8} {stats['total_trades']:>6}")
    
    print("\n" + "="*70 + "\n")
    
    # Save detailed results to JSON
    output = {}
    for strategy_name, result in results.items():
        output[strategy_name] = {
            'stats': result['stats'],
            'trades': result['engine'].trades[:20]  # First 20 trades
        }
    
    with open('/Users/zain/Documents/flo\'s project/backtest_results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print("Detailed results saved to backtest_results.json")


if __name__ == "__main__":
    main()
