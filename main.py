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

    # 🟢 BULLISH CROSSOVER CHECK (Price > 50 EMA)
    if curr_ema9 > curr_ema20 and is_curr_green and curr_close > curr_ema50:
        if prev1_ema9 <= prev1_ema20:
            return 'LONG', 0
        elif prev2_ema9 <= prev2_ema20:
            return 'LONG', 1
        elif prev3_ema9 <= prev3_ema20 and (klines[-2][4] > klines[-2][1]):
            return 'LONG', 2

    # 🔴 BEARISH CROSSOVER CHECK (Price < 50 EMA)
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

            # Precision normalization for all pairs
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
                            f"⚡ <b>Hold Rule:</b> Ride until Target TP1 or Reverse EMA Cross (No time limit)!\n\n"
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
                            f"⚡ <b>Hold Rule:</b> Ride until Target TP1 or Reverse EMA Cross (No time limit)!\n\n"
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
# 9. TRUE REVERSE CROSSOVER & TARGET/STOP-LOSS EXIT ENGINE (NO TIME LIMIT)
# ==============================================================================
def monitor_active_positions():
    """
    Rides the trend without any time limit!
    Holds position as long as:
    - LONG: Blue (9 EMA) stays >= Red (20 EMA)
    - SHORT: Blue (9 EMA) stays <= Red (20 EMA)
    Exits ONLY when:
    1. TARGET HIT (TP1): Solid profit locked in (+6% to +10%+ ROE)
    2. STOP LOSS HIT (SL): Exchange protects capital cleanly
    3. TRUE REVERSE CROSS: Blue crosses Red line in reverse direction on closed candle
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
                    # A. HARD STOP LOSS HIT (Exchange Protection)
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
                            f"• <b>Exit Price:</b> <code>
