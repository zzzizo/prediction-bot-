Here’s a compact paragraph for each bot’s approach:

- **prediction_bot.py** blends two EMAs (5 & 10) with a 14‑period RSI; it buys when the fast EMA is above the slow one **and** RSI is above 50, otherwise it signals down.  
- **prediction_bot_macd.py** uses the MACD line (EMA‑12 – EMA‑26) and its 9‑period EMA signal; a crossover of MACD above the signal means “Up”, below means “Down”.  
- **prediction_bot_bb.py** computes 20‑period Bollinger Bands (±2 σ around the SMA) and treats bounces from the lower band or moves above the middle as bullish, while rejections at the upper band or drops below the middle are bearish.  
- **prediction_bot_stoch.py** derives a stochastic oscillator (%K/%D over a 14‑bar range, smoothed 3); when %K crosses above %D it predicts up, otherwise down.

