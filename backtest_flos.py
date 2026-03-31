"""
Backtesting framework for flos-script.py (Trend Track v9)
Integrates historical Binance data into the flos-script trading logic
"""

import requests
import json
from datetime import datetime, timedelta
import logging
import sys
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# CONFIG (same as flos-script.py)
# ═══════════════════════════════════════════════════
SYMBOL = "BTCUSDT"
INTERVAL = "5m"
CRYPTO_MODE = True

ATR_PERIOD = 14
ATR_MULT_T1 = 1.0
ATR_MULT_T2 = 0.5
MIN_TARGET = 0.002
MAX_TARGET = 0.025
TARGET_1 = 0.010
TARGET_2 = 0.005

DAY_BAR = 288
MIN_DAYS_SINCE = 0
MIN_HOLD_BARS = 3
WARMUP_BARS = 500

INTERVAL_SECS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900,
                 "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
IV_SEC = INTERVAL_SECS.get(INTERVAL, 300)

# ═══════════════════════════════════════════════════
# HELPER FUNCTIONS (from flos-script)
# ═══════════════════════════════════════════════════

def ema(series, p):
    if not series:
        return float("nan")
    k = 2.0 / (p + 1)
    v = series[0]
    for x in series[1:]:
        v = x * k + v * (1 - k)
    return v


def calc_atr(period=14):
    """ATR as a fraction of price"""
    n = len(H_c)
    if n < 2:
        return TARGET_1
    trs = []
    for i in range(max(0, n - period), n):
        h_now = H_h[i]
        l_now = H_l[i]
        c_prev = H_c[i - 1] if i > 0 else 0
        tr = max(h_now - l_now, abs(h_now - c_prev), abs(l_now - c_prev))
        trs.append(tr)
    atr_val = sum(trs) / len(trs) if trs else 0
    return atr_val / H_c[-1] if H_c[-1] else 0


def dynamic_targets():
    """Calculate dynamic targets based on ATR"""
    atr = calc_atr(ATR_PERIOD)
    t1 = max(MIN_TARGET, min(MAX_TARGET, atr * ATR_MULT_T1))
    t2 = max(MIN_TARGET, min(MAX_TARGET, atr * ATR_MULT_T2))
    return t1, t2


def entry_signal(n):
    if n < 3:
        return False, False
    c = H_c[-1]
    o = H_o[-1]
    pc = H_c[-2]
    ma1 = ema(H_c, 12)
    ma2 = ema(H_c, 27)
    lt = (c > o) and (c > pc) and (ma1 > ma2)
    st = (c < o) and (c < pc) and (ma1 < ma2)
    return lt, st


def trade_open(side, price, bar_idx, h, lo):
    T.open_ = True
    T.side = side
    T.entry = price
    T.entry_bar = bar_idx
    T.hi = h
    T.lo = lo
    T.target_hit = False
    T.target2_hit = False


def trade_close(exit_c, reason, warmup):
    """Close current trade. Win = target was touched during trade."""
    ep = T.entry
    side = T.side
    w1 = T.target_hit
    w2 = T.target2_hit
    held = G.bar_count - T.entry_bar
    pl = (exit_c - ep) / ep * 100 * side if ep else 0.0

    G.total += 1
    if w1:
        G.wins1 += 1
    if w2:
        G.wins2 += 1
    G.streak1 = 0 if w1 else G.streak1 + 1
    G.streak2 = 0 if w2 else G.streak2 + 1

    if not warmup:
        s = "LONG" if side == 1 else "SHORT"
        tgt = ep * (1 + TARGET_1) if side == 1 else ep * (1 - TARGET_1)
        best = (T.hi - ep) if side == 1 else (ep - T.lo)
        print(f"\n  📊 TRADE CLOSED [{reason}]  {s}  "
              f"entry={ep:.2f}  exit={exit_c:.2f}  P/L={pl:+.2f}%  held={held}b")
        print(f"     Hi={T.hi:.2f}  Lo={T.lo:.2f}  "
              f"best={best:+.2f} ({best/ep*100:+.3f}%)  "
              f"target={tgt:.2f}  → {'✅ WIN' if w1 else '❌ LOSS'}")

    T.open_ = False
    T.side = 0
    T.entry = 0.0
    T.hi = 0.0
    T.lo = 1e15
    T.target_hit = False
    T.target2_hit = False
    return w1, w2


def process_bar(o, h, lo, c, ts, warmup=False):
    o = float(o)
    h = float(h)
    lo = float(lo)
    c = float(c)
    ts = int(ts)
    G.bar_count += 1
    n = G.bar_count

    H_o.append(o)
    H_h.append(h)
    H_l.append(lo)
    H_c.append(c)
    H_t.append(ts)

    ma1 = ema(H_c, 12)
    ma2 = ema(H_c, 27)
    ma3 = ema(H_c, 40)

    # Recalculate dynamic targets
    global TARGET_1, TARGET_2
    if n >= ATR_PERIOD + 1:
        TARGET_1, TARGET_2 = dynamic_targets()

    pc = H_c[-2] if n >= 2 else c
    ph = H_h[-2] if n >= 2 else h
    pl_prev = H_l[-2] if n >= 2 else lo
    pct_chg = (c - pc) / pc * 100 if pc else 0.0

    # ══ STEP 1: update running extremes ═══════════════
    if T.open_:
        T.hi = max(T.hi, h)
        T.lo = min(T.lo, lo)

        # Check if target was hit this bar
        tgt_l1 = T.entry * (1 + TARGET_1)
        tgt_s1 = T.entry * (1 - TARGET_1)
        tgt_l2 = T.entry * (1 + TARGET_2)
        tgt_s2 = T.entry * (1 - TARGET_2)

        if T.side == 1 and h >= tgt_l1:
            T.target_hit = True
        if T.side == -1 and lo <= tgt_s1:
            T.target_hit = True
        if T.side == 1 and h >= tgt_l2:
            T.target2_hit = True
        if T.side == -1 and lo <= tgt_s2:
            T.target2_hit = True

    # ══ STEP 2: exit conditions ════════════════════════
    held = (n - T.entry_bar) if T.open_ else 0
    can_flip = held >= MIN_HOLD_BARS
    ep = T.entry if T.open_ else c

    sl20 = T.open_ and held >= 19 and lo < pl_prev and pct_chg <= 0.333
    sl10 = T.open_ and held >= 10 and held < 19 and lo < pl_prev and pct_chg <= 0.010
    sl5 = T.open_ and held >= 5 and held < 11 and c < pl_prev and pct_chg <= -1.250
    sl3 = T.open_ and held >= 3 and held <= 4 and h > c and pct_chg <= -0.033
    esc_l = T.open_ and c <= ep and held >= 3 and T.side == 1
    esc_s = T.open_ and c >= ep and held >= 3 and T.side == -1
    trl_l = T.open_ and held > 2 and T.side == 1 and c <= (ep + ep * 0.000385 * held)
    trl_s = T.open_ and held > 2 and T.side == -1 and c >= (ep - ep * 0.000385 * held)
    ge_l = T.open_ and c < pc and held >= 9 and T.side == 1
    ge_s = T.open_ and c > pc and held >= 9 and T.side == -1
    rng = abs(h - lo)
    body = abs(c - o)
    rv = rng > 0 and body < 0.55 * rng
    ret = T.open_ and held >= 5 and rv and (
        (h > h - 0.55 * rng and c < h - 0.55 * rng and o < h - 0.55 * rng) or
        (lo < lo + 0.55 * rng and c > lo + 0.55 * rng and o > lo + 0.55 * rng))

    # ══ STEP 3: entry signals ══════════════════════════
    lt, st = entry_signal(n)

    # ══ STEP 4: close logic ════════════════════════════
    w1 = False
    w2 = False
    just_closed = False
    close_reason = ""

    if T.open_:
        if T.target_hit:
            w1, w2 = trade_close(c, "TARGET", warmup)
            just_closed = True
            close_reason = "TARGET"

        elif sl20 or sl10 or sl5 or sl3 or esc_l or esc_s or trl_l or trl_s or ge_l or ge_s or ret:
            stop_name = ("SL20" if sl20 else "SL10" if sl10 else "SL5" if sl5 else
                         "SL3" if sl3 else "ESC" if (esc_l or esc_s) else
                         "TRAIL" if (trl_l or trl_s) else "GE" if (ge_l or ge_s) else "RT")
            w1, w2 = trade_close(c, stop_name, warmup)
            just_closed = True
            close_reason = stop_name

        elif can_flip:
            flip = (lt and T.side == -1) or (st and T.side == 1)
            if flip:
                w1, w2 = trade_close(c, "FLIP", warmup)
                just_closed = True
                close_reason = "FLIP"

    # ══ STEP 5: open new trade ═════════════════════════
    if lt and (not T.open_ or just_closed):
        trade_open(1, c, n, h, lo)
    elif st and (not T.open_ or just_closed):
        trade_open(-1, c, n, h, lo)

    # Record trade stats if it closed
    if just_closed and not warmup:
        G.trade_history.append({
            'close_reason': close_reason,
            'price': c,
            'candle': n,
            'win': w1
        })


# ═══════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════
H_o = []
H_h = []
H_l = []
H_c = []
H_t = []


class Trade:
    open_ = False
    side = 0
    entry = 0.0
    entry_bar = 0
    hi = 0.0
    lo = 1e15
    target_hit = False
    target2_hit = False


T = Trade()


class Stats:
    bar_count = 0
    total = 0
    wins1 = 0
    wins2 = 0
    streak1 = 0
    streak2 = 0
    bars_ls1 = 0
    bars_ls2 = 0
    daysince1 = 0.0
    daysince2 = 0.0
    trade_history = []


G = Stats()


def get_klines_historical(symbol, interval='5m', hours=10):
    """Fetch historical klines from Binance"""
    url = "https://api.binance.com/api/v3/klines"
    limit = int((hours * 3600) / INTERVAL_SECS.get(interval, 300)) + 100

    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': min(limit, 1000)  # Max 1000 per request
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching klines: {e}")
        return []


def backtest_flos(hours=10):
    """Run backtest on flos-script strategy"""
    print("\n" + "═" * 70)
    print("  BACKTEST: flos-script (Trend Track v9)")
    print("═" * 70)
    print(f"\n  Symbol    : {SYMBOL}")
    print(f"  Interval  : {INTERVAL}")
    print(f"  Historical: Last {hours} hours")
    print(f"  Target 1  : {TARGET_1*100:.2f}%")
    print(f"  Target 2  : {TARGET_2*100:.2f}%\n")

    # Fetch data
    print(f"  Fetching {hours}h of {INTERVAL} data…", end=" ", flush=True)
    klines = get_klines_historical(SYMBOL, INTERVAL, hours)
    if not klines:
        print("FAILED")
        return None

    print(f"got {len(klines)} candles\n")

    # Process warmup bars
    print(f"  Processing {WARMUP_BARS} warmup bars…", end=" ", flush=True)
    for k in klines[:WARMUP_BARS]:
        process_bar(k[1], k[2], k[3], k[4], k[0], warmup=True)
    wr = G.wins1 / G.total * 100 if G.total else 0
    print(f"done")
    print(f"    Warmup trades: {G.total}  Wins: {G.wins1}  ({wr:.1f}%)\n")

    # Process live bars
    print(f"  Processing {len(klines) - WARMUP_BARS} live bars…\n")
    for k in klines[WARMUP_BARS:]:
        process_bar(k[1], k[2], k[3], k[4], k[0], warmup=False)

    print(f"\n")
    return get_stats()


def get_stats():
    """Generate backtest statistics"""
    if G.total == 0:
        return {
            "strategy": "flos-script (Trend Track v9)",
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "trades": []
        }

    wins = G.wins1
    losses = G.total - wins
    win_rate = (wins / G.total * 100) if G.total > 0 else 0

    return {
        "strategy": "flos-script (Trend Track v9)",
        "total_trades": G.total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "trades": G.trade_history
    }


def compare_strategies(flos_results):
    """Compare flos-script with existing strategies from backtest_results.json"""
    try:
        with open('backtest_results.json', 'r') as f:
            existing_results = json.load(f)
    except:
        print("⚠️  Could not load existing results for comparison")
        return

    print("\n" + "═" * 70)
    print("  STRATEGY COMPARISON")
    print("═" * 70 + "\n")

    print("Strategy                  │ Trades │ Wins │ Losses │ Win Rate")
    print("─" * 70)

    # Show flos-script
    flos_wr = flos_results['win_rate']
    print(f"flos-script              │ {flos_results['total_trades']:>6} │ {flos_results['wins']:>4} │ {flos_results['losses']:>6} │ {flos_wr:>6.1f}%")

    # Show existing strategies
    for strategy, data in existing_results.items():
        if isinstance(data, dict) and 'stats' in data:
            stats = data['stats']
            trades = stats.get('total_trades', 0)
            wins = stats.get('profitable_trades', 0)
            losses = stats.get('losing_trades', 0)
            wr = stats.get('win_rate', 0)
            print(f"{strategy:<24} │ {trades:>6} │ {wins:>4} │ {losses:>6} │ {wr:>6.1f}%")

    print("═" * 70)
    print("\n  ✅ Comparison complete!")


if __name__ == "__main__":
    # Run backtest (10 hours = 120 candles @ 5m interval)
    results = backtest_flos(hours=10)

    if results:
        # Save results
        with open('backtest_flos_results.json', 'w') as f:
            json.dump(results, f, indent=2)
        print(f"  📊 Results saved to backtest_flos_results.json\n")

        # Compare with other strategies
        compare_strategies(results)
