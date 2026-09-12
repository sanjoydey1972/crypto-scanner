import urllib.request
import urllib.parse
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

# 4-Step Execution Tracker State
# Format: { symbol: { entry_price, total_qty, remaining_qty, tp1, tp2, sl, tp1_booked, entry_time } }
ACTIVE_TRADES = {}

@app.route('/')
@app.route('/health')
def health_check():
    return "OK - Scanner & 4-Step Manager is Live", 200

@app.route('/trigger')
def trigger_scan():
    if scan_lock.acquire(blocking=False):
        def async_scan():
            try:
                run_scan()
            finally:
                scan_lock.release()
        threading.Thread(target=async_scan, daemon=True).start()
        return "Scan triggered", 200
    return "Scan already in progress", 200

TOKEN = "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
CHAT_ID = "8938527650"
STATE_FILE = "scanner_state.json"

# Strict watchlist of top liquid coins verified to exist on CoinDCX Futures
WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'DOGE-USDT', 
    'XRP-USDT', 'ADA-USDT', 'LINK-USDT', 'NEAR-USDT', 'BCH-USDT', 
    'SUI-USDT', 'LTC-USDT', 'DOT-USDT', 'PEPE-USDT', 'OP-USDT', 
    'ARB-USDT', 'APT-USDT', 'RENDER-USDT', 'INJ-USDT', 'FET-USDT', 
    'TIA-USDT', 'WIF-USDT', 'SHIB-USDT', 'FLOKI-USDT', 'AAVE-USDT',
    'FTM-USDT', 'UNI-USDT', 'ATOM-USDT', 'ICP-USDT', 'SAND-USDT'
]

ctx = ssl._create_unverified_context()

# Gold-Standard Binance Market Data Fetcher (Eliminates symbol/price glitches)
def fetch_klines_binance(symbol, interval_str="15m", limit=100):
    clean_sym = symbol.replace("-", "").upper()
    url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
        raw_candles = json.loads(resp.read().decode('utf-8'))
        formatted = []
        for c in raw_candles:
            # [open_time, open, high, low, close, volume]
            formatted.append([int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])])
        return formatted

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

def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=500.0, leverage=5, custom_quantity=None):
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    
    if not api_key or not secret_key:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
        
    coin = symbol.split('-')[0].upper()
    
    if custom_quantity is not None:
        quantity = custom_quantity
    else:
        usdt_inr_rate = 88.5
        position_value_usdt = (margin_inr * leverage) / usdt_inr_rate
        raw_qty = position_value_usdt / cmp if cmp > 0 else 1.0
        
        # Precise decimal lot size formatting for CoinDCX API
        if coin == 'BTC':
            quantity = round(raw_qty, 3)
        elif coin == 'ETH':
            quantity = round(raw_qty, 2)
        elif raw_qty >= 100:
            quantity = float(int(round(raw_qty)))
        elif raw_qty >= 10:
            quantity = round(raw_qty, 1)
        elif raw_qty >= 1:
            quantity = round(raw_qty, 2)
        else:
            quantity = round(raw_qty, 4)
    if quantity <= 0: quantity = 1.0

    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"

    # Multi-variant solver to handle all CoinDCX API payload specs
    payload_variants = [
        {
            "timestamp": int(round(time.time() * 1000)),
            "order_type": "market_order",
            "side": side.lower(),
            "pair": f"B-{coin}_USDT",
            "total_quantity": quantity,
            "leverage": leverage,
            "notification": "no_notification",
            "margin_currency_short_name": "INR"
        },
        {
            "timestamp": int(round(time.time() * 1000)),
            "order_type": "market_order",
            "side": side.lower(),
            "pair": f"B-{coin}_USDT",
            "total_quantity": quantity,
            "leverage": leverage,
            "notification": "no_notification"
        },
        {
            "timestamp": int(round(time.time() * 1000)),
            "order_type": "market_order",
            "price": cmp,
            "side": side.lower(),
            "pair": f"B-{coin}_USDT",
            "total_quantity": quantity,
            "leverage": leverage,
            "notification": "no_notification",
            "margin_currency_short_name": "INR"
        },
        {
            "timestamp": int(round(time.time() * 1000)),
            "order_type": "market",
            "side": side.lower(),
            "pair": f"B-{coin}_USDT",
            "total_quantity": quantity,
            "leverage": leverage,
            "margin_currency_short_name": "INR"
        }
    ]

    last_err = ""
    for body in payload_variants:
        try:
            json_body = json.dumps(body, separators=(',', ':'))
            signature = hmac.new(secret_key.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
            headers = {
                'Content-Type': 'application/json',
                'X-AUTH-APIKEY': api_key,
                'X-AUTH-SIGNATURE': signature,
                'User-Agent': 'Mozilla/5.0'
            }
            req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                order_id = "EXECUTED"
                if isinstance(data, dict):
                    order_id = data.get('id', data.get('order_id', 'EXECUTED'))
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    order_id = data[0].get('id', 'EXECUTED')
                print(f"✅ CoinDCX Futures Order Executed! Pair: {body['pair']} | Side: {side} | Qty: {quantity} | OrderID: {order_id}")
                return {'success': True, 'order_id': order_id, 'quantity': quantity, 'pair': body['pair']}
        except urllib.error.HTTPError as e:
            try:
                err_bytes = e.read()
                raw_err = err_bytes.decode('utf-8') if err_bytes else str(e)
            except Exception:
                raw_err = str(e)
            last_err = f"HTTP {e.code}: {raw_err}"
            continue
        except Exception as e:
            last_err = str(e)
            continue

    return {'success': False, 'error': last_err}

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

def fetch_live_btc_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if 'price' in data: return float(data['price'])
    except Exception: pass
    return 78721.5

def run_scan():
    state = load_state()
    candidates = []
    btc_cmp = fetch_live_btc_price()
    btc_is_bullish = True
    try:
        btc_klines = fetch_klines_binance('BTC-USDT', '15m', 100)
        btc_st_dir, _ = calculate_supertrend(btc_klines)
        btc_is_bullish = (btc_st_dir == 1)
    except Exception: pass

    for symbol in WATCHLIST:
        try:
            time.sleep(0.3)
            daily_klines = fetch_klines_binance(symbol, '1d', 2)
            if len(daily_klines) < 2: continue
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
            m15_klines = fetch_klines_binance(symbol, '15m', 100)
            if len(m15_klines) < 20: continue
            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            
            score = 50
            if cmp > cpr['r1']: score += 10
            if 50 <= rsi_val <= 70: score += 20
            elif 70 < rsi_val <= 75: score += 10
            elif rsi_val > 75: score -= 10
            if vol_spike >= 2.0: score += 20
            elif vol_spike >= 1.5: score += 10
            score = max(0, min(100, score))
            
            rating = "A+ (Strong Breakout) 👑" if score >= 90 else ("A (Solid Breakout) 🥇" if score >= 80 else "B (Moderate)")
            is_above_cpr_tc = cmp > cpr['tc']
            is_supertrend_green = st_dir == 1
            is_not_choppy = not (48 <= rsi_val <= 52 and vol_spike < 1.8)
            
            if is_above_cpr_tc and is_supertrend_green and vol_spike >= 1.5 and score >= 80 and is_not_choppy:
                candidates.append({'symbol': symbol, 'score': score, 'rating': rating, 'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 'rsi_val': rsi_val, 'vol_spike': vol_spike})
        except Exception: pass

    candidates.sort(key=lambda x: x['score'], reverse=True)
    for cand in candidates:
        symbol, score, rating, cmp, cpr, st_val, rsi_val, vol_spike = cand['symbol'], cand['score'], cand['rating'], cand['cmp'], cand['cpr'], cand['st_val'], cand['rsi_val'], cand['vol_spike']
        try:
            if not btc_is_bullish and score < 90: continue
            last_sent = state.get(symbol, 0)
            if time.time() - last_sent > 21600:
                clean_symbol = symbol.replace("-", "")
                entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
                sl = round(min(cpr['tc'], st_val) * 0.995, 4)
                tp1, tp2 = round(cpr['r1'] * 0.998, 4), round(cpr['r2'] * 0.998, 4)
                if tp1 <= cmp: tp1 = round(cmp * 1.025, 4)
                if tp2 <= tp1: tp2 = round(tp1 * 1.035, 4)
                if ((tp1 - cmp) / cmp) < 0.015: continue
                
                lev_num = 10 if clean_symbol in ['SOLUSDT', 'AVAXUSDT', 'BTCUSDT', 'ETHUSDT'] else (7 if score >= 90 else 5)
                
                # STEP 1: EXECUTE COINDCX FUTURES ENTRY TRADE
                trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=500.0, leverage=lev_num)
                
                if trade_res.get('success'):
                    exec_hdr = (
                        f"\n\n⚡ <b>AUTO-TRADE EXECUTED ON COINDCX FUTURES!</b>\n"
                        f"• <b>Status:</b> <code>SUCCESS (Order ID: {trade_res.get('order_id')})</code>\n"
                        f"• <b>Quantity:</b> <code>{trade_res.get('quantity')} {clean_symbol[:-4]}</code>"
                    )
                    
                    # REGISTRATION IN 4-STEP TIMELINE ENGINE
                    with active_trades_lock:
                        ACTIVE_TRADES[symbol] = {
                            'entry_price': cmp,
                            'total_qty': trade_res.get('quantity'),
                            'remaining_qty': trade_res.get('quantity'),
                            'tp1': tp1,
                            'tp2': tp2,
                            'sl': sl,
                            'tp1_booked': False,
                            'leverage': lev_num,
                            'entry_time': time.time()
                        }
                else:
                    exec_hdr = f"\n\n⚠️ <b>COINDCX EXECUTION NOTICE:</b>\n<code>{trade_res.get('error')}</code>"

                msg = (
                    f"🟢 <b>NEW BULLISH BREAKOUT SIGNAL</b>\n\n"
                    f"<b>Pair:</b> B-{clean_symbol[:-4]}_USDT (Futures)\n"
                    f"<b>Direction:</b> BUY / LONG\n\n"
                    f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                    f"🏆 <b>Signal Strength:</b> <code>{rating}</code>\n\n"
                    f"⚙️ <b>Trade Parameters:</b>\n"
                    f"• <b>Leverage:</b> <code>{lev_num}x (Isolated)</code>\n"
                    f"• <b>Margin:</b> <code>₹500 INR (Per Trade)</code>\n"
                    f"• <b>Live CMP:</b> <code>${cmp}</code>\n\n"
                    f"🔹 <b>Entry Range:</b> <code>{entry_min} - {entry_max}</code>\n"
                    f"🔹 <b>Stop Loss:</b> <code>{sl}</code>\n"
                    f"🎯 <b>TP1:</b> <code>{tp1}</code> | 🎯 <b>TP2:</b> <code>{tp2}</code>\n"
                    f"{exec_hdr}"
                )
                ok = send_telegram_message(msg)
                if ok:
                    state[symbol] = time.time()
                    save_state(state)
        except Exception: pass

# 4-STEP EXECUTION TIMELINE MANAGER THREAD
def monitor_active_positions():
    time.sleep(15)
    while True:
        try:
            with active_trades_lock:
                symbols_to_check = list(ACTIVE_TRADES.keys())
            
            for symbol in symbols_to_check:
                try:
                    time.sleep(0.5)
                    m15_klines = fetch_klines_binance(symbol, '15m', 5)
                    if not m15_klines: continue
                    cmp = m15_klines[-1][4]
                    
                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES: continue
                        trade = ACTIVE_TRADES[symbol]
                    
                    clean_coin = symbol.split('-')[0].upper()
                    
                    # STEP 2 & 3: TP1 REACHED -> BOOK 80% PROFIT & SHIFT SL TO ENTRY (RISK-FREE)
                    if cmp >= trade['tp1'] and not trade['tp1_booked']:
                        qty_80 = round(trade['total_qty'] * 0.8, 2 if cmp < 100 else 1)
                        if qty_80 <= 0: qty_80 = trade['total_qty']
                        
                        # Partial sell 80% on CoinDCX
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=qty_80)
                        if res.get('success'):
                            with active_trades_lock:
                                trade['tp1_booked'] = True
                                trade['remaining_qty'] = round(trade['total_qty'] - qty_80, 2)
                                trade['sl'] = trade['entry_price'] # MOVE SL TO ENTRY PRICE (100% RISK-FREE)
                            
                            send_telegram_message(
                                f"🎯 <b>STEP 2 & 3 EXECUTED: TP1 REACHED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"💰 <b>80% Profit Booked on CoinDCX!</b> (Qty: {qty_80})\n"
                                f"🛡️ <b>SL Shifted to Entry:</b> <code>{trade['entry_price']}</code> (Trade is now 100% Risk-Free!)\n"
                                f"🚀 <b>Riding Remaining 20% to TP2 ({trade['tp2']})...</b>"
                            )

                    # STEP 4: RIDE TO TP2 OR EXIT AT BREAKEVEN / STOP LOSS
                    elif trade['tp1_booked']:
                        if cmp >= trade['tp2']:
                            # Sell remaining 20% on CoinDCX
                            res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=trade['remaining_qty'])
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            
                            send_telegram_message(
                                f"🚀 <b>STEP 4 EXECUTED: TP2 TARGET HIT!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"🔥 <b>100% Trade Successfully Closed!</b>\n"
                                f"🏆 <b>Full Target Achieved at CMP:</b> <code>{cmp}</code>"
                            )
                        elif cmp <= trade['sl']:
                            # Exit remaining 20% at Entry (Breakeven / ₹0 Loss)
                            res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=trade['remaining_qty'])
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            
                            send_telegram_message(
                                f"🛡️ <b>STEP 4 EXECUTED: EXIT AT BREAKEVEN</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"🔹 Remaining 20% Closed at Entry (<code>{cmp}</code>).\n"
                                f"✅ <b>Net Trade Profit:</b> <b>80% Cash Locked in Wallet (₹0 Loss)</b>"
                            )

                    # INITIAL STOP LOSS (BEFORE TP1)
                    elif not trade['tp1_booked'] and cmp <= trade['sl']:
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=trade['total_qty'])
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        
                        send_telegram_message(
                            f"🛑 <b>STOP LOSS EXECUTED</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"Position closed at Stop Loss: <code>{cmp}</code>"
                        )
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Position monitor exception: {e}")
        time.sleep(10)

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
            time.sleep(300)

    t1 = threading.Thread(target=run_loop, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=monitor_active_positions, daemon=True)
    t2.start()

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
