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
def log_trade_event(symbol, action, details=None):
    with trade_history_lock:
        history = {}
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f:
                    history = json.load(f)
            except Exception:
                history = {}
        
        now_ist = get_ist_now()
        date_key = now_ist.strftime("%d-%m-%Y")
        if date_key not in history:
            history[date_key] = []
            
        event = {
            'time': now_ist.strftime("%I:%M:%S %p"),
            'symbol': symbol,
            'action': action,
            'details': details or {}
        }
        history[date_key].append(event)
        
        try:
            with open(TRADE_HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass

def generate_daily_summary(target_date_str=None):
    now_ist = get_ist_now()
    if not target_date_str:
        target_date_str = now_ist.strftime("%d-%m-%Y")
        
    history = {}
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
            history = {}
            
    events = history.get(target_date_str, [])
    
    total_signals = 0
    executed_trades = []
    closed_events = []
    skipped_count = 0
    
    for e in events:
        act = e.get('action')
        if act == "EXECUTED":
            total_signals += 1
            executed_trades.append(e)
        elif act == "CLOSED":
            closed_events.append(e)
        elif act in ["CANCELLED", "SKIPPED"]:
            total_signals += 1
            skipped_count += 1
            
    win_count = 0
    loss_count = 0
    total_realized_roe = 0.0
    
    for ce in closed_events:
        dt = ce.get('details', {})
        pnl = dt.get('realized_pnl_pct', 0.0)
        total_realized_roe += pnl
        if pnl > 0.0:
            win_count += 1
        elif pnl < 0.0:
            loss_count += 1
            
    total_closed = len(closed_events)
    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0.0
    
    status_icon = "💰" if total_realized_roe >= 0 else "🛑"
    
    lines = [
        f"📅 <b>DAILY AUTOMATED TRADING REPORT ({target_date_str})</b>\n",
        "📊 <b>Performance Overview:</b>",
        f"• Total Signals: <code>{total_signals}</code>",
        f"• Executed Trades: <code>{len(executed_trades)}</code>",
        f"• Non-Executed / Skipped: <code>{skipped_count}</code>",
        f"• Closed Trades: <code>{total_closed}</code>",
        f"• Win Rate: <code>{win_rate:.1f}%</code> {'🏆' if win_rate >= 50 else '⚠️'}",
        f"• Total Realized Gain: <code>{total_realized_roe:+.1f}% ROE</code> {status_icon}"
    ]
    
    if executed_trades:
        lines.append("")
        lines.append("📝 <b>Today's Executed Trades:</b>")
        for idx, e in enumerate(executed_trades, 1):
            sym = e.get("symbol", "UNKNOWN")
            t = e.get("time", "")
            dt = e.get("details", {})
            ep = dt.get('cmp', 0)
            qty = dt.get('quantity', 0)
            oid = dt.get('order_id', 'N/A')
            lines.append(f"{idx}. <b>{sym}</b> @ {t} | Entry: <code>${ep}</code> | Qty: <code>{qty}</code> | ID: <code>{oid}</code>")
            
    with active_trades_lock:
        cur_active = list(ACTIVE_TRADES.items())
        
    if cur_active:
        lines.append("")
        lines.append("⏳ <b>Currently Open Positions:</b>")
        for idx, (sym, tr) in enumerate(cur_active, 1):
            ep = tr.get('entry_price', 0)
            qty = tr.get('remaining_qty', tr.get('total_qty', 0))
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

    # Keep all pairs that have >= $2,500,000 volume (or include for live candle volume verification)
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

def sync_active_trades_from_coindcx():
    global ACTIVE_TRADES
    pos_list = fetch_all_coindcx_live_positions()
    if not pos_list or not isinstance(pos_list, list):
        return
        
    with active_trades_lock:
        for p in pos_list:
            if not isinstance(p, dict):
                continue
            pair = str(p.get('pair', '')).upper()
            if not pair.startswith("B-") or not pair.endswith("_USDT"):
                continue
            coin_part = pair[2:-5]
            orig_coin = coin_part
            for k, v in COINDCX_PAIR_ALIASES.items():
                if v == coin_part:
                    orig_coin = k
                    break
            symbol = f"{orig_coin}-USDT"
            
            qty = 0.0
            for k in ['active_units', 'open_position_qty', 'position_qty', 'active_position', 'quantity', 'size', 'current_qty', 'net_quantity', 'open_position']:
                v = p.get(k)
                if v is not None:
                    try:
                        f_val = abs(float(v))
                        if f_val > 0:
                            qty = f_val
                            break
                    except Exception:
                        pass
            
            if qty > 0 and symbol not in ACTIVE_TRADES:
                avg_price = float(p.get('avg_price', p.get('entry_price', p.get('price', 0.0))))
                ACTIVE_TRADES[symbol] = {
                    'entry_price': avg_price if avg_price > 0 else 1.0,
                    'total_qty': qty,
                    'remaining_qty': qty,
                    'tp1': avg_price * 1.032,
                    'sl': avg_price * 0.992,
                    'be_trigger': avg_price * 1.0085,
                    'is_be_active': False,
                    'leverage': 7,
                    'entry_time': time.time()
                }
        save_active_trades()

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
        
        history = {}
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f:
                    history = json.load(f)
            except Exception:
                history = {}
                
        events = history.get(target_date_str, [])
        rows = []
        for idx, e in enumerate(events, 1):
            sym = e.get('symbol', 'UNKNOWN')
            t = e.get('time', '')
            act = e.get('action', '')
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
                if 48 <= rsi_val <= 68: score += 20
                if vol_spike >= 1.20: score += 20
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
# 11. AUTONOMOUS SCANNER & TRADE GENERATION ENGINE
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
            
            # Buy Volume Check: Confirmed Green Candle Volume Spike (Not Panic Dump)
            is_buy_volume = (m15_klines[-1][4] >= m15_klines[-1][1]) or (len(m15_klines) >= 2 and m15_klines[-2][4] >= m15_klines[-2][1])
            is_valid_vol_spike = (vol_spike >= 1.20) and is_buy_volume

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
            dist_low_to_ema20 = abs(last_15m_low - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
            is_pullback_zone = (dist_low_to_ema20 <= 0.008) or (last_15m_low <= ema20_15m * 1.004)
            dist_cmp_to_ema20 = (cmp - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
            is_not_chasing = (-0.012 <= dist_cmp_to_ema20 <= 0.008)

            # CPR Buy Zone: Price holding above BC/Pivot or breaking out above TC
            is_cpr_retest = (last_15m_low <= cpr['tc'] * 1.005) and (cmp >= cpr['bc'] * 0.998)
            is_cpr_breakout = (cmp >= cpr['tc'] * 0.998) and (cmp <= cpr['tc'] * 1.025)
            is_cpr_buy_zone = (is_cpr_retest or is_cpr_breakout or is_pullback_zone) and (is_not_chasing or cmp <= cpr['tc'] * 1.020)

            # 5M Liquidity Sweep & Confirmed Green Closed Candle
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
                
                is_5m_liquidity_sweep_reclaim = (did_sweep_low and did_reclaim and is_5m_bullish_green and is_valid_vol_spike) or (is_5m_bullish_green and is_5m_engulfing and is_valid_vol_spike)
                sweep_low_price = min(k[3] for k in m5_klines[-4:])

            score = 40
            if is_cpr_buy_zone: score += 20
            if is_5m_liquidity_sweep_reclaim: score += 20
            if cmp >= cpr['tc'] * 0.998: score += 10
            if 48 <= rsi_val <= 68: score += 10
            if is_valid_vol_spike: score += 20
            score = max(0, min(100, score))
            
            rating = "A+ (CPR Breakout & Retest) 👑" if score >= 80 else ("A (Solid CPR Bounce) 🥇" if score >= 65 else "B (Moderate)")

            if is_st_green and h1_macro_bullish and is_cpr_buy_zone and is_5m_liquidity_sweep_reclaim and (score >= 80):
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
# 12. TRADE MONITORING, TRAILING STOPS & COINDCX SYNC
# ==============================================================================
def monitor_active_positions():
    while True:
        try:
            with active_trades_lock:
                trade_keys = list(ACTIVE_TRADES.keys())

            for symbol in trade_keys:
                try:
                    with active_trades_lock:
                        trade = ACTIVE_TRADES.get(symbol)
                    if not trade:
                        continue

                    raw_coin = symbol.split('-')[0].upper()
                    clean_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).replace("1000", "")
                    entry_time = trade.get('entry_time', time.time())

                    # Periodic Verification with Live CoinDCX Position State
                    if int(time.time()) % 15 == 0:
                        pos_list = fetch_all_coindcx_live_positions()
                        if pos_list is not None:
                            match = None
                            for p in pos_list:
                                if not isinstance(p, dict): continue
                                p_pair = str(p.get('pair', '')).upper()
                                p_clean = p_pair.replace("B-", "").replace("1000", "").replace("_", "").replace("-", "").replace("USDT", "")
                                if p_clean == clean_coin:
                                    match = p
                                    break
                            
                            is_closed_on_exchange = False
                            if not match:
                                is_closed_on_exchange = True
                            else:
                                for k in ['active_units', 'open_position_qty', 'position_qty', 'active_position', 'quantity', 'size', 'current_qty', 'net_quantity', 'open_position']:
                                    v = match.get(k)
                                    if v is not None:
                                        try:
                                            if abs(float(v)) <= 0:
                                                is_closed_on_exchange = True
                                        except Exception:
                                            pass
                                        break
                                        
                            if is_closed_on_exchange:
                                m1 = fetch_klines(symbol, '1m', 2)
                                exit_cmp = m1[-1][4] if m1 else trade['entry_price']
                                entry_p = trade['entry_price']
                                realized_pnl_pct = ((exit_cmp - entry_p) / entry_p) * 7 * 100 if entry_p > 0 else 0.0
                                pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                                
                                with active_trades_lock:
                                    ACTIVE_TRADES.pop(symbol, None)
                                save_active_trades()
                                
                                if exit_cmp >= trade.get('tp1', entry_p * 1.032) * 0.999:
                                    sl_type = "TAKE PROFIT LIMIT TARGET 🎯"
                                    title, icon = "TAKE PROFIT TARGET HIT 🎯", "💰"
                                elif trade.get('is_profit_locked', False) or realized_pnl_pct > 1.5:
                                    sl_type = f"TRAILING STOP PROFIT LOCK (+{realized_pnl_pct:.1f}% ROE) 💰"
                                    title, icon = "TRAILING PROFIT LOCKED 🚀", "💰"
                                elif trade.get('is_be_active', False) or abs(realized_pnl_pct) <= 1.0:
                                    sl_type = "EXCHANGE BREAKEVEN (FEES COVERED)"
                                    title, icon = "BREAKEVEN EXIT ⚖️", "⚖️"
                                else:
                                    sl_type = f"EXCHANGE SL / CLOSE HIT ({realized_pnl_pct:.1f}% ROE) 🛑"
                                    title, icon = "STOP LOSS TRIGGERED 🛑", "🛑"

                                log_trade_event(symbol, "CLOSED", {"cmp": exit_cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": sl_type})
                                st = load_state()
                                st[symbol] = time.time() + 900
                                save_state(st)
                                
                                send_telegram_message(
                                    f"🏁 <b>POSITION CLOSED: {title}</b>\n\n"
                                    f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                    f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                                    f"• <b>Exit Price:</b> <code>${exit_cmp}</code>\n"
                                    f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE ({pnl_inr:+.2f} INR)</code> {icon}\n"
                                    f"• <b>Trigger:</b> {sl_type}\n"
                                    f"🛡️ <i>30-Min Cooldown Activated (No Re-entry / No Short Trade)</i>"
                                )
                                continue

                    m1_klines = fetch_klines(symbol, '1m', 3)
                    if not m1_klines:
                        continue
                    cmp = m1_klines[-1][4]
                    entry_p = trade['entry_price']
                    live_high = m1_klines[-1][2]
                    highest_peak = max(trade.get('highest_peak', entry_p), live_high, cmp)
                    trade['highest_peak'] = highest_peak
                    
                    # 75-MINUTE STAGNATION AUTO TIME-STOP (Scratch at -1.0% to -2.0% ROE)
                    time_open = time.time() - entry_time
                    if time_open >= 4500 and not trade.get('is_be_active', False):
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            continue

                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                            sl_type = f"75-MIN TIME-STOP SCRATCH ({realized_pnl_pct:+.1f}% ROE) ⏱️"
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": sl_type})
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            send_telegram_message(
                                f"⏱️ <b>POSITION CLOSED: 75-MIN TIME-STOP</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Exit Price:</b> <code>${cmp}</code> (Entry: <code>${entry_p}</code>)\n"
                                f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE</code>\n"
                                f"• <b>Action:</b> Stagnant > 75 mins. Capital released for fresh runners!\n"
                                f"⏱️ <i>30-Min Cooldown Locked</i>"
                            )
                            continue

                    # BREAKEVEN ENGINE: ESCAPE VELOCITY @ +6.0% ROE (+0.85% Move)
                    be_trigger_price = trade.get('be_trigger', entry_p * 1.0085)
                    if highest_peak >= be_trigger_price and not trade.get('is_be_active', False):
                        fee_buffer_sl = round(entry_p * 1.0015, 4)
                        with active_trades_lock:
                            if fee_buffer_sl > trade.get('sl', 0):
                                trade['sl'] = fee_buffer_sl
                            trade['is_be_active'] = True
                        save_active_trades()
                        send_telegram_message(
                            f"🛡️ <b>BREAKEVEN PROFIT LOCK ACTIVATED (+6.0% ROE REACHED)!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>New Stop Loss:</b> <code>${fee_buffer_sl}</code> (Entry + 0.15% Net Profit Floor)\n"
                            f"• <b>Status:</b> 100% Risk-Free (Exchange Fees Covered + Profit Floor Locked)"
                        )

                    # DYNAMIC TRAILING STAGE 2: INTERMEDIATE PROFIT LOCK @ +8.4% ROE (+1.2% Move)
                    if highest_peak >= entry_p * 1.012:
                        intermediate_sl = round(max(entry_p * 1.006, highest_peak * 0.995), 4)
                        if intermediate_sl > trade.get('sl', entry_p):
                            locked_roe = ((intermediate_sl - entry_p) / entry_p) * 7 * 100
                            with active_trades_lock:
                                trade['sl'] = intermediate_sl
                                trade['is_profit_locked'] = True
                            save_active_trades()
                            send_telegram_message(
                                f"🚀 <b>STAGE 2 INTERMEDIATE PROFIT LOCK UPDATED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Peak High:</b> <code>${highest_peak}</code>\n"
                                f"• <b>New Trailing SL:</b> <code>${intermediate_sl}</code>\n"
                                f"• <b>Locked ROE Profit:</b> <code>+{locked_roe:.1f}% ROE</code> 💰"
                            )

                    # DYNAMIC TRAILING STAGE 3: RUNNER ENGINE @ +12.6% ROE (+1.8% Move)
                    if highest_peak >= entry_p * 1.018:
                        trailing_sl = round(highest_peak * 0.988, 4)
                        if trailing_sl > trade.get('sl', entry_p):
                            locked_roe = ((trailing_sl - entry_p) / entry_p) * 7 * 100
                            with active_trades_lock:
                                trade['sl'] = trailing_sl
                                trade['is_profit_locked'] = True
                            save_active_trades()
                            send_telegram_message(
                                f"🔥 <b>STAGE 3 RUNNER TRAILING EXPANSION!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Peak High:</b> <code>${highest_peak}</code>\n"
                                f"• <b>New Trailing SL:</b> <code>${trailing_sl}</code>\n"
                                f"• <b>Locked ROE Profit:</b> <code>+{locked_roe:.1f}% ROE</code> 💰"
                            )

                    # STOP LOSS / TRAILING STOP TRIGGER
                    effective_low = min(cmp, m1_klines[-1][3])
                    if effective_low <= trade['sl']:
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                trade_info = ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            if trade_info:
                                realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100 if entry_p > 0 else 0.0
                                pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                                log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": f"EXCHANGE SL HIT ({realized_pnl_pct:.1f}% ROE) 🛑"})
                                send_telegram_message(
                                    f"🏁 <b>POSITION CLOSED: STOP LOSS HIT 🛑</b>\n\n"
                                    f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                    f"• <b>Exit Price:</b> <code>${cmp}</code> (Entry: <code>${entry_p}</code>)\n"
                                    f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE ({pnl_inr:+.2f} INR)</code> 🛑\n"
                                    f"🛡️ <i>30-Min Cooldown Activated</i>"
                                )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue
                        
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                            sl_type = f"PROFIT LOCK WIN (+{realized_pnl_pct:.1f}% ROE) 💰" if cmp >= entry_p * 1.001 else (f"STOP LOSS HIT ({realized_pnl_pct:.1f}% ROE) 🛑")
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": sl_type})
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            send_telegram_message(
                                f"🏁 <b>POSITION CLOSED: {sl_type}</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"Closed at: <code>${cmp}</code> (Entry: <code>${entry_p}</code>)\n"
                                f"⏱️ <i>30-Min Cooldown Locked</i>"
                            )
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Position monitor exception: {e}")
        time.sleep(1)

# ==============================================================================
# 13. TELEGRAM BOT INTERACTIVE COMMAND LISTENER
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    last_update_id = 0
    while True:
        try:
            if not TOKEN:
                time.sleep(10)
                continue
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=20"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('ok') and data.get('result'):
                    for item in data['result']:
                        last_update_id = item['update_id']
                        msg = item.get('message', {})
                        text = msg.get('text', '').strip()
                        sender_id = str(msg.get('chat', {}).get('id', ''))
                        
                        if CHAT_ID and sender_id != CHAT_ID:
                            continue
                            
                        if text == "/stop":
                            AUTO_TRADING_ENABLED = False
                            send_telegram_message("🛑 <b>AUTO-TRADING PAUSED!</b>\nScanner will detect signals but NO new CoinDCX orders will be placed.\nUse /start to resume.")
                        elif text == "/start":
                            AUTO_TRADING_ENABLED = True
                            send_telegram_message("🟢 <b>AUTO-TRADING RESUMED!</b>\nScanner is actively placing trades on CoinDCX Futures (All 180+ Pairs).")
                        elif text == "/today":
                            summary = generate_daily_summary()
                            send_telegram_message(summary)
                        elif text == "/yesterday":
                            y_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
                            summary = generate_daily_summary(y_str)
                            send_telegram_message(summary)
        except Exception:
            time.sleep(5)
        time.sleep(1)

# ==============================================================================
# 14. BACKGROUND THREADS & APPLICATION STARTUP
# ==============================================================================
def start_background_loop():
    sync_active_trades_from_coindcx()

    def run_loop():
        time.sleep(2)
        while True:
            try:
                run_scan()
            except Exception as e:
                print(f"Scanner exception: {e}")
            time.sleep(20)

    def run_keep_alive_loop():
        time.sleep(10)
        render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://crypto-scanner-ok3t.onrender.com")
        while True:
            try:
                ping_url = f"{render_url}/healthz"
                req = urllib.request.Request(ping_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                    resp.read()
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

    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()
    threading.Thread(target=run_daily_midnight_report_loop, daemon=True).start()

    send_telegram_message(
        "⚡ <b>RENDER BOT EXPANDED SCANNER DEPLOYED!</b>\n\n"
        "• <b>Market Universe:</b> ALL 180+ CoinDCX Futures Pairs (Dynamic Discovery)\n"
        "• <b>24h Liquidity Floor:</b> Min $2,500,000 USDT ($2.5M)\n"
        "• <b>Hard Stop Loss:</b> Author CPR Logic (Below BC / Prev Low, Capped at -0.95% Drop)\n"
        "• <b>Strategy Engine:</b> CPR Breakout & Retest (Pivot, TC, BC, R1-R2)\n"
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
        "• <b>Mobile Commands:</b> /stop, /start, /today, /yesterday"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting production server on port {port}...")
    app.run(host="0.0.0.0", port=port)
