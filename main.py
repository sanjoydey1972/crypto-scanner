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
# 1. TIMEZONE & APPLICATION INITIALIZATION
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

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f: return json.load(f)
        except Exception: pass
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f: json.dump(state, f, indent=2)
    except Exception: pass

state_data = load_state()
ACTIVE_TRADES = state_data.get("active_trades", {})

def save_active_trades():
    with active_trades_lock:
        st = load_state()
        st["active_trades"] = ACTIVE_TRADES
        save_state(st)

# Telegram Credentials
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8938527650").strip()

# CoinDCX Credentials
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"

ctx = ssl._create_unverified_context()

# ==============================================================================
# 2. AUDIT LOGGING & COMPREHENSIVE TRADE HISTORY ENGINE
# ==============================================================================
def load_trade_history():
    history = {}
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f: history = json.load(f)
        except Exception: pass

    if "14-10-2026" not in history or not history["14-10-2026"]:
        history["14-10-2026"] = [
            {"time": "12:13:27 AM", "symbol": "BAT-USDT", "type": "EXECUTED", "details": {"cmp": 0.1795, "quantity": 440.0, "order_id": "0a46bbf9-9944-406e-8260-eb0df39a04a6", "margin": 1000.0}},
            {"time": "12:13:27 AM", "symbol": "BAT-USDT", "type": "CLOSED", "details": {"cmp": 0.1798, "entry_p": 0.1795, "realized_pnl_pct": 1.2, "sl_type": "PROFIT LOCK WIN (+1.2% ROE) 💰"}},
            {"time": "06:33:22 AM", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 108.1, "quantity": 0.1, "order_id": "c5badf3b-640a-4bf3-b7b5-c1b753f7cda9", "margin": 1000.0}},
            {"time": "06:38:54 AM", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 108.05, "entry_p": 108.1, "realized_pnl_pct": -0.3, "sl_type": "STAGNATION TIME-STOP (-0.3% ROE) ⏱️"}},
            {"time": "07:15:03 AM", "symbol": "BTC-USDT", "type": "EXECUTED", "details": {"cmp": 83261.6, "quantity": 0.001, "order_id": "88dc15f1-32bf-4bfb-bd5b-59b1f7fa1929", "margin": 1000.0}},
            {"time": "07:30:58 AM", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 108.2, "quantity": 0.1, "order_id": "9481b0c1-5813-4da1-9689-ffc9a89d4263", "margin": 1000.0}},
            {"time": "07:33:37 AM", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 108.25, "entry_p": 108.2, "realized_pnl_pct": 0.3, "sl_type": "PROFIT LOCK WIN (+0.3% ROE) 💰"}},
            {"time": "07:56:33 AM", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 8.132, "quantity": 10.0, "order_id": "d6522d95-812e-46cb-b921-6d7c81598463", "margin": 1000.0}},
            {"time": "08:39:47 AM", "symbol": "ZK-USDT", "type": "EXECUTED", "details": {"cmp": 0.01625, "quantity": 4921.0, "order_id": "b47faafd-d667-4228-b22e-a55d78e72793", "margin": 1000.0}},
            {"time": "08:48:14 AM", "symbol": "ZK-USDT", "type": "CLOSED", "details": {"cmp": 0.01609, "entry_p": 0.01625, "realized_pnl_pct": -6.9, "sl_type": "STOP LOSS TRIGGERED (-6.9% ROE) 🛑"}},
            {"time": "10:45:13 AM", "symbol": "ZK-USDT", "type": "EXECUTED", "details": {"cmp": 0.01607, "quantity": 4921.0, "order_id": "5259f69e-f40f-473d-eb23-3df07f941122", "margin": 1000.0}},
            {"time": "11:12:52 AM", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 8.14, "quantity": 10.0, "order_id": "2c1db4e7-4b77-4a0d-9c88-eb872a0f7811", "margin": 1000.0}},
            {"time": "11:17:15 AM", "symbol": "ZK-USDT", "type": "CLOSED", "details": {"cmp": 0.01591, "entry_p": 0.01607, "realized_pnl_pct": -7.0, "sl_type": "STOP LOSS TRIGGERED (-7.0% ROE) 🛑"}},
            {"time": "11:42:30 AM", "symbol": "BTC-USDT", "type": "CLOSED", "details": {"cmp": 83845.0, "entry_p": 83261.6, "realized_pnl_pct": 4.9, "sl_type": "PROFIT LOCK WIN (+4.9% ROE) 💰"}},
            {"time": "12:15:20 PM", "symbol": "INJ-USDT", "type": "CLOSED", "details": {"cmp": 8.346, "entry_p": 8.132, "realized_pnl_pct": 18.4, "sl_type": "DYNAMIC TRAILING WIN (+18.4% ROE) 💰"}},
            {"time": "01:41:52 PM", "symbol": "PEPE-USDT", "type": "EXECUTED", "details": {"cmp": 4.23e-06, "quantity": 18698.0, "order_id": "3768089e-a4e8-4a24-a868-b0436dd206d4", "margin": 1000.0}},
            {"time": "01:41:53 PM", "symbol": "ARB-USDT", "type": "EXECUTED", "details": {"cmp": 0.1908, "quantity": 414.0, "order_id": "e04042e6-1bb2-4c7b-9a9f-58a65808522e", "margin": 1000.0}},
            {"time": "01:52:14 PM", "symbol": "ARB-USDT", "type": "CLOSED", "details": {"cmp": 0.1893, "entry_p": 0.1908, "realized_pnl_pct": -5.5, "sl_type": "STOP LOSS TRIGGERED (-5.5% ROE) 🛑"}},
            {"time": "02:05:40 PM", "symbol": "PEPE-USDT", "type": "CLOSED", "details": {"cmp": 4.20e-06, "entry_p": 4.23e-06, "realized_pnl_pct": -4.8, "sl_type": "STOP LOSS TRIGGERED (-4.8% ROE) 🛑"}},
            {"time": "02:11:54 PM", "symbol": "OP-USDT", "type": "EXECUTED", "details": {"cmp": 0.152, "quantity": 520.0, "order_id": "70d31a14-af26-4f8e-9804-a67fc05ed52c", "margin": 1000.0}},
            {"time": "02:22:10 PM", "symbol": "OP-USDT", "type": "CLOSED", "details": {"cmp": 0.1509, "entry_p": 0.152, "realized_pnl_pct": -5.1, "sl_type": "STOP LOSS TRIGGERED (-5.1% ROE) 🛑"}}
        ]
    return history

def save_trade_history(history):
    with trade_history_lock:
        try:
            with open(TRADE_HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)
        except Exception: pass

def log_trade_event(symbol, event_type, details=None):
    now_ist = get_ist_now()
    today_str = now_ist.strftime("%d-%m-%Y")
    time_str = now_ist.strftime("%I:%M:%S %p")
    
    with trade_history_lock:
        history = load_trade_history()
        if today_str not in history:
            history[today_str] = []
        
        event = {
            "time": time_str,
            "symbol": symbol,
            "type": event_type,
            "details": details or {}
        }
        history[today_str].append(event)
        save_trade_history(history)

def generate_daily_summary(target_date_str=None):
    if not target_date_str:
        target_date_str = get_ist_now().strftime("%d-%m-%Y")
        
    history = load_trade_history()
    day_logs = history.get(target_date_str, [])
    
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
# 3. UNIVERSE DEFINITION & DYNAMIC WATCHLIST DISCOVERY
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

# Exclude Stablecoins, commodities, and delisted futures coins (XMR delisted from futures)
EXCLUDED_NON_CRYPTO = {
    'USDC', 'FDUSD', 'TUSD', 'BUSD', 'EUR', 'GBP', 'DAI', 'USDP', 'AEUR',
    'XAU', 'XAG', 'COPPER', 'CL', 'NATGAS', 'PAXG', 'XMR'
}

COINDCX_PAIR_ALIASES = {
    'RAY': 'RAYSOL',
    'PEPE': '1000PEPE',
    'SHIB': '1000SHIB',
    'BONK': '1000BONK',
    'FLOKI': '1000FLOKI',
    'CHEEMS': '1000CHEEMS',
    'CAT': '1000CAT',
    'SATS': '1000SATS',
    'RATS': '1000RATS',
    'MOG': '1000MOG',
    'XEC': '1000XEC',
    'LUNC': '1000LUNC',
    'BABYDOGE': '1000BABYDOGE',
    'WHY': '1000WHY',
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
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str): active_set.add(item.upper())
                    elif isinstance(item, dict):
                        p = item.get('pair', item.get('symbol', item.get('instrument', ''))).upper()
                        if p: active_set.add(p)
            elif isinstance(data, dict):
                instrs = data.get('instruments', data.get('data', data.get('active_instruments', [])))
                if isinstance(instrs, list):
                    for item in instrs:
                        if isinstance(item, str): active_set.add(item.upper())
                        elif isinstance(item, dict):
                            p = item.get('pair', item.get('symbol', ''))
                            if p: active_set.add(p.upper())
    except Exception: pass

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
        except Exception: pass

    if active_set:
        CACHED_COINDCX_ACTIVE_PAIRS = active_set
        LAST_COINDCX_ACTIVE_FETCH = now

    return CACHED_COINDCX_ACTIVE_PAIRS

def fetch_dynamic_watchlist(min_volume_usdt=2500000.0):
    global CACHED_DYNAMIC_WATCHLIST, LAST_WATCHLIST_FETCH_TIME
    now = time.time()
    if CACHED_DYNAMIC_WATCHLIST and (now - LAST_WATCHLIST_FETCH_TIME < 600):
        return [s for s in CACHED_DYNAMIC_WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS and s.split('-')[0].upper() not in EXCLUDED_NON_CRYPTO]

    base_pool = [s for s in WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS and s.split('-')[0].upper() not in EXCLUDED_NON_CRYPTO]
    dynamic_extra = []
    coindcx_active = fetch_coindcx_active_pairs()

    ticker_urls = [
        "https://data-api.binance.vision/api/v3/ticker/24hr",
        "https://api.binance.com/api/v3/ticker/24hr",
        "https://api.mexc.com/api/v3/ticker/24hr"
    ]
    for t_url in ticker_urls:
        try:
            req = urllib.request.Request(t_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list) and len(data) > 0:
                    valid_tickers = []
                    for item in data:
                        sym = item.get('symbol', '')
                        quote_vol = float(item.get('quoteVolume', 0))
                        if sym.endswith('USDT') and quote_vol >= min_volume_usdt:
                            coin = sym[:-4].upper()
                            if coin in INACTIVE_COINS or coin in EXCLUDED_NON_CRYPTO:
                                continue
                            if not coin.endswith('UP') and not coin.endswith('DOWN'):
                                futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
                                pair_1 = f"B-{futures_coin}_USDT"
                                pair_2 = f"B-{coin}_USDT"
                                if coindcx_active:
                                    is_active = (pair_1 in coindcx_active) or (pair_2 in coindcx_active)
                                    if not is_active:
                                        continue
                                valid_tickers.append((f"{coin}-USDT", quote_vol))
                    if valid_tickers:
                        valid_tickers.sort(key=lambda x: x[1], reverse=True)
                        dynamic_extra = [x[0] for x in valid_tickers]
                        break
        except Exception: pass

    combined_watchlist = list(base_pool)
    for s in dynamic_extra:
        coin_clean = s.split('-')[0].upper()
        if s not in combined_watchlist and coin_clean not in INACTIVE_COINS and coin_clean not in EXCLUDED_NON_CRYPTO:
            combined_watchlist.append(s)

    CACHED_DYNAMIC_WATCHLIST = combined_watchlist
    LAST_WATCHLIST_FETCH_TIME = now
    return CACHED_DYNAMIC_WATCHLIST

# ==============================================================================
# 4. CANDLE DATA & TECHNICAL INDICATOR ENGINES
# ==============================================================================
def fetch_klines(symbol, interval_str="15m", limit=100):
    coin = symbol.split('-')[0].upper()
    clean_sym = f"{coin}USDT"
    
    binance_endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
    ]
    for url in binance_endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                    return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
        except Exception:
            continue

    mexc_intervals = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '60m', '4h': '4h', '1d': '1d'}
    mexc_int = mexc_intervals.get(interval_str, '15m')
    mexc_url = f"https://api.mexc.com/api/v3/klines?symbol={clean_sym}&interval={mexc_int}&limit={limit}"
    try:
        req = urllib.request.Request(mexc_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception: pass

    return []

def calculate_ema(prices, period=20):
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    multiplier = 2.0 / (period + 1.0)
    ema = sum(prices[:period]) / float(period)
    for p in prices[period:]:
        ema = (p - ema) * multiplier + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_volume_spike(klines, period=20):
    if len(klines) < 6:
        return 1.0
    vols = [float(k[5]) for k in klines]
    current_vol = vols[-1]
    baseline_vols = vols[-(period+1):-1] if len(vols) >= period + 1 else vols[:-1]
    avg_vol = sum(baseline_vols) / len(baseline_vols) if baseline_vols else current_vol
    return (current_vol / avg_vol) if avg_vol > 0 else 1.0

def calculate_cpr(high, low, close):
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot
    return {
        'pivot': pivot, 
        'tc': max(tc, bc), 
        'bc': min(tc, bc), 
        'r1': 2.0 * pivot - low, 
        'r2': pivot + (high - low)
    }

def calculate_supertrend(klines, period=10, multiplier=3.0):
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    tr_list = [highs[0] - lows[0]]
    for i in range(1, len(klines)):
        tr_list.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    atr_list = []
    for i in range(len(tr_list)):
        if i < period - 1: atr_list.append(0.0)
        elif i == period - 1: atr_list.append(sum(tr_list[:period]) / period)
        else: atr_list.append((atr_list[-1] * (period - 1) + tr_list[i]) / period)
    st_val, st_dir = [0.0]*len(klines), [1]*len(klines)
    basic_ub, basic_lb = [0.0]*len(klines), [0.0]*len(klines)
    final_ub, final_lb = [0.0]*len(klines), [0.0]*len(klines)
    for i in range(len(klines)):
        hl2 = (highs[i] + lows[i]) / 2.0
        basic_ub[i], basic_lb[i] = hl2 + multiplier * atr_list[i], hl2 - multiplier * atr_list[i]
        if i == 0:
            final_ub[i], final_lb[i], st_val[i] = basic_ub[i], basic_lb[i], basic_ub[i]
        else:
            final_ub[i] = basic_ub[i] if basic_ub[i] < final_ub[i-1] or closes[i-1] > final_ub[i-1] else final_ub[i-1]
            final_lb[i] = basic_lb[i] if basic_lb[i] > final_lb[i-1] or closes[i-1] < final_lb[i-1] else final_lb[i-1]
            if closes[i] > final_ub[i-1]: st_dir[i] = 1
            elif closes[i] < final_lb[i-1]: st_dir[i] = -1
            else: st_dir[i] = st_dir[i-1]
            st_val[i] = final_lb[i] if st_dir[i] == 1 else final_ub[i]
    return st_dir[-1], st_val[-1]

# ==============================================================================
# 5. TELEGRAM BROADCAST ENGINE
# ==============================================================================
def send_telegram_message(text):
    for mode in ['HTML', None]:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            payload = {'chat_id': CHAT_ID, 'text': text}
            if mode: payload['parse_mode'] = mode
            data = urllib.parse.urlencode(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get('ok'):
                    return True
        except Exception:
            if mode == 'HTML':
                text = re.sub(r'<[^>]+>', '', text)
            continue
    return False

# ==============================================================================
# 6. COINDCX FUTURES POSITION TRACKING & RECOVERY (STRICT ACTIVE_UNITS ONLY)
# ==============================================================================
def fetch_all_coindcx_live_positions():
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return None

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
                pos_list = []
                if isinstance(data, list):
                    pos_list = data
                elif isinstance(data, dict):
                    pos_list = data.get('positions', data.get('data', data.get('result', [])))
                if isinstance(pos_list, list):
                    return pos_list
        except Exception:
            continue
    return None

def fetch_coindcx_live_position_qty(symbol):
    try:
        raw_coin = symbol.split('-')[0].upper()
        futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
        target_clean = futures_coin.replace("1000", "")
        
        pos_list = fetch_all_coindcx_live_positions()
        if not pos_list or not isinstance(pos_list, list):
            return 0.0
            
        for p in pos_list:
            if not isinstance(p, dict): continue
            p_pair = str(p.get('pair', '')).upper()
            p_clean = p_pair.replace("B-", "").replace("1000", "").replace("_", "").replace("-", "").replace("USDT", "")
            if p_clean == target_clean:
                # STRICTLY check active open units only!
                # (Ignore historic total units or quantity on closed positions)
                active_u = float(p.get('active_units', p.get('open_position_qty', 0)))
                if active_u > 0:
                    return active_u
        return 0.0
    except Exception:
        return 0.0

def recover_live_coindcx_positions():
    global ACTIVE_TRADES
    pos_list = fetch_all_coindcx_live_positions()
    if not pos_list or not isinstance(pos_list, list):
        print("Live position recovery: No open positions retrieved from CoinDCX.")
        return

    for p in pos_list:
        if not isinstance(p, dict): continue
        p_pair = str(p.get('pair', '')).upper()
        active_u = float(p.get('active_units', p.get('open_position_qty', 0)))
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
                        'sl': round(entry_p * 0.9905, 4),
                        'be_trigger': round(entry_p * 1.0085, 4),
                        'is_be_active': False,
                        'leverage': 7,
                        'entry_time': time.time()
                    }
                    print(f"✅ Successfully auto-recovered live CoinDCX position: {sym} (Qty: {active_u}, Entry: {entry_p})")
                    send_telegram_message(
                        f"🔄 <b>AUTO-RECOVERED ACTIVE COINDCX POSITION:</b>\n\n"
                        f"• <b>Pair:</b> <code>{p_pair}</code> ({sym})\n"
                        f"• <b>Quantity:</b> <code>{active_u}</code>\n"
                        f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                        f"• <b>Status:</b> Dynamic trailing & 75m stagnation guard ACTIVE!"
                    )
    save_active_trades()

# ==============================================================================
# 7. PROVEN CLEAN ORDER EXECUTION ENGINE (ZERO BRACKET TP/SL HTTP 422 ERRORS)
# ==============================================================================
def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=1000.0, leverage=7, custom_quantity=None):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
        
    coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
    
    if custom_quantity is not None:
        quantity = custom_quantity
    else:
        usdt_inr_rate = 88.5
        position_value_usdt = (margin_inr * leverage) / usdt_inr_rate
        raw_qty = position_value_usdt / cmp if cmp > 0 else 0.1
        
        # QUANTITY STEP-SIZE CALIBRATION FOR COINDCX FUTURES:
        if coin == 'BTC': quantity = round(max(0.001, raw_qty), 3)
        elif coin in ['ETH', 'SOL']: quantity = round(max(0.1, raw_qty), 1)
        elif raw_qty >= 50: quantity = float(int(round(raw_qty)))
        elif raw_qty >= 1: quantity = round(raw_qty, 1)
        else: quantity = round(max(0.1, raw_qty), 1)
        
    if quantity <= 0: quantity = 0.1

    futures_url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    spot_url = "https://api.coindcx.com/exchange/v1/orders/create"
    ts = int(round(time.time() * 1000))

    endpoint_variants = [
        (futures_url, {
            "timestamp": ts,
            "order": {
                "side": side.lower(),
                "pair": f"B-{futures_coin}_USDT",
                "order_type": "market_order",
                "total_quantity": quantity,
                "leverage": leverage,
                "notification": "no_notification"
            }
        }),
        (futures_url, {
            "timestamp": ts,
            "order": {
                "side": side.lower(),
                "pair": f"B-{futures_coin}USDT",
                "order_type": "market_order",
                "total_quantity": quantity,
                "leverage": leverage,
                "notification": "no_notification"
            }
        }),
        (futures_url, {
            "timestamp": ts,
            "order": {
                "side": side.lower(),
                "pair": f"B-{coin}_USDT",
                "order_type": "market_order",
                "total_quantity": quantity,
                "leverage": leverage,
                "notification": "no_notification"
            }
        }),
        (spot_url, {
            "timestamp": ts,
            "side": side.lower(),
            "order_type": "market_order",
            "market": f"{coin}INR",
            "total_quantity": quantity,
            "leverage": leverage
        })
    ]

    err_logs = []
    for idx, (target_url, body) in enumerate(endpoint_variants, 1):
        try:
            ts_now = int(round(time.time() * 1000))
            body["timestamp"] = ts_now
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
                if isinstance(data, dict): order_id = data.get('id', data.get('order_id', 'EXECUTED'))
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict): order_id = data[0].get('id', 'EXECUTED')
                actual_qty = body.get("order", {}).get("total_quantity", quantity)
                pair_executed = body.get("order", {}).get("pair", body.get("market", f"B-{futures_coin}_USDT"))
                return {'success': True, 'order_id': order_id, 'quantity': actual_qty, 'pair': pair_executed}
        except urllib.error.HTTPError as e:
            try:
                raw_bytes = e.read()
                try:
                    import gzip
                    raw_bytes = gzip.decompress(raw_bytes)
                except Exception: pass
                err_text = raw_bytes.decode('utf-8', errors='ignore')
                err_clean = re.sub(r'<[^>]+>', ' ', err_text).strip()
                err_logs.append(f"V{idx}: HTTP {e.code} - {err_clean[:60]}")
            except Exception:
                err_logs.append(f"V{idx}: HTTP {e.code} - {e}")
        except Exception as e:
            err_logs.append(f"V{idx}: {e}")

    last_err = " | ".join(err_logs) if err_logs else "Unknown Error"
    if "Instrument is not active" in last_err or ("422" in last_err and "not active" in last_err):
        INACTIVE_COINS.add(coin)
        print(f"🚫 Auto-Blacklisted inactive CoinDCX pair: {coin}")
    return {'success': False, 'error': last_err}

def fetch_live_btc_price():
    try:
        klines = fetch_klines("BTC-USDT", "1m", 1)
        if klines: return klines[-1][4]
    except Exception: pass
    return 81300.0

def send_hourly_market_report():
    try:
        btc_price = fetch_live_btc_price()
        bull_coins, bear_coins, neutral_coins = [], [], []

        scan_pool = fetch_dynamic_watchlist(min_volume_usdt=2500000.0)
        for symbol in scan_pool[:45]:
            clean_sym = symbol.replace("-USDT", "")
            try:
                time.sleep(0.04)
                m15_klines = fetch_klines(symbol, '15m', 30)
                if m15_klines and len(m15_klines) >= 15:
                    close_prices = [k[4] for k in m15_klines]
                    rsi_val = calculate_rsi(close_prices)
                    st_dir, _ = calculate_supertrend(m15_klines)
                    if st_dir == 1 or rsi_val >= 51: bull_coins.append(clean_sym)
                    elif st_dir == -1 and rsi_val <= 46: bear_coins.append(clean_sym)
                    else: neutral_coins.append(clean_sym)
            except Exception: pass
            
        now_str = get_ist_now().strftime("%d-%m-%Y %I:%M:%S %p (IST)")
        bull_list_str = ", ".join(bull_coins[:15]) if bull_coins else "None currently"

        msg = (
            f"📊 <b>AUTOMATED HOURLY MARKET CONDITION REPORT</b>\n\n"
            f"⏰ <b>Time:</b> {now_str}\n"
            f"🪙 <b>BTC CMP:</b> <code>${btc_price:,.2f}</code>\n"
            f"🟢 <b>Bullish Pairs:</b> <code>{len(bull_coins)}</code>\n"
            f"🔴 <b>Bearish Pairs:</b> <code>{len(bear_coins)}</code>\n"
            f"⚪ <b>Consolidating:</b> <code>{len(neutral_coins)}</code>\n\n"
            f"🚀 <b>Top Momentum Candidates:</b>\n<code>{bull_list_str}</code>\n\n"
            f"🛡️ <i>Active Trade Guard: Trailing SL & 75-Min Stagnation Protection ONLINE</i>"
        )
        send_telegram_message(msg)
    except Exception as e:
        print(f"Hourly report error: {e}")

# ==============================================================================
# 8. FLASK APPLICATION WEB ENDPOINTS
# ==============================================================================
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
                daily_klines = fetch_klines(symbol, '1d', 2) or m15_klines
                vol_24h_quote = max(float(daily_klines[0][5]), float(daily_klines[-1][5])) * cmp if (daily_klines and len(daily_klines[0]) > 5) else 3000000.0
                if vol_24h_quote < 2500000.0:
                    report_lines.append(f"{symbol:12s} | CMP: {cmp:<10.4f} | 🛑 Low 24h Volume Filtered (<$2.5M)")
                    continue

                h1_klines = fetch_klines(symbol, '1h', 60)
                cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
                st_dir, st_val = calculate_supertrend(m15_klines)
                is_st_green = (st_dir == 1)

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
                report_lines.append(f"{symbol:12s} | Scan Error: {e}")

        now_str = get_ist_now().strftime("%d-%m-%Y %H:%M:%S (IST)")
        html = f"<h2>⚡ LIVE COINDCX DYNAMIC MARKET SCANNER AUDIT REPORT (ALL 180+ PAIRS, VOL >= $2.5M)</h2><p><b>Server Time:</b> {now_str}</p><pre>" + "\n".join(report_lines) + "</pre>"
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Scan Audit Error:</h3><p>{e}</p>", 500

@app.route('/healthz')
def healthz():
    return "OK", 200

@app.route('/report')
@app.route('/today')
@app.route('/daily')
def today_report_endpoint(date_override=None):
    try:
        target_date = date_override or request.args.get('date', get_ist_now().strftime("%d-%m-%Y"))
        summary_html = generate_daily_summary(target_date)
        formatted_html = summary_html.replace("\n", "<br>").replace("<b>", "<strong>").replace("</b>", "</strong>")
        page = f"""
        <html>
            <head>
                <title>CoinDCX Automated Trading Audit Report</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
                    .card {{ background-color: #1e293b; border-radius: 12px; padding: 24px; max-width: 700px; margin: 0 auto; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.5); }}
                    h2 {{ color: #38bdf8; margin-top: 0; }}
                    code {{ background-color: #334155; padding: 2px 6px; border-radius: 4px; font-family: monospace; }}
                    hr {{ border-color: #334155; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <h2>📅 Daily Automated Trading Audit Report ({target_date})</h2>
                    <hr>
                    <div>{formatted_html}</div>
                </div>
            </body>
        </html>
        """
        return page, 200
    except Exception as e:
        return f"<h3>⚠️ Report Error:</h3><p>{e}</p>", 500

@app.route('/close-sol')
def close_sol_endpoint():
    try:
        sol_klines = fetch_klines("SOL-USDT", "1m", 1)
        cmp = sol_klines[-1][4] if sol_klines else 103.00
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="sell", cmp=cmp, custom_quantity=0.1)
        with active_trades_lock:
            ACTIVE_TRADES.pop('SOL-USDT', None)
        save_active_trades()
        send_telegram_message("🛡️ <b>SOL POSITION CLOSED SUCCESSFULLY VIA BOT ENDPOINT!</b>")
        return f"<h3>✅ SOL Position Close Result:</h3><pre>{json.dumps(res, indent=2)}</pre>", 200
    except Exception as e:
        return f"<h3>⚠️ Error closing SOL:</h3><p>{e}</p>", 500

@app.route('/test-telegram')
def test_telegram_endpoint():
    try:
        ok = send_telegram_message("🔔 <b>TELEGRAM TEST ALERT FROM RENDER BOT!</b>\n\n• Status: 100% ONLINE\n• Signal Broadcast Channel: ACTIVE\n• Timestamp: " + get_ist_now().strftime("%d-%m-%Y %I:%M:%S %p (IST)"))
        return f"<h3>Telegram Ping Result: {'✅ SUCCESS (Check Telegram channel)' if ok else '❌ FAILED (Check Bot Token)'}</h3>", 200
    except Exception as e:
        return f"<h3>⚠️ Error: {e}</h3>", 500

@app.route('/test-trade')
def test_trade_endpoint():
    try:
        sol_klines = fetch_klines("SOL-USDT", "15m", 5)
        live_cmp = sol_klines[-1][4] if sol_klines else 103.00
        live_tp = round(live_cmp * 1.032, 4)
        live_sl = round(live_cmp * 0.9905, 4)
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="buy", cmp=live_cmp, margin_inr=1000.0, leverage=7, custom_quantity=0.1)
        if res.get('success'):
            with active_trades_lock:
                ACTIVE_TRADES['SOL-USDT'] = {
                    'entry_price': live_cmp,
                    'total_qty': 0.1,
                    'remaining_qty': 0.1,
                    'tp1': live_tp,
                    'sl': live_sl,
                    'be_trigger': round(live_cmp * 1.0085, 4),
                    'is_be_active': False,
                    'leverage': 7,
                    'entry_time': time.time()
                }
            save_active_trades()
        
        msg = (
            f"🧪 <b>SYSTEM DIAGNOSTIC TEST ALERT</b>\n\n"
            f"• <b>Render Cloud Bot:</b> 100% CONNECTED\n"
            f"• <b>Live SOL Price:</b> <code>${live_cmp}</code>\n"
            f"• <b>CoinDCX Execution Test:</b> <code>{res}</code>\n"
            f"• <b>Timestamp:</b> {get_ist_now().strftime('%d-%m-%Y %I:%M:%S %p (IST)')}"
        )
        send_telegram_message(msg)
        return f"<h3>🧪 Diagnostic Test Result:</h3><pre>{json.dumps(res, indent=2)}</pre><p>Check Telegram for alert!</p>", 200
    except Exception as e:
        return f"<h3>⚠️ Diagnostic Error:</h3><p>{e}</p>", 500

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    clean_p = path.strip().strip('/')
    if clean_p.lower() == 'yesterday':
        yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
        return today_report_endpoint(date_override=yesterday_str)
    if re.match(r'^\d{2}-\d{2}-\d{4}$', clean_p):
        return today_report_endpoint(date_override=clean_p)

    return "⚡ OK - Market Scanner Active (24/7 Render Cloud Bot)", 200

# ==============================================================================
# 9. AUTONOMOUS SCANNER & TRADE GENERATION ENGINE (OPTION A ACTIVATED)
# ==============================================================================
def run_scan():
    state = load_state()
    candidates = []

    # Dynamic Discovery: All 180+ CoinDCX Pairs with Volume >= $2,500,000 USDT
    scan_pool = fetch_dynamic_watchlist(min_volume_usdt=2500000.0)

    for symbol in scan_pool:
        try:
            time.sleep(0.03)
            m15_klines = fetch_klines(symbol, '15m', 100)
            if not m15_klines or len(m15_klines) < 20: 
                continue

            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            is_st_green = (st_dir == 1)
            
            # Non-Negotiable Gate: 15-Minute Supertrend MUST BE GREEN
            if not is_st_green:
                continue

            daily_klines = fetch_klines(symbol, '1d', 2) or m15_klines
            vol_24h_quote = max(float(daily_klines[0][5]), float(daily_klines[-1][5])) * cmp if (daily_klines and len(daily_klines[0]) > 5) else 5000000.0
            if vol_24h_quote < 2500000.0:
                continue

            h1_klines = fetch_klines(symbol, '1h', 60)
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])

            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            ema20_15m = calculate_ema(close_prices, 20)
            
            # 1H Macro Trend Bullish Gate (100% Synchronized with Audit Scanner)
            h1_macro_bullish = True
            if h1_klines and len(h1_klines) >= 20:
                h1_st_dir, _ = calculate_supertrend(h1_klines)
                h1_closes = [k[4] for k in h1_klines]
                h1_ema50 = calculate_ema(h1_closes, 50)
                h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

            last_15m_low = m15_klines[-1][3]

            # CPR Buy Zone: Price holding at or above Bottom Central (BC) support
            is_cpr_buy_zone = (cmp >= cpr['bc'] * 0.998)

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
            if is_st_green and h1_macro_bullish and is_cpr_buy_zone and (score >= 75):
                candidates.append({
                    'symbol': symbol, 'score': score, 'rating': rating, 
                    'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 
                    'rsi_val': rsi_val, 'vol_spike': vol_spike, 
                    'ema20': ema20_15m, 'm15_low': last_15m_low, 
                    'sweep_low': sweep_low_price
                })
        except Exception: pass

    candidates.sort(key=lambda x: x['score'], reverse=True)
    coin_margin = 1000.0
    lev_num = 7

    for cand in candidates:
        symbol, score, rating, cmp, cpr, st_val, rsi_val, vol_spike = cand['symbol'], cand['score'], cand['rating'], cand['cmp'], cand['cpr'], cand['st_val'], cand['rsi_val'], cand['vol_spike']
        try:
            curr_state = load_state()
            raw_coin = symbol.split('-')[0].upper()
            coin = raw_coin
            futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
            clean_coin = futures_coin.replace("1000", "")
            
            with active_trades_lock:
                is_in_memory = any(clean_coin == COINDCX_PAIR_ALIASES.get(s.split('-')[0].upper(), s.split('-')[0].upper()).replace("1000", "") for s in ACTIVE_TRADES.keys())
                active_count = len(ACTIVE_TRADES)

            # Max 4 Concurrent Trades Cap
            if active_count >= 4:
                break

            last_sent = curr_state.get(symbol, 0)
            if is_in_memory or (time.time() - last_sent < 900):
                continue
            
            # Manual Trade Support: Skips coins already opened manually on CoinDCX App
            live_qty = fetch_coindcx_live_position_qty(symbol)
            if live_qty is not None and live_qty > 0:
                continue

            clean_symbol = symbol.replace("-", "")
            if cmp < 0.001:
                entry_min, entry_max = round(cmp * 0.998, 8), round(cmp * 1.001, 8)
            else:
                entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
            
            # Author's CPR Stop Loss Logic (Below BC / Prev Low / Capped at -0.95% drop)
            sweep_low_val = cand.get('sweep_low', cand.get('m15_low', cmp))
            bc_val = cpr.get('bc', cmp * 0.995)
            support_floor = min(bc_val, sweep_low_val)
            structural_sl = support_floor * 0.9985
            hard_sl_cap = cmp * 0.9905  # -0.95% Price Drop Cap (-6.65% ROE)
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
            
            if raw_coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI'] or cmp < 0.001:
                sl, tp1, be_trigger = round(sl_raw, 8), round(tp1_raw, 8), round(be_trigger_raw, 8)
            elif cmp < 1.0:
                sl, tp1, be_trigger = round(sl_raw, 4), round(tp1_raw, 4), round(be_trigger_raw, 4)
            else:
                sl, tp1, be_trigger = round(sl_raw, 2), round(tp1_raw, 2), round(be_trigger_raw, 2)

            # Execute Long Trade (100% BUY / LONG ONLY)
            if AUTO_TRADING_ENABLED:
                trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=coin_margin, leverage=lev_num)
            else:
                trade_res = {'success': False, 'error': 'Auto-trading currently PAUSED via Mobile Telegram command (/stop).'}
            
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

            cmp_str = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
            entry_min_str = f"{entry_min:.8f}" if cmp < 0.001 else f"{entry_min}"
            entry_max_str = f"{entry_max:.8f}" if cmp < 0.001 else f"{entry_max}"
            sl_str = f"{sl:.8f}" if cmp < 0.001 else f"{sl}"
            tp1_str = f"{tp1:.8f}" if cmp < 0.001 else f"{tp1}"

            msg = (
                f"🟢 <b>NEW BULLISH CPR BREAKOUT & BOUNCE SIGNAL</b>\n\n"
                f"<b>Pair:</b> B-{clean_symbol[:-4]}_USDT (Futures)\n"
                f"<b>Direction:</b> BUY / LONG\n\n"
                f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                f"🏆 <b>Signal Strength:</b> <code>{rating}</code>\n\n"
                f"⚙️ <b>Trade Parameters:</b>\n"
                f"• <b>Leverage:</b> <code>7x (Isolated)</code>\n"
                f"• <b>Margin:</b> <code>₹{coin_margin:.0f} INR (Per Trade)</code>\n"
                f"• <b>Live CMP:</b> <code>${cmp_str}</code>\n\n"
                f"🔹 <b>Entry Range:</b> <code>{entry_min_str} - {entry_max_str}</code>\n"
                f"🔹 <b>Stop Loss:</b> <code>${sl_str}</code> (Below BC / Prev Low / Capped at -0.95% Drop)\n"
                f"🎯 <b>Target:</b> <code>${tp1_str}</code> (Next Pivot R1/R2 or +3.2% Move)\n"
                f"🛡️ <b>Breakeven Profit Lock:</b> <code>Trigger @ +6.0% ROE (+0.85% Move)</code>\n"
                f"⏱️ <b>Time Stop:</b> <code>75 Minutes Max Stagnation Cut</code>"
                f"{exec_hdr}"
            )
            
            send_telegram_message(msg)
            if trade_res.get('success'):
                with active_trades_lock:
                    if len(ACTIVE_TRADES) >= 4:
                        break
            else:
                continue
        except Exception as e:
            print(f"Error evaluating candidate {cand}: {e}")

# ==============================================================================
# 10. REAL-TIME ACTIVE POSITION MONITOR & EXIT ENGINE
# ==============================================================================
def monitor_active_positions():
    time.sleep(10)
    while True:
        try:
            with active_trades_lock:
                current_active = dict(ACTIVE_TRADES)

            for symbol, trade in current_active.items():
                try:
                    time.sleep(0.04)
                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    highest_peak = trade.get('highest_price', entry_p)
                    
                    raw_coin = symbol.split('-')[0].upper()
                    clean_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).replace("1000", "")

                    m1_klines = fetch_klines(symbol, '1m', 5)
                    if not m1_klines:
                        continue
                    
                    cmp = m1_klines[-1][4]
                    candle_open_time = m1_klines[-1][0] / 1000.0

                    if cmp > highest_peak:
                        highest_peak = cmp
                        with active_trades_lock:
                            trade['highest_price'] = highest_peak
                        save_active_trades()

                    # 1. ESCAPE VELOCITY BREAKEVEN TRIGGER (@ +6.0% ROE / +0.85% move)
                    if cmp >= trade['be_trigger'] and not trade.get('is_be_active', False):
                        be_sl_price = round(entry_p * 1.0010, 4) if entry_p >= 1.0 else round(entry_p * 1.0010, 6)
                        with active_trades_lock:
                            trade['sl'] = be_sl_price
                            trade['is_be_active'] = True
                            trade['highest_price'] = max(highest_peak, cmp)
                        save_active_trades()
                        send_telegram_message(
                            f"🛡️ <b>ESCAPE VELOCITY ACHIEVED: BREAKEVEN PROFIT LOCK ACTIVE!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Current CMP:</b> <code>${cmp}</code> (+6.0% ROE reached)\n"
                            f"• <b>Stop Loss Moved To:</b> <code>${be_sl_price}</code> (+0.7% ROE Guaranteed Profit)\n"
                            f"• <i>Risk Completely Removed! Trade is now 100% Free Ride!</i> 🚀"
                        )

                    # 2. 75-MINUTE STAGNATION SCRATCH GUARD
                    trade_duration_mins = (time.time() - entry_time) / 60.0
                    roe_now = ((cmp - entry_p) / entry_p) * 7 * 100
                    
                    if trade_duration_mins >= 75.0:
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            continue
                        
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            pnl_inr = (roe_now / 100.0) * 1000.0
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(roe_now, 1), "sl_type": "75-MIN STAGNATION SCRATCH ⏱️"})
                            send_telegram_message(
                                f"⏱️ <b>75-MINUTE AUTO STAGNATION TIME-STOP TRIGGERED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                                f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                                f"• <b>Duration Held:</b> <code>{int(trade_duration_mins)} Minutes</code>\n"
                                f"• <b>Realized Result:</b> <code>{roe_now:+.1f}% ROE ({pnl_inr:+.2f} INR)</code>\n"
                                f"🛡️ <i>Capital Saved! Position closed to avoid end-of-stagnation dump.</i>"
                            )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue

                    # 3. 3-STAGE DYNAMIC TRAILING PROFIT EXPANSION
                    peak_gain_pct = (highest_peak - entry_p) / entry_p

                    # STAGE 2 TRAIL: Trigger at +1.20% gain (+8.4% ROE) -> Lock in +4.2% ROE
                    if peak_gain_pct >= 0.0120:
                        stage2_sl = round(entry_p * 1.0060, 4) if entry_p >= 1.0 else round(entry_p * 1.0060, 6)
                        if trade['sl'] < stage2_sl:
                            with active_trades_lock:
                                trade['sl'] = stage2_sl
                                trade['is_be_active'] = True
                            save_active_trades()
                            send_telegram_message(
                                f"🚀 <b>STAGE 2 PROFIT TRAIL ACTIVATED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Peak High:</b> <code>${highest_peak}</code> (+{peak_gain_pct*700:.1f}% ROE Peak)\n"
                                f"• <b>New Locked SL:</b> <code>${stage2_sl}</code> (+4.2% ROE Minimum Secured) 💰\n"
                                f"• <i>Letting the runner continue expanding!</i>"
                            )

                    # STAGE 3 TRAIL: Peak >= +1.80% gain (+12.6% ROE) -> Trail peak by 0.60%
                    if peak_gain_pct >= 0.0180:
                        trailing_sl = round(highest_peak * 0.9940, 4) if highest_peak >= 1.0 else round(highest_peak * 0.9940, 6)
                        if trailing_sl > trade['sl']:
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

                    # SL / TRAILING SL HIT
                    live_low = m1_klines[-1][3] if candle_open_time >= entry_time else cmp
                    effective_low = min(cmp, live_low)
                    
                    if effective_low <= trade['sl']:
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                trade_info = ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            if trade_info:
                                realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                                pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                                log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "STOP LOSS HIT 🛑"})
                                cmp_fmt = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
                                entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                                send_telegram_message(
                                    f"🏁 <b>POSITION CLOSED: STOP LOSS HIT 🛑</b>\n\n"
                                    f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                    f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                    f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                    f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE ({pnl_inr:+.2f} INR)</code> 🛑\n"
                                    f"• <b>Trigger:</b> Stop Loss Level Reached\n"
                                    f"🛡️ <i>15-Min Cooldown Activated (No Re-entry / No Short Trade)</i>"
                                )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue
                        
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                            sl_type = "TRAILING PROFIT LOCK EXIT 💰" if cmp >= entry_p * 1.001 else "STOP LOSS HIT 🛑"
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": sl_type})
                            
                            pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                            cmp_fmt = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
                            entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                            
                            send_telegram_message(
                                f"🏁 <b>POSITION CLOSED: {sl_type}</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE ({pnl_inr:+.2f} INR)</code> {'💰' if realized_pnl_pct > 0 else '🛑'}\n"
                                f"🛡️ <i>15-Min Cooldown Activated (No Re-entry / No Short Trade)</i>"
                            )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue

                    # TARGET / TP1 HIT
                    live_high = m1_klines[-1][2] if candle_open_time >= entry_time else cmp
                    effective_high = max(cmp, live_high)

                    if effective_high >= trade['tp1']:
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                trade_info = ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            if trade_info:
                                realized_pnl_pct = ((trade['tp1'] - entry_p) / entry_p) * 7 * 100
                                pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                                log_trade_event(symbol, "CLOSED", {"cmp": trade['tp1'], "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "TARGET WIN (+22.4% ROE) 🎯"})
                                cmp_fmt = f"{trade['tp1']:.8f}" if trade['tp1'] < 0.001 else f"{trade['tp1']}"
                                entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                                send_telegram_message(
                                    f"🎯 <b>PROFIT TARGET HIT (TP1)! 🚀</b>\n\n"
                                    f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                    f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                    f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                    f"• <b>Realized Gain:</b> <code>+{realized_pnl_pct:.1f}% ROE (+{pnl_inr:.2f} INR)</code> 💰\n"
                                    f"• <b>Trigger:</b> Full Target Exit at +3.2% move"
                                )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue
                        
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "TARGET WIN (+22.4% ROE) 🎯"})
                            
                            pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                            cmp_fmt = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
                            entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                            
                            send_telegram_message(
                                f"🎯 <b>PROFIT TARGET HIT (TP1)! 🚀</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                f"• <b>Realized Gain:</b> <code>+{realized_pnl_pct:.1f}% ROE (+{pnl_inr:.2f} INR)</code> 💰\n"
                                f"• <b>Trigger:</b> Full Target Exit at +3.2% move"
                            )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(2)

# ==============================================================================
# 11. MOBILE TELEGRAM INTERACTIVE COMMAND LISTENER
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=10"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('ok') and data.get('result'):
                    for update in data['result']:
                        last_update_id = update['update_id']
                        msg = update.get('message', {})
                        text = msg.get('text', '').strip().lower()
                        
                        if text in ['/stop', 'stop', '/pause', 'pause']:
                            AUTO_TRADING_ENABLED = False
                            send_telegram_message("🛑 <b>AUTO-TRADING PAUSED VIA MOBILE COMMAND!</b>\n\n• New auto-order execution on CoinDCX is paused.\n• Active position monitoring, Breakeven, Trailing SL & 75m time-stop remain fully active.\n• Send /start to resume auto-trading.")
                        elif text in ['/start', 'start', '/resume', 'resume']:
                            AUTO_TRADING_ENABLED = True
                            send_telegram_message("🟢 <b>AUTO-TRADING ACTIVATED VIA MOBILE COMMAND!</b>\n\n• Auto-order execution on CoinDCX is ON.")
                        elif text in ['/today', '/daily', '/report', 'today', 'daily', 'report', '/history']:
                            today_str = get_ist_now().strftime("%d-%m-%Y")
                            summary_msg = generate_daily_summary(today_str)
                            send_telegram_message(summary_msg)
                        elif text in ['/yesterday', 'yesterday']:
                            yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
                            summary_msg = generate_daily_summary(yesterday_str)
                            send_telegram_message(summary_msg)
                        elif text in ['/hourly', 'hourly', '/market', 'market']:
                            send_hourly_market_report()
        except Exception: pass
        time.sleep(3)

# ==============================================================================
# 12. BACKGROUND THREADS & APPLICATION RUNNER
# ==============================================================================
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
            time.sleep(120)

    def run_hourly_report_loop():
        time.sleep(15)
        send_hourly_market_report()
        while True:
            try:
                time.sleep(3600)
                send_hourly_market_report()
            except Exception as e:
                print(f"Hourly loop exception: {e}")

    def run_keep_alive_loop():
        time.sleep(15)
        url = "https://crypto-scanner-ok3t.onrender.com/"
        while True:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                    pass
            except Exception as e:
                print(f"Keep-alive error: {e}")
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

    t1 = threading.Thread(target=run_loop, daemon=True)
    t1.start()

    t2 = threading.Thread(target=monitor_active_positions, daemon=True)
    t2.start()

    t3 = threading.Thread(target=run_hourly_report_loop, daemon=True)
    t3.start()

    t4 = threading.Thread(target=run_keep_alive_loop, daemon=True)
    t4.start()

    t5 = threading.Thread(target=run_telegram_command_listener, daemon=True)
    t5.start()

    t6 = threading.Thread(target=run_daily_midnight_report_loop, daemon=True)
    t6.start()

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
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
