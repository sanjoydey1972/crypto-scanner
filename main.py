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
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip() or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or "8938527650"

# CoinDCX API Credentials (with fallback keys)
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY", "").strip() or os.environ.get("COINDCX_API_SECRET", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"

ctx = ssl._create_unverified_context()

# ==============================================================================
# 2. WATCHLIST & CRYPTO PAIR ALIASES
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
MAX_ACTIVE_TRADES = 1  # 1 position at a time to prevent overexposure

# ==============================================================================
# 3. PERMANENT AUDIT JOURNAL & HISTORY LOGGER
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
# 5. DYNAMIC PRECISION & MULTI-SOURCE CANDLE ENGINE
# ==============================================================================
def round_coin_price(price):
    if price >= 100.0: return round(price, 2)
    elif price >= 1.0: return round(price, 4)
    elif price >= 0.01: return round(price, 6)
    elif price > 0: return round(price, 8)
    return 0.0

def format_coin_price(price):
    if price >= 100.0: return f"{price:.2f}"
    elif price >= 1.0: return f"{price:.4f}"
    elif price >= 0.01: return f"{price:.6f}"
    elif price > 0: return f"{price:.8f}".rstrip('0')
    return "0.00"

def fetch_klines(symbol, interval='1m', limit=65):
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).upper()
    binance_sym = symbol.replace('-', '').upper()

    endpoints = [
        ("binance_vision", f"https://data-api.binance.vision/api/v3/klines?symbol={binance_sym}&interval={interval}&limit={limit}"),
        ("bybit", f"https://api.bybit.com/v5/market/kline?category=linear&symbol={binance_sym}&interval=1&limit={limit}"),
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
                    if len(candles) >= 25:
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
                        if len(candles) >= 25:
                            return candles[-limit:]

                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    sorted_data = sorted(data, key=lambda x: x.get('time', 0))
                    candles = []
                    for k in sorted_data:
                        candles.append([
                            float(k.get('time', 0)), float(k.get('open', 0)), float(k.get('high', 0)),
                            float(k.get('low', 0)), float(k.get('close', 0)), float(k.get('volume', 0))
                        ])
                    if len(candles) >= 25:
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
# 6. PURE 9 & 20 EMA CROSSOVER ENGINE (ELIMINATING BAD / LATE TRADES)
# ==============================================================================
def eval_crossover_setup(klines, ema9_series, ema20_series):
    """
    STRICT 9 & 20 EMA CROSSOVER RULES:
    1. Evaluated on the LAST CLOSED CANDLE (klines[-2]) to eliminate intra-candle noise.
    2. Crossover MUST BE FRESH: occurred precisely between candle -3 and candle -2.
       Never enter late in the middle of a dump or at bottom support!
    3. 20 EMA slope must agree with trade direction (rejecting flat sideways chop).
    4. Closed candle body must confirm direction (Red candle for Short, Green for Long).
    5. Minimum EMA separation (>0.03%) to ignore glued, zero-momentum EMAs.
    """
    if len(klines) < 10 or len(ema9_series) < 10 or len(ema20_series) < 10:
        return None, 0

    closed_close = klines[-2][4]
    closed_open = klines[-2][1]

    e9_closed = ema9_series[-2]
    e20_closed = ema20_series[-2]

    e9_prev = ema9_series[-3]
    e20_prev = ema20_series[-3]

    # Minimum separation to prevent flat chop wicks
    spread_pct = abs(e9_closed - e20_closed) / e20_closed if e20_closed > 0 else 0
    if spread_pct < 0.00025:
        return None, 0

    # 🔴 BEARISH DEATH CROSSOVER (SHORT)
    if e9_prev >= e20_prev and e9_closed < e20_closed:
        if closed_close <= closed_open:
            if e20_closed <= e20_prev * 1.0002:
                return 'SHORT', 0

    # 🟢 BULLISH GOLDEN CROSSOVER (LONG)
    if e9_prev <= e20_prev and e9_closed > e20_closed:
        if closed_close >= closed_open:
            if e20_closed >= e20_prev * 0.9998:
                return 'LONG', 0

    return None, 0

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
    ts_ms = int(time.time() * 1000)
    body_variants = [
        {"timestamp": ts_sec},
        {"timestamp": ts_ms},
        {"timestamp": ts_sec, "page": "1", "size": "50"}
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

            side_str = str(p.get('side', p.get('order_type', 'buy'))).lower()
            side = "SHORT" if ('short' in side_str or 'sell' in side_str) else "LONG"

            with active_trades_lock:
                if sym not in ACTIVE_TRADES:
                    tp_dist = entry_p * 0.018
                    tp_val = round_coin_price(entry_p - tp_dist if side == "SHORT" else entry_p + tp_dist)
                    sl_val = round_coin_price(entry_p + entry_p * 0.008 if side == "SHORT" else entry_p - entry_p * 0.008)

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
# 8. ORDER EXECUTION WITH LOT SIZE PRECISION NORMALIZATION & NATIVE TP/SL
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

def apply_coindcx_native_tpsl(pair, position_id, target_price, stop_loss_price):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return False
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions/create_tpsl"
    ts_sec = int(time.time())
    ts_ms = int(time.time() * 1000)

    tp_str = str(round_coin_price(target_price))
    sl_str = str(round_coin_price(stop_loss_price))

    payload_variants = [
        # 1. Official CoinDCX schema: seconds timestamp, string stop_price, order_type
        {
            "timestamp": ts_sec,
            "id": str(position_id),
            "take_profit": {"stop_price": tp_str, "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": sl_str, "order_type": "stop_market"}
        },
        # 2. Float values with seconds timestamp
        {
            "timestamp": ts_sec,
            "id": str(position_id),
            "take_profit": {"stop_price": float(target_price), "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": float(stop_loss_price), "order_type": "stop_market"}
        },
        # 3. With pair included
        {
            "timestamp": ts_sec,
            "pair": pair,
            "id": str(position_id),
            "take_profit": {"stop_price": tp_str, "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": sl_str, "order_type": "stop_market"}
        },
        # 4. Milliseconds fallback
        {
            "timestamp": ts_ms,
            "id": str(position_id),
            "take_profit": {"stop_price": tp_str, "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": sl_str, "order_type": "stop_market"}
        }
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
                if resp.status in [200, 201]: return True
        except Exception: pass
    return False

def auto_place_coindcx_native_tpsl(symbol, tp_price, sl_price, side="LONG"):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY: return False
    for attempt in range(1, 12):
        time.sleep(2)
        pos = fetch_coindcx_position_details(symbol)
        if pos and pos.get('position_id') and pos.get('quantity', 0) > 0:
            ok = apply_coindcx_native_tpsl(pos['pair'], pos['position_id'], tp_price, sl_price)
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
    return False

# ==============================================================================
# 9. SCANNER LOOP (PURE 9 & 20 EMA CROSSOVER + SWING SL)
# ==============================================================================
def run_scan():
    today_str = get_ist_now().strftime("%d-%m-%Y")
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

            m1_klines = fetch_klines(symbol, '1m', 40)
            if not m1_klines or len(m1_klines) < 30:
                continue

            closes = [k[4] for k in m1_klines]
            highs = [k[2] for k in m1_klines]
            lows = [k[3] for k in m1_klines]
            cmp = closes[-1]

            ema9_series = calculate_ema_series(closes, 9)
            ema20_series = calculate_ema_series(closes, 20)

            signal_side, candles_after_cross = eval_crossover_setup(m1_klines, ema9_series, ema20_series)
            if not signal_side:
                continue

            coin_margin = 1000.0
            lev_num = 7

            # ------------------------------------------------------------------
            # 🟢 LONG ENTRY (Initial SL = Recent Swing Low)
            # ------------------------------------------------------------------
            if signal_side == 'LONG':
                recent_swing_low = min(lows[-8:])
                raw_sl = round_coin_price(recent_swing_low * 0.9995)

                if (cmp - raw_sl) < (cmp * 0.0035):
                    raw_sl = round_coin_price(cmp * 0.995)
                elif (cmp - raw_sl) > (cmp * 0.013):
                    raw_sl = round_coin_price(cmp * 0.988)

                tp1 = round_coin_price(cmp * 1.018)

                sl_dist_pct = abs(cmp - raw_sl) / cmp * 100.0 if cmp > 0 else 0.8
                sl_roe_pct = sl_dist_pct * lev_num

                setup_title = "9-20 EMA GOLDEN CROSSOVER 🚀 (Immediate Confirmed Candle)"

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
                            f"🟢 <b>1-MIN EMA SCALP SIGNAL! (LONG)</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                            f"<b>Setup:</b> <b>{setup_title}</b>\n"
                            f"🌊 <b>Trend:</b> <code>Blue (9 EMA) crossed above Red (20 EMA)</code>\n\n"
                            f"⚙️ <b>Trade Parameters:</b>\n"
                            f"• <b>Direction:</b> <code>LONG</code> (7x Isolated)\n"
                            f"• <b>Entry CMP:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"🛑 <b>Stop Loss (Swing Low):</b> <code>${format_coin_price(raw_sl)}</code> (-{sl_dist_pct:.2f}% / -{sl_roe_pct:.1f}% ROE)\n"
                            f"🎯 <b>Target (Max TP):</b> <code>${format_coin_price(tp1)}</code> (+1.8% / +12.6% ROE)\n"
                            f"🔄 <b>Trailing Stop:</b> Breakeven at +5% ROE | Continuous Peak-Trailing (1.5% below peak) above +7% ROE!\n\n"
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
            # 🔴 SHORT ENTRY (Initial SL = Recent Swing High)
            # ------------------------------------------------------------------
            elif signal_side == 'SHORT':
                recent_swing_high = max(highs[-8:])
                raw_sl = round_coin_price(recent_swing_high * 1.0005)

                if (raw_sl - cmp) < (cmp * 0.0035):
                    raw_sl = round_coin_price(cmp * 1.005)
                elif (raw_sl - cmp) > (cmp * 0.013):
                    raw_sl = round_coin_price(cmp * 1.012)

                tp1 = round_coin_price(cmp * 0.982)

                sl_dist_pct = abs(raw_sl - cmp) / cmp * 100.0 if cmp > 0 else 0.8
                sl_roe_pct = sl_dist_pct * lev_num

                setup_title = "9-20 EMA DEATH CROSSOVER 📉 (Immediate Confirmed Candle)"

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
                            f"🔴 <b>1-MIN EMA SCALP SIGNAL! (SHORT)</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                            f"<b>Setup:</b> <b>{setup_title}</b>\n"
                            f"🌊 <b>Trend:</b> <code>Blue (9 EMA) crossed below Red (20 EMA)</code>\n\n"
                            f"⚙️ <b>Trade Parameters:</b>\n"
                            f"• <b>Direction:</b> <code>SHORT</code> (7x Isolated)\n"
                            f"• <b>Entry CMP:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"🛑 <b>Stop Loss (Swing High):</b> <code>${format_coin_price(raw_sl)}</code> (-{sl_dist_pct:.2f}% / -{sl_roe_pct:.1f}% ROE)\n"
                            f"🎯 <b>Target (Max TP):</b> <code>${format_coin_price(tp1)}</code> (+1.8% / +12.6% ROE)\n"
                            f"🔄 <b>Trailing Stop:</b> Breakeven at +5% ROE | Continuous Peak-Trailing (1.5% below peak) above +7% ROE!\n\n"
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
# 10. CONTINUOUS PEAK-TRAILING STOP LOSS & EXIT ENGINE
# ==============================================================================
def monitor_active_positions():
    """
    DYNAMIC PEAK-TRAILING STOP LOSS & PURE TREND-RIDER:
    1. Trailing SL Tier 1: At +5% ROE -> Moves SL to lock +2.0% ROE (Breakeven + fee profit)
    2. Continuous Peak Trailing: Once ROE >= +7.0% -> Dynamically trails 1.5% ROE below the highest peak ROE reached!
       (e.g., At +9.0% Peak -> SL trails to +7.5% ROE; at +12% Peak -> SL trails to +10.5% ROE)
    3. Exits on Reverse Crossover (Blue 9 EMA crosses Red 20 EMA in reverse on closed candle)
    4. Exits if Trailing/Initial SL or Target TP is reached.
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
                    current_tier = trade.get('trail_tier', 0)

                    # 1. Check if closed manually on CoinDCX
                    live_qty = fetch_coindcx_live_position_qty(symbol)
                    if live_qty <= 0.0:
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        log_trade_event(symbol, "CLOSED_MANUALLY", {"status": "Closed manually on CoinDCX"})
                        continue

                    # 30-second minimum hold before evaluation
                    if pos_age < 30:
                        continue

                    m1_klines = fetch_klines(symbol, '1m', 35)
                    if not m1_klines or len(m1_klines) < 25: continue

                    closes = [k[4] for k in m1_klines]
                    cmp = closes[-1]
                    sell_qty = min(live_qty, trade.get('remaining_qty', live_qty))

                    ema9_series = calculate_ema_series(closes, 9)
                    ema20_series = calculate_ema_series(closes, 20)
                    e9_closed = ema9_series[-2]
                    e20_closed = ema20_series[-2]

                    pnl_pct = ((cmp - entry_p) / entry_p * 100) if side == "LONG" else ((entry_p - cmp) / entry_p * 100)
                    roe_pct = pnl_pct * lev

                    # ----------------------------------------------------------
                    # 🔄 CONTINUOUS PEAK-TRAILING STOP LOSS ENGINE
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

                        # Peak-Trailing Engine: Trail 1.5% ROE below peak once peak >= 7.0%
                        if peak_roe >= 7.0:
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

                        # Tier 1: At +5% ROE -> Lock +2.0% ROE (Breakeven + fee cushion)
                        elif peak_roe >= 5.0 and current_tier < 1:
                            target_sl = round_coin_price(entry_p * (1.0 + (0.020 / lev)))
                            if target_sl > trade['sl']:
                                new_sl_val = target_sl
                                trade['trail_tier'] = 1
                                trade['last_trail_type'] = 'tier1'
                                trade['last_notified_roe'] = 2.0
                                tier_name = "TIER 1 (+5.0% ROE Reached ➔ Locked +2.0% ROE Breakeven)"
                                trail_updated = True

                    elif side == "SHORT":
                        # Track lowest peak price reached
                        if cmp < trade.get('lowest_price', entry_p):
                            trade['lowest_price'] = cmp
                        peak_p = trade['lowest_price']
                        peak_roe = ((entry_p - peak_p) / entry_p * 100.0) * lev
                        last_notified_roe = trade.get('last_notified_roe', 0.0)

                        # Peak-Trailing Engine: Trail 1.5% ROE below peak once peak >= 7.0%
                        if peak_roe >= 7.0:
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

                        # Tier 1: At +5% ROE -> Lock +2.0% ROE (Breakeven + fee cushion)
                        elif peak_roe >= 5.0 and current_tier < 1:
                            target_sl = round_coin_price(entry_p * (1.0 - (0.020 / lev)))
                            if target_sl < trade['sl']:
                                new_sl_val = target_sl
                                trade['trail_tier'] = 1
                                trade['last_trail_type'] = 'tier1'
                                trade['last_notified_roe'] = 2.0
                                tier_name = "TIER 1 (+5.0% ROE Reached ➔ Locked +2.0% ROE Breakeven)"
                                trail_updated = True

                    # Ratchet update & exchange bracket synchronization
                    if trade['sl'] != new_sl_val:
                        trade['sl'] = new_sl_val
                        save_active_trades()
                        # Update exchange native SL in background
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
                            f"✅ <i>Profits dynamically locked! Trailing 1.5% below highest peak.</i>"
                        )

                    # ----------------------------------------------------------
                    # 🏁 EXIT EVALUATION
                    # ----------------------------------------------------------
                    exit_reason = None

                    # 1. Target TP reached
                    if side == "LONG" and cmp >= trade['tp1']:
                        exit_reason = f"🎯 TARGET REACHED (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                    elif side == "SHORT" and cmp <= trade['tp1']:
                        exit_reason = f"🎯 TARGET REACHED (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"

                    # 2. Stop Loss (Trailing SL or Initial SL)
                    elif side == "LONG" and cmp <= trade['sl']:
                        if trade.get('trail_tier', 0) > 0:
                            exit_reason = f"🔒 TRAILING STOP HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                        else:
                            exit_reason = f"🛑 INITIAL SWING SL HIT ({pnl_pct:.2f}% | {roe_pct:.1f}% ROE)"
                    elif side == "SHORT" and cmp >= trade['sl']:
                        if trade.get('trail_tier', 0) > 0:
                            exit_reason = f"🔒 TRAILING STOP HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                        else:
                            exit_reason = f"🛑 INITIAL SWING SL HIT ({pnl_pct:.2f}% | {roe_pct:.1f}% ROE)"

                    # 3. REVERSE CROSSOVER: Blue line crosses Red line
                    elif side == "LONG" and e9_closed < e20_closed:
                        exit_reason = f"🔄 REVERSE CROSSOVER (Blue 9 EMA crossed below Red 20 EMA) ({pnl_pct:+.2f}%)"
                    elif side == "SHORT" and e9_closed > e20_closed:
                        exit_reason = f"🔄 REVERSE CROSSOVER (Blue 9 EMA crossed above Red 20 EMA) ({pnl_pct:+.2f}%)"

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
# 11. TELEGRAM COMMAND LISTENER (/start, /stop, /status)
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

                    if text == "/start":
                        AUTO_TRADING_ENABLED = True
                        save_active_trades()
                        send_telegram_message("▶️ <b>Auto-trading RESUMED.</b> Scanning 1M charts for crossovers.")
                    elif text == "/stop":
                        AUTO_TRADING_ENABLED = False
                        save_active_trades()
                        send_telegram_message("⏸️ <b>Auto-trading PAUSED.</b> Signals will be broadcast only.")
                    elif text == "/status":
                        with active_trades_lock:
                            count = len(ACTIVE_TRADES)
                            summary = ""
                            for k, v in ACTIVE_TRADES.items():
                                summary += f"\n• {k}: {v['side'].upper()} @ ${v['entry_price']}"
                        send_telegram_message(
                            f"🤖 <b>BOT STATUS</b>\n"
                            f"• Auto-Trading: {'🟢 ACTIVE' if AUTO_TRADING_ENABLED else '🔴 PAUSED'}\n"
                            f"• Active Scalps: {count}/{MAX_ACTIVE_TRADES}{summary}"
                        )
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
        <title>1-Min EMA Scalping Bot</title>
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
                <h1>⚡ 1-Minute 9 & 20 EMA Scalper</h1>
                <p>Status: <b>{'🟢 RUNNING' if AUTO_TRADING_ENABLED else '🔴 PAUSED'}</b> | Trailing SL: <b>Continuous Peak-Trailing (1.5% below peak above 7% ROE)</b></p>
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
    send_telegram_message("🔔 <b>Crypto-Scanner Test Alert</b>\nBot connection is fully functional and live!")
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

    # Recover any live positions immediately on boot
    recover_live_coindcx_positions()

    threading.Thread(target=run_scalp_scan_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()

    send_telegram_message(
        "⚡ <b>1-MINUTE 9 & 20 EMA SCALPING BOT DEPLOYED!</b>\n\n"
        "• <b>Strategy:</b> Pure 9/20 EMA Crossover Scalper\n"
        "• <b>Watchlist:</b> 70 Top High-Liquidity Coins\n"
        "• <b>Initial SL:</b> Recent Swing High (Short) / Swing Low (Long)\n"
        "• <b>Continuous Peak-Trailing SL:</b>\n"
        "   └ 🥉 Tier 1: At +5% ROE ➔ Locks +2.0% ROE (Breakeven)\n"
        "   └ 🚀 Peak-Trail: At ≥+7% ROE ➔ Continuously trails 1.5% ROE below highest peak!\n"
        "• <b>Exit:</b> Reverse Cross (Blue crosses Red) or Target\n"
        "• <b>Margin:</b> ₹1,000 INR (7x Isolated Leverage)\n"
        "• <b>Controls:</b> Web 1-Click Dashboard + Telegram /start & /stop"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting 1-Minute EMA Scalping server on port {port}...")
    app.run(host="0.0.0.0", port=port)
