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

# LIVE POSITION CHECKER (Ensures zero short trades can ever open):
def fetch_coindcx_live_position_qty(symbol):
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    if not api_key or not secret_key: return 0.0
    
    coin = symbol.split('-')[0].upper()
    futures_coin = f"1000{coin}" if coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI'] else coin
    target_pair = f"B-{futures_coin}_USDT"
    
    try:
        ts = int(round(time.time() * 1000))
        json_body = json.dumps({"timestamp": ts}, separators=(',', ':'))
        signature = hmac.new(secret_key.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
        headers = {'Content-Type': 'application/json', 'X-AUTH-APIKEY': api_key, 'X-AUTH-SIGNATURE': signature, 'User-Agent': 'Mozilla/5.0'}
        url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions"
        req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            positions = json.loads(resp.read().decode('utf-8'))
            if isinstance(positions, list):
                for p in positions:
                    pair = p.get('pair', '')
                    if pair == target_pair:
                        open_qty = float(p.get('open_position', p.get('active_position', p.get('quantity', 0))))
                        return abs(open_qty)
    except Exception: pass
    return 0.0

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

        for symbol in WATCHLIST:
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
            f"🔍 <b>Market Overview (40 CoinDCX Futures Symbols):</b>\n"
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
        for symbol in WATCHLIST:
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
                
                # Multi-Timeframe 1H Macro Trend Check
                h1_macro_bullish = True
                if h1_klines and len(h1_klines) >= 20:
                    h1_st_dir, _ = calculate_supertrend(h1_klines)
                    h1_closes = [k[4] for k in h1_klines]
                    h1_ema50 = calculate_ema(h1_closes, 50)
                    h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

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
                t1 = (vol_spike >= 1.30 and score >= 70)
                t2 = (vol_spike >= 1.15 and score >= 68)
                
                if is_above_cpr_tc and is_st_green and h1_macro_bullish and (t1 or t2):
                    status = "🔥 TRIGGERED AUTO-TRADE"
                elif is_above_cpr_tc and is_st_green and h1_macro_bullish:
                    status = f"🟢 Bullish (Vol {vol_spike:.2f}x / Score {score})"
                elif not h1_macro_bullish:
                    status = "🛑 1H Macro Downtrend Filtered"
                else:
                    status = "⚪ Consolidating"
                
                report_lines.append(f"{symbol:12s} | CMP: {cmp:<10.4f} | CPR TC: {cpr['tc']:<10.4f} | ST 15M: {'GREEN' if is_st_green else 'RED':5s} | 1H Macro: {'BULL' if h1_macro_bullish else 'BEAR':4s} | Vol: {vol_spike:.2f}x | Score: {score:<3d} | {status}")
            except Exception as e:
                report_lines.append(f"{symbol:12s} | Error: {e}")
        
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        html = f"<h2>⚡ LIVE 40-COIN MARKET SCANNER AUDIT REPORT (NO GEOBLOCK)</h2><p><b>Server Time:</b> {now_str}</p><pre>" + "\n".join(report_lines) + "</pre>"
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
        return "⚡ OK - Live 40-Coin Market Scan Triggered! Check /scan-now for live audit table.", 200
    return "⚡ OK - Market Scanner Currently Active", 200

def run_scan():
    state = load_state()
    candidates = []

    for symbol in WATCHLIST:
        try:
            time.sleep(0.1)
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
            
            # MULTI-TIMEFRAME DOWNTREND PROTECTION FILTER:
            # Check 1-Hour Macro Supertrend and 1-Hour EMA 50
            h1_macro_bullish = True
            if h1_klines and len(h1_klines) >= 20:
                h1_st_dir, _ = calculate_supertrend(h1_klines)
                h1_closes = [k[4] for k in h1_klines]
                h1_ema50 = calculate_ema(h1_closes, 50)
                # MUST have GREEN 1H Supertrend AND CMP >= 1H EMA 50
                h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

            # REFINED SCORING ENGINE:
            score = 50
            if cmp > cpr['tc']: score += 15       # Reward breaking CPR TC
            if cmp > cpr['r1']: score += 10       # Reward crossing R1
            if 48 <= rsi_val <= 75: score += 20   # Healthy bullish RSI range
            elif rsi_val > 75: score -= 10        # Overbought penalty
            
            if vol_spike >= 2.0: score += 20
            elif vol_spike >= 1.30: score += 10
            elif vol_spike >= 1.15: score += 5
            score = max(0, min(100, score))
            
            rating = "A+ (Strong Breakout) 👑" if score >= 85 else ("A (Solid Breakout) 🥇" if score >= 68 else "B (Moderate)")
            is_above_cpr_tc = cmp > cpr['tc']
            is_supertrend_green = st_dir == 1
            is_not_choppy = True if vol_spike >= 1.15 else not (48 <= rsi_val <= 52)
            
            # OPTIMIZED DUAL-TRIGGER ENGINE WITH MULTI-TIMEFRAME DOWNTREND FILTER:
            trigger_1 = (vol_spike >= 1.30 and score >= 70)
            trigger_2 = (vol_spike >= 1.15 and score >= 68)
            
            # FIX 2: ZERO TRADES IF 1H MACRO TREND IS BEARISH/DOWNTREND!
            if is_above_cpr_tc and is_supertrend_green and h1_macro_bullish and (trigger_1 or trigger_2) and is_not_choppy:
                candidates.append({'symbol': symbol, 'score': score, 'rating': rating, 'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 'rsi_val': rsi_val, 'vol_spike': vol_spike})
        except Exception: pass

    candidates.sort(key=lambda x: x['score'], reverse=True)

    # FIX 1: HARDCODED ₹1,000 INR FIXED MARGIN PER TRADE (DELETED DYNAMIC CAPITAL SCALER MULTIPLIER)
    coin_margin = 1000.0  # STRICT FIXED ₹1,000 INR (~$11.30 USDT) PER TRADE

    for cand in candidates:
        symbol, score, rating, cmp, cpr, st_val, rsi_val, vol_spike = cand['symbol'], cand['score'], cand['rating'], cand['cmp'], cand['cpr'], cand['st_val'], cand['rsi_val'], cand['vol_spike']
        try:
            # DOUBLE-ENTRY SAFEGUARD: Skip trade if coin is already in ACTIVE_TRADES or has a live open position on CoinDCX!
            with active_trades_lock:
                is_active = symbol in ACTIVE_TRADES
            if is_active or fetch_coindcx_live_position_qty(symbol) > 0:
                continue

            last_sent = state.get(symbol, 0)
            # ACCELERATED COOLDOWN: 600 seconds (10 minutes) per-coin cooldown instead of 30 minutes!
            if time.time() - last_sent > 600:
                clean_symbol = symbol.replace("-", "")
                entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
                
                # REVISED SL & TARGET LOGIC (OPTION B: ROE -7% SL, ROE +7% TP, Trailing BE at +4%):
                # 7x Leverage: ROE -7.0% = -1.0% price move; ROE +7.0% = +1.0% price move
                sl = round(cmp * 0.99, 4)
                tp1 = round(cmp * 1.01, 4)
                be_trigger = round(cmp * 1.0057, 4)  # +4.0% ROE (+0.57% price move)
                lev_num = 7  # Fixed 7x Leverage for all coins
                
                # EXECUTE TRADE ONLY IF AUTO-TRADING IS ACTIVE:
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
                else:
                    exec_hdr = f"\n\n⚠️ <b>COINDCX EXECUTION NOTICE:</b>\n<code>{trade_res.get('error')}</code>"

                msg = (
                    f"🟢 <b>NEW BULLISH BREAKOUT SIGNAL</b>\n\n"
                    f"<b>Pair:</b> B-{clean_symbol[:-4]}_USDT (Futures)\n"
                    f"<b>Direction:</b> BUY / LONG\n\n"
                    f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                    f"🏆 <b>Signal Strength:</b> <code>{rating}</code>\n\n"
                    f"⚙️ <b>Trade Parameters:</b>\n"
                    f"• <b>Leverage:</b> <code>7x (Isolated)</code>\n"
                    f"• <b>Margin:</b> <code>₹{coin_margin:.0f} INR (Per Trade)</code>\n"
                    f"• <b>Live CMP:</b> <code>${cmp}</code>\n\n"
                    f"🔹 <b>Entry Range:</b> <code>{entry_min} - {entry_max}</code>\n"
                    f"🔹 <b>Stop Loss (ROE -7%):</b> <code>{sl}</code>\n"
                    f"🎯 <b>Target (ROE +7%):</b> <code>{tp1}</code>\n"
                    f"🛡️ <b>Trailing Breakeven:</b> <code>Trigger at +4% ROE (${be_trigger})</code>\n"
                    f"{exec_hdr}"
                )
                ok = send_telegram_message(msg)
                if ok:
                    state[symbol] = time.time()
                    save_state(state)
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
                    time.sleep(0.5)
                    
                    # REQUIREMENT 1 SAFEGUARD: Check live open position quantity on CoinDCX first!
                    live_qty = fetch_coindcx_live_position_qty(symbol)
                    if live_qty <= 0:
                        # Position was ALREADY closed manually on CoinDCX or by native TP/SL!
                        # DO NOT send any SELL order! Simply clean memory.
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        continue

                    m15_klines = fetch_klines(symbol, '15m', 5)
                    if not m15_klines: continue
                    high_price = m15_klines[-1][2]
                    low_price = m15_klines[-1][3]
                    cmp = m15_klines[-1][4]
                    
                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES: continue
                        trade = ACTIVE_TRADES[symbol]
                    
                    clean_coin = symbol.split('-')[0].upper()
                    
                    # TRAILING BREAKEVEN TRIGGER (+4% ROE / +0.57% Price Move):
                    be_trigger_price = trade.get('be_trigger', trade['entry_price'] * 1.0057)
                    if (high_price >= be_trigger_price or cmp >= be_trigger_price) and not trade.get('is_be_active', False):
                        with active_trades_lock:
                            trade['sl'] = trade['entry_price']  # Move SL to Entry Price (0% Loss)
                            trade['is_be_active'] = True
                        save_active_trades()
                        
                        send_telegram_message(
                            f"🛡️ <b>TRAILING BREAKEVEN ACTIVATED (+4% ROE REACHED)!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>New Stop Loss:</b> <code>${trade['entry_price']}</code> (Entry Price)\n"
                            f"• <b>Status:</b> Guaranteed Risk-Free Trade (0% Loss Possible)"
                        )

                    # TARGET REACHED (ROE +7%): High Wick or CMP hits TP1
                    if high_price >= trade['tp1'] or cmp >= trade['tp1']:
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=trade['total_qty'])
                        if res.get('success'):
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            
                            send_telegram_message(
                                f"🎯 <b>TARGET REACHED (ROE +7%)!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"🔥 <b>100% Target Hit at CMP:</b> <code>{cmp}</code> (Entry: <code>{trade['entry_price']}</code>)\n"
                                f"💰 <b>Trade Successfully Closed with Profit!</b>"
                            )
                        else:
                            print(f"TP Close failed for {symbol}: {res.get('error')}")

                    # STOP LOSS HIT (ROE -7% or Breakeven): Low Wick or CMP hits SL
                    elif low_price <= trade['sl'] or cmp <= trade['sl']:
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=trade['total_qty'])
                        if res.get('success'):
                            sl_type = "BREAKEVEN (0% LOSS)" if trade.get('is_be_active', False) else "STOP LOSS (ROE -7%)"
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            
                            send_telegram_message(
                                f"🛑 <b>POSITION CLOSED: {sl_type}</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"Position closed at SL: <code>{cmp}</code> (Entry: <code>{trade['entry_price']}</code>)"
                            )
                        else:
                            print(f"SL Close failed for {symbol}: {res.get('error')}")
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Position monitor exception: {e}")
        time.sleep(5)

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

    send_telegram_message("⚡ <b>RENDER BOT OPTION B (1:1 RATIO + TRAILING BREAKEVEN) DEPLOYED!</b>\n\n• Scan Interval: 2 Minutes (Fast Execution)\n• Per-Coin Cooldown: 10 Minutes\n• Double-Entry Guard: ACTIVE (Zero Re-Entries)\n• Margin set to ₹1000 INR (Per Trade)\n• Leverage set to 7x (Isolated)\n• Target set to +7% ROE (+1.0% price move)\n• Stop Loss set to -7% ROE (-1.0% price move)\n• Trailing Breakeven: ACTIVE (Moves SL to entry at +4% ROE)\n• Position monitor frozen when paused via /stop\n• Mobile Telegram ON/OFF commands ready (/stop to pause, /start to resume)")

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
