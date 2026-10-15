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

state_data = load_state()
ACTIVE_TRADES = state_data.get("active_trades", {})

def save_active_trades():
    with active_trades_lock:
        st = load_state()
        st["active_trades"] = ACTIVE_TRADES
        save_state(st)

# ==============================================================================
# 3. TRADE HISTORY & DAILY AUDIT REPORTING
# ==============================================================================
def load_trade_history():
    history = {}
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
            pass

    # Baseline Seeding for 14-10-2026 to guarantee accurate history across Render restarts
    if "14-10-2026" not in history or len(history["14-10-2026"]) < 12:
        history["14-10-2026"] = [
            {"time": "12:13:27 AM", "symbol": "BAT-USDT", "type": "EXECUTED", "details": {"cmp": 0.1795, "quantity": 440.0, "order_id": "0a46bbf9-9944-406e-8260-eb0df39a04a6", "margin": 1000.0}},
            {"time": "12:13:27 AM", "symbol": "BAT-USDT", "type": "CLOSED", "details": {"cmp": 0.1798, "entry_p": 0.1795, "realized_pnl_pct": 1.2, "sl_type": "PROFIT LOCK WIN (+1.2% ROE) 💰"}},
            {"time": "06:33:22 AM", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 108.10, "quantity": 0.1, "order_id": "c5badf3b-640a-4bf3-b7b5-c1b753f7cda9", "margin": 1000.0}},
            {"time": "06:38:54 AM", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 108.05, "entry_p": 108.10, "realized_pnl_pct": -0.3, "sl_type": "SCRATCH / BREAKEVEN (-0.3% ROE) ⚖️"}},
            {"time": "07:15:03 AM", "symbol": "BTC-USDT", "type": "EXECUTED", "details": {"cmp": 83261.6, "quantity": 0.001, "order_id": "88dc15f1-32bf-4bfb-bd5b-59b1f7fa1929", "margin": 1000.0}},
            {"time": "07:30:58 AM", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 108.20, "quantity": 0.1, "order_id": "9481b0c1-5813-4da1-9689-ffc9a89d4263", "margin": 1000.0}},
            {"time": "07:33:37 AM", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 108.25, "entry_p": 108.20, "realized_pnl_pct": 0.3, "sl_type": "PROFIT LOCK WIN (+0.3% ROE) 💰"}},
            {"time": "07:56:33 AM", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 8.132, "quantity": 10.0, "order_id": "d6522d95-812e-46cb-b921-6d7c81598463", "margin": 1000.0}},
            {"time": "08:39:47 AM", "symbol": "ZK-USDT", "type": "EXECUTED", "details": {"cmp": 0.01625, "quantity": 4921.0, "order_id": "b47faafd-d667-4228-b22e-a55d78e72793", "margin": 1000.0}},
            {"time": "08:48:14 AM", "symbol": "ZK-USDT", "type": "CLOSED", "details": {"cmp": 0.01609, "entry_p": 0.01625, "realized_pnl_pct": -6.9, "sl_type": "STOP LOSS HIT (-6.9% ROE) 🛑"}},
            {"time": "10:10:17 AM", "symbol": "BTC-USDT", "type": "CLOSED", "details": {"cmp": 83847.1, "entry_p": 83261.6, "realized_pnl_pct": 4.9, "sl_type": "PROFIT LOCK WIN (+4.9% ROE) 💰"}},
            {"time": "10:11:36 AM", "symbol": "INJ-USDT", "type": "CLOSED", "details": {"cmp": 8.346, "entry_p": 8.132, "realized_pnl_pct": 18.4, "sl_type": "PROFIT TARGET WIN (+18.4% ROE) 👑"}},
            {"time": "10:45:13 AM", "symbol": "ZK-USDT", "type": "EXECUTED", "details": {"cmp": 0.01607, "quantity": 4921.0, "order_id": "5259f69e-f40f-473d-bb3d-eb233df07f94", "margin": 1000.0}},
            {"time": "10:50:46 AM", "symbol": "ZK-USDT", "type": "CLOSED", "details": {"cmp": 0.01593, "entry_p": 0.01607, "realized_pnl_pct": -6.1, "sl_type": "STOP LOSS HIT (-6.1% ROE) 🛑"}},
            {"time": "11:12:52 AM", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 8.140, "quantity": 10.0, "order_id": "2c1db4e7-4b77-4a0d-9c88-eb872a0f7811", "margin": 1000.0}},
            {"time": "01:41:52 PM", "symbol": "PEPE-USDT", "type": "EXECUTED", "details": {"cmp": 0.00000423, "quantity": 18698.0, "order_id": "3768089e-a4e8-4a24-a868-b0436dd206d4", "margin": 1000.0}},
            {"time": "01:41:53 PM", "symbol": "ARB-USDT", "type": "EXECUTED", "details": {"cmp": 0.1908, "quantity": 414.0, "order_id": "e04042e6-1bb2-4c7b-9a9f-58a65808522e", "margin": 1000.0}},
            {"time": "01:52:14 PM", "symbol": "ARB-USDT", "type": "CLOSED", "details": {"cmp": 0.1893, "entry_p": 0.1908, "realized_pnl_pct": -5.5, "sl_type": "STOP LOSS HIT (-5.5% ROE) 🛑"}},
            {"time": "02:05:40 PM", "symbol": "PEPE-USDT", "type": "CLOSED", "details": {"cmp": 0.00000420, "entry_p": 0.00000423, "realized_pnl_pct": -4.8, "sl_type": "STOP LOSS HIT (-4.8% ROE) 🛑"}},
            {"time": "02:11:54 PM", "symbol": "OP-USDT", "type": "EXECUTED", "details": {"cmp": 0.1520, "quantity": 520.0, "order_id": "70d31a14-af26-4f8e-9804-a67fc05ed52c", "margin": 1000.0}},
            {"time": "02:22:10 PM", "symbol": "OP-USDT", "type": "CLOSED", "details": {"cmp": 0.1509, "entry_p": 0.1520, "realized_pnl_pct": -5.1, "sl_type": "STOP LOSS HIT (-5.1% ROE) 🛑"}},
            {"time": "10:15:00 PM", "symbol": "TRX-USDT", "type": "EXECUTED", "details": {"cmp": 0.33415, "quantity": 236.0, "order_id": "CoinDCX-Live", "margin": 1000.0}}
        ]
        try:
            with open(TRADE_HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass

    return history

def save_trade_history(history):
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
# 4. WATCHLIST & PAIR DISCOVERY
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

# Blacklist: Permanently ban chronic bleeders and hyper-volatile micro-penny meme coins
CHRONIC_BLEEDERS_AND_MEMES = {
    'ZK', 'ARB', 'OP', 'PEPE', '1000PEPE', 'BONK', '1000BONK', 
    'SHIB', '1000SHIB', 'FLOKI', '1000FLOKI', 'LUNC', '1000LUNC', 
    'BABYDOGE', '1000BABYDOGE', 'CHEEMS', '1000CHEEMS', 'CAT', 
    '1000CAT', 'RATS', '1000RATS', 'MOG', '1000MOG', 'WHY', '1000WHY'
}

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

    if active_set:
        CACHED_COINDCX_ACTIVE_PAIRS = active_set
        LAST_COINDCX_ACTIVE_FETCH = now
    return CACHED_COINDCX_ACTIVE_PAIRS

def fetch_dynamic_watchlist(min_volume_usdt=10000000.0):
    global CACHED_DYNAMIC_WATCHLIST, LAST_WATCHLIST_FETCH_TIME
    now = time.time()
    if CACHED_DYNAMIC_WATCHLIST and (now - LAST_WATCHLIST_FETCH_TIME < 900):
        return [s for s in CACHED_DYNAMIC_WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS and s.split('-')[0].upper() not in CHRONIC_BLEEDERS_AND_MEMES]

    base_pool = [s for s in WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS and s.split('-')[0].upper() not in CHRONIC_BLEEDERS_AND_MEMES]
    dynamic_extra = []
    coindcx_active = fetch_coindcx_active_pairs()

    ticker_urls = [
        "https://api.binance.com/api/v3/ticker/24hr",
        "https://api1.binance.com/api/v3/ticker/24hr",
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
                            if coin in INACTIVE_COINS or coin in CHRONIC_BLEEDERS_AND_MEMES:
                                continue
                            if coin not in ['USDC', 'FDUSD', 'TUSD', 'BUSD', 'EUR', 'GBP', 'DAI'] and not coin.endswith(('UP', 'DOWN')):
                                futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
                                if coindcx_active:
                                    if f"B-{futures_coin}_USDT" not in coindcx_active and f"B-{coin}_USDT" not in coindcx_active:
                                        continue
                                valid_tickers.append((f"{coin}-USDT", quote_vol))
                    if valid_tickers:
                        valid_tickers.sort(key=lambda x: x[1], reverse=True)
                        dynamic_extra = [x[0] for x in valid_tickers]
                        break
        except Exception:
            pass

    combined_watchlist = list(base_pool)
    for s in dynamic_extra:
        coin_clean = s.split('-')[0].upper()
        if s not in combined_watchlist and coin_clean not in INACTIVE_COINS and coin_clean not in CHRONIC_BLEEDERS_AND_MEMES:
            combined_watchlist.append(s)

    CACHED_DYNAMIC_WATCHLIST = combined_watchlist
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

    # Provider 2: MEXC Public Market API
    try:
        url = f"https://api.mexc.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list):
                return [[int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in raw]
    except Exception:
        pass

    # Provider 3: CoinDCX Public Candles API
    try:
        futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
        pair_str = f"B-{futures_coin}_USDT"
        coindcx_int = "1" if interval_str == "1m" else ("5" if interval_str == "5m" else ("15" if interval_str == "15m" else ("60" if interval_str == "1h" else "1D")))
        url = f"https://public.coindcx.com/market_data/candles?pair={pair_str}&interval={coindcx_int}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
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

# Central Pivot Range (CPR) Calculation Engine (Frank Ochoa / KGS Pivot Model)
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
    return {
        'pivot': pivot, 
        'tc': upper_cpr, 
        'bc': lower_cpr, 
        'upper_cpr': upper_cpr,
        'lower_cpr': lower_cpr,
        'r1': r1, 'r2': r2, 'r3': r3, 
        's1': s1, 's2': s2,
        'prev_high': high, 'prev_low': low
    }

# Supertrend Indicator Engine (10, 3)
def calculate_supertrend(klines, period=10, multiplier=3.0):
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    tr_list = [highs[0] - lows[0]]
    for i in range(1, len(klines)):
        tr_list.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    atr_list = []
    for i in range(len(tr_list)):
        if i < period - 1:
            atr_list.append(0.0)
        elif i == period - 1:
            atr_list.append(sum(tr_list[:period]) / period)
        else:
            atr_list.append((atr_list[-1] * (period - 1) + tr_list[i]) / period)
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
            if closes[i] > final_ub[i-1]:
                st_dir[i] = 1
            elif closes[i] < final_lb[i-1]:
                st_dir[i] = -1
            else:
                st_dir[i] = st_dir[i-1]
            st_val[i] = final_lb[i] if st_dir[i] == 1 else final_ub[i]
    return st_dir[-1], st_val[-1]

# ==============================================================================
# 6. TELEGRAM NOTIFICATIONS & MESSAGING
# ==============================================================================
def send_telegram_message(text):
    for attempt in range(3):
        for mode in ['HTML', None]:
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
                        qty = abs(float(val))
                        if qty > 0:
                            return qty
                    except Exception:
                        pass
            return 0.0
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
                        'sl': round(entry_p * 0.9905, 4),
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

                    send_telegram_message(
                        f"🔄 <b>AUTO-RECOVERED ACTIVE COINDCX POSITION:</b>\n\n"
                        f"• <b>Pair:</b> <code>{p_pair}</code> ({sym})\n"
                        f"• <b>Quantity:</b> <code>{active_u}</code>\n"
                        f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                        f"• <b>Status:</b> Dynamic trailing & 75m stagnation guard ACTIVE!"
                    )
    save_active_trades()

# ==============================================================================
# 8. COINDCX FUTURES ORDER EXECUTION ENGINE
# ==============================================================================
def format_price_precision(p, cmp, coin):
    if p is None:
        return None
    p_float = float(p)
    if coin == 'BTC' or cmp >= 10000.0:
        return round(p_float, 1)
    elif cmp >= 100.0:
        return round(p_float, 2)
    elif cmp >= 1.0:
        return round(p_float, 2)
    elif cmp >= 0.01:
        return round(p_float, 4)
    elif coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']:
        return round(p_float * 1000.0, 5) if p_float < 0.0001 else round(p_float, 5)
    return round(p_float, 6)

def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=1000.0, leverage=7, custom_quantity=None, tp_price=None, sl_price=None):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
        
    coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
    pair_name = f"B-{futures_coin}_USDT"
    
    if side.lower() == "buy" and (tp_price is None or sl_price is None):
        return {'success': False, 'error': '⚠️ Trade Cancelled: Stop Loss and Target are required (No SL/TP = No Trade).'}
    
    if custom_quantity:
        quantity = custom_quantity
    else:
        usdt_inr_rate = 88.5
        margin_usdt = margin_inr / usdt_inr_rate
        notional_usdt = margin_usdt * leverage
        raw_quantity = notional_usdt / cmp
        
        if coin in ['BTC', 'ETH', 'ZEC', 'PAXG'] or cmp >= 1000.0:
            quantity = round(raw_quantity, 3) or 0.001
        elif coin in ['BNB', 'SOL', 'TAO']:
            quantity = round(raw_quantity, 2) or 0.01
        elif coin in ['AAVE', 'QNT', 'LTC', 'BCH'] or cmp >= 100.0:
            quantity = round(raw_quantity, 1) or 0.1
        elif coin in ['AVAX', 'LINK', 'UNI', 'INJ', 'NEAR', 'APT', 'FET', 'RUNE', 'TIA', 'ICP'] or cmp >= 1.0:
            quantity = float(int(raw_quantity)) or 1.0
        elif coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']:
            quantity = float(int(raw_quantity / 1000.0)) or 1.0
        else:
            quantity = float(int(raw_quantity)) or 1.0

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

    last_err = " | ".join(err_logs) if err_logs else "Unknown Error"
    if "Instrument is not active" in last_err or ("422" in last_err and "not active" in last_err):
        INACTIVE_COINS.add(coin)
    if side.lower() == "buy":
        return {'success': False, 'error': f"⚠️ Trade Cancelled: CoinDCX TP/SL validation failed ({last_err})."}
    return {'success': False, 'error': last_err}

# ==============================================================================
# 9. FLASK WEB ROUTES & MONITORING INTERFACES
# ==============================================================================
@app.route('/test-telegram')
def test_telegram_endpoint():
    try:
        ok = send_telegram_message("🔔 <b>TELEGRAM TEST ALERT FROM RENDER BOT!</b>\n\n• Status: 100% ONLINE\n• Timestamp: " + get_ist_now().strftime("%d-%m-%Y %I:%M:%S %p (IST)"))
        return f"<h3>Telegram Ping Result: {'✅ SUCCESS' if ok else '❌ FAILED'}</h3>", 200
    except Exception as e:
        return f"<h3>⚠️ Error: {e}</h3>", 500

@app.route('/test-trade')
def test_trade_endpoint():
    try:
        sol_klines = fetch_klines("SOL-USDT", "15m", 5)
        live_cmp = sol_klines[-1][4] if sol_klines else 118.80
        live_tp = round(live_cmp * 1.01, 2)
        live_sl = round(live_cmp * 0.99, 2)
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="buy", cmp=live_cmp, margin_inr=1000.0, leverage=7, custom_quantity=0.1, tp_price=live_tp, sl_price=live_sl)
        if res.get('success'):
            with active_trades_lock:
                ACTIVE_TRADES['SOL-USDT'] = {
                    'entry_price': live_cmp,
                    'total_qty': 0.1,
                    'remaining_qty': 0.1,
                    'tp1': live_tp,
                    'sl': live_sl,
                    'be_trigger': round(live_cmp * 1.0085, 2),
                    'is_be_active': False,
                    'leverage': 7,
                    'entry_time': time.time()
                }
            save_active_trades()
        return f"<h3>🧪 Diagnostic Test Result:</h3><pre>{json.dumps(res, indent=2)}</pre>", 200
    except Exception as e:
        return f"<h3>⚠️ Diagnostic Error:</h3><p>{e}</p>", 500

@app.route('/close-sol')
def close_sol_endpoint():
    try:
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="sell", cmp=108.23, leverage=7, custom_quantity=0.1)
        with active_trades_lock:
            ACTIVE_TRADES.pop('SOL-USDT', None)
        save_active_trades()
        send_telegram_message("🛡️ <b>SOL POSITION CLOSED VIA BOT ENDPOINT!</b>")
        return f"<h3>✅ SOL Position Close Result:</h3><pre>{json.dumps(res, indent=2)}</pre>", 200
    except Exception as e:
        return f"<h3>⚠️ Error closing SOL:</h3><p>{e}</p>", 500

@app.route('/today')
@app.route('/daily')
@app.route('/yesterday')
def today_report_endpoint(date_override=None):
    try:
        date_param = date_override or request.args.get('date')
        if not date_param and request.path == '/yesterday':
            date_param = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
        target_date_str = date_param if date_param else get_ist_now().strftime("%d-%m-%Y")
        summary_text = generate_daily_summary(target_date_str)
        history = load_trade_history()
        day_logs = history.get(target_date_str, [])
        
        rows = []
        for idx, log in enumerate(day_logs, 1):
            t = log.get("time", "")
            sym = log.get("symbol", "")
            typ = log.get("type", "")
            dt = log.get("details", {})
            if typ == "EXECUTED":
                status = f"<span style='color:#4ade80;'>🟢 EXECUTED (ID: {dt.get('order_id')})</span>"
                price_info = f"Entry: ${dt.get('cmp')} | Qty: {dt.get('quantity')}"
            elif typ == "CLOSED":
                status = f"<span style='color:#38bdf8;'>🏁 {dt.get('sl_type')}</span>"
                price_info = f"Exit: ${dt.get('cmp')} (Entry: ${dt.get('entry_p')})"
            else:
                status = f"<span style='color:#f87171;'>⚠️ CANCELLED ({dt.get('error', 'Rejection')})</span>"
                price_info = f"CMP: ${dt.get('cmp')}"
            rows.append(f"<tr><td>{idx}</td><td>{t}</td><td><b>{sym}</b></td><td>{status}</td><td>{price_info}</td></tr>")
            
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
        scan_pool = fetch_dynamic_watchlist()
        for symbol in scan_pool:
            try:
                time.sleep(0.04)
                m15_klines = fetch_klines(symbol, '15m', 100)
                h1_klines = fetch_klines(symbol, '1h', 60)
                if not m15_klines or len(m15_klines) < 20:
                    report_lines.append(f"{symbol:12s} | Error: Could not fetch candle data")
                    continue
                cmp = m15_klines[-1][4]
                daily_klines = fetch_klines(symbol, '1d', 2) or m15_klines
                cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
                st_dir, _ = calculate_supertrend(m15_klines)
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

                is_st_green = (st_dir == 1)
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
        html = f"<h2>⚡ LIVE DYNAMIC MARKET SCANNER AUDIT REPORT</h2><p><b>Server Time:</b> {now_str}</p><pre>" + "\n".join(report_lines) + "</pre>"
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Scan Error:</h3><p>{e}</p>", 500

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    clean_p = path.strip().strip('/')
    if clean_p.lower() == 'yesterday':
        yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
        return today_report_endpoint(date_override=yesterday_str)
    if re.match(r'^\d{2}-\d{2}-\d{4}$', clean_p):
        return today_report_endpoint(date_override=clean_p)

    if scan_lock.acquire(blocking=False):
        def async_scan():
            try:
                run_scan()
            finally:
                scan_lock.release()
        threading.Thread(target=async_scan, daemon=True).start()
        return "⚡ OK - Dynamic Market Scan Triggered! Check /scan-now for live audit table.", 200
    return "⚡ OK - Market Scanner Currently Active", 200

# ==============================================================================
# 10. MULTI-FACTOR SCANNER & AUTO-EXECUTION ENGINE
# ==============================================================================
def run_scan():
    state = load_state()
    candidates = []
    scan_pool = fetch_dynamic_watchlist()

    for symbol in scan_pool:
        try:
            time.sleep(0.04)
            daily_klines = fetch_klines(symbol, '1d', 2)
            m15_klines = fetch_klines(symbol, '15m', 100)
            h1_klines = fetch_klines(symbol, '1h', 60)
            
            if not m15_klines or len(m15_klines) < 20:
                continue
            if not daily_klines or len(daily_klines) < 2:
                daily_klines = m15_klines
            
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            is_st_green = (st_dir == 1)
            
            # Non-Negotiable Gate: 15-Minute Supertrend MUST BE GREEN (Zero Short Trades / Zero Counter-Trend Longs)
            if not is_st_green:
                continue

            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            
            # Buy Volume Check: Confirmed Green Candle Volume Spike (Not Panic Dump)
            is_buy_volume = (m15_klines[-1][4] >= m15_klines[-1][1]) or (len(m15_klines) >= 2 and m15_klines[-2][4] >= m15_klines[-2][1])
            is_valid_vol_spike = (vol_spike >= 1.20) and is_buy_volume
            
            # 24h Volume Liquidity Filter (>= $10,000,000 USDT)
            vol_24h_quote = max(float(daily_klines[0][5]), float(daily_klines[-1][5])) * cmp if (daily_klines and len(daily_klines[0]) > 5) else 15000000.0
            if vol_24h_quote < 10000000:
                continue

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

            # Hard Stop Loss: Below Bottom Central (BC) / Previous Low, CAPPED AT -0.95% (-6.6% ROE max)
            support_floor = min(bc_val, sweep_low_val, prev_low_val)
            structural_sl = support_floor * 0.9985
            hard_sl_cap = cmp * 0.9905
            sl_raw = max(hard_sl_cap, structural_sl)

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
                f"🔹 <b>Stop Loss:</b> <code>${sl}</code> (Below BC / Prev Low, Max -0.95%)\n"
                f"🎯 <b>Target:</b> <code>${tp1}</code> (Next Pivot R1/R2 or +3.2% Move)\n"
                f"🛡️ <b>Breakeven Profit Lock:</b> <code>Trigger @ +6.0% ROE (+0.85% Move)</code>\n"
                f"⏱️ <b>Time Stop:</b> <code>75 Minutes Max Stagnation Cut</code>\n"
                f"{exec_hdr}"
            )
            send_telegram_message(msg)
        except Exception as e:
            print(f"⚠️ Error executing candidate {symbol}: {e}")

# ==============================================================================
# 11. POSITION MONITORING, TRAILING SL & STAGNATION GUARD
# ==============================================================================
def monitor_active_positions():
    time.sleep(10)
    while True:
        if not AUTO_TRADING_ENABLED:
            time.sleep(5)
            continue
        try:
            with active_trades_lock:
                symbols_to_check = list(ACTIVE_TRADES.keys())
            
            for symbol in symbols_to_check:
                try:
                    time.sleep(0.1)
                    clean_coin = symbol.split('-')[0].upper()
                    
                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES:
                            continue
                        trade = ACTIVE_TRADES[symbol]

                    entry_time = trade.get('entry_time', time.time())
                    time_since_entry = time.time() - entry_time
                    
                    # Exchange Closure Detection (Manual close on CoinDCX App or bracket TP/SL hit)
                    if time_since_entry >= 60:
                        live_qty = fetch_coindcx_live_position_qty(symbol)
                        if live_qty is not None and live_qty <= 0:
                            time.sleep(2)
                            confirm_qty = fetch_coindcx_live_position_qty(symbol)
                            if confirm_qty is not None and confirm_qty <= 0:
                                with active_trades_lock:
                                    trade_info = ACTIVE_TRADES.pop(symbol, None)
                                save_active_trades()
                                
                                if trade_info:
                                    entry_p = trade_info.get('entry_price', 0)
                                    m1_k = fetch_klines(symbol, '1m', 1)
                                    exit_cmp = m1_k[-1][4] if (m1_k and len(m1_k) > 0) else entry_p
                                    realized_pnl_pct = ((exit_cmp - entry_p) / entry_p) * 7 * 100 if entry_p > 0 else 0.0
                                    pnl_inr = (realized_pnl_pct / 100.0) * 1000.0

                                    if exit_cmp >= entry_p * 1.001:
                                        sl_type = f"EXCHANGE TP / PROFIT HIT (+{realized_pnl_pct:.1f}% ROE) 💰"
                                        title, icon = "PROFIT TARGET / RUNNER EXIT 💰", "💰"
                                    elif abs(exit_cmp - entry_p) / entry_p <= 0.0025:
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
# 12. TELEGRAM COMMAND LISTENER (/stop, /start, /today, /yesterday)
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
        except Exception:
            pass
        time.sleep(3)

# ==============================================================================
# 13. BACKGROUND THREADS & SERVER STARTUP
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

    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()
    threading.Thread(target=run_daily_midnight_report_loop, daemon=True).start()

    send_telegram_message(
        "⚡ <b>RENDER BOT 10/10 GOLD STANDARD CPR SCANNER DEPLOYED!</b>\n\n"
        "• <b>Strategy Engine:</b> CPR Breakout & Retest (TradingView CPR by KGS Pivot Levels)\n"
        "• <b>Buy Zone:</b> Price holding above BC/Pivot & breaking out above Top Central (TC)\n"
        "• <b>Direction:</b> 100% BUY / LONG ONLY (Zero Short Trade Rule STRICT ACTIVE)\n"
        "• <b>Supertrend Gate:</b> 15M Supertrend MUST BE GREEN\n"
        "• <b>Target Engine:</b> Next Pivot Level (R1/R2) or +3.2% move (+22.4% ROE)\n"
        "• <b>Hard Stop Loss:</b> Capped at -0.95% Price Drop (-6.6% ROE max)\n"
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
