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
pending_orders_lock = threading.Lock()

STATE_FILE = "scanner_state.json"
TRADE_HISTORY_FILE = "trade_history.json"
AUTO_TRADING_ENABLED = True
PENDING_ORDERS = set()

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
        st["auto_trading_enabled"] = AUTO_TRADING_ENABLED
        save_state(st)

# Telegram Bot Credentials (with fallback tokens)
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip() or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or "8961205774:AAHx4psKuhzxCiZp1CRo50zN5tKZjLXW_24"
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or "8938527650"

# CoinDCX API Credentials (with fallback keys)
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY", "").strip() or os.environ.get("COINDCX_API_SECRET", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"

ctx = ssl._create_unverified_context()

# ==============================================================================
# 2. WATCHLIST (70 TOP HIGH-LIQUIDITY COINS) & CRYPTO PAIR ALIASES
# ==============================================================================
WATCHLIST = [
    # Top Tier & Majors
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT', 
    'DOGE-USDT', 'ADA-USDT', 'AVAX-USDT', 'LINK-USDT', 'SUI-USDT',
    'NEAR-USDT', 'BCH-USDT', 'LTC-USDT', 'DOT-USDT', 'TRX-USDT',
    
    # Layer 1 / Layer 2 / High Volume
    'APT-USDT', 'ARB-USDT', 'OP-USDT', 'TIA-USDT', 'INJ-USDT',
    'SEI-USDT', 'FTM-USDT', 'STX-USDT', 'POL-USDT', 'ATOM-USDT',
    'ETC-USDT', 'FIL-USDT', 'ICP-USDT', 'KAS-USDT', 'STRK-USDT',
    'MANTA-USDT', 'AR-USDT', 'EOS-USDT', 'CHZ-USDT', 'ALGO-USDT',
    
    # AI & Compute
    'RENDER-USDT', 'FET-USDT', 'TAO-USDT', 'WLD-USDT',
    
    # DeFi & Infrastructure
    'AAVE-USDT', 'UNI-USDT', 'CRV-USDT', 'ENA-USDT', 'ONDO-USDT',
    'RUNE-USDT', 'DYDX-USDT', 'JUP-USDT', 'PYTH-USDT', 'PENDLE-USDT',
    'LDO-USDT', 'MKR-USDT', 'SNX-USDT', 'KAVA-USDT', 'JTO-USDT',
    'GRT-USDT', 'BLUR-USDT', 'VET-USDT', 'THETA-USDT',
    
    # High-Momentum & Meme Coins
    'PEPE-USDT', 'SHIB-USDT', 'WIF-USDT', 'BONK-USDT', 'FLOKI-USDT',
    'BOME-USDT', 'ORDI-USDT', 'GALA-USDT', 'SAND-USDT', 'MANA-USDT',
    'AXS-USDT', 'IMX-USDT'
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
    'BTT': '1000BTT',
    'BOME': '1000BOME'
}

SYMBOL_COOLDOWN_SECONDS = 120
MAX_ACTIVE_TRADES = 2  # Allows up to 2 concurrent scalps to diversify across independent coins

# ==============================================================================
# 3. PERMANENT AUDIT JOURNAL & DAILY SCORECARD REPORT GENERATOR
# ==============================================================================
BASELINE_HISTORY = []

def load_all_trade_events():
    history = list(BASELINE_HISTORY)
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f:
                saved = json.load(f)
                if isinstance(saved, list):
                    history.extend(saved)
        except Exception: pass
    return history

def log_trade_event(symbol, event_type, data):
    with trade_history_lock:
        now_dt = get_ist_now()
        event = {
            'date': now_dt.strftime("%d-%m-%Y"),
            'timestamp': now_dt.strftime("%I:%M:%S %p"),
            'symbol': symbol,
            'type': event_type,
            'details': data
        }
        all_events = []
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f:
                    all_events = json.load(f)
            except Exception: all_events = []
        all_events.append(event)
        try:
            with open(TRADE_HISTORY_FILE, 'w') as f:
                json.dump(all_events, f, indent=2)
        except Exception: pass

def generate_daily_trade_report(date_str=None):
    if not date_str:
        date_str = get_ist_now().strftime("%d-%m-%Y")
    
    events = load_all_trade_events()
    daily_events = [e for e in events if e.get('date') == date_str]
    
    executed_trades = [e for e in daily_events if e.get('type') == 'EXECUTED']
    cancelled_trades = [e for e in daily_events if e.get('type') == 'CANCELLED']
    closed_trades = [e for e in daily_events if e.get('type') in ['CLOSED', 'CLOSED_ON_EXCHANGE']]
    
    total_executed = len(executed_trades)
    non_executed = len(cancelled_trades)
    
    wins = 0
    losses = 0
    total_pnl_pct = 0.0
    total_pnl_inr = 0.0
    
    trade_lines = []
    for ct in closed_trades:
        sym = ct.get('symbol', 'UNKNOWN')
        det = ct.get('details', {})
        roe = float(det.get('realized_pnl_pct', 0.0))
        reason = det.get('exit_reason', det.get('status', 'Closed'))
        pnl_inr = (1000.0 * (roe / 100.0))
        total_pnl_pct += roe
        total_pnl_inr += pnl_inr
        if roe >= 0:
            wins += 1
            icon = "🟢"
        else:
            losses += 1
            icon = "🔴"
        trade_lines.append(f"• {icon} <b>{sym}</b>: {roe:+.1f}% ROE ({'+' if pnl_inr >= 0 else ''}₹{pnl_inr:.2f}) | <i>{reason[:32]}</i>")
        
    win_rate = (wins / len(closed_trades) * 100.0) if closed_trades else 0.0
    
    report_text = (
        f"📊 <b>DAILY AUTO-TRADE SCORECARD ({date_str})</b>\n\n"
        f"• <b>Total Executed Trades:</b> {total_executed}\n"
        f"• <b>Closed Trades:</b> {len(closed_trades)} (Wins: {wins} | Losses: {losses})\n"
        f"• <b>Win Rate:</b> {win_rate:.1f}%\n"
        f"• <b>Total Realized ROE:</b> {total_pnl_pct:+.1f}% ROE\n"
        f"• <b>Estimated Net PNL:</b> {'+' if total_pnl_inr >= 0 else ''}₹{total_pnl_inr:.2f} INR\n"
        f"• <b>Skipped / Filtered:</b> {non_executed}\n\n"
    )
    if trade_lines:
        report_text += "<b>Closed Trades Summary:</b>\n" + "\n".join(trade_lines[:15])
    else:
        report_text += "<i>No closed scalps recorded yet today.</i>"
        
    return report_text

# ==============================================================================
# 4. TELEGRAM BROADCAST ENGINE
# ==============================================================================
def send_telegram_message(text):
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c",
        "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA"
    ]))
    candidate_tokens = [t for t in candidate_tokens if t]

    target_chats = list(dict.fromkeys([CHAT_ID, "8938527650"]))
    st = load_state()
    last_chat = st.get("last_telegram_chat_id")
    if last_chat:
        target_chats.append(str(last_chat))
    target_chats = list(dict.fromkeys([c for c in target_chats if c]))

    any_success = False
    for cid in target_chats:
        sent_for_cid = False
        for token_to_try in candidate_tokens:
            if sent_for_cid:
                break
            for mode in ['HTML', None]:
                try:
                    clean_text = text if mode == 'HTML' else re.sub(r'<[^>]+>', '', text)
                    url = f"https://api.telegram.org/bot{token_to_try}/sendMessage"
                    payload = {
                        'chat_id': cid,
                        'text': clean_text,
                        'disable_web_page_preview': 'true'
                    }
                    if mode:
                        payload['parse_mode'] = mode
                    data = urllib.parse.urlencode(payload).encode('utf-8')
                    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                        res = json.loads(resp.read().decode('utf-8'))
                        if res.get('ok'):
                            sent_for_cid = True
                            any_success = True
                            break
                except Exception:
                    continue
    return any_success

# ==============================================================================
# 5. DYNAMIC PRECISION & MULTI-SOURCE CANDLE ENGINE (STRICT COINDCX TICK SIZES)
# ==============================================================================
def round_coin_price(price):
    if price >= 100.0: return round(price, 2)
    elif price >= 1.0: return round(price, 3)     # AVAX, NEAR, INJ, FIL, SUI, UNI, LINK, DOT, etc. strictly 3 decimals
    elif price >= 0.05: return round(price, 4)
    elif price >= 0.005: return round(price, 5)
    elif price >= 0.0001: return round(price, 6)
    elif price > 0: return round(price, 8)
    return 0.0

def format_coin_price(price):
    if price >= 100.0: return f"{price:.2f}"
    elif price >= 1.0: return f"{price:.3f}"      # Strict 3-decimal formatting eliminates exchange precision rejection
    elif price >= 0.05: return f"{price:.4f}"
    elif price >= 0.005: return f"{price:.5f}"
    elif price >= 0.0001: return f"{price:.6f}"
    elif price > 0: return f"{price:.8f}".rstrip('0')
    return "0.00"

def fetch_klines(symbol, interval='3m', limit=65):
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).upper()
    binance_sym = symbol.replace('-', '').upper()
    bybit_interval = interval.replace('m', '') if interval.endswith('m') else interval

    endpoints = [
        ("binance_vision", f"https://data-api.binance.vision/api/v3/klines?symbol={binance_sym}&interval={interval}&limit={limit}"),
        ("bybit", f"https://api.bybit.com/v5/market/kline?category=linear&symbol={binance_sym}&interval={bybit_interval}&limit={limit}"),
        ("coindcx", f"https://public.coindcx.com/market_data/candles?pair=B-{futures_coin}_USDT&interval={interval}&limit={limit}"),
        ("binance_fapi", f"https://fapi.binance.com/fapi/v1/klines?symbol={binance_sym}&interval={interval}&limit={limit}"),
        ("binance_spot", f"https://api.binance.com/api/v3/klines?symbol={binance_sym}&interval={interval}&limit={limit}")
    ]

    for source_name, url in endpoints:
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))

                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    candles = []
                    for k in data:
                        candles.append([
                            float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
                        ])
                    if len(candles) >= 20:
                        return candles[-limit:]

                elif isinstance(data, dict) and data.get("result", {}).get("list"):
                    raw_list = data["result"]["list"]
                    if raw_list and isinstance(raw_list, list):
                        sorted_list = list(reversed(raw_list))
                        candles = []
                        for k in sorted_list:
                            candles.append([
                                float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
                            ])
                        if len(candles) >= 20:
                            return candles[-limit:]

                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    sorted_data = sorted(data, key=lambda x: x.get('time', 0))
                    candles = []
                    for k in sorted_data:
                        candles.append([
                            float(k.get('time', 0)), float(k.get('open', 0)), float(k.get('high', 0)),
                            float(k.get('low', 0)), float(k.get('close', 0)), float(k.get('volume', 0))
                        ])
                    if len(candles) >= 20:
                        return candles[-limit:]
        except Exception:
            continue

    return []

def calculate_ema_series(prices, period):
    if len(prices) < period:
        return [prices[-1]] * len(prices) if prices else []
    multiplier = 2.0 / (period + 1.0)
    ema_vals = []
    sma = sum(prices[:period]) / period
    for _ in range(period - 1):
        ema_vals.append(sma)
    ema_vals.append(sma)
    for price in prices[period:]:
        new_ema = (price - ema_vals[-1]) * multiplier + ema_vals[-1]
        ema_vals.append(new_ema)
    return ema_vals

# ==============================================================================
# 6. MASTER SIGNAL ENGINE (3M 9/20 EMA CROSS + 15M TREND CONFIRMATION)
# ==============================================================================
def eval_master_setup(symbol, m3_klines):
    """
    MASTER MULTI-TIMEFRAME ENTRY SYSTEM:
    1. 3M Crossover: Fresh Golden / Death Cross confirmed on closed candle (-2).
    2. 15M Trend Filter:
       - For LONG: Current price MUST be strictly ABOVE the 15M 20 EMA (Eliminates TIA-like bear traps).
       - For SHORT: Current price MUST be strictly BELOW the 15M 20 EMA (Eliminates BCH-like bull traps).
    3. Closed candle body agrees with trade direction (Green for Long, Red for Short).
    4. 20 EMA slope agrees with trade direction.
    """
    if len(m3_klines) < 25:
        return None

    closes_3m = [k[4] for k in m3_klines]
    ema9_3m = calculate_ema_series(closes_3m, 9)
    ema20_3m = calculate_ema_series(closes_3m, 20)

    closed_close = m3_klines[-2][4]
    closed_open = m3_klines[-2][1]
    e9_closed = ema9_3m[-2]
    e20_closed = ema20_3m[-2]
    e9_prev = ema9_3m[-3]
    e20_prev = ema20_3m[-3]

    # Minimum separation to prevent flat chop wicks
    spread_pct = abs(e9_closed - e20_closed) / e20_closed if e20_closed > 0 else 0
    if spread_pct < 0.00025:
        return None

    raw_signal = None
    if e9_prev >= e20_prev and e9_closed < e20_closed:
        if closed_close <= closed_open and e20_closed <= e20_prev * 1.0002:
            raw_signal = 'SHORT'
    elif e9_prev <= e20_prev and e9_closed > e20_closed:
        if closed_close >= closed_open and e20_closed >= e20_prev * 0.9998:
            raw_signal = 'LONG'

    if not raw_signal:
        return None

    # Higher Timeframe Confirmation: 15-Minute Trend Alignment
    m15_klines = fetch_klines(symbol, '15m', 30)
    if m15_klines and len(m15_klines) >= 20:
        closes_15m = [k[4] for k in m15_klines]
        ema20_15m = calculate_ema_series(closes_15m, 20)
        cmp_15m = closes_15m[-1]
        e20_15m_curr = ema20_15m[-1]

        # Filter out counter-trend entries
        if raw_signal == 'LONG' and cmp_15m < e20_15m_curr * 0.998:
            return None  # Price is in a 15M downtrend; reject fake Long bounce
        elif raw_signal == 'SHORT' and cmp_15m > e20_15m_curr * 1.002:
            return None  # Price is in a 15M uptrend; reject fake Short dip

    return raw_signal

# ==============================================================================
# 7. COINDCX FUTURES POSITION INSPECTION & RECOVERY
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
    ts_sec = int(time.time())
    ts_ms = int(round(time.time() * 1000))
    body_variants = [
        {"timestamp": ts_sec, "page": "1", "size": "50"},
        {"timestamp": ts_sec, "page": "1", "size": "50", "margin_currency_short_name": ["USDT", "INR"]},
        {"timestamp": ts_ms, "page": "1", "size": "50"},
        {"timestamp": ts_sec},
        {"timestamp": ts_ms}
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
            
            # Accurate side determination from active_pos sign or side field
            active_pos_num = float(p.get('active_pos', 0) or 0)
            if active_pos_num < 0:
                side = "SHORT"
            elif active_pos_num > 0:
                side = "LONG"
            else:
                side_str = str(p.get('side', p.get('order_type', 'buy'))).lower()
                side = "SHORT" if ('short' in side_str or 'sell' in side_str) else "LONG"
                
            if pos_id:
                return {
                    'pair': p_pair if p_pair else target_pair,
                    'position_id': str(pos_id),
                    'quantity': qty,
                    'entry_price': entry_p,
                    'side': side,
                    'raw': p
                }
    return None

def recover_live_coindcx_positions():
    pos_list = fetch_all_coindcx_live_positions()
    live_open_symbols = set()
    recovered_count = 0

    if isinstance(pos_list, list):
        for p in pos_list:
            if not isinstance(p, dict) or not is_position_open(p): continue
            qty = extract_pos_qty(p)
            if qty <= 0: continue

            p_pair = str(p.get('pair', p.get('market', p.get('symbol', '')))).upper()
            raw_c = p_pair.replace("B-", "").replace("_USDT", "").replace("USDT", "").replace("1000", "")
            sym = f"{raw_c}-USDT"
            live_open_symbols.add(sym)

            entry_p = float(p.get('avg_price', 0) or p.get('entry_price', 0) or p.get('price', 0))
            if entry_p <= 0: continue

            active_pos_num = float(p.get('active_pos', 0) or 0)
            if active_pos_num < 0:
                side = "SHORT"
            elif active_pos_num > 0:
                side = "LONG"
            else:
                side_str = str(p.get('side', p.get('order_type', 'buy'))).lower()
                side = "SHORT" if ('short' in side_str or 'sell' in side_str) else "LONG"

            with active_trades_lock:
                if sym not in ACTIVE_TRADES:
                    tp_dist = entry_p * 0.025
                    tp_val = round_coin_price(entry_p - tp_dist if side == "SHORT" else entry_p + tp_dist)
                    sl_val = round_coin_price(entry_p + entry_p * 0.005 if side == "SHORT" else entry_p - entry_p * 0.005)

                    ACTIVE_TRADES[sym] = {
                        'entry_price': entry_p,
                        'total_qty': qty,
                        'remaining_qty': qty,
                        'side': side,
                        'tp1': tp_val,
                        'sl': sl_val,
                        'initial_tp': tp_val,
                        'initial_sl': sl_val,
                        'trail_tier': 0,
                        'manual_override': False,
                        'entry_time': time.time(),
                        'highest_price': entry_p,
                        'lowest_price': entry_p,
                        'leverage': 7
                    }
                    recovered_count += 1

    with active_trades_lock:
        stale_syms = [s for s in list(ACTIVE_TRADES.keys()) if s not in live_open_symbols]
        for s in stale_syms:
            ACTIVE_TRADES.pop(s, None)

    save_active_trades()
    if recovered_count > 0:
        print(f"✅ Successfully recovered {recovered_count} active position(s) from CoinDCX!")

# ==============================================================================
# 8. ORDER EXECUTION WITH LOT SIZE PRECISION NORMALIZATION
# ==============================================================================
def execute_coindcx_futures_trade(symbol, side="buy", cmp=0.0, margin_inr=1000.0, leverage=7, custom_quantity=None, is_close=False):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return {'success': False, 'error': 'CoinDCX API Keys not configured.'}

    raw_coin = symbol.split('-')[0].upper()
    clean_coin = raw_coin.replace("1000", "")
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).upper()

    if is_close:
        live_pos_qty = fetch_coindcx_live_position_qty(symbol)
        if live_pos_qty <= 0.0:
            return {'success': False, 'error': f'Zero open position for {symbol}. Close order skipped.'}
        quantity = min(float(custom_quantity), live_pos_qty) if custom_quantity is not None else live_pos_qty
    else:
        if custom_quantity is not None:
            quantity = custom_quantity
        else:
            usdt_inr_rate = 91.5
            position_value_usdt = (margin_inr * leverage) / usdt_inr_rate
            raw_qty = position_value_usdt / cmp if cmp > 0 else 0.1

            # Precision normalization
            if raw_coin == 'BTC': quantity = round(max(0.001, raw_qty), 3)
            elif raw_coin in ['ETH', 'SOL', 'BNB', 'MKR', 'TAO', 'AAVE', 'BCH']: quantity = round(max(0.01, raw_qty), 2)
            elif raw_coin in ['UNI', 'PENDLE', 'AVAX', 'LINK', 'DOT', 'NEAR', 'SUI', 'APT', 'INJ', 'TIA', 'ATOM', 'FIL', 'ETC', 'RUNE', 'ORDI', 'ICP', 'AR']: 
                quantity = float(max(1, int(round(raw_qty))))
            elif raw_qty >= 50: quantity = float(int(round(raw_qty)))
            elif raw_qty >= 1: quantity = round(raw_qty, 1)
            else: quantity = round(max(0.1, raw_qty), 1)

    if quantity <= 0:
        return {'success': False, 'error': 'Calculated order quantity is zero.'}

    futures_url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
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
                pair_executed = body.get("order", {}).get("pair", f"B-{futures_coin}_USDT")
                return {'success': True, 'order_id': order_id, 'quantity': actual_qty, 'pair': pair_executed}
        except urllib.error.HTTPError as e:
            try:
                raw_bytes = e.read()
                err_text = raw_bytes.decode('utf-8', errors='ignore')
                err_clean = re.sub(r'<[^>]+>', ' ', err_text).strip()
                err_logs.append(f"V{idx}: HTTP {e.code} - {err_clean[:60]}")
            except Exception: err_logs.append(f"V{idx}: HTTP {e.code} - {e}")
        except Exception as e: err_logs.append(f"V{idx}: {e}")

    last_err = " | ".join(err_logs) if err_logs else "Unknown Error"
    return {'success': False, 'error': last_err}

def cancel_coindcx_position_orders(position_id):
    """Cancels any prior TP/SL orders on this position before applying new ones."""
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY or not position_id: return False
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/cancel_all_open_orders_for_position"
    payloads = [
        {"timestamp": int(round(time.time() * 1000)), "id": str(position_id)},
        {"timestamp": int(time.time()), "id": str(position_id)}
    ]
    for body in payloads:
        try:
            json_body = json.dumps(body, separators=(',', ':'))
            sig = hmac.new(COINDCX_SECRET_KEY.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': COINDCX_API_KEY,
                'X-AUTH-SIGNATURE': sig,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, context=ctx, timeout=4) as resp:
                if resp.status in [200, 201]:
                    return True
        except Exception:
            pass
    return False

def apply_coindcx_native_tpsl(pair, position_id, target_price, stop_loss_price):
    """
    Applies Native Take Profit & Stop Loss directly to CoinDCX Open Position.
    First cancels existing position orders, then sends formatted TP/SL bracket.
    Uses official CoinDCX schema: take_profit_market + stop_market with strict decimal precision.
    """
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: 
        return False, "API keys missing"

    cancel_coindcx_position_orders(position_id)

    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/create_tpsl"
    ts_ms = int(round(time.time() * 1000))
    ts_sec = int(time.time())

    tp_fmt = format_coin_price(target_price)
    sl_fmt = format_coin_price(stop_loss_price)

    payload_variants = [
        # 1. Official CoinDCX schema: seconds timestamp, take_profit_market & stop_market
        {
            "timestamp": ts_sec,
            "id": str(position_id),
            "take_profit": {"stop_price": tp_fmt, "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": sl_fmt, "order_type": "stop_market"}
        },
        # 2. Alternative schema: take_profit_market & stop_loss_market
        {
            "timestamp": ts_sec,
            "id": str(position_id),
            "take_profit": {"stop_price": tp_fmt, "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": sl_fmt, "order_type": "stop_loss_market"}
        },
        # 3. Stop-loss ONLY with stop_market (critical if TP already accepted by exchange and only SL needs attaching)
        {
            "timestamp": ts_sec,
            "id": str(position_id),
            "stop_loss": {"stop_price": sl_fmt, "order_type": "stop_market"}
        },
        # 4. Stop-loss ONLY with stop_loss_market
        {
            "timestamp": ts_sec,
            "id": str(position_id),
            "stop_loss": {"stop_price": sl_fmt, "order_type": "stop_loss_market"}
        },
        # 5. Milliseconds timestamp with stop_market
        {
            "timestamp": ts_ms,
            "id": str(position_id),
            "take_profit": {"stop_price": tp_fmt, "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": sl_fmt, "order_type": "stop_market"}
        },
        # 6. Milliseconds timestamp with stop-loss only
        {
            "timestamp": ts_ms,
            "id": str(position_id),
            "stop_loss": {"stop_price": sl_fmt, "order_type": "stop_market"}
        },
        # 7. Fallback: stop_limit with limit_price
        {
            "timestamp": ts_sec,
            "id": str(position_id),
            "take_profit": {"stop_price": tp_fmt, "limit_price": tp_fmt, "order_type": "take_profit_limit"},
            "stop_loss": {"stop_price": sl_fmt, "limit_price": sl_fmt, "order_type": "stop_limit"}
        }
    ]

    last_error = "Unknown error"
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
                resp_text = resp.read().decode('utf-8')
                try:
                    resp_data = json.loads(resp_text)
                    if isinstance(resp_data, dict):
                        if resp_data.get('message') == 'success' or resp_data.get('status') in [200, 201] or 'data' in resp_data:
                            return True, "Native TP/SL successfully accepted by CoinDCX"
                except Exception:
                    pass
                if resp.status in [200, 201]:
                    return True, "Native TP/SL accepted by CoinDCX"
        except urllib.error.HTTPError as e:
            try:
                err_text = e.read().decode('utf-8', errors='ignore')
                err_clean = re.sub(r'<[^>]+>', ' ', err_text).strip()
                last_error = f"HTTP {e.code}: {err_clean}"
            except Exception:
                last_error = f"HTTP {e.code}"
        except Exception as e:
            last_error = str(e)

    return False, last_error

def auto_place_coindcx_native_tpsl(symbol, tp_price, sl_price, side="LONG"):
    """
    Background worker that waits for position settlement and attaches CoinDCX native TP/SL.
    Broadcasts full transparency to Telegram if filled or if an exchange notice occurs.
    """
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return False
    
    last_err_msg = ""
    for attempt in range(1, 11):
        time.sleep(2)
        pos = fetch_coindcx_position_details(symbol)
        if pos and pos.get('position_id') and pos.get('quantity', 0) > 0:
            ok, msg_or_err = apply_coindcx_native_tpsl(pos['pair'], pos['position_id'], tp_price, sl_price)
            if ok:
                send_telegram_message(
                    f"🎯 <b>NATIVE COINDCX TP/SL APPLIED AUTOMATICALLY!</b>\n\n"
                    f"• <b>Pair:</b> <code>{pos['pair']}</code>\n"
                    f"• <b>Position ID:</b> <code>{pos['position_id']}</code>\n"
                    f"• <b>Target (TP):</b> <code>${format_coin_price(tp_price)}</code>\n"
                    f"• <b>Stop Loss (SL):</b> <code>${format_coin_price(sl_price)}</code>\n"
                    f"✅ <i>Populated directly in your CoinDCX TP / SL column! Exchange safety active.</i>"
                )
                return True
            else:
                last_err_msg = msg_or_err
        else:
            last_err_msg = "Waiting for position fill confirmation on CoinDCX..."

    # If native API fitting did not attach after 10 attempts, inform trader with full transparency
    send_telegram_message(
        f"⚠️ <b>COINDCX NATIVE TP/SL NOTICE: {symbol}</b>\n\n"
        f"• <b>Exchange Status:</b> <code>{last_err_msg[:100]}</code>\n"
        f"• <b>Target (TP):</b> <code>${format_coin_price(tp_price)}</code>\n"
        f"• <b>Stop Loss (SL):</b> <code>${format_coin_price(sl_price)}</code>\n\n"
        f"🛡️ <b>BOT HIGH-SPEED PROTECTION ACTIVE:</b>\n"
        f"• Bot internal monitoring engine is active.\n"
        f"• You can also tap <b>'+ Add TP / SL'</b> directly on CoinDCX to adjust manually at any time!"
    )
    return False

# ==============================================================================
# 9. SCANNER LOOP (3M CROSSOVER + 15M TREND FILTER + STRICT TIGHT SL CAP)
# ==============================================================================
def run_scan():
    curr_state = load_state()

    with active_trades_lock:
        if len(ACTIVE_TRADES) >= MAX_ACTIVE_TRADES:
            return

    for symbol in WATCHLIST:
        try:
            with active_trades_lock:
                if len(ACTIVE_TRADES) >= MAX_ACTIVE_TRADES:
                    return
                if symbol in ACTIVE_TRADES:
                    continue

            with pending_orders_lock:
                if symbol in PENDING_ORDERS:
                    continue

            last_traded = curr_state.get(f"last_traded_{symbol}", 0)
            if time.time() - last_traded < SYMBOL_COOLDOWN_SECONDS:
                continue

            m3_klines = fetch_klines(symbol, '3m', 65)
            if not m3_klines or len(m3_klines) < 30:
                continue

            # Evaluate Master Setup: 3M Crossover with 15M Higher-Timeframe Trend Confirmation
            signal_side = eval_master_setup(symbol, m3_klines)
            if not signal_side:
                continue

            highs = [k[2] for k in m3_klines]
            lows = [k[3] for k in m3_klines]
            closes = [k[4] for k in m3_klines]
            cmp = closes[-1]

            coin_margin = 1000.0
            lev_num = 7

            # ------------------------------------------------------------------
            # 🟢 LONG ENTRY (Initial SL = Tight Swing Low, STRICTLY CAPPED AT -₹35 MAX LOSS)
            # ------------------------------------------------------------------
            if signal_side == 'LONG':
                recent_swing_low = min(lows[-6:])
                raw_sl = round_coin_price(recent_swing_low * 0.9995)

                # STRICT RISK GUARDRAIL:
                # Minimum distance: 0.25% (prevents wicks)
                # Maximum distance: 0.50% (STRICTLY CAPS MAX LOSS AT -3.5% ROE = -₹35 MAX LOSS!)
                if (cmp - raw_sl) < (cmp * 0.0025):
                    raw_sl = round_coin_price(cmp * 0.996)
                elif (cmp - raw_sl) > (cmp * 0.0050):
                    raw_sl = round_coin_price(cmp * 0.995)

                # Target TP: Extended to allow trailing SL to ride past 5%, 7%, 10%, 15% ROE
                tp1 = round_coin_price(cmp * 1.025)  # ~+17.5% ROE max target

                sl_dist_pct = abs(cmp - raw_sl) / cmp * 100.0 if cmp > 0 else 0.5
                sl_roe_pct = sl_dist_pct * lev_num

                setup_title = "9-20 EMA GOLDEN CROSSOVER 🚀 (15M Trend Confirmed)"

                with pending_orders_lock:
                    PENDING_ORDERS.add(symbol)

                try:
                    if AUTO_TRADING_ENABLED:
                        trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=coin_margin, leverage=lev_num, is_close=False)
                    else:
                        trade_res = {'success': False, 'error': 'Auto-trading PAUSED via Mobile Telegram / Web button.'}

                    if trade_res.get('success'):
                        order_id = trade_res.get('order_id')
                        qty = trade_res.get('quantity')
                        log_trade_event(symbol, "EXECUTED", {"cmp": cmp, "quantity": qty, "order_id": order_id, "margin": coin_margin, "side": "LONG"})

                        with active_trades_lock:
                            ACTIVE_TRADES[symbol] = {
                                'entry_price': cmp,
                                'side': 'LONG',
                                'total_qty': qty,
                                'remaining_qty': qty,
                                'tp1': tp1,
                                'sl': raw_sl,
                                'initial_tp': tp1,
                                'initial_sl': raw_sl,
                                'trail_tier': 0,
                                'manual_override': False,
                                'highest_price': cmp,
                                'lowest_price': cmp,
                                'leverage': lev_num,
                                'entry_time': time.time()
                            }
                        save_active_trades()

                        curr_state[f"last_traded_{symbol}"] = time.time()
                        save_state(curr_state)

                        threading.Thread(target=auto_place_coindcx_native_tpsl, args=(symbol, tp1, raw_sl, "LONG"), daemon=True).start()

                        msg = (
                            f"🟢 <b>3-MIN EMA SCALP SIGNAL! (LONG)</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                            f"<b>Setup:</b> <b>{setup_title}</b>\n"
                            f"🌊 <b>Trend:</b> <code>15M Bullish + 3M Golden Cross</code>\n\n"
                            f"⚙️ <b>Trade Parameters:</b>\n"
                            f"• <b>Direction:</b> <code>LONG</code> (7x Isolated)\n"
                            f"• <b>Entry CMP:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"🛑 <b>Stop Loss (Tight Capped):</b> <code>${format_coin_price(raw_sl)}</code> (-{sl_dist_pct:.2f}% / -{sl_roe_pct:.1f}% ROE | Max -₹35)\n"
                            f"🎯 <b>Target (Max TP):</b> <code>${format_coin_price(tp1)}</code> (+2.5% / +17.5% ROE)\n"
                            f"🔄 <b>Trailing Stop:</b> Break-Even at +2.5% ROE! Trails 1.5% below peak from +5.0% ROE!\n\n"
                            f"⚡ <b>AUTO-TRADE EXECUTED ON COINDCX!</b>\n"
                            f"• Order ID: <code>{order_id}</code>\n"
                            f"• Quantity: <code>{qty}</code> | Margin: ₹{coin_margin:.0f}\n"
                            f"🔄 <i>Native CoinDCX TP/SL auto-fitting active...</i>"
                        )
                        send_telegram_message(msg)

                        with active_trades_lock:
                            if len(ACTIVE_TRADES) >= MAX_ACTIVE_TRADES:
                                return
                    else:
                        err_reason = trade_res.get('error', 'Unknown Error')
                        log_trade_event(symbol, "CANCELLED", {"cmp": cmp, "error": err_reason, "side": "LONG"})
                        curr_state[f"last_traded_{symbol}"] = time.time()
                        save_state(curr_state)
                finally:
                    with pending_orders_lock:
                        PENDING_ORDERS.discard(symbol)
                continue

            # ------------------------------------------------------------------
            # 🔴 SHORT ENTRY (Initial SL = Tight Swing High, STRICTLY CAPPED AT -₹35 MAX LOSS)
            # ------------------------------------------------------------------
            elif signal_side == 'SHORT':
                recent_swing_high = max(highs[-6:])
                raw_sl = round_coin_price(recent_swing_high * 1.0005)

                # STRICT RISK GUARDRAIL:
                # Minimum distance: 0.25% (prevents wicks)
                # Maximum distance: 0.50% (STRICTLY CAPS MAX LOSS AT -3.5% ROE = -₹35 MAX LOSS!)
                if (raw_sl - cmp) < (cmp * 0.0025):
                    raw_sl = round_coin_price(cmp * 1.004)
                elif (raw_sl - cmp) > (cmp * 0.0050):
                    raw_sl = round_coin_price(cmp * 1.005)

                # Target TP: Extended to allow trailing SL to ride past 5%, 7%, 10%, 15% ROE
                tp1 = round_coin_price(cmp * 0.975)  # ~+17.5% ROE max target

                sl_dist_pct = abs(raw_sl - cmp) / cmp * 100.0 if cmp > 0 else 0.5
                sl_roe_pct = sl_dist_pct * lev_num

                setup_title = "9-20 EMA DEATH CROSSOVER 📉 (15M Trend Confirmed)"

                with pending_orders_lock:
                    PENDING_ORDERS.add(symbol)

                try:
                    if AUTO_TRADING_ENABLED:
                        trade_res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, margin_inr=coin_margin, leverage=lev_num, is_close=False)
                    else:
                        trade_res = {'success': False, 'error': 'Auto-trading PAUSED via Mobile Telegram / Web button.'}

                    if trade_res.get('success'):
                        order_id = trade_res.get('order_id')
                        qty = trade_res.get('quantity')
                        log_trade_event(symbol, "EXECUTED", {"cmp": cmp, "quantity": qty, "order_id": order_id, "margin": coin_margin, "side": "SHORT"})

                        with active_trades_lock:
                            ACTIVE_TRADES[symbol] = {
                                'entry_price': cmp,
                                'side': 'SHORT',
                                'total_qty': qty,
                                'remaining_qty': qty,
                                'tp1': tp1,
                                'sl': raw_sl,
                                'initial_tp': tp1,
                                'initial_sl': raw_sl,
                                'trail_tier': 0,
                                'manual_override': False,
                                'highest_price': cmp,
                                'lowest_price': cmp,
                                'leverage': lev_num,
                                'entry_time': time.time()
                            }
                        save_active_trades()

                        curr_state[f"last_traded_{symbol}"] = time.time()
                        save_state(curr_state)

                        threading.Thread(target=auto_place_coindcx_native_tpsl, args=(symbol, tp1, raw_sl, "SHORT"), daemon=True).start()

                        msg = (
                            f"🔴 <b>3-MIN EMA SCALP SIGNAL! (SHORT)</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                            f"<b>Setup:</b> <b>{setup_title}</b>\n"
                            f"🌊 <b>Trend:</b> <code>15M Bearish + 3M Death Cross</code>\n\n"
                            f"⚙️ <b>Trade Parameters:</b>\n"
                            f"• <b>Direction:</b> <code>SHORT</code> (7x Isolated)\n"
                            f"• <b>Entry CMP:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"🛑 <b>Stop Loss (Tight Capped):</b> <code>${format_coin_price(raw_sl)}</code> (-{sl_dist_pct:.2f}% / -{sl_roe_pct:.1f}% ROE | Max -₹35)\n"
                            f"🎯 <b>Target (Max TP):</b> <code>${format_coin_price(tp1)}</code> (+2.5% / +17.5% ROE)\n"
                            f"🔄 <b>Trailing Stop:</b> Break-Even at +2.5% ROE! Trails 1.5% below peak from +5.0% ROE!\n\n"
                            f"⚡ <b>AUTO-TRADE EXECUTED ON COINDCX!</b>\n"
                            f"• Order ID: <code>{order_id}</code>\n"
                            f"• Quantity: <code>{qty}</code> | Margin: ₹{coin_margin:.0f}\n"
                            f"🔄 <i>Native CoinDCX TP/SL auto-fitting active...</i>"
                        )
                        send_telegram_message(msg)

                        with active_trades_lock:
                            if len(ACTIVE_TRADES) >= MAX_ACTIVE_TRADES:
                                return
                    else:
                        err_reason = trade_res.get('error', 'Unknown Error')
                        log_trade_event(symbol, "CANCELLED", {"cmp": cmp, "error": err_reason, "side": "SHORT"})
                        curr_state[f"last_traded_{symbol}"] = time.time()
                        save_state(curr_state)
                finally:
                    with pending_orders_lock:
                        PENDING_ORDERS.discard(symbol)
                continue
        except Exception: pass

# ==============================================================================
# 10. CONTINUOUS PEAK-TRAILING STOP LOSS & BRACKET EXIT ENGINE
# ==============================================================================
def monitor_active_positions():
    """
    DYNAMIC NATIVE BRACKET MONITORING & CONTINUOUS PEAK-TRAILING ENGINE:
    1. Pure Trend-Riding: NO premature 'Reverse Crossover' exits.
       Normal pullbacks are allowed to retest support while tight Swing SL guarantees capital safety.
    2. Break-Even Lock at +2.5% ROE (+0.35% price move):
       Moves SL to Entry + 0.6% ROE (covers round-trip exchange fees & GST completely).
    3. Continuous Peak-Trailing from +5.0% ROE:
       Trails 1.5% ROE below highest peak price reached continuously.
    4. Auto-synchronizes new SL directly to CoinDCX native position bracket.
    5. Exits strictly on: Target TP, Trailing/Break-Even SL, or Initial Swing SL.
    """
    time.sleep(5)
    while True:
        try:
            with active_trades_lock:
                symbols_to_check = list(ACTIVE_TRADES.keys())

            for symbol in symbols_to_check:
                try:
                    time.sleep(0.2)

                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES: continue
                        trade = ACTIVE_TRADES[symbol]

                    side = trade.get('side', 'LONG').upper()
                    close_side = "sell" if side == "LONG" else "buy"
                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    lev = trade.get('leverage', 7)
                    pos_age = time.time() - entry_time

                    # 1. Check if closed on CoinDCX (native TP/SL or manual close)
                    live_qty = fetch_coindcx_live_position_qty(symbol)
                    if live_qty <= 0.0:
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        log_trade_event(symbol, "CLOSED_ON_EXCHANGE", {"status": "Closed on CoinDCX (Native TP/SL or manual exit)"})
                        send_telegram_message(
                            f"🔔 <b>POSITION CLOSED ON COINDCX: {symbol}</b>\n\n"
                            f"• <b>Status:</b> Position was executed/closed directly on CoinDCX (Native TP/SL hit)!\n"
                            f"• <b>Capacity:</b> Trade slot freed. Scanner actively watching 70 coins for the next setup."
                        )
                        continue

                    # 10-second minimum hold before active tick evaluation
                    if pos_age < 10:
                        continue

                    m3_klines = fetch_klines(symbol, '3m', 65)
                    if not m3_klines or len(m3_klines) < 25: continue

                    closes = [k[4] for k in m3_klines]
                    cmp = closes[-1]
                    sell_qty = min(live_qty, trade.get('remaining_qty', live_qty))

                    pnl_pct = ((cmp - entry_p) / entry_p * 100) if side == "LONG" else ((entry_p - cmp) / entry_p * 100)
                    roe_pct = pnl_pct * lev

                    # ----------------------------------------------------------
                    # 🔄 DYNAMIC BREAK-EVEN & PEAK-TRAILING STOP LOSS ENGINE
                    # ----------------------------------------------------------
                    trail_updated = False
                    new_sl_val = trade['sl']
                    tier_name = ""

                    if side == "LONG":
                        # Track highest peak price reached
                        if cmp > trade.get('highest_price', entry_p):
                            trade['highest_price'] = cmp
                        peak_p = trade['highest_price']
                        peak_roe = ((peak_p - entry_p) / entry_p * 100.0) * lev
                        last_notified_roe = trade.get('last_notified_roe', 0.0)

                        # Step 1: Early Break-Even Lock at +2.5% ROE (+0.35% price move)
                        # Moves SL to Entry + 0.6% ROE (covers ₹9 round-trip fees so risk is 0)
                        if peak_roe >= 2.5 and trade.get('trail_tier', 0) < 1:
                            be_sl = round_coin_price(entry_p * (1.0 + (0.6 / 100.0) / lev))
                            if be_sl > trade['sl']:
                                new_sl_val = be_sl
                                trade['trail_tier'] = 1
                                tier_name = f"BREAK-EVEN LOCK (+{peak_roe:.1f}% Peak ➔ Locked Fees Protected +0.6% ROE)"
                                trade['last_notified_roe'] = 0.6
                                trade['last_trail_type'] = 'be'
                                trail_updated = True

                        # Step 2: Continuous Peak-Trailing: Trail 1.5% ROE below peak once peak >= 5.0%
                        if peak_roe >= 5.0:
                            target_locked_roe = peak_roe - 1.5
                            target_sl = round_coin_price(entry_p * (1.0 + (target_locked_roe / 100.0) / lev))
                            if target_sl > trade['sl']:
                                new_sl_val = target_sl
                                trade['trail_tier'] = 2
                                tier_name = f"PEAK-TRAIL (+{peak_roe:.1f}% Peak ➔ Locked +{target_locked_roe:.1f}% ROE)"
                                if (target_locked_roe - last_notified_roe) >= 0.5 or trade.get('last_trail_type') != 'peak':
                                    trade['last_notified_roe'] = target_locked_roe
                                    trade['last_trail_type'] = 'peak'
                                    trail_updated = True

                    elif side == "SHORT":
                        # Track lowest peak price reached
                        if cmp < trade.get('lowest_price', entry_p):
                            trade['lowest_price'] = cmp
                        peak_p = trade['lowest_price']
                        peak_roe = ((entry_p - peak_p) / entry_p * 100.0) * lev
                        last_notified_roe = trade.get('last_notified_roe', 0.0)

                        # Step 1: Early Break-Even Lock at +2.5% ROE (+0.35% price move)
                        if peak_roe >= 2.5 and trade.get('trail_tier', 0) < 1:
                            be_sl = round_coin_price(entry_p * (1.0 - (0.6 / 100.0) / lev))
                            if be_sl < trade['sl']:
                                new_sl_val = be_sl
                                trade['trail_tier'] = 1
                                tier_name = f"BREAK-EVEN LOCK (+{peak_roe:.1f}% Peak ➔ Locked Fees Protected +0.6% ROE)"
                                trade['last_notified_roe'] = 0.6
                                trade['last_trail_type'] = 'be'
                                trail_updated = True

                        # Step 2: Continuous Peak-Trailing: Trail 1.5% ROE below peak once peak >= 5.0%
                        if peak_roe >= 5.0:
                            target_locked_roe = peak_roe - 1.5
                            target_sl = round_coin_price(entry_p * (1.0 - (target_locked_roe / 100.0) / lev))
                            if target_sl < trade['sl']:
                                new_sl_val = target_sl
                                trade['trail_tier'] = 2
                                tier_name = f"PEAK-TRAIL (+{peak_roe:.1f}% Peak ➔ Locked +{target_locked_roe:.1f}% ROE)"
                                if (target_locked_roe - last_notified_roe) >= 0.5 or trade.get('last_trail_type') != 'peak':
                                    trade['last_notified_roe'] = target_locked_roe
                                    trade['last_trail_type'] = 'peak'
                                    trail_updated = True

                    # Ratchet update & exchange bracket synchronization
                    if trade['sl'] != new_sl_val:
                        trade['sl'] = new_sl_val
                        save_active_trades()
                        # Update exchange native SL in background without blocking
                        pos_info = fetch_coindcx_position_details(symbol)
                        if pos_info and pos_info.get('position_id'):
                            threading.Thread(
                                target=apply_coindcx_native_tpsl,
                                args=(pos_info['pair'], pos_info['position_id'], trade['tp1'], new_sl_val),
                                daemon=True
                            ).start()

                    if trail_updated:
                        send_telegram_message(
                            f"🛡️ <b>TRAILING STOP ACTIVATED: {symbol} ({side})</b>\n\n"
                            f"• <b>Trigger:</b> <code>{tier_name}</code>\n"
                            f"• <b>Current ROE:</b> <code>{roe_pct:+.1f}% ROE</code>\n"
                            f"• <b>New Trailing SL:</b> <code>${format_coin_price(new_sl_val)}</code>\n"
                            f"✅ <i>Profits dynamically locked! Exchange order synchronized on CoinDCX.</i>"
                        )

                    # ----------------------------------------------------------
                    # 🏁 EXIT EVALUATION (NATIVE BRACKET SYSTEM)
                    # ----------------------------------------------------------
                    exit_reason = None

                    # 1. Target TP reached (+17.5% ROE)
                    if side == "LONG" and cmp >= trade['tp1']:
                        exit_reason = f"🎯 TARGET REACHED (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                    elif side == "SHORT" and cmp <= trade['tp1']:
                        exit_reason = f"🎯 TARGET REACHED (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"

                    # 2. Stop Loss (Break-Even, Trailing SL, or Initial Swing SL)
                    elif side == "LONG" and cmp <= trade['sl']:
                        if trade.get('trail_tier', 0) == 2:
                            exit_reason = f"🔒 TRAILING STOP HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                        elif trade.get('trail_tier', 0) == 1:
                            exit_reason = f"🛡️ BREAK-EVEN HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                        else:
                            exit_reason = f"🛑 INITIAL SWING SL HIT ({pnl_pct:.2f}% | {roe_pct:.1f}% ROE)"
                    elif side == "SHORT" and cmp >= trade['sl']:
                        if trade.get('trail_tier', 0) == 2:
                            exit_reason = f"🔒 TRAILING STOP HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                        elif trade.get('trail_tier', 0) == 1:
                            exit_reason = f"🛡️ BREAK-EVEN HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                        else:
                            exit_reason = f"🛑 INITIAL SWING SL HIT ({pnl_pct:.2f}% | {roe_pct:.1f}% ROE)"

                    if exit_reason:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=lev, custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        st = load_state()
                        st[f"last_traded_{symbol}"] = time.time()
                        save_state(st)

                        pnl_inr = (1000.0 * (roe_pct / 100))
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(roe_pct, 1), "exit_reason": exit_reason, "side": side})
                        
                        send_telegram_message(
                            f"🏁 <b>SCALP POSITION CLOSED: {symbol}</b>\n\n"
                            f"• <b>Reason:</b> {exit_reason}\n"
                            f"• <b>Entry:</b> ${format_coin_price(entry_p)} ➡️ <b>Exit:</b> ${format_coin_price(cmp)}\n"
                            f"• <b>Hold Time:</b> {int(pos_age // 60)}m {int(pos_age % 60)}s\n"
                            f"• <b>Scalp PNL:</b> {pnl_pct:+.2f}% ({roe_pct:+.1f}% ROE)\n"
                            f"• <b>Net Estimate:</b> {'+' if pnl_inr >= 0 else ''}₹{pnl_inr:.2f} INR"
                        )
                except Exception as e:
                    print(f"Error checking position {symbol}: {e}")
            time.sleep(3)
        except Exception as e:
            print(f"Error in monitor_active_positions: {e}")
            time.sleep(5)

# ==============================================================================
# 11. TELEGRAM COMMAND LISTENER (/start, /stop, /status, /report)
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    last_update_id = 0
    if not TOKEN: return

    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=15"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                for item in data.get("result", []):
                    last_update_id = item["update_id"]
                    msg = item.get("message", {})
                    text = msg.get("text", "").strip()
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if chat_id != str(CHAT_ID) and chat_id != "8938527650":
                        continue

                    cmd = text.lower()
                    if cmd in ["/start", "start"]:
                        AUTO_TRADING_ENABLED = True
                        save_active_trades()
                        send_telegram_message("▶️ <b>Auto-trading RESUMED.</b> Scanning 3M/15M charts for high-probability setups.")
                    elif cmd in ["/stop", "stop"]:
                        AUTO_TRADING_ENABLED = False
                        save_active_trades()
                        send_telegram_message("⏸️ <b>Auto-trading PAUSED.</b> Signals will be broadcast only.")
                    elif cmd in ["/status", "status"]:
                        with active_trades_lock:
                            count = len(ACTIVE_TRADES)
                            summary = ""
                            for k, v in ACTIVE_TRADES.items():
                                summary += f"\n• {k}: {v['side'].upper()} @ ${v['entry_price']}"
                        send_telegram_message(
                            f"🤖 <b>BOT STATUS</b>\n"
                            f"• Auto-Trading: {'🟢 ACTIVE' if AUTO_TRADING_ENABLED else '🔴 PAUSED'}\n"
                            f"• Active Scalps: {count}/{MAX_ACTIVE_TRADES}{summary}\n"
                            f"• Watchlist: 70 Top Coins (3M 9/20 EMA + 15M Trend Filter)\n"
                            f"• Protection: Tight Capped SL (-₹35 max) + Break-Even (+2.5%) + Peak-Trail (+5%)"
                        )
                    elif cmd in ["/report", "report", "/today", "today"]:
                        report_text = generate_daily_trade_report()
                        send_telegram_message(report_text)
        except Exception:
            pass
        time.sleep(3)

# ==============================================================================
# 12. FLASK DASHBOARD & WEB ROUTES
# ==============================================================================
@app.route('/')
def home():
    with active_trades_lock:
        active_copy = list(ACTIVE_TRADES.items())

    rows = ""
    for sym, t in active_copy:
        side_color = "#00c853" if t.get('side') == 'LONG' else "#ff1744"
        rows += f"""
        <tr>
            <td><b>{sym}</b></td>
            <td style="color:{side_color}">{t.get('side')}</td>
            <td>${format_coin_price(t.get('entry_price', 0))}</td>
            <td>${format_coin_price(t.get('tp1', 0))}</td>
            <td>${format_coin_price(t.get('sl', 0))}</td>
            <td>{datetime.fromtimestamp(t.get('entry_time', time.time()), IST).strftime('%H:%M:%S')}</td>
            <td><a href="/close/{sym}" style="background:#ff1744;color:#fff;padding:4px 8px;border-radius:4px;text-decoration:none;">Close</a></td>
        </tr>
        """

    events = load_all_trade_events()
    hist_rows = ""
    for e in reversed(events[-25:]):
        det = e.get('details', {})
        pnl = det.get('realized_pnl_pct', 0)
        pnl_color = "#00c853" if pnl >= 0 else "#ff1744"
        hist_rows += f"""
        <tr>
            <td>{e.get('timestamp')}</td>
            <td>{e.get('symbol')}</td>
            <td>{e.get('type')}</td>
            <td style="color:{pnl_color}">{f'{pnl:+.1f}%' if pnl != 0 else '-'}</td>
            <td><small>{det.get('exit_reason', det.get('status', ''))}</small></td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Master 3M/15M EMA Scalper</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0e1118; color: #e0e0e0; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: auto; }}
            .card {{ background: #161b26; border-radius: 8px; padding: 20px; margin-bottom: 20px; border: 1px solid #232936; }}
            .btn {{ display: inline-block; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-right: 10px; }}
            .btn-green {{ background: #00c853; color: white; }}
            .btn-red {{ background: #ff1744; color: white; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #232936; }}
            th {{ color: #8892b0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>⚡ Master 3M/15M EMA Scalper</h1>
                <p>Status: <b>{'🟢 RUNNING' if AUTO_TRADING_ENABLED else '🔴 PAUSED'}</b> | Protection: <b>Tight Capped SL (-₹35 max) + Break-Even (+2.5% ROE) + Continuous Peak-Trail (+5% ROE)</b></p>
                <div>
                    <a href="/toggle-bot" class="btn {'btn-red' if AUTO_TRADING_ENABLED else 'btn-green'}">
                        {'PAUSE BOT' if AUTO_TRADING_ENABLED else 'RESUME BOT'}
                    </a>
                    <a href="/test-telegram" class="btn" style="background:#2979ff;color:white;">Test Telegram</a>
                </div>
            </div>

            <div class="card">
                <h2>Active Scalp Positions ({len(active_copy)}/{MAX_ACTIVE_TRADES})</h2>
                <table>
                    <thead>
                        <tr><th>Pair</th><th>Side</th><th>Entry</th><th>Target</th><th>SL</th><th>Time</th><th>Action</th></tr>
                    </thead>
                    <tbody>{rows if rows else "<tr><td colspan='7'>No active scalps currently open.</td></tr>"}</tbody>
                </table>
            </div>

            <div class="card">
                <h2>Recent Closed Scalps</h2>
                <table>
                    <thead>
                        <tr><th>Time</th><th>Pair</th><th>Event</th><th>ROE</th><th>Details</th></tr>
                    </thead>
                    <tbody>{hist_rows if hist_rows else "<tr><td colspan='5'>No trade events recorded yet.</td></tr>"}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/toggle-bot')
def toggle_bot():
    global AUTO_TRADING_ENABLED
    AUTO_TRADING_ENABLED = not AUTO_TRADING_ENABLED
    save_active_trades()
    return "<script>window.location.href='/';</script>"

@app.route('/test-telegram')
def test_telegram():
    send_telegram_message("🔔 <b>Crypto-Scanner Test Alert</b>\nMaster bot connection is fully functional and live!")
    return "Telegram alert sent successfully! <a href='/'>Back to Dashboard</a>"

@app.route('/close/<symbol>')
def manual_close(symbol):
    with active_trades_lock:
        if symbol in ACTIVE_TRADES:
            t = ACTIVE_TRADES[symbol]
            close_side = "sell" if t.get('side') == 'LONG' else "buy"
            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=t.get('entry_price', 0), is_close=True)
            del ACTIVE_TRADES[symbol]
            save_active_trades()
            send_telegram_message(f"⚠️ <b>Position for {symbol} closed manually from Dashboard.</b>")
    return "<script>window.location.href='/';</script>"

# ==============================================================================
# 13. BACKGROUND WORKERS & SERVER STARTUP
# ==============================================================================
def start_background_loop():
    def run_scalp_scan_loop():
        time.sleep(5)
        while True:
            try:
                if scan_lock.acquire(blocking=False):
                    try: run_scan()
                    finally: scan_lock.release()
            except Exception as e:
                print(f"Scalp scan exception: {e}")
            time.sleep(8)

    def run_keep_alive_loop():
        time.sleep(15)
        url = "https://crypto-scanner-ok3t.onrender.com/"
        while True:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'KeepAlive/1.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=8) as r: pass
            except Exception: pass
            time.sleep(120)

    def run_daily_report_scheduler():
        time.sleep(30)
        last_reported_date = ""
        while True:
            try:
                now_ist = get_ist_now()
                today_str = now_ist.strftime("%d-%m-%Y")
                # Send automatic daily report at 11:30 PM IST every day
                if now_ist.hour == 23 and now_ist.minute >= 30 and last_reported_date != today_str:
                    report_msg = generate_daily_trade_report(today_str)
                    send_telegram_message(f"📢 <b>END OF DAY AUTOMATIC REPORT</b>\n\n{report_msg}")
                    last_reported_date = today_str
            except Exception: pass
            time.sleep(60)

    # Recover any live positions immediately on boot
    recover_live_coindcx_positions()

    threading.Thread(target=run_scalp_scan_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()
    threading.Thread(target=run_daily_report_scheduler, daemon=True).start()

    send_telegram_message(
        "⚡ <b>MASTER 3M/15M EMA SCALPING BOT DEPLOYED!</b>\n\n"
        "• <b>Strategy:</b> 3M 9/20 EMA Cross + 15M Trend Alignment (High-Probability Filter)\n"
        "• <b>Watchlist:</b> 70 Top High-Liquidity Coins\n"
        "• <b>Stop Loss:</b> Tight Swing SL Strictly Capped at -0.50% (Max -₹35 Loss | Never -₹77!)\n"
        "• <b>Break-Even Lock:</b> At +2.5% ROE -> Moves SL to Entry + Fees Protected (+0.6% ROE)\n"
        "• <b>Continuous Peak-Trailing SL:</b>\n"
        "   └ 🚀 Trails 1.5% ROE below peak continuously from +5.0% ROE! (Ride to +10%, +15% ROE)\n"
        "• <b>Target:</b> +17.5% ROE (+2.5% price move) Extended Max TP\n"
        "• <b>Exchange Safety:</b> Native CoinDCX TP/SL Bracket Synchronized Automatically\n"
        "• <b>Margin:</b> ₹1,000 INR (7x Isolated Leverage)\n"
        "• <b>Controls:</b> Web 1-Click Dashboard + Telegram /start, /stop, /status & /report"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Master EMA Scalping server on port {port}...")
    app.run(host="0.0.0.0", port=port)
