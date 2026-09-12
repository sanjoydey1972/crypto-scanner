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
    return "OK", 200

TOKEN = "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
CHAT_ID = "8938527650"
STATE_FILE = "scanner_state.json"

WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'ZEC-USDT', 
    'DASH-USDT', 'ZEN-USDT', 'LIT-USDT', 'BICO-USDT', 'PROM-USDT',
    'GRASS-USDT', 'SUI-USDT', 'DOGE-USDT', 'XRP-USDT', 'ADA-USDT', 
    'LINK-USDT', 'NEAR-USDT', 'FTM-USDT', 'DOT-USDT', 'LTC-USDT', 
    'PEPE-USDT', 'BCH-USDT', 'OP-USDT', 'ARB-USDT', 'APT-USDT', 
    'RENDER-USDT', 'INJ-USDT', 'STX-USDT', 'IMX-USDT', 'FIL-USDT', 
    'ATOM-USDT', 'ICP-USDT', 'MKR-USDT', 'UNI-USDT', 'FET-USDT', 
    'PYTH-USDT', 'ONDO-USDT', 'SEI-USDT', 'EGLD-USDT', '1000RATS-USDT',
    'TIA-USDT', 'WIF-USDT', 'FLOKI-USDT', 'BONK-USDT', 'SHIB-USDT',
    'JUP-USDT', 'ENA-USDT', 'W-USDT', 'ARKM-USDT', 'GALA-USDT',
    'SAND-USDT', 'MANA-USDT', 'THETA-USDT', 'JTO-USDT', 'STRK-USDT',
    'ORDI-USDT', 'ALT-USDT', 'ALGO-USDT', 'DYDX-USDT', 'AAVE-USDT',
    'RUNE-USDT', 'KAS-USDT', 'NOT-USDT', 'BLUR-USDT', 'PENDLE-USDT',
    'GMX-USDT', 'LDO-USDT', 'CRV-USDT', 'SNX-USDT', 'POL-USDT'
]

ctx = ssl._create_unverified_context()

def fetch_klines_kucoin(symbol, interval_str="15min", limit=100):
    url = f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol}&type={interval_str}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx) as resp:
        res_data = json.loads(resp.read().decode('utf-8'))
        raw_candles = res_data.get("data", [])
        candles = list(reversed(raw_candles))
        formatted = []
        for c in candles:
            formatted.append([int(c[0]), float(c[1]), float(c[3]), float(c[4]), float(c[2]), float(c[5])])
        return formatted[-limit:]

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

def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=500.0, leverage=5):
    api_key = os.environ.get("COINDCX_API_KEY", "").strip()
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
    try:
        coin = symbol.split('-')[0].upper()
        pair_name = f"B-{coin}_USDT"
        position_value_usdt = (margin_inr * leverage) / 88.5
        quantity = round(position_value_usdt / cmp, 4 if cmp > 1 else 6)
        if quantity <= 0: quantity = 1.0
        timestamp = int(round(time.time() * 1000))
        body = {
            "timestamp": timestamp,
            "order_type": "market_order",
            "side": side.lower(),
            "pair": pair_name,
            "total_quantity": quantity,
            "leverage": leverage,
            "notification": "no_notification",
            "margin_currency_short_name": ["INR"]
        }
        json_body = json.dumps(body, separators=(',', ':'))
        signature = hmac.new(secret_key.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
        url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
        headers = {'Content-Type': 'application/json', 'X-AUTH-APIKEY': api_key, 'X-AUTH-SIGNATURE': signature, 'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            order_id = data.get('id', data.get('order_id', 'EXECUTED'))
            return {'success': True, 'order_id': order_id, 'quantity': quantity, 'pair': pair_name}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8') if e.fp else str(e)
        return {'success': False, 'error': f"HTTP {e.code}: {err_msg}"}
    except Exception as e:
        return {'success': False, 'error': str(e)}

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
        url = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"
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
        btc_klines = fetch_klines_kucoin('BTC-USDT', '15min', 100)
        btc_st_dir, _ = calculate_supertrend(btc_klines)
        btc_is_bullish = (btc_st_dir == 1)
    except Exception: pass

    for symbol in WATCHLIST:
        try:
            time.sleep(0.3)
            daily_klines = fetch_klines_kucoin(symbol, '1day', 2)
            if len(daily_klines) < 2: continue
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
            m15_klines = fetch_klines_kucoin(symbol, '15min', 100)
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
                
                # EXECUTE COINDCX FUTURES TRADE
                trade_res = execute_coindcx_futures_trade(symbol=symbol, side="buy", cmp=cmp, margin_inr=500.0, leverage=lev_num)
                
                if trade_res.get('success'):
                    exec_hdr = f"\n\n⚡ <b>AUTO-TRADE EXECUTED ON COINDCX FUTURES!</b>\n• <b>Status:</b> <code>SUCCESS (Order ID: {trade_res.get('order_id')})</code>\n• <b>Quantity:</b> <code>{trade_res.get('quantity')} {clean_symbol[:-4]}</code>"
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
                    f"• <b>Margin:</b> <code>₹500 INR (Per Trade)</code>\n\n"
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

def run_loop():
    while True:
        try:
            if scan_lock.acquire(blocking=False):
                try: run_scan()
                finally: scan_lock.release()
        except Exception: pass
        time.sleep(300)

threading.Thread(target=run_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
