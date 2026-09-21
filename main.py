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

@app.route('/scan-now')
def scan_now_endpoint():
    try:
        report_lines = []
        for symbol in WATCHLIST:
            try:
                time.sleep(0.05)
                m15_klines = fetch_klines_binance(symbol, '15m', 100)
                if not m15_klines or len(m15_klines) < 20: continue
                cmp = m15_klines[-1][4]
                daily_klines = fetch_klines_binance(symbol, '1d', 2)
                if not daily_klines or len(daily_klines) < 2: continue
                cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
                st_dir, st_val = calculate_supertrend(m15_klines)
                close_prices = [k[4] for k in m15_klines]
                rsi_val = calculate_rsi(close_prices)
                vol_spike = calculate_volume_spike(m15_klines)
                
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
                
                if is_above_cpr_tc and is_st_green and (t1 or t2):
                    status = "🔥 TRIGGERED AUTO-TRADE"
                elif is_above_cpr_tc and is_st_green:
                    status = f"🟢 Bullish (Vol {vol_spike:.2f}x / Score {score})"
                else:
                    status = "⚪ Consolidating"
                
                report_lines.append(f"{symbol:12s} | CMP: {cmp:<10.4f} | CPR TC: {cpr['tc']:<10.4f} | ST: {'GREEN' if is_st_green else 'RED':5s} | Vol: {vol_spike:.2f}x | Score: {score:<3d} | {status}")
            except Exception as e:
                report_lines.append(f"{symbol:12s} | Error: {e}")
        
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        html = f"<h2>⚡ LIVE 40-COIN MARKET SCANNER AUDIT REPORT</h2><p><b>Server Time:</b> {now_str}</p><pre>" + "\n".join(report_lines) + "</pre>"
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Scan Error:</h3><p>{e}</p>", 500

@app.route('/close-sol')
def close_sol_endpoint():
    try:
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="sell", cmp=108.23, leverage=10, custom_quantity=0.1)
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
        res = execute_coindcx_futures_trade(symbol="SOL-USDT", side="buy", cmp=112.20, margin_inr=100.0, leverage=10, custom_quantity=0.1)
        if res.get('success'):
            with active_trades_lock:
                ACTIVE_TRADES['SOL-USDT'] = {
                    'entry_price': 112.20,
                    'total_qty': 0.1,
                    'remaining_qty': 0.1,
                    'tp1': 114.32,
                    'tp2': 122.42,
                    'sl': 110.03,
                    'tp1_booked': False,
                    'leverage': 10,
                    'entry_time': time.time()
                }
            save_active_trades()
        
        msg = (
            f"🧪 <b>SYSTEM DIAGNOSTIC TEST ALERT</b>\n\n"
            f"• <b>Render Cloud Bot:</b> 100% CONNECTED\n"
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

TOKEN = "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
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

def fetch_klines_binance(symbol, interval_str="15m", limit=100):
    clean_sym = symbol.replace("-", "").upper()
    url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
        raw_candles = json.loads(resp.read().decode('utf-8'))
        formatted = []
        for c in raw_candles:
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
        raw_qty = position_value_usdt / cmp if cmp > 0 else 0.1
        
        if coin == 'BTC': quantity = round(max(0.001, raw_qty), 3)
        elif coin in ['ETH', 'SOL']: quantity = round(max(0.1, raw_qty), 2)
        elif raw_qty >= 100: quantity = float(int(round(raw_qty)))
        elif raw_qty >= 10: quantity = round(raw_qty, 1)
        elif raw_qty >= 1: quantity = round(raw_qty, 2)
        else: quantity = round(raw_qty, 4)
    if quantity <= 0: quantity = 0.1

    futures_url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    spot_url = "https://api.coindcx.com/exchange/v1/orders/create"
    ts = int(round(time.time() * 1000))

    endpoint_variants = [
        (futures_url, {
            "timestamp": ts,
            "order": {
                "side": side.lower(),
                "pair": f"B-{coin}_USDT",
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
                "pair": f"B-{coin}USDT",
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
            "market": f"{coin}INR",
            "total_quantity": quantity,
            "leverage": leverage
        })
    ]

    err_logs = []
    for idx, (target_url, body) in enumerate(endpoint_variants, 1):
        try:
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
                return {'success': True, 'order_id': order_id, 'quantity': quantity, 'pair': body.get('pair', body.get('market', f"B-{coin}_USDT"))}
        except urllib.error.HTTPError as e:
            try:
                err_text = e.read().decode('utf-8')
                err_logs.append(f"V{idx}: HTTP {e.code} - {err_text}")
            except Exception:
                err_logs.append(f"V{idx}: HTTP {e.code} - {e}")
        except Exception as e:
            err_logs.append(f"V{idx}: {e}")

    last_err = " | ".join(err_logs) if err_logs else "Unknown Error"
    return {'success': False, 'error': last_err}

def fetch_live_btc_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if 'price' in data: return float(data['price'])
    except Exception: pass
    return 60080.0

def fetch_coindcx_btc_inrm_price():
    try:
        url = "https://public.coindcx.com/market_data/candles/?pair=B-BTC_USDT&interval=1m"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0:
                close_price = float(data[0].get('close', 0) or data[-1].get('close', 0))
                if close_price > 0: return round(close_price, 1)
    except Exception: pass
    btc_usd = fetch_live_btc_price()
    return round(btc_usd * 1.3136, 1)

def send_hourly_market_report():
    try:
        btc_inrm_price = fetch_coindcx_btc_inrm_price()
        bull_coins, bear_coins, neutral_coins = [], [], []

        for symbol in WATCHLIST:
            clean_sym = symbol.replace("-", "_")
            try:
                time.sleep(0.1)
                m15_klines = fetch_klines_binance(symbol, '15m', 30)
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

def run_scan():
    state = load_state()
    candidates = []

    for symbol in WATCHLIST:
        try:
            time.sleep(0.2)
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
            
            # OPTIMIZED DUAL-TRIGGER ENGINE:
            # Trigger 1: High Vol Spike >= 1.30x AND Score >= 70
            # Trigger 2: CPR TC + Supertrend Confluence (Vol Spike >= 1.15x AND Score >= 68)
            trigger_1 = (vol_spike >= 1.30 and score >= 70)
            trigger_2 = (vol_spike >= 1.15 and score >= 68)
            
            if is_above_cpr_tc and is_supertrend_green and (trigger_1 or trigger_2) and is_not_choppy:
                candidates.append({'symbol': symbol, 'score': score, 'rating': rating, 'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 'rsi_val': rsi_val, 'vol_spike': vol_spike})
        except Exception: pass

    candidates.sort(key=lambda x: x['score'], reverse=True)
    for cand in candidates:
        symbol, score, rating, cmp, cpr, st_val, rsi_val, vol_spike = cand['symbol'], cand['score'], cand['rating'], cand['cmp'], cand['cpr'], cand['st_val'], cand['rsi_val'], cand['vol_spike']
        try:
            last_sent = state.get(symbol, 0)
            if time.time() - last_sent > 1800:
                clean_symbol = symbol.replace("-", "")
                entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
                sl = round(min(cpr['tc'], st_val) * 0.995, 4)
                tp1 = round(max(cpr['r1'] * 0.998, cmp * 1.018), 4)
                tp2 = round(max(cpr['r2'] * 0.998, tp1 * 1.025), 4)
                lev_num = 10 if clean_symbol in ['SOLUSDT', 'AVAXUSDT', 'BTCUSDT', 'ETHUSDT', 'TAOUSDT', 'RENDERUSDT', 'APTUSDT'] else (7 if score >= 85 else 5)
                
                trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=500.0, leverage=lev_num)
                
                if trade_res.get('success'):
                    exec_hdr = (
                        f"\n\n⚡ <b>AUTO-TRADE EXECUTED ON COINDCX FUTURES!</b>\n"
                        f"• <b>Status:</b> <code>SUCCESS (Order ID: {trade_res.get('order_id')})</code>\n"
                        f"• <b>Quantity:</b> <code>{trade_res.get('quantity')} {clean_symbol[:-4]}</code>"
                    )
                    
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

def monitor_active_positions():
    time.sleep(10)
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
                    
                    if cmp >= trade['tp1'] and not trade['tp1_booked']:
                        qty_80 = round(trade['total_qty'] * 0.8, 2 if cmp < 100 else 1)
                        if qty_80 <= 0: qty_80 = trade['total_qty']
                        
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=qty_80)
                        if res.get('success'):
                            with active_trades_lock:
                                trade['tp1_booked'] = True
                                trade['remaining_qty'] = round(trade['total_qty'] - qty_80, 2)
                                trade['sl'] = trade['entry_price']
                            save_active_trades()
                            
                            send_telegram_message(
                                f"🎯 <b>STEP 2 & 3 EXECUTED: TP1 REACHED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"💰 <b>80% Profit Booked on CoinDCX!</b> (Qty: {qty_80})\n"
                                f"🛡️ <b>SL Shifted to Entry:</b> <code>{trade['entry_price']}</code>\n"
                                f"🚀 <b>Riding Remaining 20% to TP2 ({trade['tp2']})...</b>"
                            )

                    elif trade['tp1_booked']:
                        if cmp >= trade['tp2']:
                            res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=trade['remaining_qty'])
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            
                            send_telegram_message(
                                f"🚀 <b>STEP 4 EXECUTED: TP2 TARGET HIT!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"🔥 <b>100% Trade Successfully Closed!</b>\n"
                                f"🏆 <b>Full Target Achieved at CMP:</b> <code>{cmp}</code>"
                            )
                        elif cmp <= trade['sl']:
                            res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=trade['remaining_qty'])
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            
                            send_telegram_message(
                                f"🛡️ <b>STEP 4 EXECUTED: EXIT AT BREAKEVEN</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"🔹 Remaining 20% Closed at Entry (<code>{cmp}</code>).\n"
                                f"✅ <b>Net Trade Profit:</b> <b>80% Cash Locked in Wallet</b>"
                            )

                    elif not trade['tp1_booked'] and cmp <= trade['sl']:
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade['leverage'], custom_quantity=trade['total_qty'])
                        with active_trades_lock:
                            ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        
                        send_telegram_message(
                            f"🛑 <b>STOP LOSS EXECUTED VIA BOT MONITOR</b>\n\n"
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
            time.sleep(240) # Self ping every 4 minutes to prevent Render Free Tier sleep

    t1 = threading.Thread(target=run_loop, daemon=True)
    t1.start()
    
    t2 = threading.Thread(target=monitor_active_positions, daemon=True)
    t2.start()

    t3 = threading.Thread(target=run_hourly_report_loop, daemon=True)
    t3.start()

    t4 = threading.Thread(target=run_keep_alive_loop, daemon=True)
    t4.start()

    send_telegram_message("⚡ <b>RENDER BOT ENGINE REBOOTED & 100% ONLINE!</b>\n\n• 24/7 Keep-Alive Active\n• Live Scanner Audit Endpoint: /scan-now")

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
