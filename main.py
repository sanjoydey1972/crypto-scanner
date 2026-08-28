import urllib.request
import urllib.parse
import json
import ssl
import os
import time
import threading
from datetime import datetime
from flask import Flask

# Start Flask Web Server
app = Flask(__name__)

@app.route('/')
def home():
    return "Scanner Bot is Active!"

# Settings
TOKEN = "8788523087:AAEn3_NMImvIUxf36NvmLC9BcHPVftHy-9c"
CHAT_ID = "8938527650"
STATE_FILE = "scanner_state.json"

# Top 40 Most Liquid and Reliable Assets
WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'ZEC-USDT', 
    'GRASS-USDT', 'SUI-USDT', 'DOGE-USDT', 'XRP-USDT', 'ADA-USDT', 
    'LINK-USDT', 'NEAR-USDT', 'FTM-USDT', 'DOT-USDT', 'LTC-USDT', 
    'WIF-USDT', 'PEPE-USDT', 'SHIB-USDT', 'BCH-USDT', 'OP-USDT', 
    'ARB-USDT', 'APT-USDT', 'RENDER-USDT', 'INJ-USDT', 'TIA-USDT', 
    'STX-USDT', 'IMX-USDT', 'FIL-USDT', 'ATOM-USDT', 'ICP-USDT', 
    'MKR-USDT', 'LDO-USDT', 'UNI-USDT', 'FET-USDT', 'JUP-USDT', 
    'PYTH-USDT', 'ONDO-USDT', 'SEI-USDT', 'BEAM-USDT', 'EGLD-USDT'
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
            formatted.append([
                int(c[0]),      # time
                float(c[1]),    # open
                float(c[3]),    # high
                float(c[4]),    # low
                float(c[2]),    # close
                float(c[5])     # volume
            ])
        return formatted[-limit:]

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * 13 + gains[i]) / 14
        avg_loss = (avg_loss * 13 + losses[i]) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_volume_spike(klines, period=20):
    volumes = [float(k[5]) for k in klines]
    current_vol = volumes[-1]
    avg_vol = sum(volumes[-period-1:-1]) / period
    if avg_vol == 0:
        return 1.0
    return current_vol / avg_vol

def calculate_cpr(high, low, close):
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = (pivot - bc) + pivot
    real_tc = max(tc, bc)
    real_bc = min(tc, bc)
    r1 = 2.0 * pivot - low
    r2 = pivot + (high - low)
    r3 = high + 2.0 * (pivot - low)
    return {'pivot': pivot, 'tc': real_tc, 'bc': real_bc, 'r1': r1, 'r2': r2, 'r3': r3}

def calculate_supertrend(klines, period=10, multiplier=3.0):
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    tr_list = []
    for i in range(len(klines)):
        if i == 0:
            tr_list.append(highs[i] - lows[i])
        else:
            tr_list.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    atr_list = []
    for i in range(len(tr_list)):
        if i < period - 1:
            atr_list.append(0.0)
        elif i == period - 1:
            atr_list.append(sum(tr_list[:period]) / period)
        else:
            atr_list.append((atr_list[-1] * (period - 1) + tr_list[i]) / period)
    st_val = [0.0] * len(klines)
    st_dir = [1] * len(klines)
    basic_ub = [0.0] * len(klines)
    basic_lb = [0.0] * len(klines)
    final_ub = [0.0] * len(klines)
    final_lb = [0.0] * len(klines)
    for i in range(len(klines)):
        hl2 = (highs[i] + lows[i]) / 2.0
        basic_ub[i] = hl2 + multiplier * atr_list[i]
        basic_lb[i] = hl2 - multiplier * atr_list[i]
        if i == 0:
            final_ub[i] = basic_ub[i]
            final_lb[i] = basic_lb[i]
            st_val[i] = basic_ub[i]
        else:
            if basic_ub[i] < final_ub[i-1] or closes[i-1] > final_ub[i-1]:
                final_ub[i] = basic_ub[i]
            else:
                final_ub[i] = final_ub[i-1]
            if basic_lb[i] > final_lb[i-1] or closes[i-1] < final_lb[i-1]:
                final_lb[i] = basic_lb[i]
            else:
                final_lb[i] = final_lb[i-1]
            if closes[i] > final_ub[i-1]:
                st_dir[i] = 1
            elif closes[i] < final_lb[i-1]:
                st_dir[i] = -1
            else:
                st_dir[i] = st_dir[i-1]
            if st_dir[i] == 1:
                st_val[i] = final_lb[i]
            else:
                st_val[i] = final_ub[i]
    return st_dir[-1], st_val[-1]

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8')).get('ok')
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return False

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

def run_scan():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting scanning cycle...")
    state = load_state()
    candidates = []
    
    # 1. Fetch BTC Trend (using KuCoin symbol BTC-USDT)
    try:
        btc_klines = fetch_klines_kucoin('BTC-USDT', '15min', 100)
        btc_st_dir, btc_st_val = calculate_supertrend(btc_klines)
        btc_is_bullish = (btc_st_dir == 1)
        print(f" -> BTC Trend (15m): {'BULLISH (GREEN)' if btc_is_bullish else 'BEARISH (RED)'}")
    except Exception as e:
        print(f"Error checking BTC trend: {e}")
        btc_is_bullish = True
        
    for symbol in WATCHLIST:
        try:
            # Add 300ms delay to respect exchange API rate limits
            time.sleep(0.3)
            
            # Daily CPR using KuCoin 1day candles
            daily_klines = fetch_klines_kucoin(symbol, '1day', 2)
            if len(daily_klines) < 2:
                continue
            yesterday = daily_klines[0]
            high_d, low_d, close_d = yesterday[2], yesterday[3], yesterday[4]
            cpr = calculate_cpr(high_d, low_d, close_d)
            
            # 15m Candles for Supertrend & CMP
            m15_klines = fetch_klines_kucoin(symbol, '15min', 100)
            if len(m15_klines) < 20:
                continue
            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            
            score = 50
            if cmp > cpr['r1']:
                score += 10
            if 50 <= rsi_val <= 70:
                score += 20
            elif 70 < rsi_val <= 75:
                score += 10
            elif rsi_val > 75:
                score -= 10
            if vol_spike >= 2.0:
                score += 20
            elif vol_spike >= 1.5:
                score += 10
            score = max(0, min(100, score))
            
            rating = "C (Low Confluence)"
            if score >= 90:
                rating = "A+ (Strong Breakout) 👑"
            elif score >= 80:
                rating = "A (Solid Breakout) 🥇"
            elif score >= 70:
                rating = "B (Moderate Breakout)"
            
            is_above_cpr_tc = cmp > cpr['tc']
            is_supertrend_green = st_dir == 1
            
            # Check Breakout Criteria (must have volume spike >= 1.5x)
            if is_above_cpr_tc and is_supertrend_green and vol_spike >= 1.5:
                candidates.append({
                    'symbol': symbol, 'score': score, 'rating': rating,
                    'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 'rsi_val': rsi_val, 'vol_spike': vol_spike
                })
        except Exception as e:
            print(f"Error scanning {symbol}: {e}")
            
    # Sort candidates by score descending and keep ONLY the best 4
    candidates.sort(key=lambda x: x['score'], reverse=True)
    top_candidates = candidates[:4]
    
    print(f"Found {len(candidates)} total breakout candidates. Dispatched top {len(top_candidates)}...")
    
    for cand in top_candidates:
        symbol, score, rating, cmp, cpr, st_val, rsi_val, vol_spike = cand['symbol'], cand['score'], cand['rating'], cand['cmp'], cand['cpr'], cand['st_val'], cand['rsi_val'], cand['vol_spike']
        try:
            if not btc_is_bullish:
                print(f"[SKIP] Skipping {symbol} alert because BTC trend is BEARISH.")
                continue
            last_sent = state.get(symbol, 0)
            if time.time() - last_sent > 21600:
                clean_symbol = symbol.replace("-", "")
                entry_min = round(cmp * 0.998, 4 if cmp > 1 else 6)
                entry_max = round(cmp * 1.001, 4 if cmp > 1 else 6)
                sl_level = min(cpr['tc'], st_val)
                sl = round(sl_level * 0.995, 4 if cmp > 1 else 6)
                tp1 = round(cpr['r1'] * 0.998, 4 if cmp > 1 else 6)
                tp2 = round(cpr['r2'] * 0.998, 4 if cmp > 1 else 6)
                if tp1 <= cmp:
                    tp1 = round(cmp * 1.025, 4 if cmp > 1 else 6)
                if tp2 <= tp1:
                    tp2 = round(tp1 * 1.035, 4 if cmp > 1 else 6)
                    
                # Dynamic Leverage logic: 10x for majors, 5x for volatile/others
                if clean_symbol in ['SOLUSDT', 'AVAXUSDT', 'BTCUSDT', 'ETHUSDT']:
                    leverage_val = "10x (Isolated)"
                else:
                    leverage_val = "5x (Isolated)"
                
                msg = (
                    f"🟢 <b>NEW BULLISH BREAKOUT SIGNAL</b>\n\n"
                    f"<b>Pair:</b> B-{clean_symbol[:-4]}_USDT (Futures)\n"
                    f"<b>Direction:</b> BUY / LONG\n\n"
                    f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                    f"🏆 <b>Signal Strength:</b> <code>{rating}</code>\n\n"
                    f"⚙️ <b>Trade Parameters:</b>\n"
                    f"• <b>Recommended Leverage:</b> <code>{leverage_val}</code>\n"
                    f"• <b>Recommended Margin:</b> <code>₹500 INR (Per Trade)</code>\n\n"
                    f"🔹 <b>Entry Price Range:</b> <code>{entry_min} - {entry_max}</code>\n"
                    f"🔹 <b>Stop Loss (SL):</b> <code>{sl}</code>\n"
                    f"🎯 <b>Take Profit 1 (TP1):</b> <code>{tp1}</code> (Near R1)\n"
                    f"🎯 <b>Take Profit 2 (TP2):</b> <code>{tp2}</code> (Near R2)\n\n"
                    f"📊 <b>Confluence Indicators:</b>\n"
                    f"• Price holds above Daily CPR TC (<code>{cpr['tc']:.4f}</code>)\n"
                    f"• 15m Supertrend is GREEN support (<code>{st_val:.4f}</code>)\n"
                    f"• 15m RSI is <code>{rsi_val:.1f}</code>\n"
                    f"• 15m Volume Spike is <code>{vol_spike:.2f}x</code>\n"
                    f"• Current CMP is <code>{cmp:.4f}</code>"
                )
                print(f"BREAKOUT TRIGGERED FOR {symbol}! Sending Telegram signal...")
                ok = send_telegram_message(msg)
                if ok:
                    state[symbol] = time.time()
                    save_state(state)
        except Exception as e:
            print(f"Error processing signal for {symbol}: {e}")

def run_loop():
    print("Scanner loop running...")
    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(900)

# Start background scanning thread
threading.Thread(target=run_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
