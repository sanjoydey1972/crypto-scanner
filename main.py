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
        save_state(st)

# Telegram Bot Credentials
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8938527650").strip()

# CoinDCX API Credentials
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"

ctx = ssl._create_unverified_context()

# ==============================================================================
# 2. WATCHLIST & CRYPTO PAIR ALIASES
# ==============================================================================
WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'DOGE-USDT', 
    'XRP-USDT', 'ADA-USDT', 'LINK-USDT', 'NEAR-USDT', 'BCH-USDT', 
    'SUI-USDT', 'LTC-USDT', 'DOT-USDT', 'PEPE-USDT', 'OP-USDT', 
    'ARB-USDT', 'APT-USDT', 'RENDER-USDT', 'INJ-USDT', 'FET-USDT', 
    'TIA-USDT', 'WIF-USDT', 'SHIB-USDT', 'AAVE-USDT', 'UNI-USDT', 
    'BNB-USDT', 'ONDO-USDT', 'POL-USDT', 'TRX-USDT', 'TAO-USDT',
    'CRV-USDT', 'ENA-USDT', 'FTM-USDT', 'SEI-USDT', 'STX-USDT'
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

SYMBOL_COOLDOWN_SECONDS = 180

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

def get_today_executed_trades_count():
    today_str = get_ist_now().strftime("%d-%m-%Y")
    with trade_history_lock:
        events = load_all_trade_events()
        return len([e for e in events if e.get('date') == today_str and e.get('type') == 'EXECUTED'])

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

def clear_telegram_webhooks():
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c",
        "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA"
    ]))
    for tok in candidate_tokens:
        if not tok: continue
        try:
            url = f"https://api.telegram.org/bot{tok}/deleteWebhook?drop_pending_updates=False"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
                pass
        except Exception: pass

# ==============================================================================
# 5. DYNAMIC PRECISION & CANDLE ENGINE
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
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode('utf-8'))

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

def eval_crossover_setup(klines, ema9_series, ema20_series, ema50_series):
    if len(klines) < 10 or len(ema9_series) < 10 or len(ema20_series) < 10 or len(ema50_series) < 10:
        return None, 0

    curr_close = klines[-1][4]
    curr_open = klines[-1][1]
    curr_high = klines[-1][2]
    curr_low = klines[-1][3]
    candle_range = curr_high - curr_low
    candle_body = abs(curr_close - curr_open)

    is_curr_green = curr_close > curr_open
    is_curr_red = curr_close < curr_open

    curr_ema9 = ema9_series[-1]
    curr_ema20 = ema20_series[-1]
    curr_ema50 = ema50_series[-1]
    prev1_ema9 = ema9_series[-2]
    prev1_ema20 = ema20_series[-2]
    prev2_ema9 = ema9_series[-3]
    prev2_ema20 = ema20_series[-3]
    prev3_ema9 = ema9_series[-4]
    prev3_ema20 = ema20_series[-4]

    ema_spread_pct = abs(curr_ema9 - curr_ema20) / curr_ema20 if curr_ema20 > 0 else 0
    if ema_spread_pct < 0.00012:
        return None, 0

    if candle_range > 0 and (candle_body / candle_range) < 0.28:
        return None, 0

    # 1. 🟢 BULLISH CROSSOVER CHECK (Price > 50 EMA)
    if curr_ema9 > curr_ema20 and is_curr_green and curr_close > curr_ema50:
        if prev1_ema9 <= prev1_ema20:
            return 'LONG', 0
        elif prev2_ema9 <= prev2_ema20:
            return 'LONG', 1
        elif prev3_ema9 <= prev3_ema20 and (klines[-2][4] > klines[-2][1]):
            return 'LONG', 2

    # 2. 🔴 BEARISH CROSSOVER CHECK (Price < 50 EMA)
    if curr_ema9 < curr_ema20 and is_curr_red and curr_close < curr_ema50:
        if prev1_ema9 >= prev1_ema20:
            return 'SHORT', 0
        elif prev2_ema9 >= prev2_ema20:
            return 'SHORT', 1
        elif prev3_ema9 >= prev3_ema20 and (klines[-2][4] < klines[-2][1]):
            return 'SHORT', 2

    return None, 0

# ==============================================================================
# 6. COINDCX FUTURES POSITION INSPECTION & RECOVERY
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

def extract_exchange_tpsl(p):
    if not isinstance(p, dict): return None, None
    tp, sl = None, None
    tp_obj = p.get('take_profit') or p.get('tp') or p.get('take_profit_order')
    if isinstance(tp_obj, dict):
        tp = tp_obj.get('stop_price') or tp_obj.get('trigger_price') or tp_obj.get('price')
    elif tp_obj is not None:
        tp = tp_obj
    if not tp:
        tp = p.get('target_price') or p.get('take_profit_price')

    sl_obj = p.get('stop_loss') or p.get('sl') or p.get('stop_loss_order')
    if isinstance(sl_obj, dict):
        sl = sl_obj.get('stop_price') or sl_obj.get('trigger_price') or sl_obj.get('price')
    elif sl_obj is not None:
        sl = sl_obj
    if not sl:
        sl = p.get('stop_loss_price') or p.get('stop_price')
    try:
        tp = float(tp) if tp is not None else None
    except Exception: tp = None
    try:
        sl = float(sl) if sl is not None else None
    except Exception: sl = None
    return tp, sl

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
                    tp_dist = entry_p * 0.010
                    tp_val = round_coin_price(entry_p - tp_dist if side == "SHORT" else entry_p + tp_dist)
                    sl_val = round_coin_price(entry_p + entry_p * 0.006 if side == "SHORT" else entry_p - entry_p * 0.006)

                    ACTIVE_TRADES[sym] = {
                        'entry_price': entry_p,
                        'total_qty': qty,
                        'remaining_qty': qty,
                        'side': side,
                        'tp1': tp_val,
                        'sl': sl_val,
                        'initial_tp': tp_val,
                        'initial_sl': sl_val,
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
# 7. ORDER EXECUTION WITH LOT SIZE PRECISION NORMALIZATION
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
            usdt_inr_rate = 88.5
            position_value_usdt = (margin_inr * leverage) / usdt_inr_rate
            raw_qty = position_value_usdt / cmp if cmp > 0 else 0.1

            # Precision normalization for all pairs (handles UNI, AVAX, PENDLE integer rules)
            if raw_coin == 'BTC': quantity = round(max(0.001, raw_qty), 3)
            elif raw_coin in ['ETH', 'SOL']: quantity = round(max(0.1, raw_qty), 1)
            elif raw_coin in ['UNI', 'PENDLE', 'AVAX', 'AAVE', 'LINK', 'DOT']: 
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
        }),
        (futures_url, {
            "order": {
                "side": side.lower(),
                "pair": f"B-{clean_coin}USDT",
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
    ts = int(time.time() * 1000)

    payload_variants = [
        {"timestamp": ts, "id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": ts, "position_id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}},
        {"timestamp": ts, "pair": pair, "id": str(position_id), "take_profit": {"stop_price": float(target_price)}, "stop_loss": {"stop_price": float(stop_loss_price)}}
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

def sync_all_open_positions_tpsl():
    pos_list = fetch_all_coindcx_live_positions()
    if not pos_list or not isinstance(pos_list, list): return []

    synced_results = []
    for p in pos_list:
        if not isinstance(p, dict) or not is_position_open(p): continue
        p_pair = str(p.get('pair', p.get('market', p.get('symbol', '')))).upper()
        raw_c = p_pair.replace("B-", "").replace("_USDT", "").replace("USDT", "").replace("1000", "")
        sym = f"{raw_c}-USDT"
        entry_p = float(p.get('avg_price', 0) or p.get('entry_price', 0) or p.get('price', 0))
        if entry_p <= 0: continue

        side_str = str(p.get('side', p.get('order_type', 'buy'))).lower()
        side = "SHORT" if ('short' in side_str or 'sell' in side_str) else "LONG"

        with active_trades_lock:
            trade = ACTIVE_TRADES.get(sym)
            if trade:
                tp_val = trade.get('tp1')
                sl_val = trade.get('sl')
            else:
                tp_dist = entry_p * 0.010
                tp_val = round_coin_price(entry_p - tp_dist if side == "SHORT" else entry_p + tp_dist)
                sl_val = round_coin_price(entry_p + entry_p * 0.006 if side == "SHORT" else entry_p - entry_p * 0.006)

        pos_id = p.get('id') or p.get('position_id') or p.get('positionId')
        if pos_id:
            success = apply_coindcx_native_tpsl(p_pair, pos_id, tp_val, sl_val)
            synced_results.append({'pair': p_pair, 'symbol': sym, 'tp': tp_val, 'sl': sl_val, 'success': success})
        time.sleep(0.5)
    return synced_results

# ==============================================================================
# 8. 9 EMA & 20 EMA 1-MINUTE SCALPING ENGINE
# ==============================================================================
def run_scan():
    today_str = get_ist_now().strftime("%d-%m-%Y")
    curr_state = load_state()

    with active_trades_lock:
        if len(ACTIVE_TRADES) >= 2:
            return

    for symbol in WATCHLIST:
        try:
            time.sleep(0.01)

            with active_trades_lock:
                if len(ACTIVE_TRADES) >= 2:
                    return
                if symbol in ACTIVE_TRADES:
                    continue

            with pending_orders_lock:
                if symbol in PENDING_ORDERS:
                    continue

            if curr_state.get(f"sl_banned_{symbol}") == today_str:
                continue

            last_traded = curr_state.get(f"last_traded_{symbol}", 0)
            if time.time() - last_traded < SYMBOL_COOLDOWN_SECONDS:
                continue

            m1_klines = fetch_klines(symbol, '1m', 65)
            if not m1_klines or len(m1_klines) < 52:
                continue

            closes = [k[4] for k in m1_klines]
            highs = [k[2] for k in m1_klines]
            lows = [k[3] for k in m1_klines]

            cmp = closes[-1]

            ema9_series = calculate_ema_series(closes, 9)
            ema20_series = calculate_ema_series(closes, 20)
            ema50_series = calculate_ema_series(closes, 50)

            curr_ema9 = ema9_series[-1]
            curr_ema20 = ema20_series[-1]
            curr_ema50 = ema50_series[-1]

            signal_side, candles_after_cross = eval_crossover_setup(m1_klines, ema9_series, ema20_series, ema50_series)
            if not signal_side:
                continue

            coin_margin = 1000.0
            lev_num = 7

            # ------------------------------------------------------------------
            # 🟢 LONG ENTRY (Above 50 EMA + 9 EMA Crossed Above 20 EMA)
            # ------------------------------------------------------------------
            if signal_side == 'LONG':
                swing_low = min(lows[-6:])
                raw_sl = min(swing_low * 0.9995, curr_ema20 * 0.9990)
                sl_dist = cmp - raw_sl
                if sl_dist > cmp * 0.008: raw_sl = cmp * 0.992
                elif sl_dist < cmp * 0.004: raw_sl = cmp * 0.996
                raw_sl = round_coin_price(raw_sl)

                tp1 = round_coin_price(max(cmp + (cmp - raw_sl) * 1.5, cmp * 1.0090))

                candle_str = "Immediate Crossover Candle" if candles_after_cross == 0 else f"{candles_after_cross} Green Candle(s) After Cross"
                setup_title = f"9-20 EMA GOLDEN CROSSOVER 🚀 ({candle_str})"

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

                        sl_dist_pct = abs(cmp - raw_sl) / cmp * 100.0 if cmp > 0 else 0.6
                        tp_dist_pct = abs(tp1 - cmp) / cmp * 100.0 if cmp > 0 else 1.0

                        msg = (
                            f"🟢 <b>1-MIN EMA SCALP SIGNAL! (LONG)</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                            f"<b>Setup:</b> <b>{setup_title}</b>\n"
                            f"🔥 <b>Trend:</b> <code>Confirmed > 50 EMA (${format_coin_price(curr_ema50)})</code>\n\n"
                            f"⚙️ <b>Trade Parameters:</b>\n"
                            f"• <b>Direction:</b> <code>LONG</code> (7x Isolated)\n"
                            f"• <b>Entry CMP:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"🛑 <b>Stop Loss (SL):</b> <code>${format_coin_price(raw_sl)}</code> (-{sl_dist_pct:.2f}% / -{sl_dist_pct * lev_num:.1f}% ROE)\n"
                            f"🎯 <b>Target (TP1):</b> <code>${format_coin_price(tp1)}</code> (+{tp_dist_pct:.2f}% / +{tp_dist_pct * lev_num:.1f}% ROE)\n"
                            f"⚡ <b>Hold Rule:</b> Ride until Target TP1 or Stop Loss (No panic exits)!\n\n"
                            f"⚡ <b>AUTO-TRADE EXECUTED ON COINDCX!</b>\n"
                            f"• Order ID: <code>{order_id}</code>\n"
                            f"• Quantity: <code>{qty}</code> | Margin: ₹{coin_margin:.0f}\n"
                            f"🔄 <i>Native CoinDCX TP/SL auto-fitting active...</i>"
                        )
                        send_telegram_message(msg)

                        with active_trades_lock:
                            if len(ACTIVE_TRADES) >= 2:
                                return
                    else:
                        err_reason = trade_res.get('error', 'Unknown Error')
                        log_trade_event(symbol, "CANCELLED", {"cmp": cmp, "error": err_reason, "side": "LONG"})
                        curr_state[f"last_traded_{symbol}"] = time.time()
                        save_state(curr_state)

                        clean_err = re.sub(r'<[^>]+>', ' ', str(err_reason))
                        notice_msg = (
                            f"⚡ <b>SCALP SIGNAL DETECTED: {symbol} (LONG)</b>\n\n"
                            f"<b>Setup:</b> {setup_title}\n"
                            f"<b>CMP:</b> ${format_coin_price(cmp)} | <b>Target:</b> ${format_coin_price(tp1)} | <b>SL:</b> ${format_coin_price(raw_sl)}\n\n"
                            f"⚠️ <b>COINDCX EXECUTION NOTICE:</b>\n"
                            f"<code>{clean_err[:120]}</code>\n\n"
                            f"<i>Cooldown locked for 3 minutes before retry.</i>"
                        )
                        send_telegram_message(notice_msg)
                finally:
                    with pending_orders_lock:
                        PENDING_ORDERS.discard(symbol)
                continue

            # ------------------------------------------------------------------
            # 🔴 SHORT ENTRY (Below 50 EMA + 9 EMA Crossed Below 20 EMA)
            # ------------------------------------------------------------------
            elif signal_side == 'SHORT':
                swing_high = max(highs[-6:])
                raw_sl = max(swing_high * 1.0005, curr_ema20 * 1.0010)
                sl_dist = raw_sl - cmp
                if sl_dist > cmp * 0.008: raw_sl = cmp * 1.008
                elif sl_dist < cmp * 0.004: raw_sl = cmp * 1.004
                raw_sl = round_coin_price(raw_sl)

                tp1 = round_coin_price(min(cmp - (raw_sl - cmp) * 1.5, cmp * 0.9910))

                candle_str = "Immediate Crossover Candle" if candles_after_cross == 0 else f"{candles_after_cross} Red Candle(s) After Cross"
                setup_title = f"9-20 EMA DEATH CROSSOVER 📉 ({candle_str})"

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

                        sl_dist_pct = abs(raw_sl - cmp) / cmp * 100.0 if cmp > 0 else 0.6
                        tp_dist_pct = abs(cmp - tp1) / cmp * 100.0 if cmp > 0 else 1.0

                        msg = (
                            f"🔴 <b>1-MIN EMA SCALP SIGNAL! (SHORT)</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                            f"<b>Setup:</b> <b>{setup_title}</b>\n"
                            f"🔥 <b>Trend:</b> <code>Confirmed < 50 EMA (${format_coin_price(curr_ema50)})</code>\n\n"
                            f"⚙️ <b>Trade Parameters:</b>\n"
                            f"• <b>Direction:</b> <code>SHORT</code> (7x Isolated)\n"
                            f"• <b>Entry CMP:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"🛑 <b>Stop Loss (SL):</b> <code>${format_coin_price(raw_sl)}</code> (-{sl_dist_pct:.2f}% / -{sl_dist_pct * lev_num:.1f}% ROE)\n"
                            f"🎯 <b>Target (TP1):</b> <code>${format_coin_price(tp1)}</code> (+{tp_dist_pct:.2f}% / +{tp_dist_pct * lev_num:.1f}% ROE)\n"
                            f"⚡ <b>Hold Rule:</b> Ride until Target TP1 or Stop Loss (No panic exits)!\n\n"
                            f"⚡ <b>AUTO-TRADE EXECUTED ON COINDCX!</b>\n"
                            f"• Order ID: <code>{order_id}</code>\n"
                            f"• Quantity: <code>{qty}</code> | Margin: ₹{coin_margin:.0f}\n"
                            f"🔄 <i>Native CoinDCX TP/SL auto-fitting active...</i>"
                        )
                        send_telegram_message(msg)

                        with active_trades_lock:
                            if len(ACTIVE_TRADES) >= 2:
                                return
                    else:
                        err_reason = trade_res.get('error', 'Unknown Error')
                        log_trade_event(symbol, "CANCELLED", {"cmp": cmp, "error": err_reason, "side": "SHORT"})
                        curr_state[f"last_traded_{symbol}"] = time.time()
                        save_state(curr_state)

                        clean_err = re.sub(r'<[^>]+>', ' ', str(err_reason))
                        notice_msg = (
                            f"⚡ <b>SCALP SIGNAL DETECTED: {symbol} (SHORT)</b>\n\n"
                            f"<b>Setup:</b> {setup_title}\n"
                            f"<b>CMP:</b> ${format_coin_price(cmp)} | <b>Target:</b> ${format_coin_price(tp1)} | <b>SL:</b> ${format_coin_price(raw_sl)}\n\n"
                            f"⚠️ <b>COINDCX EXECUTION NOTICE:</b>\n"
                            f"<code>{clean_err[:120]}</code>\n\n"
                            f"<i>Cooldown locked for 3 minutes before retry.</i>"
                        )
                        send_telegram_message(notice_msg)
                finally:
                    with pending_orders_lock:
                        PENDING_ORDERS.discard(symbol)
                continue
        except Exception: pass

# ==============================================================================
# 9. TRUE REVERSE CROSSOVER & TARGET/STOP-LOSS EXIT ENGINE
# ==============================================================================
def monitor_active_positions():
    """
    Monitors active positions with:
    1. TARGET HIT (TP1): Exits in solid profit (+6% to +10% ROE)
    2. STOP LOSS HIT (SL): Exchange protects capital cleanly (-3% to -5% ROE)
    3. TRUE REVERSE EMA CROSSOVER: 9 EMA must clearly cross 20 EMA by at least 0.05%
       (NO MORE 0.000004 MICRO-KISS EXITS!)
    4. NO 9 EMA PANIC EXITS: Gives trades room to ride out normal wicks and hit target!
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
                    pos_age = time.time() - entry_time

                    # 1. Manual Close Detection on CoinDCX
                    live_qty = fetch_coindcx_live_position_qty(symbol)
                    if live_qty <= 0.0:
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        log_trade_event(symbol, "CLOSED_MANUALLY", {"status": "Closed manually on CoinDCX"})
                        send_telegram_message(
                            f"ℹ️ <b>MANUAL POSITION CLOSE DETECTED:</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code>\n"
                            f"• Position was closed on CoinDCX.\n"
                            f"• Tracking removed cleanly."
                        )
                        continue

                    # 2. Manual SL / TP Updates on CoinDCX
                    if not trade.get('manual_override', False):
                        pos_info = fetch_coindcx_position_details(symbol)
                        if pos_info and isinstance(pos_info.get('raw'), dict):
                            exch_tp, exch_sl = extract_exchange_tpsl(pos_info['raw'])
                            init_tp = trade.get('initial_tp', trade.get('tp1', 0))
                            init_sl = trade.get('initial_sl', trade.get('sl', 0))

                            tp_changed = exch_tp and abs(exch_tp - init_tp) > 0.00001
                            sl_changed = exch_sl and abs(exch_sl - init_sl) > 0.00001

                            if tp_changed or sl_changed:
                                with active_trades_lock:
                                    trade['manual_override'] = True
                                    if exch_tp: trade['tp1'] = exch_tp
                                    if exch_sl: trade['sl'] = exch_sl
                                save_active_trades()
                                send_telegram_message(
                                    f"👤 <b>MANUAL COINDCX SL/TP DETECTED!</b>\n\n"
                                    f"<b>Pair:</b> <code>{symbol}</code>\n"
                                    f"• Your Manual TP: <code>${format_coin_price(trade['tp1'])}</code>\n"
                                    f"• Your Manual SL: <code>${format_coin_price(trade['sl'])}</code>\n"
                                    f"⏸️ <i>System stoploss paused. CoinDCX bracket active.</i>"
                                )

                    if trade.get('manual_override', False):
                        continue

                    m1_klines = fetch_klines(symbol, '1m', 35)
                    if not m1_klines or len(m1_klines) < 25: continue

                    closes = [k[4] for k in m1_klines]
                    cmp = closes[-1]
                    sell_qty = min(live_qty, trade.get('remaining_qty', live_qty))

                    if side == "LONG":
                        raw_roe_pct = ((cmp - entry_p) / entry_p) * trade.get('leverage', 7) * 100.0
                    else:
                        raw_roe_pct = ((entry_p - cmp) / entry_p) * trade.get('leverage', 7) * 100.0

                    # ----------------------------------------------------------
                    # A. HARD STOP LOSS HIT (Exchange level protection)
                    # ----------------------------------------------------------
                    is_sl_hit = (side == "LONG" and cmp <= trade['sl']) or (side == "SHORT" and cmp >= trade['sl'])
                    if is_sl_hit:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        st = load_state()
                        st[f"last_traded_{symbol}"] = time.time()
                        save_state(st)

                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_roe_pct, 1), "sl_type": "STOP LOSS HIT 🛑", "side": side})
                        send_telegram_message(
                            f"🛑 <b>SCALP STOP LOSS HIT:</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> ({side})\n"
                            f"• <b>Exit Price:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"• <b>Realized Loss:</b> <code>{raw_roe_pct:+.1f}% ROE</code>\n"
                            f"🛡️ <i>Capital protected cleanly under 1M risk rule.</i>"
                        )
                        continue

                    # ----------------------------------------------------------
                    # B. PROFIT TARGET (TP1) HIT (The Main Goal!)
                    # ----------------------------------------------------------
                    is_tp_hit = (side == "LONG" and cmp >= trade['tp1']) or (side == "SHORT" and cmp <= trade['tp1'])
                    if is_tp_hit:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        st = load_state()
                        st[f"last_traded_{symbol}"] = time.time()
                        save_state(st)

                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_roe_pct, 1), "sl_type": "PROFIT TARGET (TP1) 🚀", "side": side})
                        send_telegram_message(
                            f"🎯 <b>SCALP TARGET HIT (TP1)! 🚀</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> ({side})\n"
                            f"• <b>Entry:</b> <code>${format_coin_price(entry_p)}</code> | <b>Exit:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"• <b>Realized Gain:</b> <code>+{raw_roe_pct:.1f}% ROE</code> 💰"
                        )
                        continue

                    # ----------------------------------------------------------
                    # C. MINIMUM 90-SECOND BREATHING ROOM
                    # ----------------------------------------------------------
                    if pos_age < 90:
                        continue

                    # ----------------------------------------------------------
                    # D. TRUE REVERSE EMA CROSSOVER (Requires Meaningful Spread)
                    # ----------------------------------------------------------
                    closed_klines = m1_klines[:-1]
                    closed_closes = [k[4] for k in closed_klines]
                    closed_ema9 = calculate_ema_series(closed_closes, 9)[-1]
                    closed_ema20 = calculate_ema_series(closed_closes, 20)[-1]

                    # Must have at least 0.05% clear crossover separation
                    is_long_true_reverse = (side == "LONG" and closed_ema9 < closed_ema20 * 0.9995)
                    is_short_true_reverse = (side == "SHORT" and closed_ema9 > closed_ema20 * 1.0005)

                    if is_long_true_reverse or is_short_true_reverse:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        st = load_state()
                        st[f"last_traded_{symbol}"] = time.time()
                        save_state(st)

                        exit_title = "TRUE REVERSE EMA CROSS EXIT (LONG) 🔄" if side == "LONG" else "TRUE REVERSE EMA CROSS EXIT (SHORT) 🔄"
                        reason_desc = f"1M candle closed with confirmed reversal: 9 EMA (${format_coin_price(closed_ema9)}) crossed 20 EMA (${format_coin_price(closed_ema20)})"
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_roe_pct, 1), "sl_type": exit_title, "side": side})
                        send_telegram_message(
                            f"🏁 <b>SCALP CLOSED: {exit_title}</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> ({side})\n"
                            f"• <b>Reason:</b> {reason_desc}\n"
                            f"• <b>Exit Price:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"• <b>Realized:</b> <code>{raw_roe_pct:+.1f}% ROE</code>"
                        )
                        continue

                    # ----------------------------------------------------------
                    # E. 10-MINUTE STAGNATION TIME-STOP
                    # ----------------------------------------------------------
                    if pos_age >= 600:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        st = load_state()
                        st[f"last_traded_{symbol}"] = time.time()
                        save_state(st)

                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_roe_pct, 1), "sl_type": "10-MIN STAGNATION TIME-STOP ⏱️", "side": side})
                        send_telegram_message(
                            f"⏱️ <b>10-MINUTE SCALP TIME-STOP EXECUTED!</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> ({side})\n"
                            f"• <b>Exit Price:</b> <code>${format_coin_price(cmp)}</code>\n"
                            f"• <b>Result:</b> <code>{raw_roe_pct:+.1f}% ROE</code>\n"
                            f"• Released margin for fresh 1-minute opportunities."
                        )
                        continue

                except Exception as e:
                    print(f"Error monitoring scalp on {symbol}: {e}")
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(2)

# ==============================================================================
# 10. FLASK WEB DASHBOARD & STATUS CONTROLS
# ==============================================================================
@app.route('/scan-now')
def scan_now_endpoint():
    try:
        today_str = get_ist_now().strftime("%d-%m-%Y")
        with active_trades_lock:
            open_count = len(ACTIVE_TRADES)
            open_names = list(ACTIVE_TRADES.keys())
        
        status_txt = "🟢 LIVE (ENABLED)" if AUTO_TRADING_ENABLED else "🛑 PAUSED (OFF)"
        slot_txt = f"{open_count} / 2 Positions Open" + (f" ({', '.join(open_names)})" if open_names else " (Slots Available)")

        report_lines = [
            f"⚡ REAL-TIME 1M 9-20 EMA SCALPER DIAGNOSTICS ({today_str})",
            f"Engine Status: {status_txt} | Active Slots: {slot_txt} | Strategy: Pure 9/20 EMA with Confirmed Exits",
            f"{'='*105}",
            f"{'SYMBOL':11s} | {'CMP':<10s} | {'9 EMA':<9s} | {'20 EMA':<9s} | {'50 EMA':<9s} | {'TREND':<10s} | {'SETUP'}",
            f"{'-'*105}"
        ]

        scan_symbols = WATCHLIST[:45] if request.args.get('all') == 'true' else WATCHLIST[:20]

        for symbol in scan_symbols:
            try:
                time.sleep(0.01)
                m1 = fetch_klines(symbol, '1m', 65)
                if not m1 or len(m1) < 52:
                    report_lines.append(f"{symbol:11s} | {'SYNCING':<10s} | {'--':<9s} | {'--':<9s} | {'--':<9s} | {'CONNECTING':<10s} | 🔄 BUFFERING")
                    continue
                closes = [k[4] for k in m1]
                cmp = closes[-1]
                ema9_series = calculate_ema_series(closes, 9)
                ema20_series = calculate_ema_series(closes, 20)
                ema50_series = calculate_ema_series(closes, 50)
                ema9 = ema9_series[-1]
                ema20 = ema20_series[-1]
                ema50 = ema50_series[-1]

                if ema9 > ema20 * 1.00025 and cmp > ema50:
                    trend_txt = "🟢 BULLISH"
                elif ema9 < ema20 * 0.99975 and cmp < ema50:
                    trend_txt = "🔴 BEARISH"
                else:
                    trend_txt = "⚪ CHOP"

                signal_side, candles_after_cross = eval_crossover_setup(m1, ema9_series, ema20_series, ema50_series)
                
                if signal_side == 'LONG':
                    candle_label = "CROSS NOW" if candles_after_cross == 0 else f"+{candles_after_cross} CANDLE"
                    setup_txt = f"🔥 BUY READY ({candle_label})"
                elif signal_side == 'SHORT':
                    candle_label = "CROSS NOW" if candles_after_cross == 0 else f"+{candles_after_cross} CANDLE"
                    setup_txt = f"🔥 SHORT READY ({candle_label})"
                else:
                    if trend_txt in ["🟢 BULLISH", "🔴 BEARISH"]:
                        setup_txt = "⚪ WAITING (Trend Running)"
                    else:
                        setup_txt = "⚪ WAITING (Chop Filtered)"

                cmp_str = format_coin_price(cmp)
                ema9_str = format_coin_price(ema9)
                ema20_str = format_coin_price(ema20)
                ema50_str = format_coin_price(ema50)
                report_lines.append(f"{symbol:11s} | {cmp_str:<10s} | {ema9_str:<9s} | {ema20_str:<9s} | {ema50_str:<9s} | {trend_txt:<10s} | {setup_txt}")
            except Exception as e:
                report_lines.append(f"{symbol:11s} | {'ERROR':<10s} | {'--':<9s} | {'--':<9s} | {'--':<9s} | {'ERROR':<10s} | ⚠️ {str(e)[:15]}")

        nav_bar = f"<p><b>Status:</b> {status_txt} | <b>Active:</b> {slot_txt}</p><p><a href='/today'>⬅️ Back to Dashboard</a> | <a href='/scan-now'>🔄 Refresh Top 20</a> | <a href='/scan-now?all=true'>🌐 Scan All 45</a></p>"
        return f"<h2>⚡ 1-Minute 9-20 EMA Scalper Diagnostics</h2>{nav_bar}<pre>" + "\n".join(report_lines) + "</pre>", 200
    except Exception as e:
        return f"<h3>⚠️ Scan Error: {e}</h3>", 500

@app.route('/today')
@app.route('/daily')
@app.route('/report')
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

        exec_rows = "".join([f"<tr><td>{e.get('timestamp','').split()[-2]} {e.get('timestamp','').split()[-1]}</td><td><b>{e.get('symbol')}</b> ({e.get('details',{}).get('side','LONG')})</td><td>${format_coin_price(e.get('details',{}).get('cmp', 0))}</td><td>{e.get('details',{}).get('quantity')}</td><td><code>{str(e.get('details',{}).get('order_id'))[:8]}</code></td><td>₹1,000</td></tr>" for e in executed]) if executed else "<tr><td colspan='6' style='text-align:center;'>No trades executed today yet</td></tr>"
        closed_rows = "".join([f"<tr><td>{c.get('timestamp','').split()[-2]} {c.get('timestamp','').split()[-1]}</td><td><b>{c.get('symbol')}</b> ({c.get('details',{}).get('side','LONG')})</td><td><b style='color:{'#00c853' if c.get('details',{}).get('realized_pnl_pct',0)>=0 else '#d50000'};'>{c.get('details',{}).get('realized_pnl_pct',0):+.1f}% ROE</b></td><td>{c.get('details',{}).get('sl_type', 'MANUAL EXIT')}</td></tr>" for c in closed]) if closed else "<tr><td colspan='4' style='text-align:center;'>No closed trades today</td></tr>"

        page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>1-Min EMA Scalping Report ({target_date})</title>
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
                <h1>⚡ 1-Minute 9 & 20 EMA Scalper</h1>
                <p><b>Date:</b> {target_date} | <b>Strategy:</b> Pure 9/20 EMA with Confirmed Target Exits</p>

                <div class="ctrl-panel">
                    <div>
                        <span style="font-size:16px;"><b>Scalping Engine:</b></span> 
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
                    <a href="/scan-now" class="btn btn-blue">Live 1M Diagnostics</a>
                    <a href="/sync-tpsl" class="btn" style="background:#8957e5;">Sync TP/SL</a>
                </div>
                <div class="stats-grid">
                    <div class="stat-box"><div>Executed Today</div><div class="val" style="color:#58a6ff;">{len(executed)}</div></div>
                    <div class="stat-box"><div>Win Rate</div><div class="val" style="color: #3fb950;">{win_rate:.1f}%</div></div>
                    <div class="stat-box"><div>Realized Gain</div><div class="val" style="color: {'#3fb950' if total_pnl >= 0 else '#f85149'};">{total_pnl:+.1f}% ROE</div></div>
                </div>
                <h3>✅ Executed Scalps Today</h3>
                <table><tr><th>Time</th><th>Pair</th><th>Entry Price</th><th>Quantity</th><th>Order ID</th><th>Margin</th></tr>{exec_rows}</table>
                <h3>🏁 Closed Positions & Exits</h3>
                <table><tr><th>Time</th><th>Pair</th><th>Gain / Loss</th><th>Exit Reason</th></tr>{closed_rows}</table>
            </div>
        </body>
        </html>
        """
        return page, 200
    except Exception as e:
        return f"<h3>⚠️ Report Error: {e}</h3>", 500

@app.route('/sync-tpsl')
def sync_tpsl_endpoint():
    try:
        results = sync_all_open_positions_tpsl()
        if not results: return "<h3>ℹ️ No active CoinDCX positions found to sync.</h3>", 200
        rows = "".join([f"<li><b>{r['pair']}</b> ({r['symbol']}) - TP: ${format_coin_price(r['tp'])} | SL: ${format_coin_price(r['sl'])} -> {'<span style=\"color:green;\">✅ APPLIED</span>' if r['success'] else '<span style=\"color:red;\">❌ FAILED</span>'}</li>" for r in results])
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
        'strategy': '9-20 EMA 1-Minute Scalper (Clean Target Exits)',
        'trades_executed_today': daily_count,
        'active_positions': active_list
    }, 200

@app.route('/healthz')
def healthz():
    return "OK", 200

@app.route('/test-telegram')
def test_telegram_endpoint():
    try:
        ok = send_telegram_message("🔔 <b>TELEGRAM TEST ALERT FROM 1M EMA SCALPER!</b>\n\n• Status: 100% ONLINE\n• Signal Broadcast: ACTIVE\n• Timestamp: " + get_ist_now().strftime("%d-%m-%Y %I:%M:%S %p (IST)"))
        return f"<h3>Telegram Ping Result: {'✅ SUCCESS (Check Telegram channel)' if ok else '❌ FAILED (Check Bot Token)'}</h3>", 200
    except Exception as e:
        return f"<h3>⚠️ Error: {e}</h3>", 500

@app.route('/start')
@app.route('/resume')
@app.route('/on')
def start_auto_trading():
    global AUTO_TRADING_ENABLED
    AUTO_TRADING_ENABLED = True
    st = load_state()
    st["auto_trading_enabled"] = True
    save_state(st)
    send_telegram_message(
        "🟢 <b>1-MIN EMA SCALPER ACTIVATED!</b>\n\n"
        "• Auto-order execution on CoinDCX is now <b>LIVE</b>.\n"
        "• Trailing panic exit removed: trades now ride to Target (+1.0%) or Stop Loss.\n"
        "• Turn OFF anytime via /stop or dashboard button."
    )
    return """
    <html><head><meta http-equiv="refresh" content="2;url=/today"><style>body{background:#0b0e14;color:#e1e4e8;font-family:sans-serif;text-align:center;padding:50px;}</style></head>
    <body><h2 style='color:#3fb950;'>🟢 Auto-Trading is now ENABLED & LIVE!</h2><p>Redirecting to dashboard in 2 seconds...</p><p><a href='/today' style='color:#58a6ff;'>Click here if not redirected</a></p></body></html>
    """, 200

@app.route('/stop')
@app.route('/pause')
@app.route('/off')
def stop_auto_trading():
    global AUTO_TRADING_ENABLED
    AUTO_TRADING_ENABLED = False
    st = load_state()
    st["auto_trading_enabled"] = False
    save_state(st)
    send_telegram_message(
        "🛑 <b>1-MIN EMA SCALPER PAUSED!</b>\n\n"
        "• Auto-order execution on CoinDCX is now <b>OFF</b>.\n"
        "• Scanner will only send notifications.\n"
        "• Turn ON anytime via /start or dashboard button."
    )
    return """
    <html><head><meta http-equiv="refresh" content="2;url=/today"><style>body{background:#0b0e14;color:#e1e4e8;font-family:sans-serif;text-align:center;padding:50px;}</style></head>
    <body><h2 style='color:#ff7b72;'>🛑 Auto-Trading is now PAUSED (OFF)!</h2><p>Redirecting to dashboard in 2 seconds...</p><p><a href='/today' style='color:#58a6ff;'>Click here if not redirected</a></p></body></html>
    """, 200

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    clean_p = path.strip().strip('/')
    if clean_p.lower() in ['start', 'on', 'resume']: return start_auto_trading()
    if clean_p.lower() in ['stop', 'off', 'pause']: return stop_auto_trading()
    if clean_p.lower() == 'yesterday':
        yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
        return today_report_endpoint(date_override=yesterday_str)
    if clean_p.lower() in ['today', 'daily', 'report']:
        return today_report_endpoint()
    if re.match(r'^\d{2}-\d{2}-\d{4}$', clean_p):
        return today_report_endpoint(date_override=clean_p)

    if scan_lock.acquire(blocking=False):
        def async_scan():
            try: run_scan()
            finally: scan_lock.release()
        threading.Thread(target=async_scan, daemon=True).start()
        return "⚡ OK - 1M EMA Scalper Triggered via Keep-Alive/Ping", 200

    return "⚡ OK - 1M EMA Scalper Active (Render Cloud Bot)", 200

# ==============================================================================
# 11. TELEGRAM COMMAND LISTENER
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    clear_telegram_webhooks()
    
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
            payload = {'chat_id': chat_id, 'text': text_reply, 'parse_mode': 'HTML', 'disable_web_page_preview': 'true'}
            data = urllib.parse.urlencode(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=6) as r: pass
        except Exception:
            try:
                clean_reply = re.sub(r'<[^>]+>', '', text_reply)
                url = f"https://api.telegram.org/bot{tok}/sendMessage"
                payload = {'chat_id': chat_id, 'text': clean_reply, 'disable_web_page_preview': 'true'}
                data = urllib.parse.urlencode(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=6) as r: pass
            except Exception: pass

    while True:
        for tok in candidate_tokens:
            try:
                url = f"https://api.telegram.org/bot{tok}/getUpdates?offset={token_offsets[tok]}&timeout=4"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=6) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    if not data.get('ok'): continue
                    for update in data.get('result', []):
                        token_offsets[tok] = max(token_offsets[tok], update['update_id'] + 1)
                        msg = update.get('message') or update.get('channel_post') or update.get('edited_message')
                        if not msg: continue

                        msg_date = msg.get('date', 0)
                        if tok not in initialized and msg_date and (msg_date < boot_time - 30):
                            continue

                        user_chat_id = msg.get('chat', {}).get('id', CHAT_ID)
                        if user_chat_id:
                            st_chat = load_state()
                            if st_chat.get('last_telegram_chat_id') != str(user_chat_id):
                                st_chat['last_telegram_chat_id'] = str(user_chat_id)
                                save_state(st_chat)
                        raw_text = msg.get('text', '').strip()
                        if not raw_text: continue

                        cmd = raw_text.lower().split()[0].split('@')[0]

                        if cmd in ['/stop', 'stop', '/pause', 'pause', 'off']:
                            AUTO_TRADING_ENABLED = False
                            st = load_state()
                            st["auto_trading_enabled"] = False
                            save_state(st)
                            reply_user(tok, user_chat_id, (
                                "🛑 <b>1-MIN SCALPER PAUSED!</b>\n\n"
                                "• Auto-order execution on CoinDCX is now <b>OFF</b>.\n"
                                "• Send <code>/start</code> anytime to resume."
                            ))
                        elif cmd in ['/start', 'start', '/resume', 'resume', 'on']:
                            AUTO_TRADING_ENABLED = True
                            st = load_state()
                            st["auto_trading_enabled"] = True
                            save_state(st)
                            reply_user(tok, user_chat_id, (
                                "🟢 <b>1-MIN SCALPER ACTIVATED!</b>\n\n"
                                "• Auto-execution on CoinDCX is now <b>LIVE</b>.\n"
                                "• Trades will ride directly to Target (+1.0%) or Stop Loss.\n"
                                "• Send <code>/stop</code> anytime to pause."
                            ))
                        elif cmd in ['/status', 'status']:
                            daily_count = get_today_executed_trades_count()
                            with active_trades_lock:
                                active_list = [f"{s} ({ACTIVE_TRADES[s].get('side','LONG')})" for s in ACTIVE_TRADES]
                            reply_user(tok, user_chat_id, (
                                f"📊 <b>1-MIN EMA SCALPER STATUS:</b>\n\n"
                                f"• <b>Auto-Trading:</b> {'🟢 ACTIVE (LIVE)' if AUTO_TRADING_ENABLED else '🛑 PAUSED'}\n"
                                f"• <b>Strategy:</b> 9/20 EMA with Confirmed Target Exits\n"
                                f"• <b>Today's Trades:</b> {daily_count}\n"
                                f"• <b>Active Positions:</b> {', '.join(active_list) if active_list else 'None'}"
                            ))
                        elif cmd in ['/manual', 'manual']:
                            with active_trades_lock:
                                for s in ACTIVE_TRADES:
                                    ACTIVE_TRADES[s]['manual_override'] = True
                            save_active_trades()
                            reply_user(tok, user_chat_id, (
                                "👤 <b>MANUAL MODE ACTIVATED!</b>\n\n"
                                "• System trailing and stoploss are <b>PAUSED</b>.\n"
                                "• Your SL and TP set directly on CoinDCX will execute as per your wish."
                            ))
                        elif cmd in ['/today', '/daily', '/report', 'today', 'daily', 'report', '/history']:
                            today_str = get_ist_now().strftime("%d-%m-%Y")
                            with trade_history_lock:
                                all_e = load_all_trade_events()
                            day_e = [e for e in all_e if e.get('date') == today_str]
                            closed_e = [e for e in day_e if e.get('type') in ['CLOSED', 'CLOSED_MANUALLY']]
                            total_pnl = sum(c.get('details', {}).get('realized_pnl_pct', 0) for c in closed_e)
                            reply_user(tok, user_chat_id, (
                                f"📅 <b>TODAY'S SCALPING SUMMARY ({today_str}):</b>\n\n"
                                f"• Total Closed Scalps: <b>{len(closed_e)}</b>\n"
                                f"• Realized ROE PNL: <b>{total_pnl:+.1f}% ROE</b>\n"
                                f"• Open Positions: <b>{len(ACTIVE_TRADES)}</b>\n\n"
                                f"<i>View live charts & dashboard at /today</i>"
                            ))
                        elif cmd in ['/tpsl', 'tpsl', '/synctpsl', 'synctpsl']:
                            reply_user(tok, user_chat_id, "🔄 <i>Syncing Native CoinDCX TP/SL for all active positions...</i>")
                            threading.Thread(target=sync_all_open_positions_tpsl, daemon=True).start()
                initialized.add(tok)
            except Exception: pass
            time.sleep(1)

# ==============================================================================
# 12. BACKGROUND THREADS & APPLICATION LAUNCHER
# ==============================================================================
def start_background_loop():
    clear_telegram_webhooks()
    recover_live_coindcx_positions()
    threading.Thread(target=sync_all_open_positions_tpsl, daemon=True).start()

    def run_scalp_scan_loop():
        time.sleep(5)
        while True:
            try:
                if scan_lock.acquire(blocking=False):
                    try: run_scan()
                    finally: scan_lock.release()
            except Exception as e:
                print(f"Scalp scan exception: {e}")
            time.sleep(10)

    def run_keep_alive_loop():
        time.sleep(15)
        url = "https://crypto-scanner-ok3t.onrender.com/"
        while True:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'KeepAlive/1.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=8) as r: pass
            except Exception: pass
            time.sleep(120)

    def tpsl_sync_worker():
        time.sleep(30)
        while True:
            try:
                sync_all_open_positions_tpsl()
            except Exception: pass
            time.sleep(45)

    threading.Thread(target=run_scalp_scan_loop, daemon=True).start()
    threading.Thread(target=monitor_active_positions, daemon=True).start()
    threading.Thread(target=run_keep_alive_loop, daemon=True).start()
    threading.Thread(target=tpsl_sync_worker, daemon=True).start()
    threading.Thread(target=run_telegram_command_listener, daemon=True).start()

    send_telegram_message(
        "⚡ <b>1-MINUTE 9 & 20 EMA SCALPING BOT DEPLOYED!</b>\n\n"
        "• <b>Strategy:</b> 9-20 EMA Crossover + 50 EMA Macro Baseline\n"
        "• <b>Entry:</b> High-probability setups only (Confirmed trend)\n"
        "• <b>Exit System:</b> Trades ride directly to Target (+1.0%) or SL\n"
        "• <b>Fix:</b> Removed 9 EMA panic trailing exits\n"
        "• <b>Native TP/SL:</b> Bracket orders on CoinDCX\n"
        "• <b>Margin:</b> ₹1,000 INR (7x Isolated Leverage)\n"
        "• <b>Controls:</b> Web 1-Click Dashboard + Telegram /start & /stop"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting 1-Minute EMA Scalping server on port {port}...")
    app.run(host="0.0.0.0", port=port)
