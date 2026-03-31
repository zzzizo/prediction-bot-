#!/usr/bin/env python3
"""
Trend Track v9 — Binance WebSocket  (no API key needed)

Key changes from v7:
- Trade stays open until TARGET or STOP is hit (not just next signal)
- Win  = target price touched during trade (t_hi / t_lo)
- Loss = trade closed by any stop without hitting target
- Entry fires fresh trade; if already in trade same-direction = ignored,
  opposite direction = flip (only after MIN_HOLD_BARS)
- DaySince counts bars in losing streak / DAY_BAR correctly

Install: pip install websocket-client requests
"""

import json, time, sys, csv, os, requests
from datetime import datetime, timezone
from websocket import WebSocketApp

# ═══════════════════════════════════════════════════
#  CONFIG  ← edit here
# ═══════════════════════════════════════════════════
SYMBOL         = "BTCUSDT"
INTERVAL       = "5m"
CRYPTO_MODE    = True

# ── Dynamic target (ATR-based) ──────────────────────
# Targets are recalculated each bar from recent volatility.
# Set ATR_MULT_T1/T2 to control aggressiveness.
ATR_PERIOD     = 14       # bars used for ATR calculation
ATR_MULT_T1    = 1.0      # target1 = ATR_14 × this  (1.0 = match recent volatility)
ATR_MULT_T2    = 0.5      # target2 = ATR_14 × this
MIN_TARGET     = 0.002    # floor  – never below 0.2%
MAX_TARGET     = 0.025    # ceiling – never above 2.5%
# Static fallback used before enough bars for ATR:
TARGET_1       = 0.010    # overwritten dynamically after ATR_PERIOD bars
TARGET_2       = 0.005    # overwritten dynamically after ATR_PERIOD bars

DAY_BAR        = 288      # 5m bars per 24 h
MIN_DAYS_SINCE = 0        # min losing days before entries allowed
MIN_HOLD_BARS  = 3        # min bars before trade can flip direction

WARMUP_BARS    = 500
CSV_FILE       = "signals.csv"
# ═══════════════════════════════════════════════════

INTERVAL_SECS  = {"1m":60,"3m":180,"5m":300,"15m":900,
                  "30m":1800,"1h":3600,"4h":14400,"1d":86400}
IV_SEC = INTERVAL_SECS.get(INTERVAL, 300)

def utcdt(ts):  return datetime.fromtimestamp(ts/1000, tz=timezone.utc)
def fmtts(ts):  return utcdt(ts).strftime("%Y-%m-%d %H:%M UTC")
def ttl(ts):    return max(0, int(ts/1000 + IV_SEC - time.time()))

def ema(series, p):
    if not series: return float("nan")
    k = 2.0/(p+1); v = series[0]
    for x in series[1:]: v = x*k + v*(1-k)
    return v

def calc_atr(period=14):
    """ATR as a fraction of price (e.g. 0.008 = 0.8%).
    Uses the last `period` bars from global price history."""
    n = len(H_c)
    if n < 2: return TARGET_1     # fallback before enough bars
    trs = []
    start = max(1, n - period - 1)
    for i in range(start, n):
        pc = H_c[i-1]
        if pc == 0: continue
        tr = max(H_h[i]-H_l[i], abs(H_h[i]-pc), abs(H_l[i]-pc))
        trs.append(tr / pc)
    if not trs: return TARGET_1
    return sum(trs) / len(trs)

def dynamic_targets():
    """Return (target1, target2) clamped to [MIN_TARGET, MAX_TARGET]."""
    atr = calc_atr(ATR_PERIOD)
    t1 = max(MIN_TARGET, min(MAX_TARGET, atr * ATR_MULT_T1))
    t2 = max(MIN_TARGET, min(MAX_TARGET, atr * ATR_MULT_T2))
    return round(t1, 6), round(t2, 6)

# ── CSV ──────────────────────────────────────────────
_csv_hdr = False
def log_csv(row):
    global _csv_hdr
    new = not os.path.isfile(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new or not _csv_hdr:
            w.writerow(["datetime_utc","symbol","interval","bar","signal",
                        "detail","side","entry","price","pl_pct",
                        "trade_hi","trade_lo","ema12","ema27","ema40",
                        "atr_pct","target1_pct","target2_pct"])
            _csv_hdr = True
        w.writerow(row)

# ── Session (no-ops in CRYPTO_MODE) ─────────────────
def _et(ts):
    dt = utcdt(ts)
    return (dt.hour + (-4 if 3<=dt.month<=11 else -5)) % 24, dt.minute
def in_sess(ts):
    if CRYPTO_MODE: return True
    h,m = _et(ts); t = h*60+m; return 570 <= t < 960
def no_trade_win(ts):
    if CRYPTO_MODE: return False
    h,m = _et(ts); t = h*60+m; return 930 <= t <= 950

# ═══════════════════════════════════════════════════
#  PRICE HISTORY
# ═══════════════════════════════════════════════════
H_o=[]; H_h=[]; H_l=[]; H_c=[]; H_t=[]

# ═══════════════════════════════════════════════════
#  TRADE STATE
# ═══════════════════════════════════════════════════
class Trade:
    open_     = False
    side      = 0        # 1=long  -1=short
    entry     = 0.0
    entry_bar = 0
    hi        = 0.0      # highest HIGH seen since entry
    lo        = 1e15     # lowest  LOW  seen since entry
    target_hit= False    # did price touch the 1% target?
    target2_hit=False    # did price touch the 0.5% target?

T = Trade()

# ═══════════════════════════════════════════════════
#  STATISTICS
# ═══════════════════════════════════════════════════
class Stats:
    bar_count  = 0
    total      = 0      # closed trades
    wins1      = 0
    wins2      = 0
    streak1    = 0      # consecutive losses (trade count)
    streak2    = 0
    bars_ls1   = 0      # bar accumulator for daysince
    bars_ls2   = 0
    daysince1  = 0.0
    daysince2  = 0.0

G = Stats()
_pm = [False]*6

# ═══════════════════════════════════════════════════
#  TRADE OPEN / CLOSE
# ═══════════════════════════════════════════════════
def trade_open(side, price, bar_idx, h, lo):
    T.open_      = True
    T.side       = side
    T.entry      = price
    T.entry_bar  = bar_idx
    T.hi         = h
    T.lo         = lo
    T.target_hit = False
    T.target2_hit= False

def trade_close(exit_c, reason, warmup):
    """Close current trade. Win = target was touched during trade."""
    ep   = T.entry
    side = T.side
    w1   = T.target_hit
    w2   = T.target2_hit
    held = G.bar_count - T.entry_bar
    pl   = (exit_c - ep) / ep * 100 * side if ep else 0.0

    G.total += 1
    if w1: G.wins1 += 1
    if w2: G.wins2 += 1
    G.streak1 = 0 if w1 else G.streak1 + 1
    G.streak2 = 0 if w2 else G.streak2 + 1

    if not warmup:
        s    = "LONG" if side==1 else "SHORT"
        tgt  = ep*(1+TARGET_1) if side==1 else ep*(1-TARGET_1)
        best = (T.hi-ep) if side==1 else (ep-T.lo)
        print(f"\n  📊 TRADE CLOSED [{reason}]  {s}  "
              f"entry={ep:.2f}  exit={exit_c:.2f}  P/L={pl:+.2f}%  held={held}b")
        print(f"     Hi={T.hi:.2f}  Lo={T.lo:.2f}  "
              f"best={best:+.2f} ({best/ep*100:+.3f}%)  "
              f"target={tgt:.2f}  → {'✅ WIN' if w1 else '❌ LOSS'}")

    T.open_      = False
    T.side       = 0
    T.entry      = 0.0
    T.hi         = 0.0
    T.lo         = 1e15
    T.target_hit = False
    T.target2_hit= False
    return w1, w2

# ═══════════════════════════════════════════════════
#  ENTRY SIGNAL (crypto-native: no gap needed)
# ═══════════════════════════════════════════════════
def entry_signal(n):
    if n < 3: return False, False
    c  = H_c[-1]; o  = H_o[-1]; pc = H_c[-2]
    ma1 = ema(H_c, 12); ma2 = ema(H_c, 27)
    lt = (c > o) and (c > pc) and (ma1 > ma2)
    st = (c < o) and (c < pc) and (ma1 < ma2)
    return lt, st

# ═══════════════════════════════════════════════════
#  BAR PROCESSOR
# ═══════════════════════════════════════════════════
def process_bar(o, h, lo, c, ts, warmup=False):
    o=float(o); h=float(h); lo=float(lo); c=float(c); ts=int(ts)
    G.bar_count += 1
    n = G.bar_count

    H_o.append(o); H_h.append(h); H_l.append(lo); H_c.append(c); H_t.append(ts)

    ma1 = ema(H_c, 12); ma2 = ema(H_c, 27); ma3 = ema(H_c, 40)

    # ── Recalculate dynamic targets from ATR each bar ───
    global TARGET_1, TARGET_2
    if n >= ATR_PERIOD + 1:
        TARGET_1, TARGET_2 = dynamic_targets()

    pc      = H_c[-2] if n>=2 else c
    ph      = H_h[-2] if n>=2 else h
    pl_prev = H_l[-2] if n>=2 else lo
    pct_chg = (c-pc)/pc*100 if pc else 0.0
    sess    = in_sess(ts)
    notr    = no_trade_win(ts)

    # ══ STEP 1: update running extremes ═══════════════
    if T.open_:
        if h  > T.hi: T.hi = h
        if lo < T.lo: T.lo = lo
        ep = T.entry
        # check if target touched THIS bar (intra-bar)
        if T.side == 1:
            if T.hi  >= ep*(1+TARGET_1): T.target_hit  = True
            if T.hi  >= ep*(1+TARGET_2): T.target2_hit = True
        elif T.side == -1:
            if T.lo  <= ep*(1-TARGET_1): T.target_hit  = True
            if T.lo  <= ep*(1-TARGET_2): T.target2_hit = True

    held     = (n - T.entry_bar) if T.open_ else 0
    can_flip = held >= MIN_HOLD_BARS
    ep       = T.entry if T.open_ else c
    side     = T.side  if T.open_ else (1 if ma1>=ma2 else -1)

    pct_chg_abs = abs(pct_chg)

    # ══ STEP 2: stop conditions ════════════════════════
    sl20 = T.open_ and held>=19 and lo<pl_prev and pct_chg<= 0.333
    sl10 = T.open_ and held>=10 and held<19    and lo<pl_prev and pct_chg<= 0.010
    sl5  = T.open_ and held>=5  and held<11    and c <pl_prev and pct_chg<=-1.250
    sl3  = T.open_ and held>=3  and held<=4    and h > c      and pct_chg<=-0.033
    esc_l= T.open_ and c<=ep and held>=3 and T.side== 1
    esc_s= T.open_ and c>=ep and held>=3 and T.side==-1
    trl_l= T.open_ and held>2 and T.side== 1 and c<=(ep+ep*0.000385*held)
    trl_s= T.open_ and held>2 and T.side==-1 and c>=(ep-ep*0.000385*held)
    ge_l = T.open_ and c<pc and held>=9 and T.side== 1
    ge_s = T.open_ and c>pc and held>=9 and T.side==-1
    rng  = abs(h-lo); body=abs(c-o)
    rv   = rng>0 and body<0.55*rng
    ret  = T.open_ and held>=5 and rv and (
           (h>h-0.55*rng and c<h-0.55*rng and o<h-0.55*rng) or
           (lo<lo+0.55*rng and c>lo+0.55*rng and o>lo+0.55*rng))

    # ══ STEP 3: entry signals ══════════════════════════
    lt, st = entry_signal(n)
    lt = lt and sess and not notr
    st = st and sess and not notr

    # ══ STEP 4: close logic ════════════════════════════
    # Priority 1: target hit — close immediately, no signal needed
    # Priority 2: stop hit
    # Priority 3: opposite-direction flip (after MIN_HOLD_BARS)
    w1=False; w2=False; just_closed=False; close_reason=""

    if T.open_:
        if T.target_hit:
            # Target was touched this bar or earlier — close now
            w1, w2 = trade_close(c, "TARGET", warmup)
            just_closed=True; close_reason="TARGET"

        elif sl20 or sl10 or sl5 or sl3 or esc_l or esc_s or trl_l or trl_s or ge_l or ge_s or ret:
            stop_name = ("SL20" if sl20 else "SL10" if sl10 else "SL5" if sl5 else
                         "SL3"  if sl3  else "ESC"  if (esc_l or esc_s) else
                         "TRAIL"if (trl_l or trl_s) else "GE" if (ge_l or ge_s) else "RT")
            w1, w2 = trade_close(c, stop_name, warmup)
            just_closed=True; close_reason=stop_name

        elif can_flip:
            flip = (lt and T.side==-1) or (st and T.side==1)
            if flip:
                w1, w2 = trade_close(c, "FLIP", warmup)
                just_closed=True; close_reason="FLIP"

    # ══ STEP 5: open new trade ═════════════════════════
    if lt and (not T.open_ or just_closed):
        trade_open(1,  c, n, h, lo)
    elif st and (not T.open_ or just_closed):
        trade_open(-1, c, n, h, lo)

    # ── refresh snapshot after possible open ────────────
    ep   = T.entry if T.open_ else c
    side = T.side  if T.open_ else (1 if ma1>=ma2 else -1)
    held = (n - T.entry_bar) if T.open_ else 0

    # ══ daysince ══════════════════════════════════════
    if G.streak1 > 0: G.bars_ls1 += 1
    else:              G.bars_ls1  = 0
    if G.streak2 > 0: G.bars_ls2 += 1
    else:              G.bars_ls2  = 0
    G.daysince1 = G.bars_ls1 / DAY_BAR
    G.daysince2 = G.bars_ls2 / DAY_BAR

    # ══ targets & trail ═══════════════════════════════
    one_pct = ep * 0.01
    tgt_l1  = ep*(1+TARGET_1);  tgt_s1 = ep*(1-TARGET_1)
    tgt_l2  = ep*(1+TARGET_2);  tgt_s2 = ep*(1-TARGET_2)
    trail_l = ep + ep*0.000385*held
    trail_s = ep - ep*0.000385*held
    pl_pct  = (c-ep)/ep*100*side if (ep and side) else 0.0

    # ══ milestones ════════════════════════════════════
    def _m(x):
        if side== 1: return c>=ep+one_pct*x
        if side==-1: return c<=ep-one_pct*x
        return False
    cm = [_m(x) for x in (0.3,0.5,1.0,1.5,2.0,2.5)]
    global _pm
    mile = [cm[i] and not _pm[i] for i in range(6)]
    _pm  = cm

    if warmup: return

    # ══ BUILD SIGNALS ════════════════════════════════
    side_str = "LONG" if side==1 else "SHORT" if side==-1 else "FLAT"
    ok_days  = G.daysince1 >= MIN_DAYS_SINCE

    sigs = []
    if lt and ok_days: sigs.append(("BUY",  "🟢 BUY  – Long Entry"))
    if st and ok_days: sigs.append(("SELL", "🔴 SELL – Short Entry"))

    if just_closed:
        sigs.append(("WIN1"  if w1 else "LOSS1",
            f"{'✅ WIN' if w1 else '❌ LOSS'}  1.0%  [{close_reason}]  "
            f"streak={G.streak1}  days={G.daysince1:.2f}"))
        sigs.append(("WIN2"  if w2 else "LOSS2",
            f"{'✅ WIN' if w2 else '❌ LOSS'}  0.5%  "
            f"streak={G.streak2}"))
        if w1: sigs.append(("WINTIME","💜 Win-time – close all"))

    if T.open_ and T.target_hit and not just_closed:
        sigs.append(("TARGET","🎯 Target touched! Waiting for exit signal"))

    # Stop signals (informational even if trade wasn't closed)
    if T.open_:
        if sl20:        sigs.append(("SL20","⛔ 20-bar Stop               [50%]"))
        if sl10:        sigs.append(("SL10","⛔ 10-bar Stop               [50%]"))
        if sl5:         sigs.append(("SL5", "⚠️  5-bar Stop               [33%]"))
        if sl3:         sigs.append(("SL3", "⚠️  3-bar Stop               [25%]"))
        if esc_l or esc_s: sigs.append(("BE","🛑 Bad Escape               [15%]"))
        if trl_l or trl_s: sigs.append(("TE","🟠 Trail Exit               [15%]"))
        if ge_l or ge_s:   sigs.append(("GE","💚 Good Exit 9-bar          [40%]"))
        if ret:            sigs.append(("RT","🟠 Retracement              [25%]"))

    for i,(f,lab) in enumerate(zip(mile,["0.3%","0.5%","1.0%","1.5%","2.0%","2.5%"])):
        if f: sigs.append((f"M{lab}", f"📍 {lab} Milestone"))

    # ══ DASHBOARD ════════════════════════════════════
    trend = ("↑↑ BULLISH" if ma1>ma2>ma3 else
             "↓↓ BEARISH" if ma1<ma2<ma3 else "↔  MIXED  ")
    wr    = G.wins1/G.total*100 if G.total else 0.0
    wl    = G.wins1/max(G.total-G.wins1,1)
    best  = (T.hi-ep) if side==1 else (ep-T.lo) if side==-1 else 0.0
    need  = abs((tgt_l1 if side==1 else tgt_s1)-c)/c*100
    tgt_hit_str = "🎯 TARGET HIT" if T.open_ and T.target_hit else ""

    print("\n"+"═"*68)
    print(f"  {SYMBOL}  {INTERVAL}  │  {fmtts(ts)}  │  bar #{n}")
    print(f"  O:{o:<13.2f}  H:{h:<13.2f}  L:{lo:<13.2f}  C:{c:.2f}")
    print(f"  EMA12:{ma1:<10.2f}   EMA27:{ma2:<10.2f}   EMA40:{ma3:.2f}")
    print(f"  Trend: {trend}   Side: {side_str:<6}   P/L: {pl_pct:+.3f}%  {tgt_hit_str}")
    atr_now = calc_atr(ATR_PERIOD)
    print(f"  Entry:{ep:<16.2f}  Held:{held} bars")
    print(f"  ATR14:{atr_now*100:.3f}%  →  Target1:{TARGET_1*100:.3f}%  Target2:{TARGET_2*100:.3f}%  [dynamic]")
    print(f"  Trail↑:{trail_l:<13.2f}  Trail↓:{trail_s:.2f}")
    print(f"  1% Long  target: {tgt_l1:.2f}  (+{(tgt_l1/c-1)*100:.3f}% away)")
    print(f"  1% Short target: {tgt_s1:.2f}  (-{(1-tgt_s1/c)*100:.3f}% away)")
    if T.open_:
        print(f"  TradeHi:{T.hi:<12.2f}  TradeLo:{T.lo:.2f}")
        print(f"  Best: {best:+.2f} ({best/ep*100:+.3f}%)   Need: {need:.3f}% more")
    print(f"  {'─'*62}")
    print(f"  Trades:{G.total:<6}  Wins:{G.wins1:<6}  Losses:{G.total-G.wins1:<6}  "
          f"Win%:{wr:.1f}%  W/L:{wl:.2f}")
    print(f"  DaySince1%:{G.daysince1:.2f}   DaySince0.5%:{G.daysince2:.2f}   "
          f"Streak:{G.streak1}  Streak2:{G.streak2}")
    if sigs:
        print(f"  {'─'*62}")
        for code,desc in sigs: print(f"    [{code:<8}] {desc}")
    print("═"*68)

    dt = fmtts(ts)
    for code,desc in sigs:
        log_csv([dt,SYMBOL,INTERVAL,n,code,desc,side_str,
                 f"{ep:.4f}",f"{c:.4f}",f"{pl_pct:.4f}",
                 f"{T.hi:.4f}",f"{T.lo:.4f}",
                 f"{ma1:.4f}",f"{ma2:.4f}",f"{ma3:.4f}",
                 f"{calc_atr(ATR_PERIOD)*100:.4f}",
                 f"{TARGET_1*100:.4f}",f"{TARGET_2*100:.4f}"])

# ═══════════════════════════════════════════════════
#  WARMUP
# ═══════════════════════════════════════════════════
def fetch_history():
    print(f"  Loading {WARMUP_BARS} historical {INTERVAL} bars…", end=" ", flush=True)
    try:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol":SYMBOL,"interval":INTERVAL,"limit":WARMUP_BARS},
                         timeout=15)
        r.raise_for_status()
        klines = r.json()
        for k in klines[:-1]:
            process_bar(k[1],k[2],k[3],k[4],k[0], warmup=True)
        wr = G.wins1/G.total*100 if G.total else 0
        print(f"done — {len(klines)-1} bars | "
              f"Trades:{G.total}  Wins:{G.wins1}  ({wr:.1f}%)  "
              f"Streak:{G.streak1}  DaySince1%:{G.daysince1:.2f}")
    except Exception as e:
        print(f"\n  ⚠️  Warmup error: {e}")

# ═══════════════════════════════════════════════════
#  WEBSOCKET
# ═══════════════════════════════════════════════════
WS_URL = f"wss://stream.binance.com:9443/ws/{SYMBOL.lower()}@kline_{INTERVAL}"

def on_open(ws):
    print(f"\n✅  WebSocket live  →  {SYMBOL} {INTERVAL}\n")

def on_message(ws, msg):
    k = json.loads(msg).get("k",{})
    if k.get("x"):
        process_bar(k["o"],k["h"],k["l"],k["c"],k["t"])
    else:
        c   = float(k["c"]); tl = ttl(int(k["t"]))
        ep  = T.entry or c
        pl  = (c-ep)/ep*100*T.side if (ep and T.side) else 0.0
        sl  = "L" if T.side==1 else ("S" if T.side==-1 else "–")
        tgt = ep*(1+TARGET_1) if T.side==1 else (ep*(1-TARGET_1) if T.side==-1 else c)
        nd  = abs(tgt-c)/c*100 if T.side else 0.0
        hit = "🎯" if T.target_hit else ""
        sys.stdout.write(
            f"\r  ⟳ {SYMBOL} {c:.2f}[{sl}] "
            f"P/L:{pl:+.3f}%  need:{nd:.3f}%{hit}  TTL:{tl}s   "
        )
        sys.stdout.flush()

def on_error(ws,e): print(f"\n⚠️  {e}")
def on_close(ws,c,m): print(f"\n🔌  closed")

# ═══════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════
def main():
    print("╔"+"═"*66+"╗")
    print("║       Trend Track  v9  —  Binance WebSocket Edition         ║")
    print("╚"+"═"*66+"╝")
    print(f"\n  Symbol    : {SYMBOL}")
    print(f"  Interval  : {INTERVAL}  ({IV_SEC}s/bar)")
    print(f"  Mode      : {'24/7 Crypto' if CRYPTO_MODE else 'US Market Hours'}")
    print(f"  Targets   : {TARGET_1*100:.1f}%  /  {TARGET_2*100:.1f}%")
    print(f"  Min hold  : {MIN_HOLD_BARS} bars before flip")
    print(f"  DAY_BAR   : {DAY_BAR}")
    print(f"  CSV       : {os.path.abspath(CSV_FILE)}\n")
    fetch_history()
    ws = WebSocketApp(WS_URL, on_open=on_open, on_message=on_message,
                      on_error=on_error, on_close=on_close)
    while True:
        try:
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except KeyboardInterrupt:
            print(f"\n👋  Done.  CSV → {os.path.abspath(CSV_FILE)}")
            break
        except Exception as e:
            print(f"\n⚠️  {e} – reconnect in 5s…"); time.sleep(5)

if __name__=="__main__":
    main()