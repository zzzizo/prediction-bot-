# Trading Bot Testing Guide

## Overview

You now have a complete paper trading and backtesting framework to test your 4 trading strategies without risking real money. The framework includes:

### Scripts Available

#### 1. **quick_test.py** ⚡ - Fast Testing
- Tests all 3 strategies with **mock data** (500 simulated candles)
- Runs instantly - great for quick validation
- Shows: Final balance, return %, win rate, number of trades
- **Use this**: When you want quick feedback

**Run:**
```bash
python quick_test.py
```

#### 2. **backtest.py** 📊 - Full Backtesting
- Tests all 4 strategies with **real Binance historical data** (last 10 hours of 1-min candles)
- Complete trading simulation with realistic conditions
- Detailed metrics per strategy
- Saves results to `backtest_results.json`
- **Use this**: For serious strategy evaluation

**Run:**
```bash
python backtest.py
```

#### 3. **interactive_test.py** 🎯 - Interactive Demo
- Manually test how each strategy reacts to price movements
- Shows indicator values (RSI, EMA, MACD, Stochastic, Bollinger Bands)
- Shows prediction reasoning for each decision
- Uses sample price data
- **Use this**: To understand how each strategy works

**Run:**
```bash
python interactive_test.py
```

---

## Strategy Comparison

### Strategies Tested

1. **RSI + EMA** (prediction_bot.py)
   - Combines 5/10 EMA crossover with RSI above 50
   - Good for trending markets
   - Moderate trading frequency

2. **Bollinger Bands** (prediction_bot_bb.py)
   - Uses price bounces off bands
   - Detects overbought/oversold conditions
   - Good for range-bound markets

3. **MACD** (prediction_bot_macd.py)
   - Classic trend-following indicator
   - Uses MACD vs signal line crossover
   - Works well in strong trends

4. **Stochastic** (prediction_bot_stoch.py)
   - K% and D% crossover
   - Detects momentum reversal
   - Can be prone to whipsaws

---

## Understanding the Results

### Key Metrics Explained

```
Final Balance:        $497.95     ← Total account value after trading
Total Return:         -0.41%      ← Return percentage on initial capital
Wallet USD:           $448.11     ← Cash remaining
Wallet BTC:           0.000700    ← Bitcoin held (unrealized)
Safe Wallet:          $0.05       ← Locked profits
Total Trades:         45          ← Buy + Sell orders
Buy Trades:           23          ← Entry signals
Sell Trades:          22          ← Exit signals
Profitable Trades:    2           ← Trades that made money
Losing Trades:        20          ← Trades that lost money
Win Rate:             9.09%       ← % of trades that were profitable
Total Profit:         $-0.96      ← Net profit/loss from all trades
Avg Profit/Trade:     $-0.04      ← Average per trade
```

### Interpreting Results

**Good Signs:**
- ✅ Positive total return percentage
- ✅ Win rate > 50%
- ✅ More profitable trades than losing trades
- ✅ Moderate trade frequency (not too many entries)

**Red Flags:**
- ❌ Negative return → Strategy is losing money
- ❌ Very low win rate → Poor prediction accuracy
- ❌ Over-trading (>100 trades) → Generating false signals
- ❌ Very few trades → Strategy might be too conservative

---

## How to Test

### Quick Validation (2 minutes)
```bash
# 1. Test with mock data
python quick_test.py

# 2. See which strategy performs best
# 3. Check if strategies are functional
```

### Full Market Analysis (5-10 minutes)
```bash
# 1. Run full backtest with real data
python backtest.py

# 2. Compare all 4 strategies
# 3. Review backtest_results.json for detailed trades
```

### Detailed Debug (5 minutes)
```bash
# 1. Run interactive tester
python interactive_test.py

# 2. See how each strategy makes decisions
# 3. Understand indicator values and reasoning
```

---

## Customizing Tests

### Test Different Time Periods

Edit `backtest.py` to test different historical periods:

```python
# Line ~360 - Change the time range:
start_time = datetime.now() - timedelta(hours=10)  # Change this
klines = get_klines_historical('BTCUSDT', interval='1m', start_time=start_time, limit=500)
```

**Options:**
- `timedelta(hours=1)` - Last 1 hour (60 candles)
- `timedelta(hours=5)` - Last 5 hours (300 candles)
- `timedelta(hours=24)` - Last 24 hours (1440 candles)
- `timedelta(days=7)` - Last 7 days (10080 candles)

### Test Different Intervals

Change the candle timeframe:

```python
# In backtest.py around line 360:
klines = get_klines_historical('BTCUSDT', interval='5m', ...)  # 5-min candles
```

**Options:**
- `'1m'` - 1 minute (default)
- `'5m'` - 5 minutes
- `'15m'` - 15 minutes
- `'1h'` - 1 hour
- `'4h'` - 4 hours

### Adjust Trading Parameters

Edit `backtest.py` BacktestEngine initialization:

```python
engine = BacktestEngine(
    symbol='BTCUSDT',
    initial_balance=500.0,      # Starting capital
    trade_percent=0.1,          # % of wallet to use per trade
    fee_rate=0.001              # Trading fee (0.1%)
)
```

---

## Running Tests Live (Paper Trading)

### Option 1: Monitor Current Performance

Modify a strategy file (e.g., `prediction_bot.py`) to add logging:

```python
# At the end of the while loop, add:
if position:
    current_unrealized = (wallet_btc * current_price) - (btc_amount * buy_price)
    logging.info(f"Open Position - Unrealized P&L: {current_unrealized:.2f}")
else:
    logging.info(f"No position - Waiting for next signal")
```

Then run continuously:
```bash
python prediction_bot.py
```

### Option 2: Collect Performance Data Over Time

Create a new file `performance_tracker.py`:

```python
import json
from datetime import datetime

# Every hour, run the backtest and record results
# Save to performance_history.json to track over time
```

---

## Common Issues & Solutions

### Issue: "Not enough data" in interactive test
**Solution:** More than 10 candles are needed. Strategies require:
- RSI + EMA: 20 candles minimum
- Bollinger Bands: 20 candles minimum
- MACD: 26+ candles
- Stochastic: 14+ candles

### Issue: All strategies showing losses
**Solution:** This is normal! Short timeframes with volatile markets often show losses. Try:
1. Test on longer periods (24 hours instead of 5 hours)
2. Test on less volatile assets
3. Adjust trade_percent (maybe use 5% instead of 10%)

### Issue: Win rate is 0% or very low
**Solution:** Strategy might not fit the current market:
1. Try different timeframes
2. Try different assets beyond BTCUSDT
3. Use parameter optimization

---

## Next Steps to Improve Strategies

### 1. Optimize Parameters
- Test different RSI periods (9, 14, 21)
- Test different EMA periods (5/10, 10/20, 20/50)
- Test different Bollinger Bands periods (20, 30, 50)

### 2. Combine Strategies
- Use multiple signals for confirmation
- Example: "Buy only if RSI > 50 AND price > 20-day MA"

### 3. Risk Management
- Add stop-loss (already in code!)
- Add take-profit targets
- Reduce trade_percent in volatile markets

### 4. Market Selection
- Test on different crypto pairs (ETHUSDT, BNBUSDT, etc.)
- Test on different timeframes
- Test on top performers only

---

## File Structure

```
flo's project/
├── prediction_bot.py          ← RSI + EMA (live trading)
├── prediction_bot_bb.py       ← Bollinger Bands (live trading)
├── prediction_bot_macd.py     ← MACD (live trading)
├── prediction_bot_stoch.py    ← Stochastic (live trading)
├── backtest.py                ← Full backtesting system
├── quick_test.py              ← Fast mock data testing
├── interactive_test.py        ← Interactive strategy demo
├── backtest_results.json      ← Generated results file
└── TESTING_GUIDE.md           ← This file
```

---

## Safety Reminder: Paper Trading ≠ Live Trading

**Important differences:**
- ❌ No slippage in backtests (prices may move before execution)
- ❌ No network latency
- ❌ No partial fills
- ❌ No liquidity issues
- ✅ Good for understanding strategy behavior
- ✅ Safe way to evaluate performance

**Before going live with real money:**
1. Test on multiple time periods
2. Get consistent positive returns
3. Understand what the strategy does
4. Start with very small position sizes
5. Monitor closely for first week

---

## Questions/Issues?

The testing framework provides:
- ✅ Strategy performance metrics
- ✅ Trade-by-trade analysis
- ✅ Comparison between strategies
- ✅ Risk/reward analysis
- ✅ Detailed debugging information

Run tests regularly to evaluate your strategies before deploying to live trading!
