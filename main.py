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
# 2. WATCHLIST & CRYPTO PAIR ALIASES
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

SYMBOL_COOLDOWN_SECONDS = 3600  # 1 Hour cooldown per symbol after successful trade exit

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
# 4. TELEGRAM ENGINE (BULLETPROOF ALERT SYSTEM)
# ==============================================================================
def send_telegram_message(text):
    if not TOKEN:
        print("Telegram Token missing. Alert skipped.")
        return False
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
    ]))
    candidate_tokens = [t for t in candidate_tokens if t]

    for tok in candidate_tokens:
        try:
            url = f"https://api.telegram.org/bot{tok}/sendMessage"
            payload = {'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                if response.status == 200:
                    return True
        except Exception as e:
            print(f"Telegram error on token {tok[:10]}...: {e}")
    return False

def clear_telegram_webhooks():
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
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
# 5. CANDLESTICK FETCHING & EMA INDICATOR CALCULATIONS
# ==============================================================================
def fetch_klines(symbol, interval='1m', limit=35):
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
                    if len(candles) >= 15:
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
                        if len(candles) >= 15:
                            return candles[-limit:]

                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    sorted_data = sorted(data, key=lambda x: x.get('time', 0))
                    candles = []
                    for k in sorted_data:
                        candles.append([
                            float(k.get('time', 0)), float(k.get('open', 0)), float(k.get('high', 0)),
                            float(k.get('low', 0)), float(k.get('close', 0)), float(k.get('volume', 0))
                        ])
                    if len(candles) >= 15:
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

def calculate_volume_spike(klines, period=20):
    if len(klines) < period + 1:
        return 1.0
    recent_vol = klines[-1][5]
    prev_vols = [k[5] for k in klines[-(period + 1):-1]]
    avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 1.0
    if avg_vol <= 0: return 1.0
    return round(recent_vol / avg_vol, 2)

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
                    tp_val = round(entry_p - tp_dist if side == "SHORT" else entry_p + tp_dist, 4)
                    sl_val = round(entry_p + entry_p * 0.006 if side == "SHORT" else entry_p - entry_p * 0.006, 4)

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

    # PRUNE STALE POSITIONS: Remove any trades from ACTIVE_TRADES that are no longer open on CoinDCX
    with active_trades_lock:
        stale_syms = [s for s in list(ACTIVE_TRADES.keys()) if s not in live_open_symbols]
        for s in stale_syms:
            ACTIVE_TRADES.pop(s, None)

    save_active_trades()
    if recovered_count > 0:
        print(f"✅ Successfully recovered {recovered_count} active position(s) from CoinDCX!")

# ==============================================================================
# 7. ORDER EXECUTION & NATIVE BRACKET TP/SL ENGINE
# ==============================================================================
def execute_coindcx_futures_trade(symbol, side="buy", cmp=0.0, margin_inr=1000.0, leverage=7, custom_quantity=None, is_close=False):
    """
    Executes Market Orders directly on CoinDCX Futures.
    Never blocks the scanner; captures exact exchange notices.
    """
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

            # Precision normalization
            if raw_coin == 'BTC': quantity = round(max(0.001, raw_qty), 3)
            elif raw_coin in ['ETH', 'SOL']: quantity = round(max(0.1, raw_qty), 1)
            elif raw_coin in ['PENDLE', 'AVAX']: quantity = float(max(1, int(round(raw_qty))))
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
                    f"• <b>Target (TP):</b> <code>${tp_price}</code>\n"
                    f"• <b>Stop Loss (SL):</b> <code>${sl_price}</code>\n"
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
                tp_val = round(entry_p - tp_dist if side == "SHORT" else entry_p + tp_dist, 4)
                sl_val = round(entry_p + entry_p * 0.006 if side == "SHORT" else entry_p - entry_p * 0.006, 4)

        pos_id = p.get('id') or p.get('position_id') or p.get('positionId')
        if pos_id:
            success = apply_coindcx_native_tpsl(p_pair, pos_id, tp_val, sl_val)
            synced_results.append({'pair': p_pair, 'symbol': sym, 'tp': tp_val, 'sl': sl_val, 'success': success})
        time.sleep(0.5)
    return synced_results

# ==============================================================================
# 8. 9 EMA & 20 EMA 1-MINUTE SCALPING ENGINE (LONG & SHORT)
# ==============================================================================
def run_scan():
    """
    1-Minute Scalping Engine based on Trader Pankaj Gupta's 9 EMA & 20 EMA Blueprint.
    Executes both LONG and SHORT trades with immediate non-blocking execution.
    """
    today_str = get_ist_now().strftime("%d-%m-%Y")
    curr_state = load_state()

    # Rule: Max 2 Concurrent Active Positions (Maintains sufficient wallet margin buffer)
    with active_trades_lock:
        if len(ACTIVE_TRADES) >= 2:
            return

    candidates = []

    for symbol in WATCHLIST:
        try:
            time.sleep(0.01)

            # Check Stop Loss Day Ban
            if curr_state.get(f"sl_banned_{symbol}") == today_str:
                continue

            # Check Symbol Cooldown
            last_traded = curr_state.get(f"last_traded_{symbol}", 0)
            if time.time() - last_traded < SYMBOL_COOLDOWN_SECONDS:
                continue

            with active_trades_lock:
                if symbol in ACTIVE_TRADES: continue

            # Fetch 1-Minute Candlesticks (using multi-source non-blocking engine)
            m1_klines = fetch_klines(symbol, '1m', 35)
            if not m1_klines or len(m1_klines) < 25:
                continue

            closes = [k[4] for k in m1_klines]
            opens = [k[1] for k in m1_klines]
            highs = [k[2] for k in m1_klines]
            lows = [k[3] for k in m1_klines]

            cmp = closes[-1]
            curr_open = opens[-1]
            curr_high = highs[-1]
            curr_low = lows[-1]

            # Calculate 9 EMA and 20 EMA series
            ema9_series = calculate_ema_series(closes, 9)
            ema20_series = calculate_ema_series(closes, 20)

            curr_ema9 = ema9_series[-1]
            curr_ema20 = ema20_series[-1]
            prev_ema9 = ema9_series[-2]
            prev_ema20 = ema20_series[-2]
            prev2_ema9 = ema9_series[-3] if len(ema9_series) >= 3 else prev_ema9
            prev2_ema20 = ema20_series[-3] if len(ema20_series) >= 3 else prev_ema20

            # ------------------------------------------------------------------
            # CHOP FILTER: Skip if EMAs are flat or crisscrossing (Sideways Zone)
            # ------------------------------------------------------------------
            ema_spread_pct = abs(curr_ema9 - curr_ema20) / curr_ema20
            if ema_spread_pct < 0.0003:
                continue

            # Volume Confirmation Spike (>= 1.05x 20-period average volume)
            vol_spike = calculate_volume_spike(m1_klines, 20)
            if vol_spike < 1.05:
                continue

            # ------------------------------------------------------------------
            # 🟢 LONG SETUP EVALUATION
            # ------------------------------------------------------------------
            is_long_crossover = (prev_ema9 <= prev_ema20 or prev2_ema9 <= prev2_ema20) and (curr_ema9 > curr_ema20)
            is_long_pullback = (curr_ema9 > curr_ema20) and (min(lows[-2:]) <= curr_ema9 * 1.001) and (cmp > curr_ema9)
            is_long_breakout = (curr_ema9 > curr_ema20) and (cmp > closes[-2]) and (cmp > curr_ema9) and (vol_spike >= 1.05)
            is_long_confirmed = (cmp > curr_open or cmp > closes[-2]) and (cmp > curr_ema9) and (cmp > curr_ema20)

            if (is_long_crossover or is_long_pullback or is_long_breakout) and is_long_confirmed:
                swing_low = min(lows[-6:])
                raw_sl = min(swing_low * 0.9995, curr_ema20 * 0.9990)
                sl_dist = cmp - raw_sl
                if sl_dist > cmp * 0.008: raw_sl = round(cmp * 0.992, 4)
                elif sl_dist < cmp * 0.004: raw_sl = round(cmp * 0.996, 4)
                else: raw_sl = round(raw_sl, 4)

                tp1 = round(max(cmp + (cmp - raw_sl) * 1.5, cmp * 1.0090), 4)
                if is_long_crossover:
                    setup_title = "9-20 EMA LONG CROSSOVER 🚀"
                    score = 100
                elif is_long_pullback:
                    setup_title = "9 EMA PULLBACK & BOUNCE 🟢"
                    score = 90
                else:
                    setup_title = "1M MOMENTUM BREAKOUT 💥"
                    score = 85

                candidates.append({
                    'symbol': symbol,
                    'side': 'LONG',
                    'setup_name': setup_title,
                    'cmp': cmp,
                    'sl': raw_sl,
                    'tp1': tp1,
                    'vol_spike': vol_spike,
                    'ema9': curr_ema9,
                    'ema20': curr_ema20,
                    'score': score
                })
                continue

            # ------------------------------------------------------------------
            # 🔴 SHORT SETUP EVALUATION
            # ------------------------------------------------------------------
            is_short_crossover = (prev_ema9 >= prev_ema20 or prev2_ema9 >= prev2_ema20) and (curr_ema9 < curr_ema20)
            is_short_pullback = (curr_ema9 < curr_ema20) and (max(highs[-2:]) >= curr_ema9 * 0.999) and (cmp < curr_ema9)
            is_short_breakdown = (curr_ema9 < curr_ema20) and (cmp < closes[-2]) and (cmp < curr_ema9) and (vol_spike >= 1.05)
            is_short_confirmed = (cmp < curr_open or cmp < closes[-2]) and (cmp < curr_ema9) and (cmp < curr_ema20)

            if (is_short_crossover or is_short_pullback or is_short_breakdown) and is_short_confirmed:
                swing_high = max(highs[-6:])
                raw_sl = max(swing_high * 1.0005, curr_ema20 * 1.0010)
                sl_dist = raw_sl - cmp
                if sl_dist > cmp * 0.008: raw_sl = round(cmp * 1.008, 4)
                elif sl_dist < cmp * 0.004: raw_sl = round(cmp * 1.004, 4)
                else: raw_sl = round(raw_sl, 4)

                tp1 = round(min(cmp - (raw_sl - cmp) * 1.5, cmp * 0.9910), 4)
                if is_short_crossover:
                    setup_title = "9-20 EMA SHORT CROSSOVER 📉"
                    score = 100
                elif is_short_pullback:
                    setup_title = "9 EMA PULLBACK & REJECT 🔴"
                    score = 90
                else:
                    setup_title = "1M MOMENTUM BREAKDOWN 💥"
                    score = 85

                candidates.append({
                    'symbol': symbol,
                    'side': 'SHORT',
                    'setup_name': setup_title,
                    'cmp': cmp,
                    'sl': raw_sl,
                    'tp1': tp1,
                    'vol_spike': vol_spike,
                    'ema9': curr_ema9,
                    'ema20': curr_ema20,
                    'score': score
                })
        except Exception: pass

    candidates.sort(key=lambda x: (x['score'], x['vol_spike']), reverse=True)
    coin_margin = 1000.0
    lev_num = 7

    for cand in candidates:
        with active_trades_lock:
            if len(ACTIVE_TRADES) >= 2: break

        symbol = cand['symbol']
        side = cand['side']
        cmp = cand['cmp']
        sl = cand['sl']
        tp1 = cand['tp1']
        vol_spike = cand['vol_spike']
        score = cand['score']
        setup_name = cand['setup_name']

        coindcx_side = "buy" if side == "LONG" else "sell"

        # FIRE ORDER IMMEDIATELY (NON-BLOCKING)
        if AUTO_TRADING_ENABLED:
            trade_res = execute_coindcx_futures_trade(symbol=symbol, side=coindcx_side, cmp=cmp, margin_inr=coin_margin, leverage=lev_num, is_close=False)
        else:
            trade_res = {'success': False, 'error': 'Auto-trading PAUSED via Mobile Telegram / Web button.'}

        if trade_res.get('success'):
            order_id = trade_res.get('order_id')
            qty = trade_res.get('quantity')
            log_trade_event(symbol, "EXECUTED", {"cmp": cmp, "quantity": qty, "order_id": order_id, "margin": coin_margin, "side": side})

            with active_trades_lock:
                ACTIVE_TRADES[symbol] = {
                    'entry_price': cmp,
                    'side': side,
                    'total_qty': qty,
                    'remaining_qty': qty,
                    'tp1': tp1,
                    'sl': sl,
                    'initial_tp': tp1,
                    'initial_sl': sl,
                    'manual_override': False,
                    'highest_price': cmp,
                    'lowest_price': cmp,
                    'leverage': lev_num,
                    'entry_time': time.time()
                }
            save_active_trades()

            curr_state[f"last_traded_{symbol}"] = time.time()
            save_state(curr_state)

            # Auto-place Native CoinDCX Bracket TP/SL asynchronously in background thread
            threading.Thread(target=auto_place_coindcx_native_tpsl, args=(symbol, tp1, sl, side), daemon=True).start()

            sl_dist_pct = abs(cmp - sl) / cmp * 100.0
            tp_dist_pct = abs(tp1 - cmp) / cmp * 100.0
            icon = "🟢" if side == "LONG" else "🔴"

            # FULL TRANSPARENCY TELEGRAM ALERT
            msg = (
                f"{icon} <b>1-MIN EMA SCALP SIGNAL! ({side})</b>\n\n"
                f"<b>Pair:</b> <code>{symbol}</code> (Futures)\n"
                f"<b>Setup:</b> <b>{setup_name}</b>\n"
                f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                f"📊 <b>1M Volume Surge:</b> <code>{vol_spike:.2f}x Average</code>\n\n"
                f"⚙️ <b>Trade Parameters:</b>\n"
                f"• <b>Direction:</b> <code>{side}</code> (7x Isolated)\n"
                f"• <b>Entry CMP:</b> <code>${cmp}</code>\n"
                f"🛑 <b>Stop Loss (SL):</b> <code>${sl}</code> (-{sl_dist_pct:.2f}% move / -{sl_dist_pct * lev_num:.1f}% ROE)\n"
                f"🎯 <b>Target (TP1):</b> <code>${tp1}</code> (+{tp_dist_pct:.2f}% move / +{tp_dist_pct * lev_num:.1f}% ROE)\n"
                f"⚡ <b>Trailing Guide:</b> Exit immediately on 1M close beyond 9 EMA!\n\n"
                f"⚡ <b>AUTO-TRADE EXECUTED ON COINDCX!</b>\n"
                f"• Order ID: <code>{order_id}</code>\n"
                f"• Quantity: <code>{qty}</code> | Margin: ₹{coin_margin:.0f}\n"
                f"🔄 <i>Native CoinDCX TP/SL auto-fitting active...</i>"
            )
            send_telegram_message(msg)
            break
        else:
            # 100% TRANSPARENCY ON COINDCX NOTICES & REJECTIONS
            err_reason = trade_res.get('error', 'Unknown Error')
            log_trade_event(symbol, "CANCELLED", {"cmp": cmp, "error": err_reason, "side": side})
            # Lock for only 2 minutes on failed order attempt instead of 1 hour
            curr_state[f"last_traded_{symbol}"] = time.time() - (SYMBOL_COOLDOWN_SECONDS - 120)
            save_state(curr_state)

            notice_msg = (
                f"⚡ <b>SCALP SIGNAL DETECTED: {symbol} ({side})</b>\n\n"
                f"<b>Setup:</b> {setup_name}\n"
                f"<b>CMP:</b> ${cmp} | <b>Target:</b> ${tp1} | <b>SL:</b> ${sl}\n\n"
                f"⚠️ <b>COINDCX EXECUTION NOTICE:</b>\n"
                f"<code>{err_reason}</code>\n\n"
                f"<i>Cooldown locked for 2 minutes before retry.</i>"
            )
            send_telegram_message(notice_msg)

# ==============================================================================
# 9. REAL-TIME POSITION MONITORING & 9 EMA TRAILING EXITS
# ==============================================================================
def monitor_active_positions():
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

                    # 1. Manual Close Detection on CoinDCX
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
                            f"• Tracking removed cleanly."
                        )
                        continue

                    # 2. Detect Manual SL / TP Updates on CoinDCX (Direct Manual Control)
                    if not trade.get('manual_override', False):
                        pos_info = fetch_coindcx_position_details(symbol)
                        if pos_info and isinstance(pos_info.get('raw'), dict):
                            exch_tp, exch_sl = extract_exchange_tpsl(pos_info['raw'])
                            init_tp = trade.get('initial_tp', trade.get('tp1', 0))
                            init_sl = trade.get('initial_sl', trade.get('sl', 0))

                            tp_changed = exch_tp and abs(exch_tp - init_tp) > 0.0001
                            sl_changed = exch_sl and abs(exch_sl - init_sl) > 0.0001

                            if tp_changed or sl_changed:
                                with active_trades_lock:
                                    trade['manual_override'] = True
                                    if exch_tp: trade['tp1'] = exch_tp
                                    if exch_sl: trade['sl'] = exch_sl
                                save_active_trades()
                                send_telegram_message(
                                    f"👤 <b>MANUAL COINDCX SL/TP DETECTED!</b>\n\n"
                                    f"<b>Pair:</b> <code>{symbol}</code>\n"
                                    f"• Your Manual TP: <code>${trade['tp1']}</code>\n"
                                    f"• Your Manual SL: <code>${trade['sl']}</code>\n"
                                    f"⏸️ <b>System stoploss is now PAUSED.</b> CoinDCX will execute directly!"
                                )

                    if trade.get('manual_override', False):
                        continue

                    # Fetch live 1-Minute candles for trailing exit check
                    m1_klines = fetch_klines(symbol, '1m', 15)
                    if not m1_klines: continue

                    cmp = m1_klines[-1][4]
                    curr_close = m1_klines[-1][4]
                    ema9_series = calculate_ema_series([k[4] for k in m1_klines], 9)
                    curr_ema9 = ema9_series[-1]

                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    sell_qty = min(live_qty, trade.get('remaining_qty', live_qty))

                    # Calculate ROE %
                    if side == "LONG":
                        raw_roe_pct = ((cmp - entry_p) / entry_p) * trade.get('leverage', 7) * 100.0
                    else:
                        raw_roe_pct = ((entry_p - cmp) / entry_p) * trade.get('leverage', 7) * 100.0

                    # ----------------------------------------------------------
                    # A. 9 EMA TRAILING VIOLATION EXIT
                    # ----------------------------------------------------------
                    is_long_ema9_exit = (side == "LONG" and curr_close < curr_ema9 * 0.9995)
                    is_short_ema9_exit = (side == "SHORT" and curr_close > curr_ema9 * 1.0005)

                    if is_long_ema9_exit or is_short_ema9_exit:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        exit_title = "9 EMA MOMENTUM EXIT (LONG) 🎯" if side == "LONG" else "9 EMA MOMENTUM EXIT (SHORT) 🎯"
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_roe_pct, 1), "sl_type": exit_title, "side": side})
                        send_telegram_message(
                            f"🏁 <b>SCALP CLOSED: {exit_title}</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> ({side})\n"
                            f"• <b>Reason:</b> 1M candle closed beyond 9 EMA (${curr_ema9:.4f})\n"
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                            f"• <b>Realized Gain:</b> <code>{raw_roe_pct:+.1f}% ROE</code> 💰"
                        )
                        continue

                    # ----------------------------------------------------------
                    # B. TARGET (TP1) HIT
                    # ----------------------------------------------------------
                    is_tp_hit = (side == "LONG" and cmp >= trade['tp1']) or (side == "SHORT" and cmp <= trade['tp1'])
                    if is_tp_hit:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_roe_pct, 1), "sl_type": "PROFIT TARGET (TP1) 🚀", "side": side})
                        send_telegram_message(
                            f"🎯 <b>SCALP TARGET HIT (TP1)! 🚀</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> ({side})\n"
                            f"• <b>Entry:</b> <code>${entry_p}</code> | <b>Exit:</b> <code>${cmp}</code>\n"
                            f"• <b>Realized Gain:</b> <code>+{raw_roe_pct:.1f}% ROE</code> 💰"
                        )
                        continue

                    # ----------------------------------------------------------
                    # C. STOP LOSS HIT
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
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                            f"• <b>Realized Loss:</b> <code>{raw_roe_pct:+.1f}% ROE</code>\n"
                            f"🛡️ <i>Loss contained cleanly under 1M risk rule. Capital protected.</i>"
                        )
                        continue

                    # ----------------------------------------------------------
                    # D. 10-MINUTE SCALP STAGNATION GUARD
                    # ----------------------------------------------------------
                    if time.time() - entry_time >= 600:
                        if sell_qty > 0:
                            execute_coindcx_futures_trade(symbol=symbol, side=close_side, cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty, is_close=True)
                        with active_trades_lock: ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()

                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_roe_pct, 1), "sl_type": "10-MIN STAGNATION TIME-STOP ⏱️", "side": side})
                        send_telegram_message(
                            f"⏱️ <b>10-MINUTE SCALP TIME-STOP EXECUTED!</b>\n\n"
                            f"<b>Pair:</b> <code>{symbol}</code> ({side})\n"
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
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
            f"Engine Status: {status_txt} | Active Slots: {slot_txt}",
            f"{'='*95}",
            f"{'SYMBOL':11s} | {'CMP':<9s} | {'9 EMA':<9s} | {'20 EMA':<9s} | {'TREND':<10s} | {'VOL':<6s} | {'SETUP'}",
            f"{'-'*95}"
        ]

        # Scan top 20 liquid pairs for fast <2s page response, or all if requested
        scan_symbols = WATCHLIST[:45] if request.args.get('all') == 'true' else WATCHLIST[:20]

        for symbol in scan_symbols:
            try:
                time.sleep(0.01)
                m1 = fetch_klines(symbol, '1m', 25)
                if not m1 or len(m1) < 20:
                    report_lines.append(f"{symbol:11s} | {'SYNCING':<9s} | {'--':<9s} | {'--':<9s} | {'CONNECTING':<10s} | {'--':<6s} | 🔄 BUFFERING")
                    continue
                closes = [k[4] for k in m1]
                cmp = closes[-1]
                ema9 = calculate_ema_series(closes, 9)[-1]
                ema20 = calculate_ema_series(closes, 20)[-1]
                vol_spike = calculate_volume_spike(m1, 20)

                if ema9 > ema20 * 1.0003:
                    trend_txt = "🟢 BULLISH"
                elif ema9 < ema20 * 0.9997:
                    trend_txt = "🔴 BEARISH"
                else:
                    trend_txt = "⚪ CHOP"

                setup_txt = "⚪ WAITING"
                if trend_txt == "🟢 BULLISH" and closes[-1] > closes[-2] and closes[-1] > ema9 and vol_spike >= 1.05:
                    setup_txt = "🔥 BUY READY"
                elif trend_txt == "🔴 BEARISH" and closes[-1] < closes[-2] and closes[-1] < ema9 and vol_spike >= 1.05:
                    setup_txt = "🔥 SHORT READY"

                report_lines.append(f"{symbol:11s} | {cmp:<9.4f} | {ema9:<9.4f} | {ema20:<9.4f} | {trend_txt:<10s} | {vol_spike:.2f}x | {setup_txt}")
            except Exception as e:
                report_lines.append(f"{symbol:11s} | {'ERROR':<9s} | {'--':<9s} | {'--':<9s} | {'ERROR':<10s} | {'--':<6s} | ⚠️ {str(e)[:15]}")

        nav_bar = f"<p><b>Status:</b> {status_txt} | <b>Active:</b> {slot_txt}</p><p><a href='/today'>⬅️ Back to Dashboard</a> | <a href='/scan-now'>🔄 Refresh Top 20</a> | <a href='/scan-now?all=true'>🌐 Scan All 45</a></p>"
        return f"<h2>⚡ 1-Minute 9-20 EMA Scalper Diagnostics</h2>{nav_bar}<pre>" + "\n".join(report_lines) + "</pre>", 200
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

        exec_rows = "".join([f"<tr><td>{e.get('timestamp','').split()[-2]} {e.get('timestamp','').split()[-1]}</td><td><b>{e.get('symbol')}</b> ({e.get('details',{}).get('side','LONG')})</td><td>${e.get('details',{}).get('cmp')}</td><td>{e.get('details',{}).get('quantity')}</td><td><code>{str(e.get('details',{}).get('order_id'))[:8]}</code></td><td>₹1,000</td></tr>" for e in executed]) if executed else "<tr><td colspan='6' style='text-align:center;'>No trades executed today yet</td></tr>"
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
                <p><b>Date:</b> {target_date} | <b>Strategy:</b> 9-20 EMA Crossover & Trailing Momentum (Long + Short)</p>

                <!-- 1-Click Mobile Control Panel -->
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
        'strategy': '9-20 EMA 1-Minute Scalper (Long + Short)',
        'trades_executed_today': daily_count,
        'active_positions': active_list
    }, 200

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
        "• Both LONG and SHORT setups will execute automatically.\n"
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
    return today_report_endpoint()

# ==============================================================================
# 11. TELEGRAM COMMAND LISTENER (DIRECT /start & /stop CONTROLLER)
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    clear_telegram_webhooks()
    
    candidate_tokens = list(dict.fromkeys([
        TOKEN,
        "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
    ]))
    candidate_tokens = [t for t in candidate_tokens if t]
    token_offsets = {t: 0 for t in candidate_tokens}
    boot_time = time.time()
    initialized = set()

    def reply_user(tok, chat_id, text_reply):
        try:
            url = f"https://api.telegram.org/bot{tok}/sendMessage"
            payload = {'chat_id': chat_id, 'text': text_reply, 'parse_mode': 'HTML'}
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, context=ctx, timeout=5) as r: pass
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
                                "• High-conviction 9 & 20 EMA Long and Short setups will fire automatically.\n"
                                "• Send <code>/stop</code> anytime to pause."
                            ))
                        elif cmd in ['/status', 'status']:
                            daily_count = get_today_executed_trades_count()
                            with active_trades_lock:
                                active_list = [f"{s} ({ACTIVE_TRADES[s].get('side','LONG')})" for s in ACTIVE_TRADES]
                            reply_user(tok, user_chat_id, (
                                f"📊 <b>1-MIN EMA SCALPER STATUS:</b>\n\n"
                                f"• <b>Auto-Trading:</b> {'🟢 ACTIVE (LIVE)' if AUTO_TRADING_ENABLED else '🛑 PAUSED'}\n"
                                f"• <b>Strategy:</b> 9 & 20 EMA 1-Minute Scalper (Long + Short)\n"
                                f"• <b>Today's Trades:</b> {daily_count}\n"
                                f"• <b>Active Positions:</b> {', '.join(active_list) if active_list else 'None'}\n"
                                f"• <b>Risk per Trade:</b> Strict -0.6% SL & 9 EMA Trailing"
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
            time.sleep(15)

    def run_keep_alive_loop():
        time.sleep(15)
        url = "https://crypto-scanner-ok3t.onrender.com/"
        while True:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'KeepAlive/1.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=8) as r: pass
            except Exception: pass
            time.sleep(180)

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
        "• <b>Strategy:</b> 9-20 EMA Crossover & Pullback Momentum\n"
        "• <b>Timeframe:</b> 1-Minute (Ultra-fast execution)\n"
        "• <b>Modes:</b> Both 🟢 LONG and 🔴 SHORT trades active\n"
        "• <b>Risk Control:</b> Strict ~0.6% SL & 9 EMA Trailing Exits\n"
        "• <b>Native TP/SL:</b> Auto-fitting bracket orders on CoinDCX\n"
        "• <b>Manual Control:</b> Edit SL/TP on CoinDCX -> System Stoploss stops!\n"
        "• <b>Margin:</b> ₹1,000 INR (7x Isolated Leverage)\n"
        "• <b>Controls:</b> Web 1-Click Dashboard + Telegram /start & /stop"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting 1-Minute EMA Scalping server on port {port}...")
    app.run(host="0.0.0.0", port=port)
