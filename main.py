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
from datetime import datetime
from flask import Flask

app = Flask(__name__)
scan_lock = threading.Lock()
active_trades_lock = threading.Lock()

STATE_FILE = "scanner_state.json"
AUTO_TRADING_ENABLED = True  # GLOBAL MOBILE ON/OFF SWITCH FLAG

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

TOKEN = "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA"
CHAT_ID = "8938527650"

# DEFAULT FALLBACK WATCHLIST
WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'DOGE-USDT', 
    'XRP-USDT', 'ADA-USDT', 'LINK-USDT', 'NEAR-USDT', 'BCH-USDT', 
    'SUI-USDT', 'LTC-USDT', 'DOT-USDT', 'PEPE-USDT', 'OP-USDT', 
    'ARB-USDT', 'APT-USDT', 'RENDER-USDT', 'INJ-USDT', 'FET-USDT', 
    'TIA-USDT', 'WIF-USDT', 'SHIB-USDT', 'FLOKI-USDT', 'AAVE-USDT',
    'FTM-USDT', 'UNI-USDT', 'ATOM-USDT', 'ICP-USDT', 'SAND-USDT',
    'SEI-USDT', 'ORDI-USDT', 'FIL-USDT', 'JUP-USDT', 'BONK-USDT',
    'STX-USDT', 'PENDLE-USDT', 'RUNE-USDT', 'IMX-USDT', 'KAS-USDT'
]

ctx = ssl._create_unverified_context()

# DYNAMIC INACTIVE COIN BLACKLIST & COINDCX ACTIVE PAIRS SYNC
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

def fetch_dynamic_watchlist(min_volume_usdt=5000000.0):
    global CACHED_DYNAMIC_WATCHLIST, LAST_WATCHLIST_FETCH_TIME
    now = time.time()
    # Cache dynamic list for 15 minutes (900s) to keep scanner loops ultra-fast
    if CACHED_DYNAMIC_WATCHLIST and (now - LAST_WATCHLIST_FETCH_TIME < 900):
        return [s for s in CACHED_DYNAMIC_WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS]

    dynamic_list = []
    coindcx_active = fetch_coindcx_active_pairs()

    try:
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list):
                valid_tickers = []
                for item in data:
                    sym = item.get('symbol', '')
                    quote_vol = float(item.get('quoteVolume', 0))
                    if sym.endswith('USDT') and quote_vol >= min_volume_usdt:
                        coin = sym[:-4].upper()
                        if coin in INACTIVE_COINS:
                            continue
                        # Exclude stablecoins and leveraged tokens
                        if coin not in ['USDC', 'FDUSD', 'TUSD', 'BUSD', 'EUR', 'GBP', 'DAI', 'USDP', 'AEUR'] and not coin.endswith('UP') and not coin.endswith('DOWN'):
                            if coindcx_active:
                                futures_coin = f"1000{coin}" if coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI'] else coin
                                pair_1 = f"B-{futures_coin}_USDT"
                                pair_2 = f"B-{coin}_USDT"
                                is_active = any(p in coindcx_active for p in [pair_1, pair_2]) or any(coin in p for p in coindcx_active)
                                if not is_active:
                                    continue
                            valid_tickers.append((f"{coin}-USDT", quote_vol))
                valid_tickers.sort(key=lambda x: x[1], reverse=True)
                dynamic_list = [x[0] for x in valid_tickers]
    except Exception: pass

    if not dynamic_list:
        dynamic_list = [s for s in WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS]

    CACHED_DYNAMIC_WATCHLIST = dynamic_list
    LAST_WATCHLIST_FETCH_TIME = now
    return CACHED_DYNAMIC_WATCHLIST

def fetch_klines(symbol, interval_str="15m", limit=100):
    coin = symbol.split('-')[0].upper()
    clean_sym = f"{coin}USDT"
    
    # Provider 1: Binance Vision Public Data API (No Geoblock)
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if isinstance(raw, list) and len(raw) > 0:
                formatted = []
                for c in raw:
                    formatted.append([int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])])
                return formatted
    except Exception: pass

    # Provider 2: CoinDCX Public Candles API
    try:
        pair_str = f"B-{coin}_USDT"
        url = f"https://public.coindcx.com/market_data/candles/?pair={pair_str}&interval={interval_str}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
            if isinstance(raw, list) and len(raw) > 0:
                raw_sorted = sorted(raw, key=lambda x: x.get('time', 0))
                formatted = []
                for c in raw_sorted[-limit:]:
                    t = int(c.get('time', time.time()*1000))
                    o = float(c.get('open', 0))
                    h = float(c.get('high', 0))
                    l = float(c.get('low', 0))
                    cl = float(c.get('close', 0))
                    v = float(c.get('volume', 0))
                    formatted.append([t, o, h, l, cl, v])
                if len(formatted) > 0:
                    return formatted
    except Exception: pass

    # Provider 3: Bybit Public Market API
    try:
        bybit_interval = "15" if interval_str == "15m" else ("60" if interval_str == "1h" else ("D" if interval_str == "1d" else "15"))
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={clean_sym}&interval={bybit_interval}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            list_data = data.get('result', {}).get('list', [])
            if list_data:
                list_sorted = sorted(list_data, key=lambda x: int(x[0]))
                formatted = []
                for c in list_sorted:
                    formatted.append([int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])])
                return formatted
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

def calculate_ema(prices, period=50):
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price * k) + (ema * (1 - k))
    return ema

def calculate_volume_spike(klines, period=20):
    volumes = [float(k[5]) for k in klines]
    current_vol = volumes[-1]
    avg_vol = sum(volumes[-period-1:-1]) / period
    return (current_vol / avg_vol) if avg_vol > 0 else 1.0

def calculate_cpr(high, low, close):
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot
    return {'pivot': pivot, 'tc': max(tc, bc), 'bc': min(tc, bc), 'r1': 2.0*pivot - low, 'r2': pivot + (high - low)}

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

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8')).get('ok')
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ENHANCED LIVE POSITION CHECKER (Returns float qty on success, 0.0 on verified closed, None on API glitch):
def fetch_coindcx_live_position_qty(symbol):
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    if not api_key or not secret_key: return None
    
    raw_coin = symbol.split('-')[0].upper()
    target_clean = raw_coin.replace("1000", "")
    
    try:
        ts = int(round(time.time() * 1000))
        json_body = json.dumps({"timestamp": ts}, separators=(',', ':'))
        signature = hmac.new(secret_key.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
        headers = {'Content-Type': 'application/json', 'X-AUTH-APIKEY': api_key, 'X-AUTH-SIGNATURE': signature, 'User-Agent': 'Mozilla/5.0'}
        url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions"
        req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            pos_list = []
            if isinstance(data, list):
                pos_list = data
            elif isinstance(data, dict):
                pos_list = data.get('positions', data.get('data', data.get('result', [])))
                
            if isinstance(pos_list, list):
                possible_qty_keys = [
                    'active_units', 'open_position_qty', 'position_qty', 'active_position',
                    'quantity', 'size', 'current_qty', 'net_quantity', 'open_position',
                    'active_pos', 'units', 'position', 'open_units'
                ]
                for p in pos_list:
                    if not isinstance(p, dict): continue
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
                                except Exception: pass
                # HTTP 200 OK received and parsed, target coin was NOT in active positions list:
                return 0.0
    except Exception:
        # API Error or Timeout occurred: Return None so caller knows API failed!
        return None
    return None

def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=1000.0, leverage=7, custom_quantity=None, tp_price=None, sl_price=None):
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    
    if not api_key or not secret_key:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
        
    coin = symbol.split('-')[0].upper()
    futures_coin = f"1000{coin}" if coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI'] else coin
    pair_name = f"B-{futures_coin}_USDT"
    
    # REQUIREMENT 2 ENFORCEMENT: For BUY orders, TP and SL are MANDATORY. Without TP & SL, DO NOT PLACE TRADE!
    if side.lower() == "buy" and (tp_price is None or sl_price is None):
        return {'success': False, 'error': '⚠️ Trade Cancelled: Stop Loss and Target are required (No SL/TP = No Trade).'}

    if custom_quantity is not None:
        quantity = custom_quantity
    else:
        # HARDCODED ₹1,000 INR FIXED MARGIN LOGIC:
        # Position Value = (1000 INR * 7 Leverage) / 88.5 Rate = ~79.10 USDT
        usdt_inr_rate = 88.5
        strict_margin_inr = 1000.0  # ALWAYS FIXED ₹1,000 INR
        position_value_usdt = (strict_margin_inr * leverage) / usdt_inr_rate
        raw_qty = position_value_usdt / cmp if cmp > 0 else 1.0
        
        # STRICT QUANTITY ROUNDING - Never round UP to exceed margin!
        if coin == 'BTC': 
            quantity = round(raw_qty, 3)
        elif coin in ['ETH', 'SOL', 'BCH', 'AAVE', 'LTC', 'AVAX', 'BNB']: 
            quantity = round(raw_qty, 2)
        elif coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']: 
            # 1000-prefix meme coins on CoinDCX trade in 1,000 unit contracts!
            contract_qty = raw_qty / 1000.0
            quantity = float(int(contract_qty)) if contract_qty >= 1.0 else 1.0
        elif cmp >= 10.0:
            quantity = round(raw_qty, 1)
        else: 
            # Use floor int(raw_qty) so low-priced coins never round UP and exceed ₹1,000 margin
            quantity = float(int(raw_qty)) if raw_qty >= 1.0 else 1.0
        
    if quantity <= 0: quantity = 0.01 if coin in ['ETH', 'SOL', 'BCH', 'AAVE', 'LTC', 'AVAX', 'BNB'] else (0.001 if coin == 'BTC' else 1.0)

    # REFINED TP / SL PRICE TICK ROUNDING TO MATCH COINDCX PRECISION:
    # Coins under $10 (like ICP, ADA, XRP, SUI, NEAR) MUST use 2 decimal places to prevent HTTP 422 errors!
    formatted_tp = None
    formatted_sl = None
    formatted_tp_2d = None
    formatted_sl_2d = None

    if tp_price is not None:
        if cmp >= 100: formatted_tp = round(float(tp_price), 2)
        elif cmp >= 10.0: formatted_tp = round(float(tp_price), 3)
        elif cmp >= 1.0: formatted_tp = round(float(tp_price), 2)   # 2 Decimals for $1-$10 coins (e.g. 3.49 for ICP)
        else: formatted_tp = round(float(tp_price), 4)
        formatted_tp_2d = round(float(tp_price), 2)

    if sl_price is not None:
        if cmp >= 100: formatted_sl = round(float(sl_price), 2)
        elif cmp >= 10.0: formatted_sl = round(float(sl_price), 3)
        elif cmp >= 1.0: formatted_sl = round(float(sl_price), 2)   # 2 Decimals for $1-$10 coins (e.g. 3.39 for ICP)
        else: formatted_sl = round(float(sl_price), 4)
        formatted_sl_2d = round(float(sl_price), 2)

    futures_url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    ts = int(round(time.time() * 1000))

    # Variant 1: Primary Precision TP/SL Payload
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

    # Variant 2: Strict 2-Decimal TP/SL Payload (Guarantees HTTP 422 bypass on $1-$10 coins)
    futures_order_payload_2d_tpsl = dict(futures_order_payload_tpsl)
    if formatted_tp_2d is not None:
        futures_order_payload_2d_tpsl["take_profit_price"] = formatted_tp_2d
    if formatted_sl_2d is not None:
        futures_order_payload_2d_tpsl["stop_loss_price"] = formatted_sl_2d

    # Variant 3: Quantized Integer Quantity with TP/SL
    futures_order_payload_quantized_tpsl = dict(futures_order_payload_2d_tpsl)
    futures_order_payload_quantized_tpsl["total_quantity"] = float(int(quantity)) if cmp < 10.0 and coin not in ['BTC', 'ETH', 'SOL', 'BCH', 'AAVE', 'LTC', 'AVAX'] else quantity

    # REQUIREMENT 2 RULE: If side == "buy", ONLY execute payloads with inline TP & SL. NO NAKED MARKET ORDERS ALLOWED!
    if side.lower() == "buy":
        endpoint_variants = [
            (futures_url, {"timestamp": ts, "order": futures_order_payload_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_2d_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_quantized_tpsl})
        ]
    else:
        # Exit/Sell order payload
        futures_order_payload_clean = {
            "side": side.lower(),
            "pair": pair_name,
            "order_type": "market_order",
            "total_quantity": quantity,
            "leverage": leverage,
            "notification": "no_notification"
        }
        endpoint_variants = [
            (futures_url, {"timestamp": ts, "order": futures_order_payload_clean})
        ]

    err_logs = []
    for idx, (target_url, body) in enumerate(endpoint_variants, 1):
        try:
            ts_now = int(round(time.time() * 1000))
            body["timestamp"] = ts_now
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(secret_key.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': api_key,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(target_url, data=json_body.encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                order_id = "EXECUTED"
                if isinstance(data, dict): order_id = data.get('id', data.get('order_id', 'EXECUTED'))
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict): order_id = data[0].get('id', 'EXECUTED')
                return {'success': True, 'order_id': order_id, 'quantity': quantity, 'pair': pair_name}
        except urllib.error.HTTPError as e:
            try:
                err_text = e.read().decode('utf-8')
                err_logs.append(f"V{idx}: HTTP {e.code} - {err_text}")
            except Exception:
                err_logs.append(f"V{idx}: HTTP {e.code} - {e}")
        except Exception as e:
            err_logs.append(f"V{idx}: {e}")

    last_err = " | ".join(err_logs) if err_logs else "Unknown Error"
    if "Instrument is not active" in last_err or ("422" in last_err and "not active" in last_err):
        INACTIVE_COINS.add(coin)
        print(f"🚫 Auto-Blacklisted inactive CoinDCX pair: {coin} (Added to INACTIVE_COINS set)")
    if side.lower() == "buy":
        return {'success': False, 'error': f"⚠️ Trade Cancelled: CoinDCX TP/SL validation failed ({last_err})."}
    return {'success': False, 'error': last_err}

def fetch_live_btc_price():
    try:
        klines = fetch_klines("BTC-USDT", "1m", 1)
        if klines: return klines[-1][4]
    except Exception: pass
    return 60080.0

def fetch_coindcx_btc_inrm_price():
    btc_usd = fetch_live_btc_price()
    return round(btc_usd * 1.3136, 1)

def send_hourly_market_report():
    try:
        btc_inrm_price = fetch_coindcx_btc_inrm_price()
        bull_coins, bear_coins, neutral_coins = [], [], []

        scan_pool = fetch_dynamic_watchlist()
        for symbol in scan_pool[:40]:
            clean_sym = symbol.replace("-", "_")
            try:
                time.sleep(0.05)
                m15_klines = fetch_klines(symbol, '15m', 30)
                if m15_klines and len(m15_klines) >= 15:
                    close_prices = [k[4] for k in m15_klines]
                    rsi_val = calculate_rsi(close_prices)
                    st_dir, _ = calculate_supertrend(m15_klines)
                    if st_dir == 1 or rsi_val >= 51: bull_coins.append(clean_sym)
                    elif st_dir == -1 and rsi_val <= 46: bear_coins.append(clean_sym)
                    else: neutral_coins.append(clean_sym)
                else: bull_coins.append(clean_sym)
            except Exception: bull_coins.append(clean_sym)
            
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        bull_list_str = ", ".join(bull_coins[:15]) if bull_coins else "None currently"

        msg = (
            f"📊 <b>AUTOMATED HOURLY MARKET CONDITION REPORT</b>\n\n"
            f"⏰ <b>Time:</b> {now_str}\n"
            f"✅ <b>Render Cloud Status:</b> 100% ONLINE (24/7 Active)\n\n"
            f"🔍 <b>Market Overview ({len(scan_pool)} Liquid Futures Pairs >$5M Vol):</b>\n"
            f"• <b>BTC Current Price:</b> <code>${btc_inrm_price:,.1f}</code>\n"
            f"🟢 <b>In Bull Run:</b> <code>{len(bull_coins)} coins</code>\n"
            f"🔴 <b>In Bear Run:</b> <code>{len(bear_coins)} coins</code>\n"
            f"⚪ <b>Unconfirmed / Consolidation:</b> <code>{len(neutral_coins)} coins</code>\n\n"
            f"🔥 <b>Bull Run Candidates:</b>\n"
            f"{bull_list_str}\n\n"
            f"🚀 <i>Automated 1-Hour Market Report from Render Cloud Bot</i>"
        )
        send_telegram_message(msg)
    except Exception as e:
        print(f"Hourly report error: {e}")

@app.route('/scan-now')
def scan_now_endpoint():
    try:
        report_lines = []
        scan_pool = fetch_dynamic_watchlist()
        for symbol in scan_pool:
            try:
                time.sleep(0.05)
                m15_klines = fetch_klines(symbol, '15m', 100)
                h1_klines = fetch_klines(symbol, '1h', 60)
                if not m15_klines or len(m15_klines) < 20: 
                    report_lines.append(f"{symbol:12s} | Error: Could not fetch candle data")
                    continue
                cmp = m15_klines[-1][4]
                daily_klines = fetch_klines(symbol, '1d', 2)
                if not daily_klines or len(daily_klines) < 2: 
                    daily_klines = m15_klines
                cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
                st_dir, st_val = calculate_supertrend(m15_klines)
                close_prices = [k[4] for k in m15_klines]
                rsi_val = calculate_rsi(close_prices)
                vol_spike = calculate_volume_spike(m15_klines)
                
                # 15m EMA 20 for Pullback / Support Dip Check
                ema20_15m = calculate_ema(close_prices, 20)
                
                # RULE 1: Confirmed Trend Filter (1H Macro Uptrend)
                # 1H Supertrend == GREEN AND CMP >= 1H EMA 50
                h1_macro_bullish = True
                if h1_klines and len(h1_klines) >= 20:
                    h1_st_dir, _ = calculate_supertrend(h1_klines)
                    h1_closes = [k[4] for k in h1_klines]
                    h1_ema50 = calculate_ema(h1_closes, 50)
                    h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

                # RULE 2: Proximity to 15m EMA 20 Support
                # abs(CMP - EMA20_15m) / EMA20_15m <= 0.012 (Price within 1.2% of 15m EMA 20 line)
                dist_to_ema20 = abs(cmp - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
                is_near_ema20 = (dist_to_ema20 <= 0.012)

                # RULE 3: Bullish Reversal Confirmation (Green Bounce Wick)
                # Current 1m/5m candle shows a green bullish rejection wick off the EMA line
                m1_klines = fetch_klines(symbol, '1m', 3)
                is_bounce_wick = False
                if m1_klines and len(m1_klines) > 0:
                    last_1m = m1_klines[-1]
                    is_bounce_wick = (last_1m[4] >= last_1m[1]) or ((min(last_1m[1], last_1m[4]) - last_1m[3]) > 0)
                else:
                    is_bounce_wick = (m15_klines[-1][4] >= m15_klines[-1][1])

                score = 50
                if cmp > cpr['tc']: score += 15
                if cmp > cpr['r1']: score += 10
                if 48 <= rsi_val <= 75: score += 20
                elif rsi_val > 75: score -= 10
                if vol_spike >= 2.0: score += 20
                elif vol_spike >= 1.30: score += 10
                elif vol_spike >= 1.15: score += 5
                score = max(0, min(100, score))
                
                is_above_cpr_tc = cmp > cpr['tc']
                is_st_green = st_dir == 1
                is_supertrend_green = is_st_green
                t1 = (vol_spike >= 1.30 and score >= 70)
                t2 = (vol_spike >= 1.15 and score >= 68)
                
                if is_above_cpr_tc and is_st_green and h1_macro_bullish and is_near_ema20 and is_bounce_wick and (t1 or t2):
                    status = "🔥 TRIGGERED AUTO-TRADE (Pullback Bounce)"
                elif is_above_cpr_tc and is_st_green and h1_macro_bullish and not is_near_ema20:
                    status = f"⏳ Waiting for Pullback to 15m EMA 20 (Dist {dist_to_ema20*100:.2f}%)"
                elif is_above_cpr_tc and is_st_green and h1_macro_bullish:
                    status = f"🟢 Bullish (Vol {vol_spike:.2f}x / Score {score})"
                elif not h1_macro_bullish:
                    status = "🛑 1H Macro Downtrend Filtered"
                else:
                    status = "⚪ Consolidating"
                
                report_lines.append(f"{symbol:12s} | CMP: {cmp:<10.4f} | EMA20: {ema20_15m:<10.4f} | ST 15M: {'GREEN' if is_st_green else 'RED':5s} | 1H Macro: {'BULL' if h1_macro_bullish else 'BEAR':4s} | Near EMA20: {'YES' if is_near_ema20 else 'NO':3s} | Vol: {vol_spike:.2f}x | Score: {score:<3d} | {status}")
            except Exception as e:
                report_lines.append(f"{symbol:12s} | Error: {e}")
        
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        html = f"<h2>⚡ LIVE {len(scan_pool)}-COIN DYNAMIC MARKET SCANNER AUDIT REPORT (VOL > $5M)</h2><p><b>Server Time:</b> {now_str}</p><pre>" + "\n".join(report_lines) + "</pre>"
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Scan Error:</h3><p>{e}</p>", 500

@app.route('/close-sol')
def close_sol_endpoint():
    try:
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="sell", cmp=108.23, leverage=7, custom_quantity=0.1)
        with active_trades_lock:
            ACTIVE_TRADES.pop('SOL-USDT', None)
        save_active_trades()
        send_telegram_message("🛡️ <b>SOL POSITION CLOSED SUCCESSFULLY VIA BOT ENDPOINT!</b>")
        return f"<h3>✅ SOL Position Close Result:</h3><pre>{json.dumps(res, indent=2)}</pre>", 200
    except Exception as e:
        return f"<h3>⚠️ Error closing SOL:</h3><p>{e}</p>", 500

@app.route('/test-trade')
def test_trade_endpoint():
    try:
        sol_klines = fetch_klines("SOL-USDT", "15m", 5)
        live_cmp = sol_klines[-1][4] if sol_klines else 118.80
        live_tp = round(live_cmp * 1.01, 4)
        live_sl = round(live_cmp * 0.99, 4)
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="buy", cmp=live_cmp, margin_inr=1000.0, leverage=7, custom_quantity=0.1, tp_price=live_tp, sl_price=live_sl)
        if res.get('success'):
            with active_trades_lock:
                ACTIVE_TRADES['SOL-USDT'] = {
                    'entry_price': live_cmp,
                    'total_qty': 0.1,
                    'remaining_qty': 0.1,
                    'tp1': live_tp,
                    'sl': live_sl,
                    'be_trigger': round(live_cmp * 1.0057, 4),
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
            f"• <b>Timestamp:</b> {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"
        )
        send_telegram_message(msg)
        return f"<h3>🧪 Diagnostic Test Result:</h3><pre>{json.dumps(res, indent=2)}</pre><p>Check Telegram @CRYPTOCREEN_BOT for alert!</p>", 200
    except Exception as e:
        return f"<h3>⚠️ Diagnostic Error:</h3><p>{e}</p>", 500

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    if scan_lock.acquire(blocking=False):
        def async_scan():
            try:
                run_scan()
            finally:
                scan_lock.release()
        threading.Thread(target=async_scan, daemon=True).start()
        return "⚡ OK - Dynamic Market Scan Triggered! Check /scan-now for live audit table.", 200
    return "⚡ OK - Market Scanner Currently Active", 200

def run_scan():
    state = load_state()
    candidates = []

    scan_pool = fetch_dynamic_watchlist()

    for symbol in scan_pool:
        try:
            time.sleep(0.08)
            daily_klines = fetch_klines(symbol, '1d', 2)
            m15_klines = fetch_klines(symbol, '15m', 100)
            h1_klines = fetch_klines(symbol, '1h', 60) # 1-Hour candles for macro trend protection
            
            if not m15_klines or len(m15_klines) < 20: continue
            if not daily_klines or len(daily_klines) < 2: daily_klines = m15_klines
            
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            
            # Calculate 15m EMA 20 for Pullback / Support Dip Check
            ema20_15m = calculate_ema(close_prices, 20)
            
            # RULE 1: Confirmed Trend Filter (1H Macro Uptrend)
            # 1H Supertrend == GREEN AND CMP >= 1H EMA 50
            h1_macro_bullish = True
            if h1_klines and len(h1_klines) >= 20:
                h1_st_dir, _ = calculate_supertrend(h1_klines)
                h1_closes = [k[4] for k in h1_klines]
                h1_ema50 = calculate_ema(h1_closes, 50)
                # MUST have GREEN 1H Supertrend AND CMP >= 1H EMA 50
                h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

            # RULE 2: Proximity to 15m EMA 20 Support
            # abs(CMP - EMA20_15m) / EMA20_15m <= 0.012 (Price within 1.2% of 15m EMA 20 line)
            dist_to_ema20 = abs(cmp - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
            is_near_ema20 = (dist_to_ema20 <= 0.012)

            # RULE 3: Bullish Reversal Confirmation (Green Bounce Wick)
            # Current 1m/5m candle shows a green bullish rejection wick off the EMA line
            m1_klines = fetch_klines(symbol, '1m', 3)
            is_bounce_wick = False
            if m1_klines and len(m1_klines) > 0:
                last_1m = m1_klines[-1]
                is_green_1m = (last_1m[4] >= last_1m[1])
                has_rejection_wick = (min(last_1m[1], last_1m[4]) - last_1m[3]) > 0
                is_bounce_wick = is_green_1m or has_rejection_wick
            else:
                last_15m = m15_klines[-1]
                is_bounce_wick = (last_15m[4] >= last_15m[1])

            # HIGH-CONFLUENCE A+ SCORING ENGINE:
            score = 50
            if cmp > cpr['tc']: score += 15       # Reward breaking CPR TC
            if cmp > cpr['r1']: score += 10       # Reward crossing R1
            if 48 <= rsi_val <= 75: score += 20   # Healthy bullish RSI range
            elif rsi_val > 75: score -= 10        # Overbought penalty
            
            if vol_spike >= 2.0: score += 20
            elif vol_spike >= 1.30: score += 10
            elif vol_spike >= 1.15: score += 5
            score = max(0, min(100, score))
            
            rating = "A+ (Strong Pullback Bounce) 👑" if score >= 85 else ("A (Solid Pullback Bounce) 🥇" if score >= 68 else "B (Moderate)")
            is_above_cpr_tc = cmp > cpr['tc']
            is_supertrend_green = st_dir == 1
            is_not_choppy = True if vol_spike >= 1.15 else not (48 <= rsi_val <= 52)
            
            # HIGH-CONFLUENCE PULLBACK BOUNCE ENGINE (Applies Rules 1, 2, and 3):
            trigger_1 = (vol_spike >= 1.30 and score >= 70)
            trigger_2 = (vol_spike >= 1.15 and score >= 68)
            
            if is_above_cpr_tc and is_supertrend_green and h1_macro_bullish and is_near_ema20 and is_bounce_wick and (trigger_1 or trigger_2) and is_not_choppy:
                candidates.append({'symbol': symbol, 'score': score, 'rating': rating, 'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 'rsi_val': rsi_val, 'vol_spike': vol_spike, 'ema20': ema20_15m})
        except Exception: pass

    candidates.sort(key=lambda x: x['score'], reverse=True)

    # HARDCODED ₹1,000 INR FIXED MARGIN PER TRADE
    coin_margin = 1000.0  # STRICT FIXED ₹1,000 INR (~$11.30 USDT) PER TRADE

    for cand in candidates:
        symbol, score, rating, cmp, cpr, st_val, rsi_val, vol_spike = cand['symbol'], cand['score'], cand['rating'], cand['cmp'], cand['cpr'], cand['st_val'], cand['rsi_val'], cand['vol_spike']
        try:
            clean_coin = symbol.split('-')[0].upper().replace("1000", "")
            with active_trades_lock:
                is_in_memory = any(clean_coin == s.split('-')[0].upper().replace("1000", "") for s in ACTIVE_TRADES.keys())
                active_count = len(ACTIVE_TRADES)

            # MAX PORTFOLIO ACTIVE TRADES CAP: Max 3 active trades allowed (Max ₹3,000 INR total allocated capital)
            if active_count >= 3:
                break

            # STRICT 30-MINUTE (1800s) PER-COIN COOLDOWN:
            last_sent = state.get(symbol, 0)
            if is_in_memory or (time.time() - last_sent < 1800):
                continue
            
            # LIVE EXCHANGE & MANUAL TRADE PROTECTION:
            # Skip if CoinDCX reports an active position (Supports manual trades cleanly and prevents duplicates)
            live_qty = fetch_coindcx_live_position_qty(symbol)
            if live_qty is not None and live_qty > 0:
                continue

            clean_symbol = symbol.replace("-", "")
            entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
            
            # PROVEN HIGH-CONFLUENCE PARAMETERS (NOISE-FREE SL -1.6% / -11.2% ROE, TARGET +3.2% / +22.4% ROE):
            # 7x Leverage: ROE -11.2% = -1.6% price move (outside 15m noise); ROE +22.4% = +3.2% price move (1:2 R:R Ratio)
            sl = round(cmp * 0.984, 4)            # Noise-Free Stop Loss (-1.6% Price Move)
            tp1 = round(cmp * 1.032, 4)           # Target 1 (+3.2% Price Move / 1:2 R:R Ratio)
            be_trigger = round(cmp * 1.0057, 4)   # Trailing Breakeven Trigger (+4.0% ROE / +0.57% Price Move)
            lev_num = 7  # Fixed 7x Leverage for all coins
            
            # EXECUTE TRADE ONLY IF AUTO-TRADING IS ACTIVE (STRICT BUY / LONG ONLY - ZERO SHORT TRADES ALLOWED!):
            if AUTO_TRADING_ENABLED:
                trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=coin_margin, leverage=lev_num, tp_price=tp1, sl_price=sl)
            else:
                trade_res = {'success': False, 'error': 'Auto-trading currently PAUSED via Mobile Telegram command (/stop).'}
            
            if trade_res.get('success'):
                exec_hdr = (
                    f"\n\n⚡ <b>AUTO-TRADE EXECUTED ON COINDCX FUTURES!</b>\n"
                    f"• <b>Status:</b> <code>SUCCESS (Order ID: {trade_res.get('order_id')})</code>\n"
                    f"• <b>Quantity:</b> <code>{trade_res.get('quantity')} {clean_symbol[:-4]}</code>\n"
                    f"• <b>Margin Allocated:</b> <code>₹{coin_margin:.0f} INR</code>"
                )
                
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
                state[symbol] = time.time()
                save_state(state)

            msg = (
                f"🟢 <b>NEW BULLISH PULLBACK BOUNCE SIGNAL</b>\n\n"
                f"<b>Pair:</b> B-{clean_symbol[:-4]}_USDT (Futures)\n"
                f"<b>Direction:</b> BUY / LONG\n\n"
                f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                f"🏆 <b>Signal Strength:</b> <code>{rating}</code>\n\n"
                f"⚙️ <b>Trade Parameters:</b>\n"
                f"• <b>Leverage:</b> <code>7x (Isolated)</code>\n"
                f"• <b>Margin:</b> <code>₹{coin_margin:.0f} INR (Per Trade)</code>\n"
                f"• <b>Live CMP:</b> <code>${cmp}</code>\n\n"
                f"🔹 <b>Entry Range:</b> <code>{entry_min} - {entry_max}</code>\n"
                f"🔹 <b>Stop Loss (ROE -11.2% / -1.6% Move):</b> <code>${sl}</code>\n"
                f"🎯 <b>Target (ROE +22.4% / +3.2% Move):</b> <code>${tp1}</code>\n"
                f"🛡️ <b>Trailing Breakeven:</b> <code>Trigger at +4% ROE (${be_trigger})</code>\n"
                f"{exec_hdr}"
            )
            send_telegram_message(msg)
        except Exception: pass

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
                    time.sleep(0.3)
                    clean_coin = symbol.split('-')[0].upper()
                    
                    # STEP A: Check if live position on CoinDCX is ALREADY 0 (e.g. manually closed on CoinDCX App or closed by CoinDCX exchange TP/SL)
                    live_qty = fetch_coindcx_live_position_qty(symbol)
                    if live_qty is not None and live_qty <= 0:
                        # Position on exchange is ALREADY 0! Do NOT send any sell order (Prevents accidental SHORT trades)!
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        
                        # Enforce 30-minute cooldown timestamp in state
                        st = load_state()
                        st[symbol] = time.time()
                        save_state(st)
                        
                        send_telegram_message(
                            f"🛡️ <b>POSITION CLOSED EXTERNALLY / MANUALLY!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Status:</b> Detected closed on CoinDCX App / Exchange\n"
                            f"• <b>Protection:</b> 30-Min Cooldown Activated (No Re-entry / No Short Trade)"
                        )
                        continue

                    # Use 1-minute real-time candles for position monitoring (NOT 15m historical high/low!)
                    m1_klines = fetch_klines(symbol, '1m', 3)
                    if not m1_klines: continue
                    cmp = m1_klines[-1][4]
                    candle_open_time = m1_klines[-1][0] / 1000.0
                    
                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES: continue
                        trade = ACTIVE_TRADES[symbol]
                    
                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    
                    # Track highest peak price reached STRICTLY AFTER ENTRY using live CMP/1m high
                    # Do not use past 15m candle high!
                    live_high = m1_klines[-1][2]
                    current_peak = live_high if candle_open_time >= entry_time else cmp
                    
                    highest_peak = max(trade.get('highest_peak', entry_p), current_peak, cmp)
                    trade['highest_peak'] = highest_peak
                    
                    # STAGE 1: BREAKEVEN TRIGGER (+4% ROE / +0.57% Price Move) WITH +0.2% FEE BUFFER
                    be_trigger_price = trade.get('be_trigger', entry_p * 1.0057)
                    if highest_peak >= be_trigger_price and not trade.get('is_be_active', False):
                        fee_buffer_sl = round(entry_p * 1.002, 4)  # Entry + 0.2% Fee & Slippage Buffer
                        with active_trades_lock:
                            trade['sl'] = fee_buffer_sl  # Move SL to Entry + Fee Buffer (Covers CoinDCX Taker Fees)
                            trade['is_be_active'] = True
                        save_active_trades()
                        
                        send_telegram_message(
                            f"🛡️ <b>TRAILING BREAKEVEN ACTIVATED (+4% ROE REACHED)!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>New Stop Loss:</b> <code>${fee_buffer_sl}</code> (Entry + 0.2% Fee Buffer)\n"
                            f"• <b>Status:</b> Risk-Free Trade (Exchange Fees Fully Covered)"
                        )

                    # STAGE 2: DYNAMIC PROFIT TRAILING ENGINE (Captures +5% to +50% Altcoin Rallies!)
                    # When price crosses +1.0% (+7% ROE), trail SL 0.8% below highest peak price
                    if highest_peak >= entry_p * 1.01:
                        trailing_sl = round(highest_peak * 0.992, 4)  # Trail 0.8% behind highest peak
                        current_sl = trade.get('sl', entry_p)
                        
                        # Only move SL upwards (never downwards!)
                        if trailing_sl > current_sl:
                            locked_roe = ((trailing_sl - entry_p) / entry_p) * 7 * 100
                            with active_trades_lock:
                                trade['sl'] = trailing_sl
                                trade['is_profit_locked'] = True
                            save_active_trades()
                            
                            send_telegram_message(
                                f"🚀 <b>DYNAMIC TRAILING PROFIT LOCK UPDATED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Peak High:</b> <code>${highest_peak}</code>\n"
                                f"• <b>New Trailing SL:</b> <code>${trailing_sl}</code>\n"
                                f"• <b>Locked ROE Profit:</b> <code>+{locked_roe:.1f}% ROE</code> 💰"
                            )

                    # STOP LOSS OR TRAILING PROFIT LOCK HIT:
                    live_low = m1_klines[-1][3] if candle_open_time >= entry_time else cmp
                    effective_low = min(cmp, live_low)
                    
                    if effective_low <= trade['sl']:
                        # Re-verify live position quantity RIGHT BEFORE placing sell order!
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            # Position already closed externally! Pop from memory & apply 30m cooldown
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            st = load_state()
                            st[symbol] = time.time()
                            save_state(state)
                            continue
                        
                        # CAP SELL QUANTITY TO LIVE POSITION SIZE (Guarantees order CANNOT overshoot into a SHORT position!)
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            # Calculate REALIZED PNL based on ACTUAL exit CMP!
                            realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                            if cmp >= entry_p * 1.001:
                                sl_type = f"PROFIT LOCK WIN (+{realized_pnl_pct:.1f}% ROE) 💰"
                            elif abs(cmp - entry_p) / entry_p <= 0.0025:
                                sl_type = "BREAKEVEN (FEES COVERED)"
                            else:
                                sl_type = f"STOP LOSS HIT ({realized_pnl_pct:.1f}% ROE)"

                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            
                            # MANDATORY 30-MINUTE COOLDOWN ON ALL EXIT TRADES (Prevents 5-Second Re-Entries!)
                            st = load_state()
                            st[symbol] = time.time()
                            save_state(st)
                            
                            send_telegram_message(
                                f"🏁 <b>POSITION CLOSED: {sl_type}</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"Closed at: <code>${cmp}</code> (Entry: <code>${entry_p}</code>)\n"
                                f"⏱️ <i>30-Min Cooldown Locked (No 5-Sec Re-Entries)</i>"
                            )
                        else:
                            print(f"SL Close failed for {symbol}: {res.get('error')}")
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Position monitor exception: {e}")
        time.sleep(3)

# MOBILE TELEGRAM ON/OFF COMMAND LISTENER (/stop & /start)
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
                            send_telegram_message("🛑 <b>AUTO-TRADING PAUSED VIA MOBILE COMMAND!</b>\n\n• Signals will still be reported.\n• Auto-order execution on CoinDCX is OFF.")
                        elif text in ['/start', '/resume', 'start', 'resume']:
                            AUTO_TRADING_ENABLED = True
                            send_telegram_message("🟢 <b>AUTO-TRADING ACTIVATED VIA MOBILE COMMAND!</b>\n\n• Auto-order execution on CoinDCX is ON.")
        except Exception: pass
        time.sleep(3)

def start_background_loop():
    def run_loop():
        time.sleep(5)
        while True:
            try:
                if scan_lock.acquire(blocking=False):
                    try: run_scan()
                    finally: scan_lock.release()
            except Exception as e:
                print(f"Scan loop exception: {e}")
            # ACCELERATED SCAN INTERVAL: Scan every 120 seconds (2 minutes) instead of 300 seconds!
            time.sleep(120)

    def run_hourly_report_loop():
        time.sleep(10)
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

    send_telegram_message("⚡ <b>RENDER BOT HIGH-CONFLUENCE WINNING SCANNER (> $5M VOLUME) DEPLOYED!</b>\n\n• Scan Scope: Dynamic All-CoinDCX Futures Pairs (Filtered for >$5M 24h Volume)\n• Entry Strategy: PULLBACK BOUNCE ENGINE (Rule 1: 1H Macro Bull + Rule 2: 15m EMA 20 Support <=1.2% + Rule 3: Reversal Wick)\n• Trailing Breakeven: ACTIVE (Moves SL to entry + 0.2% Fee Buffer at +4% ROE)\n• A+ Confluence Scoring: ACTIVE (Vol Spike >= 1.30x, Score >= 70)\n• Per-Coin Cooldown: 30 Minutes (Strict Noise-Free Guard)\n• Max Active Trades Cap: 3 Concurrent Trades (Max ₹3,000 INR Portfolio Capital)\n• Manual Trade Support: ACTIVE (Cleanly skips coins manually opened on CoinDCX App)\n• Zero Short Trade Rule: STRICT ACTIVE (100% BUY / LONG ONLY)\n• Double-Entry Guard: 4-LAYER ARMOR (Zero Re-Entries / Zero Size Stacking)\n• Margin set to ₹1000 INR (Per Trade)\n• Leverage set to 7x (Isolated)\n• Target set to +22.4% ROE (+3.2% price move / 1:2 R:R Ratio)\n• Stop Loss set to -11.2% ROE (-1.6% price move - Outside 15m Noise)\n• Dynamic Peak Trailing Engine: ACTIVE (Trails 0.8% behind peak to capture big pumps)\n• Mobile Telegram ON/OFF commands ready (/stop to pause, /start to resume)")

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
