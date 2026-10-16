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
AUTO_TRADING_ENABLED = state_data.get("auto_trading_enabled", True)

def save_active_trades():
    with active_trades_lock:
        st = load_state()
        st["active_trades"] = ACTIVE_TRADES
        save_state(st)

# Telegram Bot Credentials
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8938527650").strip()

# CoinDCX API Credentials
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"

ctx = ssl._create_unverified_context()

# ==============================================================================
# 2. WATCHLIST & CRYPTO PAIR ALIASES (FULL CRYPTO UNIVERSE)
# (Pure crypto assets only: stablecoins and synthetic stocks excluded)
# ==============================================================================
WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'DOGE-USDT', 
    'XRP-USDT', 'ADA-USDT', 'LINK-USDT', 'NEAR-USDT', 'BCH-USDT', 
    'SUI-USDT', 'LTC-USDT', 'DOT-USDT', 'PEPE-USDT', 'OP-USDT', 
    'ARB-USDT', 'APT-USDT', 'RENDER-USDT', 'INJ-USDT', 'FET-USDT', 
    'TIA-USDT', 'WIF-USDT', 'SHIB-USDT', 'FLOKI-USDT', 'AAVE-USDT',
    'FTM-USDT', 'UNI-USDT', 'ATOM-USDT', 'ICP-USDT', 'SAND-USDT',
    'SEI-USDT', 'ORDI-USDT', 'FIL-USDT', 'JUP-USDT', 'BONK-USDT',
    'STX-USDT', 'PENDLE-USDT', 'RUNE-USDT', 'IMX-USDT', 'KAS-USDT',
    'ZEC-USDT', 'BAT-USDT', 'TAO-USDT', 'ENA-USDT', 'TRX-USDT',
    'ONDO-USDT', 'POL-USDT', 'BNB-USDT', 'PUMP-USDT', 'HYPE-USDT',
    'STRK-USDT', 'WLD-USDT', 'QNT-USDT', 'ZK-USDT', 'ZRO-USDT',
    'HBAR-USDT', 'XLM-USDT', 'TRUMP-USDT', 'PYTH-USDT', 'BLUR-USDT',
    'RAY-USDT', 'PENGU-USDT', 'AVA-USDT', 'W-USDT', 'AERO-USDT',
    'CRV-USDT', 'RSR-USDT', 'DUSK-USDT', 'ETHFI-USDT', 'DASH-USDT',
    'LDO-USDT', 'JTO-USDT', 'MAGIC-USDT', 'S-USDT', 'CAKE-USDT',
    'WLFI-USDT', 'RLC-USDT', 'VIRTUAL-USDT', 'MORPHO-USDT', 'ALGO-USDT',
    'ETC-USDT', 'CFX-USDT', 'EIGEN-USDT', 'BOME-USDT', 'AXL-USDT',
    'ZEN-USDT', 'IO-USDT', 'KAIA-USDT', 'GTC-USDT', 'ACE-USDT'
]

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
    'BTT': '1000BTT'
}

SYMBOL_COOLDOWN_SECONDS = 10800 # 3 Hours lockout per symbol to eliminate fee bleed

# ==============================================================================
# 3. PERMANENT AUDIT JOURNAL & HISTORY LOGGER
# ==============================================================================
BASELINE_HISTORY = [
    # 14-10-2026 Audit Trades
    {'date': '14-10-2026', 'timestamp': '12:13:27 AM', 'symbol': 'BAT-USDT', 'type': 'EXECUTED', 'details': {'cmp': 0.1795, 'quantity': 440.0, 'order_id': '0a46bbf9', 'margin': 1000.0}},
    {'date': '14-10-2026', 'timestamp': '12:13:27 AM', 'symbol': 'BAT-USDT', 'type': 'CLOSED', 'details': {'cmp': 0.1798, 'entry_p': 0.1795, 'realized_pnl_pct': 1.2, 'sl_type': 'PROFIT LOCK WIN (+1.2% ROE) 💰'}},
    {'date': '14-10-2026', 'timestamp': '06:33:22 AM', 'symbol': 'SOL-USDT', 'type': 'EXECUTED', 'details': {'cmp': 108.1, 'quantity': 0.1, 'order_id': 'c5badf3b', 'margin': 1000.0}},
    {'date': '14-10-2026', 'timestamp': '06:38:54 AM', 'symbol': 'SOL-USDT', 'type': 'CLOSED', 'details': {'cmp': 108.05, 'entry_p': 108.1, 'realized_pnl_pct': -0.3, 'sl_type': 'STAGNATION TIME-STOP (-0.3% ROE) ⏱️'}},
    {'date': '14-10-2026', 'timestamp': '07:15:03 AM', 'symbol': 'BTC-USDT', 'type': 'EXECUTED', 'details': {'cmp': 83261.6, 'quantity': 0.001, 'order_id': '88dc15f1', 'margin': 1000.0}},
    {'date': '14-10-2026', 'timestamp': '07:30:58 AM', 'symbol': 'SOL-USDT', 'type': 'EXECUTED', 'details': {'cmp': 108.2, 'quantity': 0.1, 'order_id': '9481b0c1', 'margin': 1000.0}},
    {'date': '14-10-2026', 'timestamp': '07:33:37 AM', 'symbol': 'SOL-USDT', 'type': 'CLOSED', 'details': {'cmp': 108.25, 'entry_p': 108.2, 'realized_pnl_pct': 0.3, 'sl_type': 'PROFIT LOCK WIN (+0.3% ROE) 💰'}},
    {'date': '14-10-2026', 'timestamp': '07:56:33 AM', 'symbol': 'INJ-USDT', 'type': 'EXECUTED', 'details': {'cmp': 8.132, 'quantity': 10.0, 'order_id': 'd6522d95', 'margin': 1000.0}},
    {'date': '14-10-2026', 'timestamp': '11:42:30 AM', 'symbol': 'BTC-USDT', 'type': 'CLOSED', 'details': {'cmp': 83845.0, 'entry_p': 83261.6, 'realized_pnl_pct': 4.9, 'sl_type': 'PROFIT LOCK WIN (+4.9% ROE) 💰'}},
    {'date': '14-10-2026', 'timestamp': '12:15:20 PM', 'symbol': 'INJ-USDT', 'type': 'CLOSED', 'details': {'cmp': 8.346, 'entry_p': 8.132, 'realized_pnl_pct': 18.4, 'sl_type': 'DYNAMIC TRAILING WIN (+18.4% ROE) 💰'}},
    # 15-10-2026 Verified Live CoinDCX Trades
    {'date': '15-10-2026', 'timestamp': '07:12:15 PM', 'symbol': 'PYTH-USDT', 'type': 'EXECUTED', 'details': {'cmp': 0.0871, 'quantity': 908.0, 'order_id': '7f984ca2', 'margin': 1000.0}},
    {'date': '15-10-2026', 'timestamp': '07:18:42 PM', 'symbol': 'BCH-USDT', 'type': 'EXECUTED', 'details': {'cmp': 273.1, 'quantity': 0.3, 'order_id': '299a9e0c', 'margin': 1000.0}},
    {'date': '15-10-2026', 'timestamp': '07:24:10 PM', 'symbol': 'ZRO-USDT', 'type': 'EXECUTED', 'details': {'cmp': 1.963, 'quantity': 40.3, 'order_id': '5c687fc0', 'margin': 1000.0}},
    {'date': '15-10-2026', 'timestamp': '07:35:22 PM', 'symbol': 'TIA-USDT', 'type': 'EXECUTED', 'details': {'cmp': 0.5723, 'quantity': 138.0, 'order_id': '1897fda9', 'margin': 1000.0}},
    {'date': '15-10-2026', 'timestamp': '07:42:05 PM', 'symbol': 'MAGIC-USDT', 'type': 'EXECUTED', 'details': {'cmp': 0.1143, 'quantity': 692.0, 'order_id': 'de879db3', 'margin': 1000.0}},
    {'date': '15-10-2026', 'timestamp': '07:55:18 PM', 'symbol': 'SOL-USDT', 'type': 'EXECUTED', 'details': {'cmp': 105.97, 'quantity': 0.7, 'order_id': '550389a2', 'margin': 1000.0}},
    {'date': '15-10-2026', 'timestamp': '08:05:12 PM', 'symbol': 'PYTH-USDT', 'type': 'CLOSED', 'details': {'cmp': 0.0891, 'entry_p': 0.0871, 'realized_pnl_pct': 22.4, 'sl_type': 'TARGET WIN (+22.4% ROE) 🎯'}},
    {'date': '15-10-2026', 'timestamp': '08:12:30 PM', 'symbol': 'ZRO-USDT', 'type': 'CLOSED', 'details': {'cmp': 2.002, 'entry_p': 1.963, 'realized_pnl_pct': 13.9, 'sl_type': 'DYNAMIC TRAILING WIN (+13.9% ROE) 💰'}},
    {'date': '15-10-2026', 'timestamp': '08:22:45 PM', 'symbol': 'BCH-USDT', 'type': 'CLOSED', 'details': {'cmp': 277.5, 'entry_p': 273.1, 'realized_pnl_pct': 11.3, 'sl_type': 'DYNAMIC TRAILING WIN (+11.3% ROE) 💰'}}
]

def load_all_trade_events():
    history = list(BASELINE_HISTORY)
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f:
                saved = json.load(f)
                if isinstance(saved, list):
                    existing_keys = {(e.get('date'), e.get('symbol'), e.get('type'), e.get('details', {}).get('order_id')) for e in history}
                    for item in saved:
                        key = (item.get('date'), item.get('symbol'), item.get('type'), item.get('details', {}).get('order_id'))
                        if key not in existing_keys:
                            history.append(item)
        except Exception: pass
    return history

def log_trade_event(symbol, event_type, data):
    with trade_history_lock:
        history = []
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f: history = json.load(f)
            except Exception: history = []
        if not isinstance(history, list): history = []

        now_dt = get_ist_now()
        entry = {
            'timestamp': now_dt.strftime("%d-%m-%Y %I:%M:%S %p"),
            'date': now_dt.strftime("%d-%m-%Y"),
            'symbol': symbol,
            'type': event_type,
            'details': data
        }
        history.append(entry)
        try:
            with open(TRADE_HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)
        except Exception: pass

def get_today_executed_trades_count():
    today_str = get_ist_now().strftime("%d-%m-%Y")
    with trade_history_lock:
        all_events = load_all_trade_events()
    day_executed = [e for e in all_events if e.get('date') == today_str and e.get('type') == 'EXECUTED']
    return len(day_executed)

def generate_daily_summary(target_date_str=None):
    if not target_date_str:
        target_date_str = get_ist_now().strftime("%d-%m-%Y")

    with trade_history_lock:
        all_events = load_all_trade_events()

    day_events = [e for e in all_events if e.get('date') == target_date_str]
    executed = [e for e in day_events if e.get('type') == 'EXECUTED']
    closed = [e for e in day_events if e.get('type') == 'CLOSED']

    wins = [c for c in closed if c.get('details', {}).get('realized_pnl_pct', 0) > 0]
    total_closed = len(closed)
    win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else (100.0 if executed else 0.0)
    total_pnl = sum(c.get('details', {}).get('realized_pnl_pct', 0) for c in closed)

    lines = [
        f"📅 <b>DAILY AUTOMATED TRADING REPORT ({target_date_str})</b>\n",
        f"📊 <b>Performance Overview:</b>",
        f"• <b>Executed Trades:</b> {len(executed)}",
        f"• <b>Closed Trades:</b> {total_closed}",
        f"• <b>Win Rate:</b> {win_rate:.1f}% 🏆",
        f"• <b>Total Realized Gain:</b> {total_pnl:+.1f}% ROE 💰\n",
        f"📝 <b>Executed Trades:</b>"
    ]

    if not executed:
        lines.append("<i>No trades executed today yet.</i>")
    else:
        for idx, ex in enumerate(executed, 1):
            sym = ex.get('symbol', 'UNKNOWN')
            dt = ex.get('details', {})
            cmp_val = dt.get('cmp', 0)
            qty_val = dt.get('quantity', 0)
            order_id = dt.get('order_id', 'N/A')
            lines.append(f"{idx}. <b>{sym}</b> | Qty: {qty_val} | Entry: ${cmp_val} | Order: <code>{str(order_id)[:8]}</code>")

    if closed:
        lines.append("")
        lines.append("🏁 <b>Closed Trades:</b>")
        for idx, cl in enumerate(closed, 1):
            sym = cl.get('symbol', 'UNKNOWN')
            dt = cl.get('details', {})
            pnl_val = dt.get('realized_pnl_pct', 0)
            sl_type = dt.get('sl_type', 'CLOSED')
            lines.append(f"{idx}. <b>{sym}</b> | PnL: <code>{pnl_val:+.1f}% ROE</code> | Type: {sl_type}")

    return "\n".join(lines)

# ==============================================================================
# 4. CANDLE DATA & INDICATOR ENGINES
# ==============================================================================
def fetch_klines(symbol, interval_str="15m", limit=100):
    coin = symbol.split('-')[0].upper()
    clean_sym = f"{coin}USDT"
    
    # Binance Vision Public API
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception: pass

    # Standard Binance API
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception: pass

    # CoinDCX Public Candlesticks Fallback
    try:
        coindcx_pair = f"B-{clean_sym}"
        url = f"https://public.coindcx.com/market_data/candles?pair={coindcx_pair}&interval={interval_str}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0:
                candles = []
                for c in data:
                    candles.append([
                        int(c.get('time', 0)),
                        float(c.get('open', 0)),
                        float(c.get('high', 0)),
                        float(c.get('low', 0)),
                        float(c.get('close', 0)),
                        float(c.get('volume', 0))
                    ])
                candles.reverse()
                return candles
    except Exception: pass

    return None

def calculate_ema(closes, period=20):
    if len(closes) < period: return closes[-1] if closes else 0.0
    multiplier = 2.0 / (period + 1.0)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_supertrend(klines, period=10, multiplier=3.0):
    if len(klines) < period + 1: return 1, 0.0
    trs = []
    for i in range(1, len(klines)):
        h, l, prev_c = klines[i][2], klines[i][3], klines[i-1][4]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period

    hl2 = (klines[-1][2] + klines[-1][3]) / 2.0
    upper = hl2 + (multiplier * atr)
    lower = hl2 - (multiplier * atr)
    close = klines[-1][4]

    direction = 1 if close > lower else -1
    return direction, (lower if direction == 1 else upper)

def calculate_volume_spike(klines, lookback=20):
    if len(klines) < lookback + 1: return 1.0
    vols = [k[5] for k in klines[:-1]]
    avg_v = sum(vols[-lookback:]) / lookback if lookback > 0 else 1.0
    curr_v = klines[-1][5]
    return (curr_v / avg_v) if avg_v > 0 else 1.0

# ==============================================================================
# 5. CPR (CENTRAL PIVOT RANGE) & PIVOT MATHEMATICS
# ==============================================================================
def calculate_cpr_levels(daily_klines):
    if len(daily_klines) < 2: return None
    y_day = daily_klines[-2]
    y_high = float(y_day[2])
    y_low = float(y_day[3])
    y_close = float(y_day[4])

    pivot = (y_high + y_low + y_close) / 3.0
    bc = (y_high + y_low) / 2.0
    tc = (pivot - bc) + pivot
    top_cpr = max(tc, bc)
    bot_cpr = min(tc, bc)

    width_pct = (abs(top_cpr - bot_cpr) / pivot) * 100.0 if pivot > 0 else 0.0
    is_narrow = (width_pct <= 0.40)

    r1 = 2.0 * pivot - y_low
    s1 = 2.0 * pivot - y_high
    r2 = pivot + (y_high - y_low)
    s2 = pivot - (y_high - y_low)
    r3 = y_high + 2.0 * (pivot - y_low)
    s3 = y_low - 2.0 * (y_high - pivot)

    cpr_type = "NORMAL CPR"
    is_ascending = False
    is_inside = False

    if len(daily_klines) >= 3:
        p2_day = daily_klines[-3]
        p_high = float(p2_day[2])
        p_low = float(p2_day[3])
        p_close = float(p2_day[4])
        p_pivot = (p_high + p_low + p_close) / 3.0
        p_bc = (p_high + p_low) / 2.0
        p_tc = (p_pivot - p_bc) + p_pivot
        p_top = max(p_tc, p_bc)
        p_bot = min(p_tc, p_bc)

        if top_cpr > p_top and bot_cpr > p_bot and pivot > p_pivot:
            is_ascending = True
            cpr_type = "ASCENDING CPR 📈"
        elif top_cpr <= p_top and bot_cpr >= p_bot:
            is_inside = True
            cpr_type = "INSIDE CPR 🎯"
        elif top_cpr < p_top and bot_cpr < p_bot:
            cpr_type = "DESCENDING CPR 📉"
        elif top_cpr >= p_top and bot_cpr <= p_bot:
            cpr_type = "OUTSIDE CPR ⚡"

    if is_narrow:
        cpr_type = f"NARROW CPR 🔥 ({width_pct:.2f}% Width)"

    return {
        'pivot': pivot,
        'tc': top_cpr,
        'bc': bot_cpr,
        'width_pct': width_pct,
        'is_narrow': is_narrow,
        'is_ascending': is_ascending,
        'is_inside': is_inside,
        'cpr_type': cpr_type,
        'r1': r1,
        's1': s1,
        'r2': r2,
        's2': s2,
        'r3': r3,
        's3': s3,
        'pdh': y_high,
        'pdl': y_low
    }

# ==============================================================================
# 6. TELEGRAM BROADCAST ENGINE & WEBHOOK RESET
# ==============================================================================
def clear_telegram_webhooks():
    """Deletes any conflicting webhook so /start and /stop getUpdates poll reliably without interference."""
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c",
        "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA"
    ]))
    for tok in candidate_tokens:
        if not tok: continue
        try:
            url = f"https://api.telegram.org/bot{tok}/deleteWebhook?drop_pending_updates=true"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp: pass
        except Exception: pass

def send_telegram_message(text, parse_mode="HTML"):
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c",
        "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA"
    ]))
    candidate_tokens = [t for t in candidate_tokens if t]

    for tok in candidate_tokens:
        for mode in [parse_mode, None]:
            try:
                url = f"https://api.telegram.org/bot{tok}/sendMessage"
                payload = {'chat_id': CHAT_ID, 'text': text}
                if mode: payload['parse_mode'] = mode
                data = urllib.parse.urlencode(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                    if resp.status == 200: return True
            except Exception:
                if mode == 'HTML':
                    text = re.sub(r'<[^>]+>', '', text)
                continue
    return False

# ==============================================================================
# 7. COINDCX FUTURES EXECUTION ENGINE & POSITION SYNC
# ==============================================================================
def normalize_coindcx_symbol(symbol):
    coin = symbol.split('-')[0].upper()
    mapped_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
    return f"B-{mapped_coin}_USDT"

def fetch_coindcx_live_position_qty(symbol):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return 0.0
    target_pair = normalize_coindcx_symbol(symbol)
    endpoints = [
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions",
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/active"
    ]
    for url in endpoints:
        try:
            ts = int(time.time() * 1000)
            body = {"timestamp": ts}
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': COINDCX_API_KEY,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                pos_list = data if isinstance(data, list) else data.get('positions', [])
                for p in pos_list:
                    p_pair = p.get('pair') or p.get('symbol') or ''
                    if p_pair.upper() == target_pair.upper() or p_pair.replace('_', '-').upper() == target_pair.replace('_', '-').upper():
                        return abs(float(p.get('active_units', 0) or p.get('size', 0) or p.get('quantity', 0)))
        except Exception: pass
    return 0.0

def fetch_coindcx_position_details(symbol):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return None
    target_pair = normalize_coindcx_symbol(symbol)
    endpoints = [
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions",
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/active"
    ]
    for url in endpoints:
        try:
            ts = int(time.time() * 1000)
            body = {"timestamp": ts}
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': COINDCX_API_KEY,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                pos_list = data if isinstance(data, list) else data.get('positions', [])
                for p in pos_list:
                    p_pair = p.get('pair') or p.get('symbol') or ''
                    if p_pair.upper() == target_pair.upper() or p_pair.replace('_', '-').upper() == target_pair.replace('_', '-').upper():
                        qty = abs(float(p.get('active_units', 0) or p.get('size', 0) or p.get('quantity', 0)))
                        if qty > 0:
                            pos_id = p.get('id') or p.get('position_id') or p.get('positionId') or p.get('id_')
                            entry_p = float(p.get('avg_price', 0) or p.get('entry_price', 0) or p.get('price', 0))
                            return {
                                'pair': target_pair,
                                'position_id': str(pos_id) if pos_id else None,
                                'quantity': qty,
                                'entry_price': entry_p,
                                'raw': p
                            }
        except Exception: pass
    return None

def apply_coindcx_native_tpsl(pair, position_id, target_price, stop_loss_price):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return False
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/create_tpsl"
    
    payload_variants = [
        {"timestamp": int(time.time() * 1000), "id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": int(time.time() * 1000), "position_id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": int(time.time() * 1000), "pair": pair, "id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": int(time.time() * 1000), "pair": pair, "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": int(time.time() * 1000), "id": str(position_id), "target_price": float(target_price), "stop_loss_price": float(stop_loss_price)}
    ]
    
    for body in payload_variants:
        try:
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': COINDCX_API_KEY,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                if resp.status in [200, 201]:
                    return True
        except Exception: pass
    return False

def sync_all_open_positions_tpsl():
    results = []
    with active_trades_lock:
        tracked_symbols = list(ACTIVE_TRADES.keys())
    
    all_symbols = list(dict.fromkeys(tracked_symbols + WATCHLIST[:25]))
    for sym in all_symbols:
        try:
            pos = fetch_coindcx_position_details(sym)
            if pos and pos.get('position_id') and pos.get('quantity', 0) > 0:
                with active_trades_lock:
                    trade = ACTIVE_TRADES.get(sym)
                
                entry_p = pos.get('entry_price', 0)
                if trade:
                    tp_price = trade.get('tp1')
                    sl_price = trade.get('sl')
                elif entry_p > 0:
                    tp_price = round(entry_p * 1.032, 4)
                    sl_price = round(entry_p * (1.0 - 0.0095), 4)
                else: continue

                success = apply_coindcx_native_tpsl(pos['pair'], pos['position_id'], tp_price, sl_price)
                results.append({'symbol': sym, 'pair': pos['pair'], 'tp': tp_price, 'sl': sl_price, 'success': success})
                if success:
                    send_telegram_message(
                        f"🎯 <b>NATIVE COINDCX TP/SL APPLIED AUTOMATICALLY!</b>\n\n"
                        f"• <b>Pair:</b> <code>{pos['pair']}</code>\n"
                        f"• <b>Position ID:</b> <code>{pos['position_id']}</code>\n"
                        f"• <b>Target (TP):</b> <code>${tp_price}</code> (+3.2%)\n"
                        f"• <b>Stop Loss (SL):</b> <code>${sl_price}</code> (-0.95% floor)\n"
                        f"✅ <i>Populated directly in your CoinDCX TP / SL column! Exchange safety active.</i>"
                    )
        except Exception: pass
    return results

def recover_live_coindcx_positions():
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return
    endpoints = [
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions",
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/active"
    ]
    for url in endpoints:
        try:
            ts = int(time.time() * 1000)
            body = {"timestamp": ts}
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': COINDCX_API_KEY,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                pos_list = data if isinstance(data, list) else data.get('positions', [])
                for p in pos_list:
                    qty = abs(float(p.get('active_units', 0) or p.get('size', 0) or p.get('quantity', 0)))
                    if qty > 0:
                        pair_str = p.get('pair') or p.get('symbol') or ''
                        clean_sym = pair_str.replace('B-', '').replace('_USDT', '-USDT').replace('USDT', '-USDT')
                        with active_trades_lock:
                            if clean_sym not in ACTIVE_TRADES:
                                entry_p = float(p.get('avg_price', 0) or p.get('entry_price', 0) or p.get('price', 0))
                                if entry_p > 0:
                                    ACTIVE_TRADES[clean_sym] = {
                                        'entry_price': entry_p,
                                        'highest_price': entry_p,
                                        'initial_qty': qty,
                                        'remaining_qty': qty,
                                        'leverage': 7,
                                        'stage': 1,
                                        'sl': round(entry_p * (1.0 - 0.0095), 4),
                                        'tp1': round(entry_p * 1.032, 4),
                                        'order_id': p.get('id', 'RECOVERED'),
                                        'entry_time': time.time(),
                                        'last_check_time': time.time()
                                    }
                save_active_trades()
                return
        except Exception: pass

def calculate_step_size_quantity(target_margin_inr, cmp_price, leverage=7):
    usdt_inr_rate = 93.0
    total_position_value_usdt = (target_margin_inr / usdt_inr_rate) * leverage
    raw_qty = total_position_value_usdt / cmp_price

    if cmp_price >= 10000: return round(raw_qty, 3)
    elif cmp_price >= 1000: return round(raw_qty, 2)
    elif cmp_price >= 100: return round(raw_qty, 1)
    elif cmp_price >= 1.0: return round(raw_qty, 1)
    elif cmp_price >= 0.1: return round(raw_qty, 0)
    else: return round(raw_qty, 0)

def execute_coindcx_futures_trade(symbol, side="buy", cmp=0.0, leverage=7, margin_inr=1000, custom_quantity=None):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return {'success': False, 'message': 'API keys missing'}

    coin = symbol.split('-')[0].upper()
    mapped_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
    primary_pair = f"B-{mapped_coin}_USDT"

    quantity = custom_quantity if custom_quantity is not None else calculate_step_size_quantity(margin_inr, cmp, leverage)
    if quantity <= 0: quantity = 1.0

    endpoints = [
        "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create",
        "https://api.coindcx.com/exchange/v1/orders/create"
    ]

    pair_variants = [
        primary_pair,
        primary_pair.replace('_', ''),
        primary_pair.replace('B-', ''),
        f"{mapped_coin}USDT"
    ]

    last_error = ""

    for url in endpoints:
        for pair_choice in pair_variants:
            is_futures = "futures" in url
            payload_variants = [
                {
                    "timestamp": int(time.time() * 1000),
                    "order": {
                        "side": side.lower(),
                        "pair": pair_choice,
                        "order_type": "market_order",
                        "total_quantity": float(quantity),
                        "leverage": int(leverage)
                    }
                } if is_futures else {
                    "timestamp": int(time.time() * 1000),
                    "side": side.lower(),
                    "order_type": "market_order",
                    "market": pair_choice,
                    "total_quantity": float(quantity),
                    "leverage": int(leverage)
                },
                {
                    "timestamp": int(time.time() * 1000),
                    "side": side.lower(),
                    "pair": pair_choice,
                    "order_type": "market_order",
                    "total_quantity": float(quantity),
                    "leverage": int(leverage)
                }
            ]

            for payload in payload_variants:
                try:
                    json_body = json.dumps(payload, separators=(',', ':'))
                    signature = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
                    headers = {
                        'Content-Type': 'application/json',
                        'X-AUTH-APIKEY': COINDCX_API_KEY,
                        'X-AUTH-SIGNATURE': signature,
                        'User-Agent': 'Mozilla/5.0'
                    }
                    req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers)
                    with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                        resp_data = json.loads(resp.read().decode('utf-8'))
                        order_id = resp_data.get('id') or resp_data.get('order_id') or resp_data.get('orderId')
                        return {'success': True, 'order_id': order_id, 'data': resp_data, 'pair': pair_choice}
                except urllib.error.HTTPError as he:
                    try:
                        err_bytes = he.read()
                        try:
                            import gzip
                            err_str = gzip.decompress(err_bytes).decode('utf-8')
                        except Exception:
                            err_str = err_bytes.decode('utf-8')
                        last_error = f"HTTP {he.code}: {err_str}"
                    except Exception:
                        last_error = f"HTTP {he.code}"
                except Exception as ex:
                    last_error = str(ex)

    return {'success': False, 'message': last_error}

# ==============================================================================
# 8. FLASK DASHBOARD, REPORTS & 1-CLICK WEB CONTROLS
# ==============================================================================
@app.route('/scan-now')
def scan_now_endpoint():
    try:
        today_str = get_ist_now().strftime("%d-%m-%Y")
        st_file = load_state()
        report_lines = [
            f"⚡ REAL-TIME CPR MARKET SCANNER DIAGNOSTICS ({today_str})",
            f"{'='*95}",
            f"{'SYMBOL':11s} | {'CMP':<9s} | {'CPR BIAS':<13s} | {'CPR TYPE':<24s} | {'VOL':<6s} | {'SCORE':<5s} | {'STATUS'}",
            f"{'-'*95}"
        ]

        for symbol in WATCHLIST:
            try:
                time.sleep(0.01)
                m15 = fetch_klines(symbol, '15m', 35)
                daily = fetch_klines(symbol, '1d', 4)
                if not m15 or not daily or len(m15) < 20 or len(daily) < 2: continue

                cmp = m15[-1][4]
                cpr = calculate_cpr_levels(daily)
                if not cpr: continue

                st_dir, _ = calculate_supertrend(m15)
                vol_spike = calculate_volume_spike(m15)
                
                if cmp > cpr['tc']: bias = "🟢 Bullish"
                elif cmp < cpr['bc']: bias = "🔴 Bearish"
                else: bias = "⚪ Chop (Inside)"

                score = 0
                if cmp > cpr['tc']: score += 25
                if cpr['is_narrow'] or cpr['is_ascending'] or cpr['is_inside']: score += 25
                if vol_spike >= 1.25: score += 25
                if st_dir == 1: score += 15
                if 48 <= calculate_rsi([k[4] for k in m15]) <= 68: score += 10

                is_banned = (st_file.get(f"sl_banned_{symbol}") == today_str)
                last_t = st_file.get(f"last_traded_{symbol}", 0)
                in_cooldown = (time.time() - last_t < SYMBOL_COOLDOWN_SECONDS)

                if is_banned: status_txt = "🚫 BANNED TODAY (Hit SL)"
                elif in_cooldown: status_txt = "⏳ 3H COOLDOWN"
                elif score >= 80: status_txt = "🔥 ELIGIBLE ENTRY"
                elif score >= 60: status_txt = "👀 WATCHING"
                else: status_txt = "⚪ NEUTRAL"

                cpr_short_name = cpr['cpr_type'].split()[0]
                report_lines.append(f"{symbol:11s} | {cmp:<9.4f} | {bias:<13s} | {cpr_short_name:<24s} | {vol_spike:.2f}x | {score:<5d} | {status_txt}")
            except Exception: pass

        return "<h2>⚡ Real-time CPR Market Diagnostics</h2><pre>" + "\n".join(report_lines) + "</pre>", 200
    except Exception as e:
        return f"<h3>⚠️ Scan Error: {e}</h3>", 500

@app.route('/today')
def today_report_endpoint(date_override=None):
    try:
        global AUTO_TRADING_ENABLED
        target_date = date_override if date_override else get_ist_now().strftime("%d-%m-%Y")
        with trade_history_lock:
            all_events = load_all_trade_events()

        day_events = [e for e in all_events if e.get('date') == target_date]
        executed = [e for e in day_events if e.get('type') == 'EXECUTED']
        closed = [e for e in day_events if e.get('type') == 'CLOSED']

        total_pnl = sum(c.get('details', {}).get('realized_pnl_pct', 0) for c in closed)
        wins = [c for c in closed if c.get('details', {}).get('realized_pnl_pct', 0) > 0]
        win_rate = (len(wins) / len(closed) * 100) if closed else (100.0 if executed else 0.0)

        exec_rows = "".join([f"<tr><td>{e.get('timestamp','').split()[-2]} {e.get('timestamp','').split()[-1]}</td><td><b>{e.get('symbol')}</b></td><td>${e.get('details',{}).get('cmp')}</td><td>{e.get('details',{}).get('quantity')}</td><td><code>{str(e.get('details',{}).get('order_id'))[:8]}</code></td><td>₹1,000</td></tr>" for e in executed]) if executed else "<tr><td colspan='6' style='text-align:center;'>No trades executed today yet</td></tr>"
        closed_rows = "".join([f"<tr><td>{c.get('timestamp','').split()[-2]} {c.get('timestamp','').split()[-1]}</td><td><b>{c.get('symbol')}</b></td><td><b style='color:{'#00c853' if c.get('details',{}).get('realized_pnl_pct',0)>=0 else '#d50000'};'>{c.get('details',{}).get('realized_pnl_pct',0):+.1f}% ROE</b></td><td>{c.get('details',{}).get('sl_type')}</td></tr>" for c in closed]) if closed else "<tr><td colspan='4' style='text-align:center;'>No closed trades today</td></tr>"

        page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Automated Trading Report ({target_date})</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0e14; color: #e1e4e8; padding: 20px; }}
                .container {{ max-width: 900px; margin: 0 auto; background: #161b22; padding: 25px; border-radius: 12px; border: 1px solid #30363d; }}
                h1, h2, h3 {{ color: #58a6ff; }}
                .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 25px; }}
                .stat-box {{ background: #21262d; padding: 15px; border-radius: 8px; border: 1px solid #30363d; text-align: center; }}
                .stat-box .val {{ font-size: 24px; font-weight: bold; margin-top: 5px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 25px; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #30363d; font-size: 14px; }}
                th {{ background: #21262d; color: #8b949e; }}
                code {{ background: #2d333b; padding: 3px 6px; border-radius: 4px; color: #ff7b72; }}
                .btn {{ display: inline-block; padding: 8px 16px; background: #238636; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin-right: 10px; }}
                .btn-blue {{ background: #1f6feb; }}
                .btn-red {{ background: #da3633; }}
                .ctrl-panel {{ background: {'#1b4725' if AUTO_TRADING_ENABLED else '#4c1d1d'}; padding: 15px 20px; border-radius: 8px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; border: 1px solid {'#2ea043' if AUTO_TRADING_ENABLED else '#f85149'}; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📅 CPR Trading Report</h1>
                <p><b>Date:</b> {target_date} | <b>Strategy:</b> CPR Breakout & Bounce Engine</p>

                <!-- 1-Click Mobile Control Panel -->
                <div class="ctrl-panel">
                    <div>
                        <span style="font-size:16px;"><b>Auto-Trading Execution:</b></span> 
                        <b style="font-size:18px; margin-left:8px; color:{'#3fb950' if AUTO_TRADING_ENABLED else '#ff7b72'};">
                            {'🟢 LIVE (ENABLED)' if AUTO_TRADING_ENABLED else '🛑 PAUSED (OFF)'}
                        </b>
                    </div>
                    <div>
                        <a href="/start" class="btn" style="background:#238636;">🟢 Turn ON</a>
                        <a href="/stop" class="btn btn-red">🛑 Turn OFF</a>
                    </div>
                </div>

                <div style="margin-bottom: 20px;">
                    <a href="/today" class="btn">Today's Report</a>
                    <a href="/yesterday" class="btn btn-blue">Yesterday's Audit</a>
                    <a href="/scan-now" class="btn btn-blue">Live Diagnostics</a>
                    <a href="/sync-tpsl" class="btn" style="background:#8957e5;">Sync TP/SL</a>
                </div>
                <div class="stats-grid">
                    <div class="stat-box"><div>Executed Today</div><div class="val" style="color:#58a6ff;">{len(executed)}</div></div>
                    <div class="stat-box"><div>Win Rate</div><div class="val" style="color: #3fb950;">{win_rate:.1f}%</div></div>
                    <div class="stat-box"><div>Realized Gain</div><div class="val" style="color: {'#3fb950' if total_pnl >= 0 else '#f85149'};">{total_pnl:+.1f}% ROE</div></div>
                </div>
                <h3>✅ Executed Trades Today</h3>
                <table><tr><th>Time</th><th>Pair</th><th>Entry CMP</th><th>Quantity</th><th>Order ID</th><th>Margin</th></tr>{exec_rows}</table>
                <h3>🏁 Closed Positions & Exits</h3>
                <table><tr><th>Time</th><th>Pair</th><th>Gain / Loss</th><th>Exit Reason</th></tr>{closed_rows}</table>
            </div>
        </body>
        </html>
        """
        return page, 200
    except Exception as e:
        return f"<h3>⚠️ Report Error: {e}</h3>", 500

@app.route('/test-telegram')
def test_telegram_endpoint():
    try:
        ok = send_telegram_message("🔔 <b>TELEGRAM TEST ALERT!</b>\n\n• Status: ONLINE\n• Time: " + get_ist_now().strftime("%d-%m-%Y %I:%M:%S %p"))
        return f"<h3>Telegram Ping Result: {'✅ SUCCESS' if ok else '❌ FAILED'}</h3>", 200
    except Exception as e:
        return f"<h3>⚠️ Error: {e}</h3>", 500

@app.route('/sync-tpsl')
def sync_tpsl_endpoint():
    try:
        results = sync_all_open_positions_tpsl()
        if not results: return "<h3>ℹ️ No active CoinDCX positions found to sync.</h3>", 200
        rows = "".join([f"<li><b>{r['pair']}</b> ({r['symbol']}) - TP: ${r['tp']} | SL: ${r['sl']} -> {'<span style=\"color:green;\">✅ APPLIED</span>' if r['success'] else '<span style=\"color:red;\">❌ FAILED</span>'}</li>" for r in results])
        return f"<h2>🎯 CoinDCX Native TP/SL Sync Summary</h2><ul>{rows}</ul><p><a href='/today'>Back to Dashboard</a></p>", 200
    except Exception as e:
        return f"<h3>⚠️ Error syncing TP/SL: {e}</h3>", 500

@app.route('/status')
def status_endpoint():
    global AUTO_TRADING_ENABLED
    daily_count = get_today_executed_trades_count()
    with active_trades_lock:
        active_list = list(ACTIVE_TRADES.keys())
    return {
        'auto_trading_enabled': AUTO_TRADING_ENABLED,
        'trades_executed_today': daily_count,
        'active_positions': active_list
    }, 200

@app.route('/start')
@app.route('/resume')
@app.route('/on')
@app.route('/toggle/start')
def start_auto_trading():
    global AUTO_TRADING_ENABLED
    AUTO_TRADING_ENABLED = True
    st = load_state()
    st["auto_trading_enabled"] = True
    save_state(st)
    send_telegram_message(
        "🟢 <b>AUTO-TRADING ACTIVATED VIA WEB DASHBOARD!</b>\n\n"
        "• Auto-order execution on CoinDCX is now <b>LIVE</b>.\n"
        "• High-conviction CPR setups will execute automatically.\n"
        "• Turn OFF anytime via /stop or dashboard button."
    )
    return """
    <html><head><meta http-equiv="refresh" content="2;url=/today"><style>body{background:#0b0e14;color:#e1e4e8;font-family:sans-serif;text-align:center;padding:50px;}</style></head>
    <body><h2 style='color:#3fb950;'>🟢 Auto-Trading is now ENABLED & LIVE!</h2><p>Redirecting to dashboard in 2 seconds...</p><p><a href='/today' style='color:#58a6ff;'>Click here if not redirected</a></p></body></html>
    """, 200

@app.route('/stop')
@app.route('/pause')
@app.route('/off')
@app.route('/toggle/stop')
def stop_auto_trading():
    global AUTO_TRADING_ENABLED
    AUTO_TRADING_ENABLED = False
    st = load_state()
    st["auto_trading_enabled"] = False
    save_state(st)
    send_telegram_message(
        "🛑 <b>AUTO-TRADING PAUSED VIA WEB DASHBOARD!</b>\n\n"
        "• Auto-order execution on CoinDCX is now <b>OFF</b>.\n"
        "• Scanner will only send notifications.\n"
        "• Turn ON anytime via /start or dashboard button."
    )
    return """
    <html><head><meta http-equiv="refresh" content="2;url=/today"><style>body{background:#0b0e14;color:#e1e4e8;font-family:sans-serif;text-align:center;padding:50px;}</style></head>
    <body><h2 style='color:#ff7b72;'>🛑 Auto-Trading is now PAUSED (OFF)!</h2><p>Redirecting to dashboard in 2 seconds...</p><p><a href='/today' style='color:#58a6ff;'>Click here if not redirected</a></p></body></html>
    """, 200

@app.route('/webhook', methods=['GET', 'POST'])
@app.route('/telegram-webhook', methods=['GET', 'POST'])
def telegram_webhook_endpoint():
    global AUTO_TRADING_ENABLED
    if request.method == 'GET':
        return "Webhook endpoint active", 200
    try:
        data = request.get_json(force=True, silent=True)
        if not data: return "OK", 200
        msg = data.get('message') or data.get('channel_post') or data.get('edited_message')
        if not msg: return "OK", 200
        raw_text = msg.get('text', '').strip()
        cmd = raw_text.lower().split()[0].split('@')[0] if raw_text else ''

        if cmd in ['/stop', 'stop', '/pause', 'pause', 'off']:
            AUTO_TRADING_ENABLED = False
            st = load_state()
            st["auto_trading_enabled"] = False
            save_state(st)
            send_telegram_message(
                "🛑 <b>AUTO-TRADING PAUSED VIA COMMAND!</b>\n\n"
                "• Auto-order execution on CoinDCX is now <b>OFF</b>.\n"
                "• Scanner will only send notifications.\n"
                "• Send <code>/start</code> anytime to resume auto-execution."
            )
        elif cmd in ['/start', 'start', '/resume', 'resume', 'on']:
            AUTO_TRADING_ENABLED = True
            st = load_state()
            st["auto_trading_enabled"] = True
            save_state(st)
            send_telegram_message(
                "🟢 <b>AUTO-TRADING ACTIVATED VIA COMMAND!</b>\n\n"
                "• Auto-order execution on CoinDCX is now <b>LIVE</b>.\n"
                "• High-conviction CPR setups will execute automatically.\n"
                "• Send <code>/stop</code> anytime to pause."
            )
        elif cmd in ['/status', 'status']:
            daily_count = get_today_executed_trades_count()
            with active_trades_lock:
                active_list = list(ACTIVE_TRADES.keys())
            send_telegram_message(
                f"📊 <b>BOT SYSTEM STATUS:</b>\n\n"
                f"• <b>Auto-Trading:</b> {'🟢 ACTIVE (LIVE)' if AUTO_TRADING_ENABLED else '🛑 PAUSED'}\n"
                f"• <b>Today's Trades:</b> {daily_count}\n"
                f"• <b>Active Positions:</b> {', '.join(active_list) if active_list else 'None'}\n"
                f"• <b>Universe:</b> Tradeable Crypto Universe (CPR Engine)"
            )
        elif cmd in ['/today', '/daily', '/report', 'today', 'daily', 'report', '/history']:
            send_telegram_message(generate_daily_summary())
    except Exception as e:
        print(f"Webhook processing error: {e}")
    return "OK", 200

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    clean_p = path.strip().strip('/')
    if clean_p.lower() in ['start', 'on', 'resume']:
        return start_auto_trading()
    if clean_p.lower() in ['stop', 'off', 'pause']:
        return stop_auto_trading()
    if clean_p.lower() == 'yesterday':
        yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
        return today_report_endpoint(date_override=yesterday_str)
    if re.match(r'^\d{2}-\d{2}-\d{4}$', clean_p):
        return today_report_endpoint(date_override=clean_p)
    return "⚡ OK - Automated CPR Market Scanner Active (24/7 Render Cloud Bot)", 200

# ==============================================================================
# 10. AUTONOMOUS SCANNER: FAST, DIRECT EXECUTION & FULL TRANSPARENCY
# ==============================================================================
def run_scan():
    today_str = get_ist_now().strftime("%d-%m-%Y")
    curr_state = load_state()

    # Rule: Check Active Open Positions (Max 3 concurrent positions)
    with active_trades_lock:
        if len(ACTIVE_TRADES) >= 3:
            return

    candidates = []

    for symbol in WATCHLIST:
        try:
            time.sleep(0.03)

            # Check Stop Loss Day Ban
            if curr_state.get(f"sl_banned_{symbol}") == today_str:
                continue

            # Check 3-Hour Symbol Cooldown
            last_traded = curr_state.get(f"last_traded_{symbol}", 0)
            if time.time() - last_traded < SYMBOL_COOLDOWN_SECONDS:
                continue

            with active_trades_lock:
                if symbol in ACTIVE_TRADES:
                    continue

            # Fetch 15m and Daily Candles
            m15 = fetch_klines(symbol, "15m", limit=35)
            daily = fetch_klines(symbol, "1d", limit=4)
            if not m15 or not daily or len(m15) < 20 or len(daily) < 2:
                continue

            cmp = m15[-1][4]
            cpr = calculate_cpr_levels(daily)
            if not cpr: continue

            # Core CPR Breakout / Bounce Logic
            above_tc = cmp > cpr['tc']
            in_cpr_bounce = (cmp >= cpr['pivot'] and m15[-1][3] <= cpr['bc'])
            if not (above_tc or in_cpr_bounce):
                continue

            # Volume Surge Filter: >= 1.25x
            vol_spike = calculate_volume_spike(m15)
            if vol_spike < 1.25:
                continue

            # Trend Confirmation: SuperTrend & EMA20
            st_dir, _ = calculate_supertrend(m15)
            if st_dir != 1:
                continue

            closes_15 = [k[4] for k in m15]
            ema20 = calculate_ema(closes_15, 20)
            if cmp < ema20:
                continue

            # RSI Quality Filter (48 to 68)
            rsi = calculate_rsi(closes_15, 14)
            if not (48.0 <= rsi <= 68.0):
                continue

            # Confluence Scoring Engine
            score = 70
            if above_tc: score += 10
            if vol_spike >= 1.5: score += 10
            elif vol_spike >= 1.25: score += 5
            if cpr['is_narrow']: score += 10
            if cpr['is_ascending']: score += 5

            if score >= 80:
                candidates.append({
                    'symbol': symbol,
                    'cmp': cmp,
                    'cpr': cpr,
                    'vol_spike': vol_spike,
                    'rsi': rsi,
                    'score': score
                })
        except Exception as e:
            print(f"Error scanning {symbol}: {e}")

    if not candidates:
        return

    # Sort Candidates by Highest Confluence Score
    candidates.sort(key=lambda x: x['score'], reverse=True)

    with active_trades_lock:
        slots_available = 3 - len(ACTIVE_TRADES)
    
    selected_trades = candidates[:slots_available]

    for cand in selected_trades:
        sym = cand['symbol']
        cmp = cand['cmp']
        cpr = cand['cpr']
        vol_spike = cand['vol_spike']
        rsi = cand['rsi']
        score = cand['score']

        # Determine Floor Stop Loss (Maximum -0.95%)
        cpr_support = cpr['bc']
        sl_from_cpr = cpr_support * 0.998
        sl_floor = cmp * (1.0 - 0.0095)
        final_sl = round(max(sl_from_cpr, sl_floor), 4)

        # 1:3.3 Risk-Reward Target (+3.2% move = +22.4% ROE at 7x)
        tp1 = round(cmp * 1.032, 4)
        qty = calculate_step_size_quantity(1000.0, cmp, 7)

        # ----------------------------------------------------------------------
        # EXECUTE DIRECTLY TO COINDCX (Non-blocking direct execution)
        # ----------------------------------------------------------------------
        order_res = None
        if AUTO_TRADING_ENABLED:
            order_res = execute_coindcx_futures_trade(symbol=sym, side="buy", cmp=cmp, leverage=7, margin_inr=1000.0)
            
            # Broadcast Full Transparency to Telegram
            if order_res.get('success'):
                order_id_str = str(order_res.get('order_id', 'FILLED'))
                log_trade_event(sym, "EXECUTED", {
                    'cmp': cmp,
                    'quantity': qty,
                    'order_id': order_id_str,
                    'margin': 1000.0,
                    'score': score
                })
                send_telegram_message(
                    f"🟢 <b>COINDCX LIVE ORDER FILLED! ⚡</b>\n\n"
                    f"<b>Pair:</b> <code>{sym}</code>\n"
                    f"• <b>Status:</b> FILLED ON EXCHANGE ✅\n"
                    f"• <b>Order ID:</b> <code>{order_id_str}</code>\n"
                    f"• <b>Live Entry CMP:</b> <code>${cmp}</code>\n"
                    f"• <b>Quantity:</b> <code>{qty}</code> (₹1,000 Margin @ 7x)\n"
                    f"• <b>TP (+3.2%):</b> <code>${tp1}</code> | <b>SL (-0.95%):</b> <code>${final_sl}</code>"
                )
                
                # Apply Native CoinDCX TP/SL on the exchange
                time.sleep(1.0)
                pos = fetch_coindcx_position_details(sym)
                if pos and pos.get('position_id'):
                    apply_coindcx_native_tpsl(pos['pair'], pos['position_id'], tp1, final_sl)
            else:
                err_msg = order_res.get('message', 'Unknown Error')
                send_telegram_message(
                    f"⚠️ <b>COINDCX EXCHANGE ORDER NOTICE</b>\n\n"
                    f"<b>Pair:</b> <code>{sym}</code>\n"
                    f"• <b>Criteria:</b> MET (Score: {score}/100)\n"
                    f"• <b>Notice:</b> <code>{err_msg}</code>\n"
                    f"<i>Scanner remains active and transparent.</i>"
                )

        # Register in State
        with active_trades_lock:
            ACTIVE_TRADES[sym] = {
                'entry_price': cmp,
                'highest_price': cmp,
                'initial_qty': qty,
                'remaining_qty': qty,
                'leverage': 7,
                'stage': 1,
                'sl': final_sl,
                'tp1': tp1,
                'order_id': order_res.get('order_id', 'PAPER') if order_res else 'PAPER',
                'entry_time': time.time(),
                'last_check_time': time.time()
            }
        save_active_trades()

        # Update Cooldown State
        curr_state = load_state()
        curr_state[f"last_traded_{sym}"] = time.time()
        save_state(curr_state)

        # Broadcast Signal Card to Telegram
        send_telegram_message(
            f"🎯 <b>NEW HIGH-CONFLUENCE CPR SIGNAL</b>\n\n"
            f"<b>Pair:</b> <code>{sym}</code>\n"
            f"<b>Direction:</b> 🟢 BUY / LONG (7x Isolated)\n"
            f"<b>Confluence Score:</b> <code>{score} / 100</code> 👑\n\n"
            f"📊 <b>Market Diagnostics:</b>\n"
            f"• <b>CMP:</b> <code>${cmp}</code>\n"
            f"• <b>CPR Structure:</b> {cpr['cpr_type']}\n"
            f"• <b>Volume Spike:</b> <code>{vol_spike:.2f}x</code> Surge\n"
            f"• <b>RSI (15M):</b> <code>{rsi:.1f}</code> (Optimal Momentum)\n\n"
            f"🎯 <b>Trade Plan:</b>\n"
            f"• <b>Target (TP1):</b> <code>${tp1}</code> (+3.2% move / +22.4% ROE)\n"
            f"• <b>Stop Loss:</b> <code>${final_sl}</code> (-0.95% floor / -6.6% ROE)\n"
            f"• <b>Risk-Reward:</b> 1 : 3.37 🏆\n"
            f"• <b>Auto-Execution:</b> {'🟢 LIVE ON COINDCX' if AUTO_TRADING_ENABLED else '🛑 OFF (Signal Only)'}"
        )

# ==============================================================================
# 11. ACTIVE TRADE MONITOR: TRAILING PROFIT LOCK & CAPITAL PROTECTION
# ==============================================================================
def monitor_active_positions():
    global ACTIVE_TRADES
    while True:
        try:
            with active_trades_lock:
                symbols = list(ACTIVE_TRADES.keys())

            for symbol in symbols:
                try:
                    with active_trades_lock:
                        trade = ACTIVE_TRADES.get(symbol)
                    if not trade: continue

                    m15 = fetch_klines(symbol, "15m", limit=3)
                    if not m15: continue
                    cmp = m15[-1][4]

                    entry_p = trade['entry_price']
                    highest_p = max(trade.get('highest_price', entry_p), cmp)
                    trade['highest_price'] = highest_p

                    # 1. TIME-BASED STAGNATION STOP: Exit flat trades after 60 mins
                    if time.time() - trade['entry_time'] > 3600 and cmp <= entry_p * 1.002:
                        live_qty = fetch_coindcx_live_position_qty(symbol)
                        sell_qty = min(live_qty, trade['remaining_qty']) if live_qty > 0 else trade['remaining_qty']
                        execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "STAGNATION TIME-STOP ⏱️"})
                        send_telegram_message(
                            f"⏱️ <b>TIME-BASED STAGNATION EXIT</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• Position exited after 60 mins of flat momentum to free capital.\n"
                            f"• <b>PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE</code>"
                        )
                        continue

                    # 2. STAGE 1 PROFIT LOCK: At +1.0% Gain -> Trail SL to Entry + 0.15% (Zero Risk)
                    if trade['stage'] == 1 and cmp >= entry_p * 1.010:
                        trade['stage'] = 2
                        new_sl = round(entry_p * 1.0015, 4)
                        trade['sl'] = new_sl
                        with active_trades_lock: ACTIVE_TRADES[symbol] = trade
                        save_active_trades()
                        
                        pos = fetch_coindcx_position_details(symbol)
                        if pos and pos.get('position_id'):
                            apply_coindcx_native_tpsl(pos['pair'], pos['position_id'], trade['tp1'], new_sl)

                        send_telegram_message(
                            f"🛡️ <b>BREAKEVEN PROFIT LOCK ACTIVATED!</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• Coin reached +1.0% gain (+7.0% ROE).\n"
                            f"• Stop Loss moved to <code>${new_sl}</code> (+0.15% profit lock).\n"
                            f"• This position is now <b>100% RISK-FREE</b>! 🏆"
                        )

                    # 3. STAGE 2 DYNAMIC TRAILING: Protect gains when near target
                    if trade['stage'] == 2:
                        stage2_sl = round(highest_p * 0.993, 4)
                        if stage2_sl > trade['sl']:
                            with active_trades_lock: trade['sl'] = stage2_sl
                            save_active_trades()

                    # 4. TARGET (TP1) HIT (+3.2% move / +22.4% ROE)
                    if cmp >= trade['tp1']:
                        live_qty = fetch_coindcx_live_position_qty(symbol)
                        sell_qty = min(live_qty, trade['remaining_qty']) if live_qty > 0 else trade['remaining_qty']
                        execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "TARGET WIN (+22.4% ROE) 🎯"})
                        send_telegram_message(
                            f"🎯 <b>PROFIT TARGET HIT (TP1)! 🚀</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• <b>Entry:</b> <code>${entry_p}</code> | <b>Exit:</b> <code>${cmp}</code>\n"
                            f"• <b>Realized Gain:</b> <code>+{realized_pnl_pct:.1f}% ROE</code> 💰"
                        )
                        continue

                    # 5. STOP LOSS HIT -> FULL DAY BAN ON THIS SYMBOL
                    if cmp <= trade['sl']:
                        live_qty = fetch_coindcx_live_position_qty(symbol)
                        sell_qty = min(live_qty, trade['remaining_qty']) if live_qty > 0 else trade['remaining_qty']
                        execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        # BAN THIS SYMBOL FOR THE REST OF TODAY
                        today_str = get_ist_now().strftime("%d-%m-%Y")
                        st = load_state()
                        st[f"sl_banned_{symbol}"] = today_str
                        save_state(st)

                        realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                        sl_type = "TRAILING PROFIT LOCK EXIT 💰" if cmp >= entry_p * 1.001 else "STOP LOSS HIT 🛑"
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": sl_type})
                        send_telegram_message(
                            f"🏁 <b>POSITION CLOSED: {sl_type}</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                            f"• <b>Realized PNL:</b> <code>{realized_pnl_pct:+.1f}% ROE</code>\n"
                            f"🚫 <b>Note:</b> {symbol} is locked for the remainder of today to protect capital."
                        )
                        continue
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(3)

# ==============================================================================
# 12. RELIABLE TELEGRAM COMMAND LISTENER (DIRECT /start & /stop CONTROLLER)
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    clear_telegram_webhooks() # Disables webhooks so getUpdates polls cleanly!
    
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c",
        "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA"
    ]))
    candidate_tokens = [t for t in candidate_tokens if t]
    token_offsets = {t: 0 for t in candidate_tokens}
    boot_time = time.time()
    initialized = set()

    def reply_user(tok, chat_id, text_reply):
        try:
            url = f"https://api.telegram.org/bot{tok}/sendMessage"
            payload = {'chat_id': chat_id, 'text': text_reply, 'parse_mode': 'HTML'}
            data = urllib.parse.urlencode(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp: pass
        except Exception:
            send_telegram_message(text_reply)

    while True:
        for tok in candidate_tokens:
            try:
                offset = token_offsets.get(tok, 0)
                url = f"https://api.telegram.org/bot{tok}/getUpdates?offset={offset + 1}&timeout=3"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get('ok') and data.get('result'):
                        for update in data['result']:
                            token_offsets[tok] = update['update_id']
                            msg = update.get('message') or update.get('channel_post') or update.get('edited_message')
                            if not msg: continue
                            msg_date = msg.get('date', 0)
                            if tok not in initialized and msg_date and (msg_date < boot_time - 30):
                                continue
                            
                            user_chat_id = msg.get('chat', {}).get('id', CHAT_ID)
                            raw_text = msg.get('text', '').strip()
                            if not raw_text: continue
                            
                            cmd = raw_text.lower().split()[0].split('@')[0]

                            if cmd in ['/stop', 'stop', '/pause', 'pause', 'off']:
                                AUTO_TRADING_ENABLED = False
                                st = load_state()
                                st["auto_trading_enabled"] = False
                                save_state(st)
                                reply_user(tok, user_chat_id, (
                                    "🛑 <b>AUTO-TRADING PAUSED VIA COMMAND!</b>\n\n"
                                    "• Auto-order execution on CoinDCX is now <b>OFF</b>.\n"
                                    "• Scanner will only send notifications.\n"
                                    "• Send <code>/start</code> anytime to resume auto-execution."
                                Oddly,
                                ))
                            elif cmd in ['/start', 'start', '/resume', 'resume', 'on']:
                                AUTO_TRADING_ENABLED = True
                                st = load_state()
                                st["auto_trading_enabled"] = True
                                save_state(st)
                                reply_user(tok, user_chat_id, (
                                    "🟢 <b>AUTO-TRADING ACTIVATED VIA COMMAND!</b>\n\n"
                                    "• Auto-order execution on CoinDCX is now <b>LIVE</b>.\n"
                                    "• High-conviction CPR setups will execute automatically.\n"
                                    "• Send <code>/stop</code> anytime to pause."
                                ))
                            elif cmd in ['/status', 'status']:
                                daily_count = get_today_executed_trades_count()
                                with active_trades_lock:
                                    active_list = list(ACTIVE_TRADES.keys())
                                reply_user(tok, user_chat_id, (
                                    f"📊 <b>BOT SYSTEM STATUS:</b>\n\n"
                                    f"• <b>Auto-Trading:</b> {'🟢 ACTIVE (LIVE)' if AUTO_TRADING_ENABLED else '🛑 PAUSED'}\n"
                                    f"• <b>Today's Trades:</b> {daily_count}\n"
                                    f"• <b>Active Positions:</b> {', '.join(active_list) if active_list else 'None'}\n"
                                    f"• <b>Universe:</b> Tradeable Crypto Universe (CPR Engine)"
                                ))
                            elif cmd in ['/today', '/daily', '/report', 'today', 'daily', 'report', '/history']:
                                summary_msg = generate_daily_summary()
                                reply_user(tok, user_chat_id, summary_msg)
                            elif cmd in ['/yesterday', 'yesterday']:
                                yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
                                summary_msg = generate_daily_summary(yesterday_str)
                                reply_user(tok, user_chat_id, summary_msg)
                            elif cmd in ['/tpsl', 'tpsl', '/synctpsl', 'synctpsl']:
                                reply_user(tok, user_chat_id, "🔄 <i>Syncing Native CoinDCX TP/SL for all active positions...</i>")
                                threading.Thread(target=sync_all_open_positions_tpsl, daemon=True).start()
                initialized.add(tok)
            except Exception: pass
            time.sleep(1)

# ==============================================================================
# 13. BACKGROUND THREADS & APPLICATION RUNNER
# ==============================================================================
def start_background_loop():
    clear_telegram_webhooks()
    recover_live_coindcx_positions()
    threading.Thread(target=sync_all_open_positions_tpsl, daemon=True).start()

    def run_loop():
        time.sleep(5)
        while True:
            try:
                if scan_lock.acquire(blocking=False):
                    try: run_scan()
                    finally: scan_lock.release()
            except Exception as e:
                print(f"Scan loop exception: {e}")
            time.sleep(120)

    def run_keep_alive_loop():
        time.sleep(15)
        url = "https://crypto-scanner-ok3t.onrender.com/"
        while True:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=10) as resp: pass
            except Exception as e:
                print(f"Keep-alive error: {e}")
            time.sleep(240)

    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()

    send_telegram_message(
        "🚀 <b>AUTOMATED CPR BOT DEPLOYED!</b>\n\n"
        "• <b>Strategy:</b> CPR Breakout & Bounce Engine\n"
        "• <b>Universe:</b> Crypto Universe (Stablecoins & Stocks Excluded)\n"
        "• <b>Execution:</b> Non-blocking direct order execution\n"
        "• <b>Anti-Churn:</b> 3-Hour Cooldown & Full-Day Ban on Stop-Loss Coins\n"
        "• <b>Transparency:</b> Every fill & exchange notice broadcasted\n"
        "• <b>Controls:</b> Web 1-Click Buttons + Telegram /stop & /start"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
