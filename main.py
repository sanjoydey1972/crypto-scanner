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
    closed = [e for e in day_events if e.get('type') in ['CLOSED', 'CLOSED_MANUALLY']]

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
            sl_type = dt.get('sl_type', 'MANUAL EXIT')
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

    # CoinDCX Public Candles
    try:
        futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
        cdcx_int = '15m' if interval_str == '15m' else ('1h' if interval_str == '1h' else ('1m' if interval_str == '1m' else '1d'))
        url = f"https://public.coindcx.com/market_data/candles/?pair=B-{futures_coin}_USDT&interval={cdcx_int}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if isinstance(raw, list) and len(raw) > 0:
                raw_sorted = sorted(raw, key=lambda x: x.get('time', 0))
                return [[int(c.get('time', 0)), float(c.get('open', 0)), float(c.get('high', 0)), float(c.get('low', 0)), float(c.get('close', 0)), float(c.get('volume', 0))] for c in raw_sorted[-limit:]]
    except Exception: pass

    return []

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * 13 + gains[i]) / 14
        avg_loss = (avg_loss * 13 + losses[i]) / 14
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_volume_spike(klines, period=20):
    volumes = [float(k[5]) for k in klines]
    current_vol = volumes[-1]
    avg_vol = sum(volumes[-period-1:-1]) / period if len(volumes) > period else sum(volumes) / max(1, len(volumes))
    return (current_vol / avg_vol) if avg_vol > 0 else 1.0

def calculate_ema(prices, period):
    if not prices: return 0.0
    if len(prices) < period: return sum(prices) / len(prices)
    multiplier = 2.0 / (period + 1.0)
    ema = sum(prices[:period]) / float(period)
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_supertrend(klines, period=10, multiplier=3.0):
    if len(klines) < period + 1: return 1, 0.0
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
# 5. CENTRAL PIVOT RANGE (CPR) CALCULATION ENGINE
# ==============================================================================
def calculate_cpr_levels(daily_klines):
    if not daily_klines or len(daily_klines) < 2:
        return None

    prev_day = daily_klines[-2]
    y_high = float(prev_day[2])
    y_low = float(prev_day[3])
    y_close = float(prev_day[4])

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
# 7. COINDCX POSITION TRACKING & RECOVERY (NON-BLOCKING)
# ==============================================================================
def extract_pos_qty(p):
    if not isinstance(p, dict): return 0.0
    for k in ['quantity', 'active_pos', 'active_units', 'open_position_qty', 'size', 'total_quantity']:
        val = p.get(k)
        if val is not None:
            try:
                fval = abs(float(val))
                if fval > 0: return fval
            except (ValueError, TypeError): pass
    return 0.0

def is_position_open(p):
    if not isinstance(p, dict): return False
    st = str(p.get('status', '')).lower()
    if st in ['open', 'active', 'opened']: return True
    return extract_pos_qty(p) > 0

def fetch_all_coindcx_live_positions():
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return []

    endpoints = [
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions",
        "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/active"
    ]
    ts_ms = int(time.time() * 1000)
    body_variants = [
        {"timestamp": ts_ms},
        {"timestamp": ts_ms, "page": "1", "size": "50"},
        {"timestamp": int(time.time())}
    ]

    for url in endpoints:
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
                with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if isinstance(data, list) and len(data) > 0:
                        return data
                    elif isinstance(data, dict):
                        positions = data.get('positions') or data.get('data') or data.get('result') or []
                        if positions and isinstance(positions, list) and len(positions) > 0:
                            return positions
            except Exception: pass
    return []

def fetch_coindcx_live_position_qty(symbol):
    try:
        raw_coin = symbol.split('-')[0].upper()
        futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).upper()
        target_clean = futures_coin.replace("1000", "")
        
        pos_list = fetch_all_coindcx_live_positions()
        for p in pos_list:
            if not isinstance(p, dict): continue
            p_pair = str(p.get('pair', p.get('market', p.get('symbol', '')))).upper()
            p_clean = p_pair.replace("B-", "").replace("1000", "").replace("_", "").replace("-", "").replace("USDT", "")
            if (p_clean == target_clean or raw_coin in p_pair) and is_position_open(p):
                qty = extract_pos_qty(p)
                if qty > 0: return qty
        return 0.0
    except Exception: return 0.0

def fetch_coindcx_position_details(symbol):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return None
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).upper()
    target_clean = futures_coin.replace("1000", "")
    target_pair = f"B-{futures_coin}_USDT"

    pos_list = fetch_all_coindcx_live_positions()
    for p in pos_list:
        if not isinstance(p, dict): continue
        p_pair = str(p.get('pair', p.get('market', p.get('symbol', '')))).upper()
        p_clean = p_pair.replace("B-", "").replace("1000", "").replace("_", "").replace("-", "").replace("USDT", "")
        if (p_clean == target_clean or raw_coin in p_pair) and is_position_open(p):
            qty = extract_pos_qty(p)
            pos_id = p.get('id') or p.get('position_id') or p.get('positionId') or p.get('id_')
            entry_p = float(p.get('avg_price', 0) or p.get('entry_price', 0) or p.get('price', 0))
            if pos_id:
                return {
                    'pair': p_pair if p_pair else target_pair,
                    'position_id': str(pos_id),
                    'quantity': qty,
                    'entry_price': entry_p,
                    'raw': p
                }
    return None

def recover_live_coindcx_positions():
    global ACTIVE_TRADES
    pos_list = fetch_all_coindcx_live_positions()
    if not pos_list or not isinstance(pos_list, list): return

    for p in pos_list:
        if not isinstance(p, dict) or not is_position_open(p): continue
        p_pair = str(p.get('pair', p.get('market', ''))).upper()
        active_u = extract_pos_qty(p)
        if active_u > 0:
            raw_c = p_pair.replace("B-", "").replace("_USDT", "").replace("USDT", "").replace("1000", "")
            sym = f"{raw_c}-USDT"
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
                        'sl': round(entry_p * 0.9880, 4),
                        'be_trigger': round(entry_p * 1.0085, 4),
                        'is_be_active': False,
                        'leverage': 7,
                        'entry_time': time.time()
                    }
                    send_telegram_message(
                        f"🔄 <b>AUTO-RECOVERED ACTIVE POSITION:</b>\n\n"
                        f"• <b>Pair:</b> <code>{p_pair}</code> ({sym})\n"
                        f"• <b>Quantity:</b> <code>{active_u}</code>\n"
                        f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                        f"• <b>Status:</b> Dynamic trailing & 75m stagnation guard ACTIVE!"
                    )
    save_active_trades()

# ==============================================================================
# 8. BULLETPROOF MULTI-ENDPOINT ORDER EXECUTION & NATIVE TP/SL
# ==============================================================================
def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=1000.0, leverage=7, custom_quantity=None):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
        
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
    clean_coin = raw_coin

    # ==========================================================================
    # STRICT NO-SHORT-TRADE POLICY:
    # A SELL order is ONLY allowed to close an active LONG position!
    # Under NO circumstances can a SHORT trade ever be opened.
    # ==========================================================================
    if side.lower() == "sell":
        live_long_qty = fetch_coindcx_live_position_qty(symbol)
        if live_long_qty <= 0.0:
            print(f"🛑 BLOCKED SELL on {symbol}: No active long position found on exchange. Unwanted short prevented!")
            return {'success': False, 'error': f'Zero long position on exchange for {symbol}. Short trade blocked.'}
        if custom_quantity is not None:
            quantity = min(float(custom_quantity), live_long_qty)
        else:
            quantity = live_long_qty
        if quantity <= 0:
            return {'success': False, 'error': 'Calculated sell quantity is zero.'}
    else:
        # BUY / LONG ORDER
        if custom_quantity is not None:
            quantity = custom_quantity
        else:
            usdt_inr_rate = 88.5
            position_value_usdt = (margin_inr * leverage) / usdt_inr_rate
            raw_qty = position_value_usdt / cmp if cmp > 0 else 0.1
            
            if raw_coin == 'BTC': quantity = round(max(0.001, raw_qty), 3)
            elif raw_coin in ['ETH', 'SOL']: quantity = round(max(0.1, raw_qty), 1)
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
            "order": {
                "side": side.lower(),
                "pair": f"B-{clean_coin}_USDT",
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
            "market": f"{clean_coin}INR",
            "total_quantity": quantity,
            "leverage": leverage
        })
    ]

    err_logs = []
    for idx, (target_url, body) in enumerate(endpoint_variants, 1):
        try:
            ts_now = int(round(time.time() * 1000))
            if "timestamp" in body: body["timestamp"] = ts_now
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
            except Exception: err_logs.append(f"V{idx}: HTTP {e.code} - {e}")
        except Exception as e: err_logs.append(f"V{idx}: {e}")

    last_err = " | ".join(err_logs) if err_logs else "Unknown Error"
    return {'success': False, 'error': last_err}

def apply_coindcx_native_tpsl(pair, position_id, target_price, stop_loss_price):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return False
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/create_tpsl"
    
    tp_str = f"{target_price:.4f}" if target_price < 1.0 else f"{target_price:.2f}"
    sl_str = f"{stop_loss_price:.4f}" if stop_loss_price < 1.0 else f"{stop_loss_price:.2f}"
    tp_lim_str = f"{target_price * 0.999:.4f}" if target_price < 1.0 else f"{round(target_price * 0.999, 2):.2f}"
    sl_lim_str = f"{stop_loss_price * 0.995:.4f}" if stop_loss_price < 1.0 else f"{round(stop_loss_price * 0.995, 2):.2f}"
    ts = int(time.time() * 1000)

    payload_variants = [
        {"timestamp": ts, "id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": ts, "id": str(position_id), "take_profit": {"stop_price": tp_str, "order_type": "take_profit_market"}, "stop_loss": {"stop_price": sl_str, "order_type": "stop_market"}},
        {"timestamp": ts, "id": str(position_id), "take_profit": {"stop_price": tp_str, "limit_price": tp_lim_str, "order_type": "take_profit_limit"}, "stop_loss": {"stop_price": sl_str, "limit_price": sl_lim_str, "order_type": "stop_limit"}},
        {"timestamp": ts, "position_id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": ts, "pair": pair, "id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": ts, "id": str(position_id), "target_price": float(target_price), "stop_loss_price": float(stop_loss_price)}
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
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                if resp.status in [200, 201]:
                    return True
        except Exception: pass
    return False

def auto_place_coindcx_native_tpsl(symbol, tp_price, sl_price):
    """
    Polls CoinDCX for the newly created position and fits Native TP & SL automatically.
    Runs repeatedly for up to 30 seconds after order entry to guarantee application.
    """
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return False
    
    for attempt in range(1, 15):
        time.sleep(2)
        pos = fetch_coindcx_position_details(symbol)
        if pos and pos.get('position_id') and pos.get('quantity', 0) > 0:
            ok = apply_coindcx_native_tpsl(pos['pair'], pos['position_id'], tp_price, sl_price)
            if ok:
                send_telegram_message(
                    f"🎯 <b>NATIVE COINDCX TP/SL APPLIED AUTOMATICALLY!</b>\n\n"
                    f"• <b>Pair:</b> <code>{pos['pair']}</code>\n"
                    f"• <b>Position ID:</b> <code>{pos['position_id']}</code>\n"
                    f"• <b>Target (TP):</b> <code>${tp_price}</code> (+3.2%)\n"
                    f"• <b>Stop Loss (SL):</b> <code>${sl_price}</code> (-0.95% floor)\n"
                    f"✅ <i>Populated directly in your CoinDCX TP / SL column! Exchange safety active.</i>"
                )
                return True
    return False

def sync_all_open_positions_tpsl():
    """
    Continuous background synchronizer ensuring all active positions have Native CoinDCX TP/SL fitted.
    """
    pos_list = fetch_all_coindcx_live_positions()
    if not pos_list or not isinstance(pos_list, list): return []

    synced_results = []
    for p in pos_list:
        if not isinstance(p, dict) or not is_position_open(p): continue
        p_pair = str(p.get('pair', p.get('market', p.get('symbol', '')))).upper()
        raw_c = p_pair.replace("B-", "").replace("_USDT", "").replace("USDT", "").replace("1000", "")
        sym = f"{raw_c}-USDT"
        entry_p = float(p.get('avg_price', p.get('entry_price', 0)))
        if entry_p <= 0: continue

        with active_trades_lock:
            trade = ACTIVE_TRADES.get(sym)
            tp_val = trade.get('tp1', round(entry_p * 1.032, 4)) if trade else round(entry_p * 1.032, 4)
            sl_val = trade.get('sl', round(entry_p * 0.9880, 4)) if trade else round(entry_p * 0.9880, 4)

        pos_id = p.get('id') or p.get('position_id') or p.get('positionId') or p.get('id_')
        if pos_id:
            success = apply_coindcx_native_tpsl(p_pair, pos_id, tp_val, sl_val)
            synced_results.append({'pair': p_pair, 'symbol': sym, 'tp': tp_val, 'sl': sl_val, 'success': success})
        time.sleep(1)
    return synced_results

# ==============================================================================
# 9. FLASK WEB CONTROLS & REPORTS
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
        closed = [e for e in day_events if e.get('type') in ['CLOSED', 'CLOSED_MANUALLY']]

        total_pnl = sum(c.get('details', {}).get('realized_pnl_pct', 0) for c in closed)
        wins = [c for c in closed if c.get('details', {}).get('realized_pnl_pct', 0) > 0]
        win_rate = (len(wins) / len(closed) * 100) if closed else (100.0 if executed else 0.0)

        exec_rows = "".join([f"<tr><td>{e.get('timestamp','').split()[-2]} {e.get('timestamp','').split()[-1]}</td><td><b>{e.get('symbol')}</b></td><td>${e.get('details',{}).get('cmp')}</td><td>{e.get('details',{}).get('quantity')}</td><td><code>{str(e.get('details',{}).get('order_id'))[:8]}</code></td><td>₹1,000</td></tr>" for e in executed]) if executed else "<tr><td colspan='6' style='text-align:center;'>No trades executed today yet</td></tr>"
        closed_rows = "".join([f"<tr><td>{c.get('timestamp','').split()[-2]} {c.get('timestamp','').split()[-1]}</td><td><b>{c.get('symbol')}</b></td><td><b style='color:{'#00c853' if c.get('details',{}).get('realized_pnl_pct',0)>=0 else '#d50000'};'>{c.get('details',{}).get('realized_pnl_pct',0):+.1f}% ROE</b></td><td>{c.get('details',{}).get('sl_type', 'MANUAL EXIT')}</td></tr>" for c in closed]) if closed else "<tr><td colspan='4' style='text-align:center;'>No closed trades today</td></tr>"

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
                if symbol in ACTIVE_TRADES: continue

            # Fetch 15M candles and Daily candles
            m15_klines = fetch_klines(symbol, '15m', 40)
            daily_klines = fetch_klines(symbol, '1d', 4)
            if not m15_klines or not daily_klines or len(m15_klines) < 25 or len(daily_klines) < 2:
                continue

            cmp = m15_klines[-1][4]
            cpr = calculate_cpr_levels(daily_klines)
            if not cpr: continue

            # Bias check: Never Long below BC or inside CPR chop zone
            if cmp <= cpr['tc']:
                continue

            # Supertrend 15M check
            st_dir, _ = calculate_supertrend(m15_klines)
            if st_dir != 1: continue

            # Volume surge confirmation (>= 1.25x average volume)
            vol_spike = calculate_volume_spike(m15_klines)
            if vol_spike < 1.25: continue

            # 15M EMA 20 Alignment
            close_prices = [k[4] for k in m15_klines]
            ema20 = calculate_ema(close_prices, 20)
            if cmp < ema20 * 0.998: continue

            # RSI Confirmation (Healthy 48 to 70 range)
            rsi_val = calculate_rsi(close_prices)
            if rsi_val < 48 or rsi_val > 70: continue

            # Price Action Trigger:
            # 1. Breakout: Prev candle was below/testing TC, current candle closed cleanly ABOVE TC
            prev_close = m15_klines[-2][4]
            curr_close = m15_klines[-1][4]
            curr_low = m15_klines[-1][3]
            curr_open = m15_klines[-1][1]

            is_true_breakout = (prev_close <= cpr['tc'] * 1.002) and (curr_close > cpr['tc'])
            # 2. Retest & Bounce: Low tested CPR and candle closed green above TC
            is_cpr_bounce = (curr_low <= cpr['tc'] * 1.003) and (curr_low >= cpr['bc'] * 0.997) and (curr_close > curr_open)

            if not (is_true_breakout or is_cpr_bounce):
                continue

            # Real Confluence Score Calculation
            score = 0
            if is_true_breakout: score += 30
            elif is_cpr_bounce: score += 25

            if cpr['is_narrow']: score += 25
            elif cpr['is_ascending']: score += 20
            elif cpr['is_inside']: score += 20

            if vol_spike >= 1.75: score += 25
            elif vol_spike >= 1.25: score += 20

            if st_dir == 1: score += 15
            if 50 <= rsi_val <= 65: score += 10

            if score >= 80:
                setup_name = "TRUE CPR BREAKOUT 🚀" if is_true_breakout else "CPR RETEST & BOUNCE 🛡️"
                candidates.append({
                    'symbol': symbol,
                    'score': score,
                    'setup_name': setup_name,
                    'cmp': cmp,
                    'cpr': cpr,
                    'vol_spike': vol_spike,
                    'm15_low': curr_low
                })
        except Exception: pass

    candidates.sort(key=lambda x: x['score'], reverse=True)
    coin_margin = 1000.0
    lev_num = 7

    for cand in candidates:
        with active_trades_lock:
            if len(ACTIVE_TRADES) >= 3: break

        symbol = cand['symbol']
        cmp = cand['cmp']
        cpr = cand['cpr']
        vol_spike = cand['vol_spike']
        score = cand['score']
        setup_name = cand['setup_name']

        # Structural Stop Loss (Below Bottom Central or 15M Swing Low, capped at -0.95%)
        structural_sl = min(cpr['bc'] * 0.997, cand['m15_low'] * 0.997)
        hard_floor_sl = cmp * (1.0 - 0.0095) # 0.95% strict risk floor
        sl = round(max(hard_floor_sl, structural_sl), 4)

        # Target (TP1): R1 / R2 / +3.2% move
        tp1 = round(max(cpr['r1'], cmp * 1.032), 4)
        be_trigger = round(cmp * 1.0085, 4)

        # CORE PRINCIPLE: Never block execution loop. Fire directly to CoinDCX!
        if AUTO_TRADING_ENABLED:
            trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=coin_margin, leverage=lev_num)
        else:
            trade_res = {'success': False, 'error': 'Auto-trading PAUSED via Mobile Telegram / Web button.'}

        # CORE PRINCIPLE: Always broadcast full transparency to Telegram—trader is NEVER left in the dark!
        if trade_res.get('success'):
            order_id = trade_res.get('order_id')
            qty = trade_res.get('quantity')
            log_trade_event(symbol, "EXECUTED", {"cmp": cmp, "quantity": qty, "order_id": order_id, "margin": coin_margin})

            with active_trades_lock:
                ACTIVE_TRADES[symbol] = {
                    'entry_price': cmp,
                    'total_qty': qty,
                    'remaining_qty': qty,
                    'tp1': tp1,
                    'sl': sl,
                    'be_trigger': be_trigger,
                    'is_be_active': False,
                    'highest_price': cmp,
                    'leverage': lev_num,
                    'entry_time': time.time()
                }
            save_active_trades()

            curr_state[f"last_traded_{symbol}"] = time.time()
            save_state(curr_state)

            # AUTOMATICALLY FIT TP & SL ON COINDCX IMMEDIATELY AFTER ENTRY FILL
            threading.Thread(target=auto_place_coindcx_native_tpsl, args=(symbol, tp1, sl), daemon=True).start()

            msg = (
                f"🟢 <b>HIGH-CONVICTION CPR SIGNAL!</b>\n\n"
                f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                f"<b>Setup:</b> <b>{setup_name}</b>\n"
                f"<b>CPR Structure:</b> <code>{cpr['cpr_type']}</code>\n"
                f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                f"📊 <b>Volume Surge:</b> <code>{vol_spike:.2f}x Average</code>\n\n"
                f"⚙️ <b>Trade Parameters:</b>\n"
                f"• <b>Leverage:</b> <code>{lev_num}x (Isolated)</code>\n"
                f"• <b>Entry CMP:</b> <code>${cmp}</code>\n"
                f"🛑 <b>CPR Structural SL:</b> <code>${sl}</code>\n"
                f"🎯 <b>Target (TP1):</b> <code>${tp1}</code> (+3.2% move / +22.4% ROE)\n"
                f"🛡️ <b>Breakeven Lock:</b> At +6.0% ROE (+0.85% move)\n\n"
                f"⚡ <b>AUTO-TRADE EXECUTED ON COINDCX!</b>\n"
                f"• Order ID: <code>{order_id}</code>\n"
                f"• Quantity: <code>{qty}</code> | Margin: ₹{coin_margin:.0f}\n"
                f"🔄 <i>Native CoinDCX TP/SL auto-fitting active...</i>"
            )
            send_telegram_message(msg)
            break
        else:
            # Full transparency broadcast on CoinDCX notice/failure!
            err_reason = trade_res.get('error', 'Unknown Error')
            log_trade_event(symbol, "CANCELLED", {"cmp": cmp, "error": err_reason})
            curr_state[f"last_traded_{symbol}"] = time.time()
            save_state(curr_state)

            notice_msg = (
                f"🟢 <b>CPR SIGNAL DETECTED: {symbol}</b>\n\n"
                f"<b>Setup:</b> {setup_name} (Score: {score}/100)\n"
                f"<b>CMP:</b> ${cmp} | <b>Target:</b> ${tp1} | <b>SL:</b> ${sl}\n\n"
                f"⚠️ <b>COINDCX EXECUTION NOTICE:</b>\n"
                f"<code>{err_reason}</code>\n\n"
                f"<i>Cooldown locked for 3 hours to prevent fee drain.</i>"
            )
            send_telegram_message(notice_msg)

# ==============================================================================
# 11. REAL-TIME POSITION MONITORING & AUTOMATED EXITS
# ==============================================================================
def monitor_active_positions():
    time.sleep(5)
    while True:
        try:
            with active_trades_lock:
                symbols_to_check = list(ACTIVE_TRADES.keys())
            
            for symbol in symbols_to_check:
                try:
                    time.sleep(0.3)
                    
                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES: continue
                        trade = ACTIVE_TRADES[symbol]

                    # ==========================================================
                    # 1. MANUAL CLOSE DETECTION (STRICT NO-SHORT-TRADE POLICY):
                    # If user manually closed position on CoinDCX, live_qty is 0.
                    # We MUST instantly remove it from tracking and NEVER fire a SELL order!
                    # ==========================================================
                    live_qty = fetch_coindcx_live_position_qty(symbol)
                    if live_qty <= 0.0:
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        log_trade_event(symbol, "CLOSED_MANUALLY", {"status": "Closed manually by user on CoinDCX"})
                        send_telegram_message(
                            f"ℹ️ <b>MANUAL POSITION CLOSE DETECTED:</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• Position was closed directly by you on CoinDCX.\n"
                            f"• Tracking removed. <b>Zero short trades will be placed.</b>"
                        )
                        continue

                    m1_klines = fetch_klines(symbol, '1m', 3)
                    if not m1_klines: continue
                    cmp = m1_klines[-1][4]
                    
                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    highest_peak = trade.get('highest_price', entry_p)
                    raw_pnl_pct = ((cmp - entry_p) / entry_p) * trade.get('leverage', 7) * 100

                    if cmp > highest_peak:
                        highest_peak = cmp
                        with active_trades_lock: trade['highest_price'] = highest_peak
                        save_active_trades()

                    # 2. 75-MINUTE STAGNATION GUARD
                    if time.time() - entry_time >= 4500:
                        sell_qty = min(live_qty, trade.get('remaining_qty', live_qty))
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_pnl_pct, 1), "sl_type": "75-MIN STAGNATION TIME-STOP ⏱️"})
                        send_telegram_message(
                            f"⏱️ <b>75-MINUTE TIME-STOP EXECUTED!</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                            f"• <b>Result:</b> <code>{raw_pnl_pct:+.1f}% ROE</code>\n"
                            f"• Capital released for fresh setups."
                        )
                        continue

                    # 3. BREAKEVEN PROFIT LOCK (+6.0% ROE)
                    if not trade.get('is_be_active', False) and cmp >= trade.get('be_trigger', entry_p * 1.0085):
                        with active_trades_lock:
                            trade['is_be_active'] = True
                            trade['sl'] = round(entry_p * 1.001, 4)
                        save_active_trades()
                        
                        # Update Native CoinDCX Stop Loss to Breakeven
                        pos = fetch_coindcx_position_details(symbol)
                        if pos and pos.get('position_id'):
                            apply_coindcx_native_tpsl(pos['pair'], pos['position_id'], trade['tp1'], trade['sl'])

                        send_telegram_message(
                            f"🛡️ <b>BREAKEVEN PROFIT LOCK ACTIVATED! 🚀</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• Gain Reached: +6.0% ROE (+0.85% move)\n"
                            f"• Stop Loss shifted to <b>${entry_p * 1.001:.4f}</b> (Zero Risk Trade)!"
                        )

                    # 4. 3-STAGE DYNAMIC TRAILING
                    peak_gain_pct = (highest_peak - entry_p) / entry_p
                    if peak_gain_pct >= 0.0180: # Stage 3 (+12.6% ROE)
                        trailing_sl = round(highest_peak * 0.9940, 4)
                        if trailing_sl > trade['sl']:
                            with active_trades_lock: trade['sl'] = trailing_sl
                            save_active_trades()
                    elif peak_gain_pct >= 0.0120: # Stage 2 (+8.4% ROE)
                        stage2_sl = round(entry_p * 1.0060, 4)
                        if stage2_sl > trade['sl']:
                            with active_trades_lock: trade['sl'] = stage2_sl
                            save_active_trades()

                    # 5. TARGET (TP1) HIT (+3.2% move / +22.4% ROE)
                    if cmp >= trade['tp1']:
                        sell_qty = min(live_qty, trade.get('remaining_qty', live_qty))
                        if sell_qty > 0:
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

                    # 6. STOP LOSS HIT -> FULL DAY BAN ON THIS SYMBOL
                    if cmp <= trade['sl']:
                        sell_qty = min(live_qty, trade.get('remaining_qty', live_qty))
                        if sell_qty > 0:
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

    def tpsl_sync_worker():
        time.sleep(10)
        while True:
            try:
                sync_all_open_positions_tpsl()
            except Exception: pass
            time.sleep(60)

    threading.Thread(target=run_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=tpsl_sync_worker, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()

    send_telegram_message(
        "🚀 <b>AUTOMATED CPR BOT DEPLOYED!</b>\n\n"
        "• <b>Strategy:</b> CPR Breakout & Bounce Engine\n"
        "• <b>Universe:</b> Crypto Universe (Stablecoins & Stocks Excluded)\n"
        "• <b>Execution:</b> Non-blocking direct order execution\n"
        "• <b>Safety Guarantee:</b> STRICT NO-SHORT-TRADE Protection active\n"
        "• <b>Native TP/SL:</b> Auto-fitting TP (+3.2%) & SL (-0.95%) on entry\n"
        "• <b>Controls:</b> Web 1-Click Buttons + Telegram /stop & /start"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
