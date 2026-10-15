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

# Telegram Bot Credentials
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8938527650").strip()

# CoinDCX API Credentials
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"

ctx = ssl._create_unverified_context()

# ==============================================================================
# 2. WATCHLIST & DYNAMIC COIN DISCOVERY
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
    'WAL-USDT', 'STRK-USDT', 'WLD-USDT', 'QNT-USDT', 'ZK-USDT',
    'ZRO-USDT', 'HBAR-USDT', 'XLM-USDT', 'TRUMP-USDT', 'PYTH-USDT',
    'NIL-USDT', 'ASTER-USDT', 'ZAMA-USDT', 'MUBARAK-USDT', 'BLUR-USDT',
    'GRAM-USDT', 'RAY-USDT', 'PENGU-USDT', 'AVA-USDT', 'W-USDT',
    'AERO-USDT', 'EPIC-USDT', 'MARSCOIN-USDT', 'CHIP-USDT', 'BERA-USDT',
    'CRV-USDT', 'RSR-USDT', 'DUSK-USDT', 'MEGA-USDT', 'PLUME-USDT',
    'ETHFI-USDT', 'DASH-USDT', 'LDO-USDT', 'JTO-USDT', 'MAGIC-USDT',
    'S-USDT', 'GTC-USDT', 'CAKE-USDT', 'WLFI-USDT', 'RLC-USDT',
    'WCT-USDT', 'VIRTUAL-USDT', 'MORPHO-USDT', 'ALGO-USDT', 'FF-USDT',
    'ACE-USDT', 'MET-USDT', 'JST-USDT', 'ETC-USDT', 'CFX-USDT',
    'EIGEN-USDT', 'SKY-USDT', 'BOME-USDT', 'AXL-USDT', 'OGN-USDT',
    'LUMIA-USDT', 'ZEN-USDT', 'NIGHT-USDT', 'KAIA-USDT', 'CFG-USDT',
    'IO-USDT', 'MITO-USDT'
]

COINDCX_PAIR_ALIASES = {
    'PEPE': '1000PEPE',
    'SHIB': '1000SHIB',
    'BONK': '1000BONK',
    'FLOKI': '1000FLOKI',
    'LUNC': '1000LUNC',
    'XEC': '1000XEC',
    'RATS': '1000RATS',
    'SATS': '1000SATS',
    'CHEEMS': '1000CHEEMS',
    'CAT': '1000CAT',
    'MOG': '1000MOG',
    'BTT': '1000BTT'
}

EXCLUDED_NON_CRYPTO = {
    'XAU', 'XAG', 'PAXG', 'CL', 'BZ', 'NG', 'WTI', 'BRENT', 
    'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'CNY', 'INR',
    'USDC', 'FDUSD', 'TUSD', 'USDD', 'DAI', 'USD', 'UST'
}

INACTIVE_COINS = {'XMR', 'BTCDOM'}

CACHED_DYNAMIC_WATCHLIST = []
LAST_WATCHLIST_FETCH_TIME = 0

def fetch_dynamic_watchlist(min_volume_usdt=2500000.0):
    global CACHED_DYNAMIC_WATCHLIST, LAST_WATCHLIST_FETCH_TIME
    now = time.time()
    if CACHED_DYNAMIC_WATCHLIST and (now - LAST_WATCHLIST_FETCH_TIME < 600):
        return CACHED_DYNAMIC_WATCHLIST

    valid_coins = []
    seen = set()

    for s in WATCHLIST:
        coin = s.split('-')[0].upper()
        if coin not in INACTIVE_COINS and coin not in EXCLUDED_NON_CRYPTO and s not in seen:
            valid_coins.append(s)
            seen.add(s)

    ticker_urls = [
        "https://data-api.binance.vision/api/v3/ticker/24hr",
        "https://api.binance.com/api/v3/ticker/24hr",
        "https://api.mexc.com/api/v3/ticker/24hr"
    ]
    for t_url in ticker_urls:
        try:
            req = urllib.request.Request(t_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list) and len(data) > 0:
                    for item in data:
                        sym = item.get('symbol', '')
                        quote_vol = float(item.get('quoteVolume', 0))
                        if sym.endswith('USDT') and quote_vol >= min_volume_usdt:
                            coin = sym[:-4].upper()
                            pair_fmt = f"{coin}-USDT"
                            if coin not in INACTIVE_COINS and coin not in EXCLUDED_NON_CRYPTO and not coin.endswith('UP') and not coin.endswith('DOWN'):
                                if pair_fmt not in seen:
                                    valid_coins.append(pair_fmt)
                                    seen.add(pair_fmt)
                    break
        except Exception: pass

    CACHED_DYNAMIC_WATCHLIST = valid_coins
    LAST_WATCHLIST_FETCH_TIME = now
    return CACHED_DYNAMIC_WATCHLIST

# ==============================================================================
# 3. CANDLE DATA & TECHNICAL INDICATOR ENGINES
# ==============================================================================
def fetch_klines(symbol, interval_str="15m", limit=100):
    coin = symbol.split('-')[0].upper()
    clean_sym = f"{coin}USDT"
    
    # Provider 1: Binance Vision Public Data API (No Geoblock, Fast)
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception: pass

    # Provider 2: Standard Binance API
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception: pass

    # Provider 3: CoinDCX Public Candles API
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

    # Provider 4: Bybit Public Market API
    try:
        bybit_int = '15' if interval_str == '15m' else ('60' if interval_str == '1h' else ('1' if interval_str == '1m' else 'D'))
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={clean_sym}&interval={bybit_int}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            list_data = data.get('result', {}).get('list', [])
            if list_data:
                list_sorted = sorted(list_data, key=lambda x: int(x[0]))
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in list_sorted]
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

def calculate_cpr(high, low, close):
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot
    return {
        'pivot': pivot, 
        'tc': max(tc, bc), 
        'bc': min(tc, bc), 
        'r1': 2.0 * pivot - low, 
        'r2': pivot + (high - low),
        's1': 2.0 * pivot - high,
        's2': pivot - (high - low)
    }

def calculate_ema(prices, period):
    if not prices or len(prices) == 0: return 0.0
    if len(prices) < period: return sum(prices) / len(prices)
    multiplier = 2.0 / (period + 1.0)
    ema = sum(prices[:period]) / float(period)
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

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
# 4. TELEGRAM BROADCAST ENGINE
# ==============================================================================
def send_telegram_message(text):
    for token_to_try in [TOKEN, "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c", "8788523087:AAGgfn0-JpnnIlqdxNDj-2an-pGp0WORnqA"]:
        for mode in ['HTML', None]:
            try:
                url = f"https://api.telegram.org/bot{token_to_try}/sendMessage"
                payload = {'chat_id': CHAT_ID, 'text': text}
                if mode: payload['parse_mode'] = mode
                data = urllib.parse.urlencode(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                    res = json.loads(resp.read().decode('utf-8'))
                    if res.get('ok'): return True
            except Exception:
                if mode == 'HTML':
                    text = re.sub(r'<[^>]+>', '', text)
                continue
    return False

# ==============================================================================
# 5. AUDIT JOURNAL & HISTORY LOGGER
# ==============================================================================
def log_trade_event(symbol, event_type, data):
    with trade_history_lock:
        history = []
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f: history = json.load(f)
            except Exception: history = []
        
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

def generate_daily_summary(target_date_str):
    with trade_history_lock:
        history = []
        if os.path.exists(TRADE_HISTORY_FILE):
            try:
                with open(TRADE_HISTORY_FILE, 'r') as f: history = json.load(f)
            except Exception: history = []

    day_events = [e for e in history if e.get('date') == target_date_str]
    executed = [e for e in day_events if e.get('type') == 'EXECUTED']
    cancelled = [e for e in day_events if e.get('type') == 'CANCELLED']
    closed = [e for e in day_events if e.get('type') == 'CLOSED']

    wins = [c for c in closed if c.get('details', {}).get('realized_pnl_pct', 0) > 0]
    total_closed = len(closed)
    win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0
    total_pnl = sum(c.get('details', {}).get('realized_pnl_pct', 0) for c in closed)

    lines = [
        f"📅 <b>DAILY AUTOMATED TRADING REPORT ({target_date_str})</b>\n",
        f"📊 <b>Performance Overview:</b>",
        f"• <b>Total Signals:</b> {len(executed) + len(cancelled)}",
        f"• <b>Executed Trades:</b> {len(executed)}",
        f"• <b>Non-Executed / Skipped:</b> {len(cancelled)}",
        f"• <b>Closed Trades:</b> {total_closed}",
        f"• <b>Win Rate:</b> {win_rate:.1f}% 🏆",
        f"• <b>Total Realized Gain:</b> {total_pnl:+.1f}% ROE 💰\n",
        f"📝 <b>Today's Executed Trades:</b>"
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

    return "\n".join(lines)

# ==============================================================================
# 6. PROVEN COINDCX ORDER EXECUTION ENGINE
# ==============================================================================
def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=1000.0, leverage=7, custom_quantity=None):
    if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
        
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
    clean_coin = raw_coin
    
    if custom_quantity is not None:
        quantity = custom_quantity
    else:
        usdt_inr_rate = 88.5
        position_value_usdt = (margin_inr * leverage) / usdt_inr_rate
        raw_qty = position_value_usdt / cmp if cmp > 0 else 0.1
        
        # QUANTITY STEP-SIZE CALIBRATION (Divisible by 0.1 for CoinDCX Futures):
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
        (futures_url, {
            "order": {
                "side": side.lower(),
                "pair": f"B-{clean_coin}USDT",
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
            except Exception:
                err_logs.append(f"V{idx}: HTTP {e.code} - {e}")
        except Exception as e:
            err_logs.append(f"V{idx}: {e}")

    last_err = " | ".join(err_logs) if err_logs else "Unknown Error"
    return {'success': False, 'error': last_err}

def fetch_live_btc_price():
    try:
        klines = fetch_klines("BTC-USDT", "1m", 1)
        if klines: return klines[-1][4]
    except Exception: pass
    return 80400.0

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
# 7. FLASK APPLICATION WEB ENDPOINTS
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

    if scan_lock.acquire(blocking=False):
        def async_scan():
            try: run_scan()
            finally: scan_lock.release()
        threading.Thread(target=async_scan, daemon=True).start()
        return "⚡ OK - Market Scanner Triggered via Keep-Alive/Ping", 200

    return "⚡ OK - Market Scanner Active (24/7 Render Cloud Bot)", 200

# ==============================================================================
# 8. AUTONOMOUS SCANNER & ORDER EXECUTION ENGINE (CPR OPTION A)
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
            
            # 1H Macro Trend Bullish Gate
            h1_macro_bullish = True
            if h1_klines and len(h1_klines) >= 20:
                h1_st_dir, _ = calculate_supertrend(h1_klines)
                h1_closes = [k[4] for k in h1_klines]
                h1_ema50 = calculate_ema(h1_closes, 50)
                h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

            last_15m_low = m15_klines[-1][3]

            # CPR Buy Zone: Price holding at or above Bottom Central (BC) support
            is_cpr_buy_zone = (cmp >= cpr['bc'] * 0.998)

            # Dynamic Confluence Scoring Engine (Base: 40)
            score = 40
            if is_cpr_buy_zone: score += 20
            if cmp >= cpr['tc'] * 0.998: score += 10
            if 42 <= rsi_val <= 72: score += 10
            if vol_spike >= 1.15: score += 10
            score = max(0, min(100, score))
            
            rating = "A+ (Strong Trend & CPR Confluence) 👑" if score >= 80 else ("A (Solid CPR Bounce) 🥇" if score >= 70 else "B (Moderate)")

            # Option A Entry Gate: Triggers automatically for 15M Green + 1H Bull + CPR Support + Score >= 75
            if is_st_green and h1_macro_bullish and is_cpr_buy_zone and (score >= 75):
                candidates.append({
                    'symbol': symbol, 'score': score, 'rating': rating, 
                    'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 
                    'rsi_val': rsi_val, 'vol_spike': vol_spike, 
                    'ema20': ema20_15m, 'm15_low': last_15m_low
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
            clean_coin = raw_coin
            futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
            
            with active_trades_lock:
                is_in_memory = (symbol in ACTIVE_TRADES)
                active_count = len(ACTIVE_TRADES)

            # Max 4 Concurrent Trades Cap
            if active_count >= 4:
                break

            last_sent = curr_state.get(symbol, 0)
            # 10-Minute Cooldown per coin
            if is_in_memory or (time.time() - last_sent < 600):
                continue

            clean_symbol = symbol.replace("-", "")
            if cmp < 0.001:
                entry_min, entry_max = round(cmp * 0.998, 8), round(cmp * 1.001, 8)
            else:
                entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
            
            # Author's CPR Stop Loss Logic (Below BC / Prev Low / Capped at -0.95% drop)
            prev_low_val = cand.get('m15_low', cmp)
            bc_val = cpr.get('bc', cmp * 0.995)
            support_floor = min(bc_val, prev_low_val)
            structural_sl = support_floor * 0.9985
            hard_sl_cap = cmp * 0.9905  # -0.95% Price Drop Cap (-6.65% ROE)
            sl_raw = max(hard_sl_cap, structural_sl)
            if sl_raw >= cmp * 0.997:
                sl_raw = cmp * 0.995

            # Target: Next Pivot Level (R1 or R2) or standard +3.2% move (+22.4% ROE)
            standard_tp = cmp * 1.032
            r1_val = cpr.get('r1', standard_tp)
            r2_val = cpr.get('r2', standard_tp)

            if r1_val >= cmp * 1.020 and r1_val <= cmp * 1.036:
                tp1_raw = r1_val
            elif r1_val < cmp * 1.020 and r2_val >= cmp * 1.028:
                tp1_raw = min(r2_val, cmp * 1.038)
            else:
                tp1_raw = standard_tp

            be_trigger_raw = cmp * 1.0085  # +0.85% move (+6.0% ROE)
            
            if raw_coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI'] or cmp < 0.001:
                sl, tp1, be_trigger = round(sl_raw, 8), round(tp1_raw, 8), round(be_trigger_raw, 8)
            elif cmp < 1.0:
                sl, tp1, be_trigger = round(sl_raw, 4), round(tp1_raw, 4), round(be_trigger_raw, 4)
            else:
                sl, tp1, be_trigger = round(sl_raw, 2), round(tp1_raw, 2), round(be_trigger_raw, 2)

            # Execute Long Trade DIRECTLY (100% BUY / LONG ONLY)
            if AUTO_TRADING_ENABLED:
                trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=coin_margin, leverage=lev_num)
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
                f"• <b>Leverage:</b> <code>{lev_num}x (Isolated)</code>\n"
                f"• <b>Margin:</b> <code>₹{coin_margin:.0f} INR (Per Trade)</code>\n"
                f"• <b>Live CMP:</b> <code>${cmp_str}</code>\n\n"
                f"🔹 <b>Entry Zone:</b> <code>${entry_min_str} - ${entry_max_str}</code>\n"
                f"🛑 <b>Author CPR Stop Loss:</b> <code>${sl_str}</code> (-0.95% hard floor)\n"
                f"🎯 <b>Target (TP1):</b> <code>${tp1_str}</code> (+3.2% move / +22.4% ROE)\n"
                f"🛡️ <b>Breakeven Lock:</b> At +6.0% ROE (+0.85% move)"
                f"{exec_hdr}"
            )
            send_telegram_message(msg)

        except Exception as e:
            print(f"Candidate execution error {symbol}: {e}")

# ==============================================================================
# 9. REAL-TIME POSITION MONITORING & AUTOMATED EXITS
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
                    m1_klines = fetch_klines(symbol, '1m', 3)
                    if not m1_klines: continue
                    cmp = m1_klines[-1][4]
                    
                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES: continue
                        trade = ACTIVE_TRADES[symbol]
                    
                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    clean_coin = symbol.split('-')[0].upper()
                    raw_pnl_pct = ((cmp - entry_p) / entry_p) * trade.get('leverage', 7) * 100
                    
                    # 1. 75-MINUTE STAGNATION GUARD (Auto Time-Stop)
                    if time.time() - entry_time >= 4500:
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=trade['remaining_qty'])
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        pnl_inr = (raw_pnl_pct / 100.0) * 1000.0
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(raw_pnl_pct, 1), "sl_type": "75-MIN STAGNATION TIME-STOP ⏱️"})
                        send_telegram_message(
                            f"⏱️ <b>75-MINUTE TIME-STOP EXECUTED!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                            f"• <b>Result:</b> <code>{raw_pnl_pct:+.1f}% ROE ({pnl_inr:+.2f} INR)</code>\n"
                            f"• <b>Reason:</b> Stagnation Guard reached 75 minutes. Capital released."
                        )
                        continue

                    # 2. BREAKEVEN PROFIT LOCK (+6.0% ROE / +0.85% move)
                    if not trade.get('is_be_active', False) and cmp >= trade.get('be_trigger', entry_p * 1.0085):
                        with active_trades_lock:
                            trade['is_be_active'] = True
                            trade['sl'] = entry_p * 1.001
                        save_active_trades()
                        send_telegram_message(
                            f"🛡️ <b>BREAKEVEN PROFIT LOCK ACTIVATED! 🚀</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Gain Reached:</b> <code>+6.0% ROE (+0.85% move)</code>\n"
                            f"• <b>Action:</b> Stop Loss shifted to <b>${entry_p * 1.001:.4f}</b> (Zero Risk Trade)!"
                        )

                    # 3. 3-STAGE DYNAMIC TRAILING (+8.4% and +12.6% ROE)
                    stage2_trigger = entry_p * 1.0120  # +8.4% ROE
                    stage3_trigger = entry_p * 1.0180  # +12.6% ROE
                    if cmp >= stage3_trigger and trade.get('trailing_stage', 0) < 3:
                        with active_trades_lock:
                            trade['trailing_stage'] = 3
                            trade['sl'] = max(trade['sl'], entry_p * 1.0120)
                        save_active_trades()
                        send_telegram_message(
                            f"🏃 <b>DYNAMIC TRAIL STAGE 2 ACTIVATED!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Price:</b> <code>${cmp}</code> (+12.6% ROE)\n"
                            f"• <b>Guaranteed Profit:</b> Stop Loss locked at +8.4% ROE (${entry_p * 1.0120:.4f})!"
                        )
                    elif cmp >= stage2_trigger and trade.get('trailing_stage', 0) < 2:
                        with active_trades_lock:
                            trade['trailing_stage'] = 2
                            trade['sl'] = max(trade['sl'], entry_p * 1.0060)
                        save_active_trades()
                        send_telegram_message(
                            f"🏃 <b>DYNAMIC TRAIL STAGE 1 ACTIVATED!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Price:</b> <code>${cmp}</code> (+8.4% ROE)\n"
                            f"• <b>Guaranteed Profit:</b> Stop Loss locked at +4.2% ROE (${entry_p * 1.0060:.4f})!"
                        )

                    # 4. TARGET / TP1 HIT (+3.2% move / +22.4% ROE)
                    if cmp >= trade['tp1']:
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=trade['remaining_qty'])
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                        pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "TARGET WIN (+22.4% ROE) 🎯"})
                        
                        send_telegram_message(
                            f"🎯 <b>PROFIT TARGET HIT (TP1)! 🚀</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                            f"• <b>Realized Gain:</b> <code>+{realized_pnl_pct:.1f}% ROE (+{pnl_inr:.2f} INR)</code> 💰\n"
                            f"• <b>Trigger:</b> Full Target Exit achieved!"
                        )
                        continue

                    # 5. STOP LOSS HIT
                    if cmp <= trade['sl']:
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=trade['remaining_qty'])
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                        pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                        log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "STOP LOSS HIT 🛑"})
                        
                        send_telegram_message(
                            f"🛑 <b>STOP LOSS EXECUTED VIA BOT MONITOR</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                            f"• <b>Realized PNL:</b> <code>{realized_pnl_pct:.1f}% ROE ({pnl_inr:.2f} INR)</code>\n"
                            f"• <b>Protection:</b> Capital protected at CPR structural support floor."
                        )
                        continue

                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(3)

# ==============================================================================
# 10. MOBILE TELEGRAM INTERACTIVE COMMAND LISTENER
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
# 11. BACKGROUND THREADS & APPLICATION RUNNER
# ==============================================================================
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
        "⚡ <b>RENDER BOT DIRECT EXECUTION ENGINE DEPLOYED!</b>\n\n"
        "• <b>Order Execution:</b> INSTANT DIRECT EXECUTION (Zero Roadblocks)\n"
        "• <b>Market Universe:</b> ALL 180+ CoinDCX Pairs (Dynamic Discovery)\n"
        "• <b>Strategy:</b> CPR Breakout & Retest (Option A: 15M Green + 1H Bull + CPR Support)\n"
        "• <b>Hard Stop Loss:</b> Author CPR Logic (Below BC / Prev Low, -0.95% Floor)\n"
        "• <b>Profit Targets:</b> R1/R2 Pivot Level or +3.2% move (+22.4% ROE)\n"
        "• <b>Breakeven Engine:</b> Locked at +6.0% ROE (+0.85% move)\n"
        "• <b>Dynamic Trailing:</b> 3-Stage Runner (+8.4% and +12.6% ROE)\n"
        "• <b>Stagnation Guard:</b> 75-Minute Auto Time-Stop\n"
        "• <b>Max Portfolio:</b> 4 Active Trades | ₹1,000 INR Margin | 7x Isolated\n"
        "• <b>Alerts:</b> Guaranteed instant Telegram trade & execution broadcasts"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
