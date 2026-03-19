"""
Interactive strategy tester - test predictions with manual price inputs
"""

from collections import deque
from datetime import datetime


# Indicator functions
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


class StrategyTester:
    def __init__(self):
        self.closes = deque(maxlen=200)
        self.opens = deque(maxlen=200)
        self.lows = deque(maxlen=200)
        self.highs = deque(maxlen=200)
    
    def add_price(self, open_price, high_price, low_price, close_price):
        """Add a new candle"""
        self.opens.append(open_price)
        self.highs.append(high_price)
        self.lows.append(low_price)
        self.closes.append(close_price)
    
    def get_indicators(self):
        """Get all indicator values"""
        if len(self.closes) < 20:
            return None
        
        indicators = {
            'ema5': ema(list(self.closes), 5),
            'ema10': ema(list(self.closes), 10),
            'rsi14': rsi(list(self.closes), 14),
        }
        
        if len(self.closes) >= 20:
            lower, mid, upper = bollinger_bands(list(self.closes))
            indicators['bb_lower'] = lower
            indicators['bb_middle'] = mid
            indicators['bb_upper'] = upper
        
        if len(self.closes) >= 26:
            macd, signal = macd_indicator(list(self.closes))
            indicators['macd'] = macd
            indicators['signal'] = signal
        
        if len(self.closes) >= 14:
            k, d = stochastic(self.closes, self.lows, self.highs)
            indicators['stoch_k'] = k
            indicators['stoch_d'] = d
        
        return indicators
    
    def predict_rsi_ema(self):
        if len(self.closes) < 20:
            return "WAIT", "Not enough data"
        ema5 = ema(list(self.closes[-20:]), 5)
        ema10 = ema(list(self.closes[-20:]), 10)
        rsi_val = rsi(list(self.closes[-20:]), 14)
        
        reason = f"EMA5={ema5:.2f}, EMA10={ema10:.2f}, RSI={rsi_val:.2f}"
        if ema5 > ema10 and rsi_val > 50:
            return "UP", reason
        return "DOWN", reason
    
    def predict_bb(self):
        if len(self.closes) < 20:
            return "WAIT", "Not enough data"
        lower, mid, upper = bollinger_bands(list(self.closes[-20:]))
        last = self.closes[-1]
        prev = self.closes[-2]
        reason = f"Price={last:.2f}, Lower={lower:.2f}, Mid={mid:.2f}, Upper={upper:.2f}"
        
        if prev < lower and last > prev:
            return "UP", reason + " (bounce off lower band)"
        if prev > upper and last < prev:
            return "DOWN", reason + " (rejected at upper band)"
        return ("UP" if last > mid else "DOWN"), reason
    
    def predict_macd(self):
        if len(self.closes) < 26:
            return "WAIT", "Need 26+ candles"
        macd, signal = macd_indicator(list(self.closes))
        reason = f"MACD={macd:.6f}, Signal={signal:.6f}, Hist={macd-signal:.6f}"
        return ("UP" if macd > signal else "DOWN"), reason
    
    def predict_stoch(self):
        if len(self.closes) < 14:
            return "WAIT", "Need 14+ candles"
        k, d = stochastic(self.closes, self.lows, self.highs)
        reason = f"K%={k:.2f}, D%={d:.2f}"
        return ("UP" if k > d else "DOWN"), reason


def generate_sample_data():
    """Generate sample price data for testing"""
    prices = [
        (43000, 43100, 42900, 43050),
        (43050, 43200, 43000, 43150),
        (43150, 43300, 43100, 43200),
        (43200, 43250, 43050, 43100),
        (43100, 43150, 42950, 43000),
        (43000, 43100, 42800, 42900),
        (42900, 42950, 42700, 42850),
        (42850, 43000, 42800, 42950),
        (42950, 43100, 42900, 43050),
        (43050, 43200, 43000, 43150),
    ]
    return prices


def interactive_demo():
    """Interactive demo"""
    print("\n" + "="*70)
    print("INTERACTIVE STRATEGY TESTER")
    print("="*70 + "\n")
    
    tester = StrategyTester()
    sample_data = generate_sample_data()
    
    print(f"Loading {len(sample_data)} sample candles...\n")
    
    for i, (open_p, high, low, close) in enumerate(sample_data, 1):
        tester.add_price(open_p, high, low, close)
        print(f"\nCandle #{i}: O={open_p} H={high} L={low} C={close}")
        
        # Get indicators
        indicators = tester.get_indicators()
        if indicators:
            print(f"\nIndicators:")
            print(f"  EMA5:     {indicators['ema5']:.2f}")
            print(f"  EMA10:    {indicators['ema10']:.2f}")
            print(f"  RSI(14):  {indicators['rsi14']:.2f}")
            
            if 'bb_lower' in indicators:
                print(f"  BB Lower: {indicators['bb_lower']:.2f}")
                print(f"  BB Mid:   {indicators['bb_middle']:.2f}")
                print(f"  BB Upper: {indicators['bb_upper']:.2f}")
            
            if 'macd' in indicators:
                print(f"  MACD:     {indicators['macd']:.6f}")
                print(f"  Signal:   {indicators['signal']:.6f}")
            
            if 'stoch_k' in indicators:
                print(f"  Stoch K:  {indicators['stoch_k']:.2f}")
                print(f"  Stoch D:  {indicators['stoch_d']:.2f}")
        
        # Get predictions
        print(f"\nPredictions:")
        
        pred_rsi_ema, reason_rsi_ema = tester.predict_rsi_ema()
        print(f"  RSI + EMA:      {pred_rsi_ema:>4}  ({reason_rsi_ema})")
        
        pred_bb, reason_bb = tester.predict_bb()
        print(f"  Bollinger Bands: {pred_bb:>4}  ({reason_bb})")
        
        pred_macd, reason_macd = tester.predict_macd()
        print(f"  MACD:            {pred_macd:>4}  ({reason_macd})")
        
        pred_stoch, reason_stoch = tester.predict_stoch()
        print(f"  Stochastic:      {pred_stoch:>4}  ({reason_stoch})")
        
        print("-" * 70)
    
    print("\n✓ Interactive demo completed!\n")
    print("This shows how each strategy would predict price movement given the data.")
    print("Predictions include reasoning and indicator values.\n")
    print("="*70 + "\n")


if __name__ == "__main__":
    interactive_demo()
