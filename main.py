import urllib.request
import urllib.parse
import urllib.error
import json
import ssl
import os
import time
import threading
import hmac
import hashlib
import re
from datetime import datetime, timedelta, timezone
from flask import Flask, request

# ==============================================================================
# 1. TIMEZONE & FLASK APPLICATION INITIALIZATION
# ==============================================================================
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    return datetime.now(IST)

app = Flask(__name__)
scan_lock = threading.Lock()
active_trades_lock = threading.Lock()
trade_history_lock = threading.Lock()

STATE_FILE = "scanner_state.json"
TRADE_HISTORY_FILE = "trade_history.json"
AUTO_TRADING_ENABLED = True  # Controlled via Telegram /start and /stop commands

# Telegram Bot Credentials
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8938527650").strip()

# CoinDCX API Credentials
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1").strip()
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY", "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920").strip()

ctx = ssl._create_unverified_context()

# ==============================================================================
# 2. STATE PERSISTENCE & ACTIVE TRADES
# ==============================================================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

ACTIVE_TRADES = {}
ACTIVE_TRADES_FILE = "active_trades.json"

def load_active_trades():
    global ACTIVE_TRADES
    if os.path.exists(ACTIVE_TRADES_FILE):
        try:
            with open(ACTIVE_TRADES_FILE, 'r') as f:
                ACTIVE_TRADES = json.load(f)
        except Exception:
            ACTIVE_TRADES = {}

def save_active_trades():
    try:
        with open(ACTIVE_TRADES_FILE, 'w') as f:
            json.dump(ACTIVE_TRADES, f, indent=2)
    except Exception:
        pass

load_active_trades()

# ==============================================================================
# 3. DAILY AUDIT & TRADE HISTORY LOGGING
# ==============================================================================
def load_trade_history():
    with trade_history_lock:
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

def save_trade_history(history):
    with trade_history_lock:
        try:
            with open(TRADE_HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass

def log_trade_event(symbol, event_type, details):
    with trade_history_lock:
        history = load_trade_history()
        today_str = get_ist_now().strftime("%d-%m-%Y")
        if today_str not in history:
            history[today_str] = []
        entry = {
            "time": get_ist_now().strftime("%I:%M:%S %p"),
            "symbol": symbol,
            "type": event_type,
            "details": details
        }
        history[today_str].append(entry)
        save_trade_history(history)

def generate_daily_summary(target_date_str=None):
    if not target_date_str:
        target_date_str = get_ist_now().strftime("%d-%m-%Y")
    
    history = load_trade_history()
    day_logs = history.get(target_date_str, [])
    
    with active_trades_lock:
        active_items = list(ACTIVE_TRADES.items())

    total_signals = len(day_logs)
    executed_events = [e for e in day_logs if e.get("type") == "EXECUTED"]
    cancelled_events = [e for e in day_logs if e.get("type") == "CANCELLED"]
    closed_events = [e for e in day_logs if e.get("type") == "CLOSED"]
    
    win_events = [e for e in closed_events if e.get("details", {}).get("realized_pnl_pct", 0) > 0]
    win_rate = (len(win_events) / len(closed_events) * 100) if closed_events else (100.0 if executed_events else 0.0)
    total_roe = sum(e.get("details", {}).get("realized_pnl_pct", 0) for e in closed_events)
    
    lines = [
        f"📅 <b>DAILY AUTOMATED TRADING REPORT ({target_date_str})</b>",
        f"",
        f"📊 <b>Performance Overview:</b>",
        f"• <b>Total Signals:</b> <code>{total_signals}</code>",
        f"• <b>Executed Trades:</b> <code>{len(executed_events)}</code>",
        f"• <b>Active Open Trades:</b> <code>{len(active_items)}</code> ⚡",
        f"• <b>Non-Executed / Skipped:</b> <code>{len(cancelled_events)}</code>",
        f"• <b>Closed Trades:</b> <code>{len(closed_events)}</code>",
        f"• <b>Win Rate:</b> <code>{win_rate:.1f}%</code> 🏆",
        f"• <b>Total Realized Gain:</b> <code>{total_roe:+.1f}% ROE</code> {'💰' if total_roe >= 0 else '🛑'}",
        f"",
        f"📝 <b>Today's Executed Trades:</b>"
    ]
    
    if executed_events:
        for idx, e in enumerate(executed_events, 1):
            sym = e.get("symbol", "UNKNOWN")
            t = e.get("time", "")
            dt = e.get("details", {})
            lines.append(f"{idx}. <b>{sym}</b> @ {t} | Entry: <code>${dt.get('cmp')}</code> | Qty: <code>{dt.get('quantity')}</code> | ID: <code>{dt.get('order_id')}</code>")
    else:
        lines.append("<i>No trades executed today yet.</i>")
        
    if active_items:
        lines.append("")
        lines.append("⚡ <b>Currently Active Live Positions:</b>")
        for idx, (sym, tr) in enumerate(active_items, 1):
            ep = tr.get('entry_price', 0)
            qty = tr.get('total_qty', 0)
            tp = tr.get('tp1', 0)
            sl = tr.get('sl', 0)
            lines.append(f"{idx}. <b>{sym}</b> | Entry: <code>${ep}</code> | Qty: <code>{qty}</code> | TP: <code>${tp}</code> | SL: <code>${sl}</code> 🟢 (Active)")
            
    if closed_events:
        lines.append("")
        lines.append("🏁 <b>Today's Closed Trades:</b>")
        for idx, e in enumerate(closed_events, 1):
            sym = e.get("symbol", "UNKNOWN")
            t = e.get("time", "")
            dt = e.get("details", {})
            pnl = dt.get('realized_pnl_pct', 0)
            icon = '💰' if pnl >= 0 else '🛑'
            lines.append(f"{idx}. <b>{sym}</b> @ {t} | Closed: <code>${dt.get('cmp')}</code> | PnL: <code>{pnl:+.1f}% ROE</code> {icon}")

    return "\n".join(lines)

# ==============================================================================
# 4. WATCHLIST & DYNAMIC COINDCX DISCOVERY ENGINE (ALL 180+ PAIRS SUPPORT)
# ==============================================================================
WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'DOGE-USDT', 
    'XRP-USDT', 'ADA-USDT', 'LINK-USDT', 'NEAR-USDT', 'BCH-USDT', 
    'SUI-USDT', 'LTC-USDT', 'DOT-USDT', 'APT-USDT', 'RENDER-USDT', 
    'INJ-USDT', 'FET-USDT', 'TIA-USDT', 'WIF-USDT', 'AAVE-USDT',
    'FTM-USDT', 'UNI-USDT', 'ATOM-USDT', 'ICP-USDT', 'SAND-USDT',
    'SEI-USDT', 'ORDI-USDT', 'FIL-USDT', 'JUP-USDT', 'STX-USDT', 
    'PENDLE-USDT', 'RUNE-USDT', 'IMX-USDT', 'KAS-USDT', 'ZEC-USDT', 
    'BAT-USDT', 'TAO-USDT', 'ENA-USDT', 'TRX-USDT', 'ONDO-USDT', 
    'POL-USDT'
]

COINDCX_PAIR_ALIASES = {
    'RAY': 'RAYSOL', 'PEPE': '1000PEPE', 'SHIB': '1000SHIB', 'BONK': '1000BONK',
    'FLOKI': '1000FLOKI', 'CHEEMS': '1000CHEEMS', 'CAT': '1000CAT', 'SATS': '1000SATS',
    'RATS': '1000RATS', 'MOG': '1000MOG', 'XEC': '1000XEC', 'LUNC': '1000LUNC',
    'BABYDOGE': '1000BABYDOGE', 'WHY': '1000WHY'
}

CACHED_DYNAMIC_WATCHLIST = []
LAST_WATCHLIST_FETCH_TIME = 0.0
INACTIVE_COINS = set()
CACHED_COINDCX_ACTIVE_PAIRS = set()
LAST_COINDCX_ACTIVE_FETCH = 0.0

def fetch_coindcx_active_pairs():
    global CACHED_COINDCX_ACTIVE_PAIRS, LAST_COINDCX_ACTIVE_FETCH
    now = time.time()
    if CACHED_COINDCX_ACTIVE_PAIRS and (now - LAST_COINDCX_ACTIVE_FETCH < 1800):
        return CACHED_COINDCX_ACTIVE_PAIRS
    
    active_set = set()
    try:
        url = "https://api.coindcx.com/exchange/v1/derivatives/futures/data/active_instruments"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data if isinstance(data, list) else data.get('instruments', data.get('data', []))
            for item in items:
                p = item if isinstance(item, str) else item.get('pair', item.get('symbol', ''))
                if p: active_set.add(str(p).upper())
    except Exception:
        pass

    if not active_set:
        try:
            url = "https://public.coindcx.com/market_data/trade_info"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            p = str(item.get('pair', '')).upper()
                            if p: active_set.add(p)
        except Exception:
            pass

    if active_set:
        CACHED_COINDCX_ACTIVE_PAIRS = active_set
        LAST_COINDCX_ACTIVE_FETCH = now
    return CACHED_COINDCX_ACTIVE_PAIRS

def fetch_dynamic_watchlist(min_volume_usdt=2500000.0):
    global CACHED_DYNAMIC_WATCHLIST, LAST_WATCHLIST_FETCH_TIME
    now = time.time()
    if CACHED_DYNAMIC_WATCHLIST and (now - LAST_WATCHLIST_FETCH_TIME < 900):
        return [s for s in CACHED_DYNAMIC_WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS]

    coindcx_active = fetch_coindcx_active_pairs()
    all_discovered_pairs = []

    # Dynamic Discovery: Parse ALL 180+ CoinDCX active futures pairs
    if coindcx_active:
        for p in coindcx_active:
            p_upper = str(p).upper()
            if p_upper.startswith("B-") and p_upper.endswith("_USDT"):
                coin_part = p_upper[2:-5]
                orig_coin = coin_part
                for k, v in COINDCX_PAIR_ALIASES.items():
                    if v == coin_part:
                        orig_coin = k
                        break
                sym = f"{orig_coin}-USDT"
                if sym not in all_discovered_pairs and orig_coin not in INACTIVE_COINS:
                    all_discovered_pairs.append(sym)

    # Fallback to WATCHLIST if active instruments endpoint was unreachable
    if not all_discovered_pairs:
        all_discovered_pairs = [s for s in WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS]

    # Fetch 24hr volumes from Binance/MEXC to filter by min_volume_usdt (>= $2.5M)
    ticker_urls = [
        "https://api.binance.com/api/v3/ticker/24hr",
        "https://api1.binance.com/api/v3/ticker/24hr",
        "https://api.mexc.com/api/v3/ticker/24hr"
    ]
    ticker_vol_map = {}
    for t_url in ticker_urls:
        try:
            req = urllib.request.Request(t_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list) and len(data) > 0:
                    for item in data:
                        sym = item.get('symbol', '')
                        if sym.endswith('USDT'):
                            coin = sym[:-4].upper()
                            quote_vol = float(item.get('quoteVolume', 0))
                            ticker_vol_map[f"{coin}-USDT"] = quote_vol
                    break
        except Exception:
            pass

    # Keep all pairs that have >= $2,500,000 volume
    qualified_pairs = []
    for sym in all_discovered_pairs:
        vol = ticker_vol_map.get(sym, 5000000.0)
        if vol >= min_volume_usdt:
            qualified_pairs.append((sym, vol))

    if qualified_pairs:
        qualified_pairs.sort(key=lambda x: x[1], reverse=True)
        CACHED_DYNAMIC_WATCHLIST = [x[0] for x in qualified_pairs]
    else:
        CACHED_DYNAMIC_WATCHLIST = all_discovered_pairs

    LAST_WATCHLIST_FETCH_TIME = now
    return CACHED_DYNAMIC_WATCHLIST

# ==============================================================================
# 5. MARKET DATA & TECHNICAL INDICATOR ENGINE
# ==============================================================================
def fetch_klines(symbol, interval_str="15m", limit=100):
    coin = symbol.split('-')[0].upper()
    clean_sym = f"{coin}USDT"
    
    # Provider 1: Binance Endpoints
    binance_endpoints = [
        f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
    ]
    for url in binance_endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                raw = json.loads(resp.read().decode('utf-8'))
                if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list):
                    return [[int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in raw]
        except Exception:
            pass

    # Provider 2: MEXC Endpoints
    mexc_interval = 'Min15' if interval_str == '15m' else ('Min5' if interval_str == '5m' else ('Min60' if interval_str == '1h' else 'Day1'))
    mexc_endpoints = [
        f"https://api.mexc.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}",
        f"https://contract.mexc.com/api/v1/contract/kline/{clean_sym}?interval={mexc_interval}"
    ]
    for url in mexc_endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                raw = json.loads(resp.read().decode('utf-8'))
                if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list):
                    return [[int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in raw]
                elif isinstance(raw, dict) and raw.get('data'):
                    d = raw['data']
                    return [[int(d['time'][i] * 1000), float(d['open'][i]), float(d['high'][i]), float(d['low'][i]), float(d['close'][i]), float(d['vol'][i])] for i in range(len(d['time']))][-limit:]
        except Exception:
            pass

    # Provider 3: Gate.io Fallback
    try:
        gate_interval = '15m' if interval_str == '15m' else ('5m' if interval_str == '5m' else ('1h' if interval_str == '1h' else '1d'))
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={coin}_USDT&interval={gate_interval}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if isinstance(raw, list) and len(raw) > 0:
                raw_sorted = sorted(raw, key=lambda x: x.get('time', 0))
                return [[int(c.get('time', 0)), float(c.get('open', 0)), float(c.get('high', 0)), float(c.get('low', 0)), float(c.get('close', 0)), float(c.get('volume', 0))] for c in raw_sorted[-limit:]]
    except Exception:
        pass

    return []

def calculate_ema(prices, period=20):
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_volume_spike(klines, period=20):
    if not klines or len(klines) < period + 1:
        return 1.0
    vols = [float(k[5]) for k in klines]
    current_vol = vols[-1]
    baseline_vols = vols[-period-1:-1]
    avg_vol = sum(baseline_vols) / len(baseline_vols) if baseline_vols else current_vol
    return (current_vol / avg_vol) if avg_vol > 0 else 1.0

# Central Pivot Range (CPR) Calculation Engine (Frank Ochoa Model with full R1-R4, S1-S4)
def calculate_cpr(high, low, close):
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot
    upper_cpr = max(tc, bc)
    lower_cpr = min(tc, bc)
    r1 = 2.0 * pivot - low
    s1 = 2.0 * pivot - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    r3 = high + 2.0 * (pivot - low)
    s3 = low - 2.0 * (high - pivot)
    r4 = high + 3.0 * (pivot - low)
    s4 = low - 3.0 * (high - pivot)
    return {
        'pivot': pivot, 
        'tc': upper_cpr, 
        'bc': lower_cpr, 
        'upper_cpr': upper_cpr,
        'lower_cpr': lower_cpr,
        'r1': r1, 'r2': r2, 'r3': r3, 'r4': r4,
        's1': s1, 's2': s2, 's3': s3, 's4': s4,
        'prev_high': high, 'prev_low': low
    }

# Supertrend Indicator Engine (10, 3)
def calculate_supertrend(klines, period=10, multiplier=3.0):
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    n = len(closes)
    if n < period + 1:
        return 1, closes[-1] if closes else 0.0

    tr = [0.0] * n
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    atr = [0.0] * n
    atr[period] = sum(tr[1:period + 1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    st_direction = 1
    supertrend = 0.0
    for i in range(period, n):
        basic_upper = (highs[i] + lows[i]) / 2.0 + multiplier * atr[i]
        basic_lower = (highs[i] + lows[i]) / 2.0 - multiplier * atr[i]

        if i == period:
            supertrend = basic_lower
            st_direction = 1
        else:
            if closes[i] > supertrend:
                st_direction = 1
                supertrend = max(basic_lower, supertrend)
            else:
                st_direction = -1
                supertrend = min(basic_upper, supertrend)

    return st_direction, supertrend

# ==============================================================================
# 6. TELEGRAM NOTIFICATION SYSTEM
# ==============================================================================
def send_telegram_message(text):
    if not TOKEN or not CHAT_ID:
        return False
    for mode in ['HTML', None]:
        for attempt in range(2):
            try:
                url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                payload = {'chat_id': CHAT_ID, 'text': text}
                if mode: payload['parse_mode'] = mode
                data = urllib.parse.urlencode(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                    res = json.loads(resp.read().decode('utf-8'))
                    if res.get('ok'):
                        return True
            except Exception:
                if mode == 'HTML':
                    text = re.sub(r'<[^>]+>', '', text)
                continue
        time.sleep(1)
    return False

# ==============================================================================
# 7. COINDCX POSITION DISCOVERY & MANUAL TRADE SUPPORT
# ==============================================================================
def fetch_all_coindcx_live_positions():
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return None

    body_variants = [
        {"timestamp": int(time.time()), "page": "1", "size": "50", "margin_currency_short_name": ["USDT"]},
        {"timestamp": int(round(time.time() * 1000)), "page": "1", "size": "50"},
        {"timestamp": int(round(time.time() * 1000))}
    ]
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions"
    for body in body_variants:
        try:
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': COINDCX_API_KEY,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                pos_list = data if isinstance(data, list) else data.get('positions', data.get('data', data.get('result', [])))
                if isinstance(pos_list, list):
                    return pos_list
        except Exception:
            continue
    return None

def fetch_coindcx_live_position_qty(symbol):
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
    target_clean = futures_coin.replace("1000", "")
    
    pos_list = fetch_all_coindcx_live_positions()
    if pos_list is None:
        return None
        
    possible_qty_keys = [
        'active_units', 'open_position_qty', 'position_qty', 'active_position',
        'quantity', 'size', 'current_qty', 'net_quantity', 'open_position', 'units'
    ]
    for p in pos_list:
        if not isinstance(p, dict):
            continue
        p_pair = str(p.get('pair', '')).upper()
        p_clean = p_pair.replace("B-", "").replace("1000", "").replace("_", "").replace("-", "").replace("USDT", "")
        if p_clean == target_clean:
            for k in possible_qty_keys:
                val = p.get(k)
                if val is not None:
                    try:
                        f_val = abs(float(val))
                        if f_val > 0:
                            return f_val
                    except Exception:
                        pass
            return 1.0
    return 0.0

def recover_live_coindcx_positions():
    global ACTIVE_TRADES
    pos_list = fetch_all_coindcx_live_positions()
    if not pos_list or not isinstance(pos_list, list):
        print("Live position recovery: No open positions retrieved from CoinDCX.")
        return

    for p in pos_list:
        if not isinstance(p, dict):
            continue
        p_pair = str(p.get('pair', '')).upper()
        active_u = float(p.get('active_units', p.get('open_position_qty', p.get('quantity', 0))))
        if active_u > 0:
            raw_c = p_pair.replace("B-", "").replace("_USDT", "").replace("USDT", "")
            orig_c = raw_c.replace("1000", "")
            sym = f"{orig_c}-USDT"
            with active_trades_lock:
                if sym not in ACTIVE_TRADES:
                    entry_p = float(p.get('avg_price', p.get('entry_price', 0)))
                    if entry_p <= 0:
                        k1 = fetch_klines(sym, '1m', 1)
                        entry_p = k1[-1][4] if k1 else 1.0
                    ACTIVE_TRADES[sym] = {
                        'entry_price': entry_p,
                        'total_qty': active_u,
                        'remaining_qty': active_u,
                        'tp1': round(entry_p * 1.032, 4),
                        'sl': round(entry_p * (1.0 - 0.0095), 4),
                        'be_trigger': round(entry_p * 1.0085, 4),
                        'is_be_active': False,
                        'leverage': 7,
                        'entry_time': time.time()
                    }
                    print(f"✅ Auto-recovered live CoinDCX position: {sym} (Qty: {active_u}, Entry: {entry_p})")
                    try:
                        hist = load_trade_history()
                        today_str = get_ist_now().strftime("%d-%m-%Y")
                        today_execs = [e for e in hist.get(today_str, []) if e.get("type") == "EXECUTED" and e.get("symbol") == sym]
                        if not today_execs:
                            log_trade_event(sym, "EXECUTED", {
                                "cmp": entry_p,
                                "quantity": active_u,
                                "order_id": p.get('order_id', p.get('id', 'CoinDCX-Live-Recovery')),
                                "margin": 1000.0
                            })
                    except Exception as e:
                        print(f"Error logging recovered trade: {e}")

# ==============================================================================
# 8. PRECISION & LOT SIZE FORMATTERS
# ==============================================================================
def format_coindcx_quantity(raw_qty, cmp, coin):
    if coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI', 'CHEEMS', 'CAT', 'SATS', 'RATS', 'MOG', 'XEC', 'LUNC', 'BABYDOGE', 'WHY']:
        return max(1.0, round(raw_qty))
    if cmp >= 1000.0:
        return round(raw_qty, 3)
    elif cmp >= 100.0:
        return round(raw_qty, 2)
    elif cmp >= 1.0:
        return round(raw_qty, 1)
    else:
        return round(raw_qty, 0)

def format_price_precision(price, cmp, coin):
    if price is None or price <= 0:
        return None
    if coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI', 'CHEEMS', 'CAT', 'SATS', 'RATS', 'MOG', 'XEC', 'LUNC', 'BABYDOGE', 'WHY']:
        return round(price, 8)
    if cmp >= 1000.0:
        return round(price, 1)
    elif cmp >= 100.0:
        return round(price, 2)
    elif cmp >= 1.0:
        return round(price, 4)
    else:
        return round(price, 6)

# ==============================================================================
# 9. COINDCX FUTURES ORDER EXECUTION ENGINE
# ==============================================================================
def execute_coindcx_futures_trade(symbol, side="buy", cmp=0.0, margin_inr=1000.0, leverage=7, custom_quantity=None, tp_price=None, sl_price=None):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return {'success': False, 'error': 'CoinDCX API credentials missing'}

    coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
    pair_name = f"B-{futures_coin}_USDT"

    usdt_inr_rate = 90.0
    margin_usdt = margin_inr / usdt_inr_rate
    notional_value_usdt = margin_usdt * leverage

    if custom_quantity is not None and custom_quantity > 0:
        quantity = custom_quantity
    else:
        raw_quantity = notional_value_usdt / cmp if cmp > 0 else 0
        quantity = format_coindcx_quantity(raw_quantity, cmp, coin)

    formatted_tp = format_price_precision(tp_price, cmp, coin)
    formatted_sl = format_price_precision(sl_price, cmp, coin)

    futures_url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    ts = int(round(time.time() * 1000))

    futures_order_payload_tpsl = {
        "side": side.lower(),
        "pair": pair_name,
        "order_type": "market_order",
        "total_quantity": quantity,
        "leverage": leverage,
        "notification": "no_notification"
    }
    if formatted_tp is not None:
        futures_order_payload_tpsl["take_profit_price"] = formatted_tp
    if formatted_sl is not None:
        futures_order_payload_tpsl["stop_loss_price"] = formatted_sl

    futures_order_payload_clean = {
        "side": side.lower(),
        "pair": pair_name,
        "order_type": "market_order",
        "total_quantity": quantity,
        "leverage": leverage,
        "notification": "no_notification"
    }

    if side.lower() == "buy":
        endpoint_variants = [
            (futures_url, {"timestamp": ts, "order": futures_order_payload_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_clean})
        ]
    else:
        endpoint_variants = [
            (futures_url, {"timestamp": ts, "order": futures_order_payload_clean})
        ]

    err_logs = []
    for idx, (target_url, body) in enumerate(endpoint_variants, 1):
        try:
            body["timestamp"] = int(round(time.time() * 1000))
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': COINDCX_API_KEY,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(target_url, data=json_body.encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                order_id = "EXECUTED"
                if isinstance(data, dict):
                    order_id = data.get('id', data.get('order_id', 'EXECUTED'))
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    order_id = data[0].get('id', 'EXECUTED')
                actual_qty = body.get("order", {}).get("total_quantity", quantity)
                return {'success': True, 'order_id': order_id, 'quantity': actual_qty, 'pair': pair_name}
        except urllib.error.HTTPError as e:
            try:
                raw_bytes = e.read()
                try:
                    import gzip
                    raw_bytes = gzip.decompress(raw_bytes)
                except Exception:
                    pass
                err_clean = re.sub(r'<[^>]+>', ' ', raw_bytes.decode('utf-8', errors='ignore')).strip()
                err_logs.append(f"V{idx}: HTTP {e.code} - {err_clean[:60]}")
            except Exception:
                err_logs.append(f"V{idx}: HTTP {e.code} - {e}")
        except Exception as e:
            err_logs.append(f"V{idx}: {e}")

    return {'success': False, 'error': " | ".join(err_logs)}

# ==============================================================================
# 10. FLASK WEB SERVER & WEBHOOKS
# ==============================================================================
@app.route('/')
def home():
    now_ist = get_ist_now().strftime("%d-%m-%Y %I:%M:%S %p (IST)")
    active_count = len(ACTIVE_TRADES)
    status_str = "🟢 ACTIVE" if AUTO_TRADING_ENABLED else "🔴 PAUSED"
    return (
        f"<h2>⚡ CoinDCX Autonomous Trading Engine (180+ Dynamic Pairs)</h2>"
        f"<p><b>Server Time:</b> {now_ist}</p>"
        f"<p><b>Status:</b> {status_str}</p>"
        f"<p><b>Active Positions:</b> {active_count} / 4 Concurrent</p>"
        f"<p><b>Trade Trigger Mode:</b> Option A (Score >= 75 Instant Fire)</p>"
        f"<p><b>Stop Loss Engine:</b> Author CPR Logic (Below BC / Prev Low, Capped at -0.95%)</p>"
        f"<p><a href='/report'>View Today's Trading Report</a> | <a href='/scan-now'>Run Live Dynamic Market Audit</a></p>"
    ), 200

@app.route('/healthz')
def healthz():
    return "OK", 200

@app.route('/report')
def report_endpoint():
    try:
        now_ist = get_ist_now()
        target_date_str = request.args.get('date', now_ist.strftime("%d-%m-%Y"))
        
        summary_text = generate_daily_summary(target_date_str)
        
        history = load_trade_history()
        events = history.get(target_date_str, [])
        rows = []
        for idx, e in enumerate(events, 1):
            sym = e.get('symbol', 'UNKNOWN')
            t = e.get('time', '')
            act = e.get('type', e.get('action', ''))
            dt = e.get('details', {})
            dt_str = " | ".join([f"{k}: {v}" for k, v in dt.items() if k not in ['order_id', 'margin']])
            color = "#10b981" if act == "EXECUTED" else ("#ef4444" if act == "CLOSED" else "#f59e0b")
            rows.append(f"<tr><td>{idx}</td><td>{t}</td><td><b>{sym}</b></td><td style='color:{color};font-weight:bold;'>{act}</td><td><code>{dt_str}</code></td></tr>")
            
        rows_html = "\n".join(rows) if rows else f"<tr><td colspan='5'>No signals or trades logged for {target_date_str}.</td></tr>"
        html = f"""<!DOCTYPE html><html><head><title>Trading Report - {target_date_str}</title>
<style>body {{ font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }}
h2 {{ color: #38bdf8; }} table {{ width: 100%; border-collapse: collapse; margin-top: 15px; background: #1e293b; }}
th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #334155; }} th {{ background: #0284c7; color: white; }}
pre {{ background: #1e293b; padding: 15px; border-radius: 8px; font-size: 15px; border: 1px solid #334155; line-height: 1.5; }}</style></head>
<body><h2>📅 Daily Automated Trading Audit Report ({target_date_str})</h2><pre>{summary_text}</pre>
<h3>📝 Itemized Event History ({target_date_str})</h3><table><thead><tr><th>#</th><th>Time</th><th>Pair</th><th>Status / Action</th><th>Price Details</th></tr></thead>
<tbody>{rows_html}</tbody></table></body></html>"""
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Report Error:</h3><p>{e}</p>", 500

@app.route('/scan-now')
def scan_now_endpoint():
    try:
        report_lines = []
        scan_pool = fetch_dynamic_watchlist(min_volume_usdt=2500000.0)
        for symbol in scan_pool:
            try:
                time.sleep(0.03)
                m15_klines = fetch_klines(symbol, '15m', 100)
                if not m15_klines or len(m15_klines) < 20:
                    report_lines.append(f"{symbol:12s} | Error: Could not fetch candle data")
                    continue
                cmp = m15_klines[-1][4]
                st_dir, _ = calculate_supertrend(m15_klines)
                is_st_green = (st_dir == 1)
                
                # Check 24h volume threshold (>= $2,500,000)
                daily_klines = fetch_klines(symbol, '1d', 2) or m15_klines
                vol_24h_quote = max(float(daily_klines[0][5]), float(daily_klines[-1][5])) * cmp if (daily_klines and len(daily_klines[0]) > 5) else 3000000.0
                if vol_24h_quote < 2500000:
                    report_lines.append(f"{symbol:12s} | CMP: {cmp:<10.4f} | 🛑 Low 24h Volume Filtered (<$2.5M)")
                    continue

                h1_klines = fetch_klines(symbol, '1h', 60)
                cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
                close_prices = [k[4] for k in m15_klines]
                rsi_val = calculate_rsi(close_prices)
                vol_spike = calculate_volume_spike(m15_klines)
                ema20_15m = calculate_ema(close_prices, 20)
                
                h1_macro_bullish = True
                if h1_klines and len(h1_klines) >= 20:
                    h1_st_dir, _ = calculate_supertrend(h1_klines)
                    h1_closes = [k[4] for k in h1_klines]
                    h1_ema50 = calculate_ema(h1_closes, 50)
                    h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

                is_cpr_buy_zone = (cmp >= cpr['bc'] * 0.998)
                score = 40
                if is_cpr_buy_zone: score += 20
                if cmp >= cpr['tc'] * 0.998: score += 10
                if 42 <= rsi_val <= 72: score += 10
                if vol_spike >= 1.15: score += 10
                score = min(100, score)
                
                status = "🟢 Bullish" if (is_st_green and h1_macro_bullish and is_cpr_buy_zone) else "⚪ Consolidating"
                report_lines.append(f"{symbol:12s} | CMP: {cmp:<10.4f} | EMA20: {ema20_15m:<10.4f} | ST 15M: {'GREEN' if is_st_green else 'RED':5s} | 1H: {'BULL' if h1_macro_bullish else 'BEAR':4s} | CPR: {'YES' if is_cpr_buy_zone else 'NO ':3s} | Vol: {vol_spike:.2f}x | Score: {score:<3d} | {status}")
            except Exception as e:
                report_lines.append(f"{symbol:12s} | Error: {e}")
        
        now_str = get_ist_now().strftime("%d-%m-%Y %H:%M:%S (IST)")
        html = f"<h2>⚡ LIVE COINDCX DYNAMIC MARKET SCANNER AUDIT REPORT (ALL 180+ PAIRS, VOL >= $2.5M)</h2><p><b>Server Time:</b> {now_str}</p><pre>" + "\n".join(report_lines) + "</pre>"
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Scan Error:</h3><p>{e}</p>", 500

# ==============================================================================
# 11. AUTONOMOUS SCANNER & TRADE GENERATION ENGINE (OPTION A)
# ==============================================================================
def run_scan():
    state = load_state()
    candidates = []
    # Dynamic: Scans all 180+ CoinDCX Pairs with 24h Volume >= $2,500,000 USDT
    scan_pool = fetch_dynamic_watchlist(min_volume_usdt=2500000.0)

    for symbol in scan_pool:
        try:
            time.sleep(0.03)
            # Fetch 15M candles first for fast evaluation
            m15_klines = fetch_klines(symbol, '15m', 100)
            if not m15_klines or len(m15_klines) < 20:
                continue

            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            is_st_green = (st_dir == 1)
            
            # Non-Negotiable Gate: 15-Minute Supertrend MUST BE GREEN (Zero Short Trades / Zero Counter-Trend Longs)
            if not is_st_green:
                continue

            # Fetch daily candles to verify 24h volume >= $2,500,000 USDT
            daily_klines = fetch_klines(symbol, '1d', 2) or m15_klines
            vol_24h_quote = max(float(daily_klines[0][5]), float(daily_klines[-1][5])) * cmp if (daily_klines and len(daily_klines[0]) > 5) else 5000000.0
            if vol_24h_quote < 2500000:
                continue

            h1_klines = fetch_klines(symbol, '1h', 60)
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])

            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            ema20_15m = calculate_ema(close_prices, 20)
            ema50_15m = calculate_ema(close_prices, 50)
            
            # 1H Macro Trend Bullish Gate
            h1_macro_bullish = False
            if h1_klines and len(h1_klines) >= 20:
                h1_closes = [k[4] for k in h1_klines]
                h1_lows = [k[3] for k in h1_klines]
                h1_ema20 = calculate_ema(h1_closes, 20)
                h1_ema50 = calculate_ema(h1_closes, 50)
                h1_st_dir, _ = calculate_supertrend(h1_klines)
                
                recent_h1_low = min(h1_lows[-10:-1])
                prev_h1_low = min(h1_lows[-25:-10])
                is_higher_lows = (recent_h1_low >= prev_h1_low * 0.995)
                h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50) and (h1_ema20 >= h1_ema50 * 0.998) and is_higher_lows

            last_15m_low = m15_klines[-1][3]
            dist_cmp_to_ema20 = (cmp - ema20_15m) / ema20_15m if ema20_15m > 0 else 0.0

            # CPR Buy Zone: Price holding at or above Bottom Central (BC) support or above TC
            is_cpr_buy_zone = (cmp >= cpr['bc'] * 0.998) and (dist_cmp_to_ema20 <= 0.050)

            # 5M Liquidity Sweep & Confirmed Green Closed Candle (Bonus Confirmation)
            m5_klines = fetch_klines(symbol, '5m', 20)
            is_5m_liquidity_sweep_reclaim = False
            sweep_low_price = last_15m_low

            if m5_klines and len(m5_klines) >= 6:
                m5_recent_lows = [k[3] for k in m5_klines[-10:-2]]
                m5_swing_low = min(m5_recent_lows)
                m5_last, m5_prev = m5_klines[-1], m5_klines[-2]
                
                did_sweep_low = any(k[3] < m5_swing_low for k in m5_klines[-4:])
                did_reclaim = (m5_last[4] > m5_swing_low) or (m5_prev[4] > m5_swing_low)
                is_5m_bullish_green = (m5_prev[4] > m5_prev[1]) or (m5_last[4] > m5_last[1] and m5_last[4] >= m5_prev[4])
                is_5m_engulfing = (m5_last[4] >= m5_prev[2]) or ((m5_last[4] - m5_last[1]) > (m5_prev[1] - m5_prev[4]))
                
                is_5m_liquidity_sweep_reclaim = (did_sweep_low and did_reclaim and is_5m_bullish_green) or (is_5m_bullish_green and is_5m_engulfing)
                sweep_low_price = min(k[3] for k in m5_klines[-4:])

            # Dynamic Confluence Scoring Engine (Base: 40)
            score = 40
            if is_cpr_buy_zone: score += 20
            if cmp >= cpr['tc'] * 0.998: score += 10
            if 42 <= rsi_val <= 72: score += 10
            if vol_spike >= 1.15: score += 10
            if is_5m_liquidity_sweep_reclaim: score += 10
            score = max(0, min(100, score))
            
            rating = "A+ (Strong Trend & CPR Confluence) 👑" if score >= 80 else ("A (Solid CPR Bounce) 🥇" if score >= 70 else "B (Moderate)")

            # Option A Entry Gate: Triggers automatically for 15M Green + 1H Bull + CPR Support + Score >= 75
            # (Enters momentum leaders like TRX and XMR without waiting for a rare 5M sweep)
            if is_st_green and h1_macro_bullish and is_cpr_buy_zone and (score >= 75):
                candidates.append({'symbol': symbol, 'score': score, 'rating': rating, 'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 'rsi_val': rsi_val, 'vol_spike': vol_spike, 'ema20': ema20_15m, 'm15_low': last_15m_low, 'sweep_low': sweep_low_price})
        except Exception:
            pass

    candidates.sort(key=lambda x: x['score'], reverse=True)
    coin_margin = 1000.0

    for cand in candidates:
        symbol = cand['symbol']
        score, rating, cmp, cpr = cand['score'], cand['rating'], cand['cmp'], cand['cpr']
        try:
            curr_state = load_state()
            raw_coin = symbol.split('-')[0].upper()
            futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
            clean_coin = futures_coin.replace("1000", "")
            
            with active_trades_lock:
                is_in_memory = any(clean_coin == COINDCX_PAIR_ALIASES.get(s.split('-')[0].upper(), s.split('-')[0].upper()).replace("1000", "") for s in ACTIVE_TRADES.keys())
                active_count = len(ACTIVE_TRADES)

            # Max 4 Concurrent Trades Cap
            if active_count >= 4:
                break

            # 30-Minute Cooldown & Duplicate Check
            last_sent = curr_state.get(symbol, 0)
            if is_in_memory or (time.time() - last_sent < 900):
                continue
            
            # Manual Trade Support: Cleanly skips coins already opened manually on CoinDCX App
            live_qty = fetch_coindcx_live_position_qty(symbol)
            if live_qty is not None and live_qty > 0:
                continue

            clean_symbol = symbol.replace("-", "")
            entry_min = round(cmp * 0.998, 4) if cmp >= 0.001 else round(cmp * 0.998, 8)
            entry_max = round(cmp * 1.001, 4) if cmp >= 0.001 else round(cmp * 1.001, 8)
            
            sweep_low_val = cand.get('sweep_low', cand.get('m15_low', cmp))
            bc_val = cpr.get('bc', cmp * 0.995)
            prev_low_val = cpr.get('prev_low', sweep_low_val)

            # Author's CPR Logic (Frank Ochoa / "Secrets of a Pivot Boss"):
            # Stop Loss placed structurally below Bottom Central (BC), 5M Sweep Low, or Previous Day Low
            # Capped at -0.95% price drop (-6.65% ROE) as safety guard against wide CPR spreads
            support_floor = min(bc_val, sweep_low_val, prev_low_val)
            structural_sl = support_floor * 0.9985
            hard_sl_cap = cmp * (1.0 - 0.0095)  # -0.95% Price Drop Cap (-6.65% ROE)
            sl_raw = max(hard_sl_cap, structural_sl)
            if sl_raw >= cmp * 0.997:
                sl_raw = cmp * 0.995

            # Target: Next Pivot Level (R1 or R2) or standard +3.2% move (+22.4% ROE / 1:2 R:R Ratio)
            standard_tp = cmp * 1.032
            r1_val = cpr.get('r1', standard_tp)
            r2_val = cpr.get('r2', standard_tp)

            if r1_val >= cmp * 1.020 and r1_val <= cmp * 1.036:
                tp1_raw = r1_val
            elif r1_val < cmp * 1.020 and r2_val >= cmp * 1.028:
                tp1_raw = min(r2_val, cmp * 1.038)
            else:
                tp1_raw = standard_tp

            be_trigger_raw = cmp * 1.0085
            sl = round(sl_raw, 4) if cmp < 100.0 else round(sl_raw, 2)
            tp1 = round(tp1_raw, 4) if cmp < 100.0 else round(tp1_raw, 2)
            be_trigger = round(be_trigger_raw, 4) if cmp < 100.0 else round(be_trigger_raw, 2)
            lev_num = 7
            
            # Execute Long Trade (100% BUY / LONG ONLY)
            if AUTO_TRADING_ENABLED:
                trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=coin_margin, leverage=lev_num, tp_price=tp1, sl_price=sl)
            else:
                trade_res = {'success': False, 'error': 'Auto-trading PAUSED via Mobile Telegram command (/stop).'}
            
            if trade_res.get('success'):
                exec_hdr = (
                    f"\n\n⚡ <b>AUTO-TRADE EXECUTED ON COINDCX FUTURES!</b>\n"
                    f"• <b>Status:</b> <code>SUCCESS (Order ID: {trade_res.get('order_id')})</code>\n"
                    f"• <b>Quantity:</b> <code>{trade_res.get('quantity')} {clean_symbol[:-4]}</code>\n"
                    f"• <b>Margin Allocated:</b> <code>₹{coin_margin:.0f} INR</code>"
                )
                log_trade_event(symbol, "EXECUTED", {"cmp": cmp, "quantity": trade_res.get('quantity'), "order_id": trade_res.get('order_id'), "margin": coin_margin})
                with active_trades_lock:
                    ACTIVE_TRADES[symbol] = {
                        'entry_price': cmp,
                        'total_qty': trade_res.get('quantity'),
                        'remaining_qty': trade_res.get('quantity'),
                        'tp1': tp1,
                        'sl': sl,
                        'be_trigger': be_trigger,
                        'is_be_active': False,
                        'leverage': lev_num,
                        'entry_time': time.time()
                    }
                save_active_trades()
                state[symbol] = time.time()
                save_state(state)
            else:
                exec_hdr = f"\n\n⚠️ <b>COINDCX EXECUTION NOTICE:</b>\n<code>{trade_res.get('error')}</code>"
                log_trade_event(symbol, "CANCELLED", {"cmp": cmp, "error": trade_res.get('error')})
                state[symbol] = time.time()
                save_state(state)

            msg = (
                f"🟢 <b>NEW CPR BREAKOUT & BOUNCE SIGNAL</b>\n\n"
                f"<b>Pair:</b> B-{clean_symbol[:-4]}_USDT (Futures)\n"
                f"<b>Direction:</b> BUY / LONG\n\n"
                f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                f"🏆 <b>Signal Strength:</b> <code>{rating}</code>\n\n"
                f"⚙️ <b>Trade Parameters:</b>\n"
                f"• <b>Leverage:</b> <code>7x (Isolated)</code>\n"
                f"• <b>Margin:</b> <code>₹{coin_margin:.0f} INR (Per Trade)</code>\n"
                f"• <b>Live CMP:</b> <code>${cmp}</code>\n\n"
                f"🔹 <b>Entry Range:</b> <code>{entry_min} - {entry_max}</code>\n"
                f"🔹 <b>Stop Loss:</b> <code>${sl}</code> (Below BC / Prev Low / Capped at -0.95% Drop)\n"
                f"🎯 <b>Target:</b> <code>${tp1}</code> (Next Pivot R1/R2 or +3.2% Move)\n"
                f"🛡️ <b>Breakeven Profit Lock:</b> <code>Trigger @ +6.0% ROE (+0.85% Move)</code>\n"
                f"⏱️ <b>Time Stop:</b> <code>75 Minutes Max Stagnation Cut</code>\n"
                f"{exec_hdr}"
            )
            send_telegram_message(msg)
        except Exception as e:
            print(f"⚠️ Error executing candidate {symbol}: {e}")

# ==============================================================================
# 12. POSITION MONITORING, TRAILING SL & STAGNATION GUARD
# ==============================================================================
def monitor_active_positions():
    time.sleep(10)
    while True:
        if not AUTO_TRADING_ENABLED:
            time.sleep(5)
            continue
            
        with active_trades_lock:
            symbols = list(ACTIVE_TRADES.keys())

        for sym in symbols:
            try:
                with active_trades_lock:
                    trade = ACTIVE_TRADES.get(sym)
                if not trade:
                    continue

                m1 = fetch_klines(sym, '1m', 2)
                if not m1:
                    continue
                cmp = m1[-1][4]
                ep = trade['entry_price']
                lev = trade.get('leverage', 7)
                roe = ((cmp - ep) / ep) * lev * 100

                # 75-Minute Auto Time-Stop Guard
                open_mins = (time.time() - trade.get('entry_time', time.time())) / 60.0
                if open_mins >= 75 and roe <= 2.0:
                    res = execute_coindcx_futures_trade(symbol=sym, side="sell", cmp=cmp, custom_quantity=trade['total_qty'])
                    if res.get('success'):
                        log_trade_event(sym, "CLOSED", {"cmp": cmp, "realized_pnl_pct": roe, "reason": "75-Min Stagnation Time-Stop"})
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(sym, None)
                        save_active_trades()
                        send_telegram_message(f"⏱️ <b>75-MIN STAGNATION TIME-STOP TRIGGERED</b>\n\n• Pair: <b>{sym}</b>\n• Closed at: <code>${cmp}</code>\n• Realized PnL: <code>{roe:+.1f}% ROE</code>\n• Reason: Trade stagnant > 75 mins.")
                        continue

                # Breakeven Profit Lock @ +6.0% ROE (+0.85% Move)
                if roe >= 6.0 and not trade.get('is_be_active', False):
                    new_sl = round(ep * 1.002, 4)
                    trade['sl'] = new_sl
                    trade['is_be_active'] = True
                    save_active_trades()
                    send_telegram_message(f"🛡️ <b>BREAKEVEN PROFIT LOCK ACTIVATED!</b>\n\n• Pair: <b>{sym}</b>\n• Gain: <code>+{roe:.1f}% ROE</code>\n• Stop-loss moved to: <code>${new_sl}</code> (Risk-Free Trade)")

                # Dynamic Trailing Stage 2 @ +8.4% ROE (+1.2% Move)
                if roe >= 8.4 and not trade.get('trailing_stage_2', False):
                    new_sl = round(ep * 1.006, 4)
                    trade['sl'] = new_sl
                    trade['trailing_stage_2'] = True
                    save_active_trades()
                    send_telegram_message(f"📈 <b>STAGE 2 TRAILING STOP ACTIVATED!</b>\n\n• Pair: <b>{sym}</b>\n• Gain: <code>+{roe:.1f}% ROE</code>\n• Profit Locked: <code>+4.2% ROE Minimum</code>")

                # Dynamic Trailing Stage 3 @ +12.6% ROE (+1.8% Move)
                if roe >= 12.6 and not trade.get('trailing_stage_3', False):
                    new_sl = round(ep * 1.012, 4)
                    trade['sl'] = new_sl
                    trade['trailing_stage_3'] = True
                    save_active_trades()
                    send_telegram_message(f"🚀 <b>STAGE 3 RUNNER ENGINE ACTIVATED!</b>\n\n• Pair: <b>{sym}</b>\n• Gain: <code>+{roe:.1f}% ROE</code>\n• Profit Locked: <code>+8.4% ROE Minimum</code>")

                # Target Hit (TP)
                if cmp >= trade['tp1']:
                    res = execute_coindcx_futures_trade(symbol=sym, side="sell", cmp=cmp, custom_quantity=trade['total_qty'])
                    if res.get('success'):
                        log_trade_event(sym, "CLOSED", {"cmp": cmp, "realized_pnl_pct": roe, "reason": "Target Hit 🎯"})
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(sym, None)
                        save_active_trades()
                        send_telegram_message(f"🎯 <b>TARGET REACHED & POSITION CLOSED!</b>\n\n• Pair: <b>{sym}</b>\n• Exit CMP: <code>${cmp}</code>\n• Realized PnL: <code>{roe:+.1f}% ROE 💰</code>")
                        continue

                # Stop Loss Hit (SL)
                if cmp <= trade['sl']:
                    res = execute_coindcx_futures_trade(symbol=sym, side="sell", cmp=cmp, custom_quantity=trade['total_qty'])
                    if res.get('success'):
                        log_trade_event(sym, "CLOSED", {"cmp": cmp, "realized_pnl_pct": roe, "reason": "Stop Loss Hit 🛑"})
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(sym, None)
                        save_active_trades()
                        send_telegram_message(f"🛑 <b>STOP LOSS HIT & POSITION CLOSED</b>\n\n• Pair: <b>{sym}</b>\n• Exit CMP: <code>${cmp}</code>\n• Realized PnL: <code>{roe:+.1f}% ROE</code>")
                        continue
            except Exception as e:
                print(f"Error in monitor loop for {sym}: {e}")
        time.sleep(3)

# ==============================================================================
# 13. AUTOMATED HOURLY MARKET CONDITION REPORT GENERATOR
# ==============================================================================
def generate_hourly_market_report():
    now_ist = get_ist_now()
    now_str = now_ist.strftime("%d-%m-%Y %I:%M %p (IST)")
    
    scan_pool = fetch_dynamic_watchlist(min_volume_usdt=2500000.0)
    bullish_coins = []
    consolidating_coins = []
    
    btc_klines = fetch_klines('BTC-USDT', '15m', 20)
    btc_cmp = btc_klines[-1][4] if btc_klines else 0.0
    btc_st, _ = calculate_supertrend(btc_klines) if btc_klines else (1, 0)
    btc_status = "🟢 BULLISH" if btc_st == 1 else "🔴 BEARISH"
    
    for symbol in scan_pool[:45]:
        try:
            m15 = fetch_klines(symbol, '15m', 30)
            if not m15 or len(m15) < 20: continue
            st_dir, _ = calculate_supertrend(m15)
            coin_clean = symbol.replace("-USDT", "")
            if st_dir == 1:
                bullish_coins.append(coin_clean)
            else:
                consolidating_coins.append(coin_clean)
        except Exception:
            pass
            
    total_eval = len(bullish_coins) + len(consolidating_coins)
    bull_pct = (len(bullish_coins) / total_eval * 100) if total_eval > 0 else 50.0
    sentiment = "🟢 BULLISH BIAS" if bull_pct >= 55 else ("🔴 BEARISH BIAS" if bull_pct <= 35 else "⚖️ NEUTRAL / CONSOLIDATION")
    
    with active_trades_lock:
        active_count = len(ACTIVE_TRADES)
        active_list = list(ACTIVE_TRADES.keys())
    active_str = ", ".join([s.replace("-USDT", "") for s in active_list]) if active_list else "None (100% Cash Liquid)"
    
    today_str = now_ist.strftime("%d-%m-%Y")
    history = load_trade_history()
    events = history.get(today_str, [])
    closed_today = [e for e in events if e.get('type') == "CLOSED" or e.get('action') == "CLOSED"]
    total_roe = sum([e.get('details', {}).get('realized_pnl_pct', 0.0) for e in closed_today])
    
    top_bulls = ", ".join(bullish_coins[:8]) if bullish_coins else "None"
    
    lines = [
        f"📊 <b>AUTOMATED HOURLY MARKET CONDITION REPORT</b>",
        f"🕒 <b>Time:</b> <code>{now_str}</code>\n",
        f"🌐 <b>Macro Market State:</b>",
        f"• <b>BTC Trend (15M):</b> <b>{btc_status}</b> (${btc_cmp:,.1f})",
        f"• <b>Market Sentiment:</b> <b>{sentiment}</b> ({bull_pct:.0f}% Bullish)",
        f"• <b>Top Bullish Coins (15M Green):</b> <code>{top_bulls}</code>\n",
        f"💼 <b>Portfolio & Execution Status:</b>",
        f"• <b>Active Positions:</b> <code>{active_count} / 4 Concurrent</code> [{active_str}]",
        f"• <b>Closed Trades Today:</b> <code>{len(closed_today)}</code> (Net ROE: <code>{total_roe:+.1f}%</code>)",
        f"• <b>Auto-Trading Engine:</b> <b>{'🟢 ACTIVE' if AUTO_TRADING_ENABLED else '🔴 PAUSED'}</b>",
        f"• <b>Stop Loss Logic:</b> <code>Author CPR (Below BC / Prev Low, Max -0.95%)</code>",
        f"• <b>Trade Entry Mode:</b> <code>Option A (Score >= 75 Instant Fire)</code>"
    ]
    return "\n".join(lines)

# ==============================================================================
# 14. TELEGRAM COMMAND LISTENER & BACKGROUND THREADS
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    last_update_id = 0
    time.sleep(10)
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('ok') and isinstance(data.get('result'), list):
                    for item in data['result']:
                        last_update_id = item.get('update_id', last_update_id)
                        message = item.get('message', {})
                        text = message.get('text', '').strip().lower()
                        
                        if text in ['/stop', '/pause', 'stop', 'pause']:
                            AUTO_TRADING_ENABLED = False
                            send_telegram_message("🛑 <b>AUTO-TRADING PAUSED VIA MOBILE COMMAND!</b>\n\n• Market signals will still be alerted.\n• CoinDCX auto-execution is OFF.")
                        elif text in ['/start', '/resume', 'start', 'resume']:
                            AUTO_TRADING_ENABLED = True
                            send_telegram_message("🟢 <b>AUTO-TRADING ACTIVATED VIA MOBILE COMMAND!</b>\n\n• CoinDCX auto-execution is ON.")
                        elif text in ['/today', '/daily', '/report', 'today', 'daily', 'report', '/history']:
                            today_str = get_ist_now().strftime("%d-%m-%Y")
                            summary_msg = generate_daily_summary(today_str)
                            send_telegram_message(summary_msg)
                        elif text in ['/yesterday', 'yesterday']:
                            yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
                            summary_msg = generate_daily_summary(yesterday_str)
                            send_telegram_message(summary_msg)
                        elif text in ['/hourly', 'hourly', '/market', 'market', '/pulse']:
                            hourly_msg = generate_hourly_market_report()
                            send_telegram_message(hourly_msg)
        except Exception:
            pass
        time.sleep(3)

def start_background_loop():
    recover_live_coindcx_positions()

    def run_loop():
        time.sleep(5)
        while True:
            try:
                if scan_lock.acquire(blocking=False):
                    try:
                        run_scan()
                    finally:
                        scan_lock.release()
            except Exception as e:
                print(f"Scan loop exception: {e}")
            time.sleep(60)

    def run_keep_alive_loop():
        time.sleep(15)
        url = "https://crypto-scanner-ok3t.onrender.com/"
        while True:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                    pass
            except Exception as e:
                print(f"Keep-alive ping error: {e}")
            time.sleep(240)

    def run_daily_midnight_report_loop():
        time.sleep(20)
        last_reported_day = ""
        while True:
            try:
                now_ist = get_ist_now()
                today_str = now_ist.strftime("%d-%m-%Y")
                if now_ist.hour == 23 and now_ist.minute >= 58 and last_reported_day != today_str:
                    daily_msg = generate_daily_summary(today_str)
                    send_telegram_message(daily_msg)
                    last_reported_day = today_str
            except Exception as e:
                print(f"Daily report loop exception: {e}")
            time.sleep(45)

    def run_hourly_market_condition_report_loop():
        time.sleep(40)
        last_reported_hour = -1
        while True:
            try:
                now_ist = get_ist_now()
                # Run automatically at the top of every hour (minute 00)
                if now_ist.minute == 0 and now_ist.hour != last_reported_hour:
                    hourly_msg = generate_hourly_market_report()
                    send_telegram_message(hourly_msg)
                    last_reported_hour = now_ist.hour
            except Exception as e:
                print(f"Hourly report loop exception: {e}")
            time.sleep(30)

    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()
    threading.Thread(target=run_daily_midnight_report_loop, daemon=True).start()
    threading.Thread(target=run_hourly_market_condition_report_loop, daemon=True).start()

    send_telegram_message(
        "⚡ <b>RENDER BOT EXPANDED SCANNER DEPLOYED!</b>\n\n"
        "• <b>Market Universe:</b> ALL 180+ CoinDCX Futures Pairs (Dynamic Discovery)\n"
        "• <b>24h Liquidity Floor:</b> Min $2,500,000 USDT ($2.5M)\n"
        "• <b>Hard Stop Loss:</b> Author CPR Logic (Below BC / Prev Low, Capped at -0.95% Drop)\n"
        "• <b>Strategy Engine:</b> CPR Breakout & Retest (Pivot, TC, BC, R1-R2)\n"
        "• <b>Trade Entry Mode:</b> Option A (15M Green + 1H Bull + CPR + Score >= 75 Instant Fire)\n"
        "• <b>Direction:</b> 100% BUY / LONG ONLY (Zero Short Trade Rule ACTIVE)\n"
        "• <b>Supertrend Gate:</b> 15M Supertrend MUST BE GREEN\n"
        "• <b>Target Engine:</b> Next Pivot Level (R1/R2) or +3.2% move (+22.4% ROE)\n"
        "• <b>Stagnation Guard:</b> 75-Minute Auto Time-Stop\n"
        "• <b>Breakeven Engine:</b> Escape Velocity @ +6.0% ROE (+0.85% move)\n"
        "• <b>Dynamic Trailing:</b> 3-Stage Runner Engine (+8.4% ROE & +12.6% ROE)\n"
        "• <b>State Auto-Recovery:</b> ACTIVE (Syncs open CoinDCX positions on boot)\n"
        "• <b>Manual Trade Support:</b> ACTIVE (Skips coins manually opened on App)\n"
        "• <b>Max Active Trades:</b> 4 Concurrent Trades (₹4,000 INR Max Portfolio)\n"
        "• <b>Margin & Leverage:</b> ₹1,000 INR per trade | 7x Isolated\n"
        "• <b>Automated Reports:</b> Hourly Condition Report & Midnight Audit Report\n"
        "• <b>Mobile Commands:</b> /stop, /start, /today, /yesterday, /hourly"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting production server on port {port}...")
    app.run(host="0.0.0.0", port=port)
