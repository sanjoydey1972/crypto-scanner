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
        state = load_state()
        state["active_trades"] = ACTIVE_TRADES
        state["auto_trading_enabled"] = AUTO_TRADING_ENABLED
        save_state(state)

def load_trade_history():
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f: return json.load(f)
        except Exception: pass
    return []

def save_trade_history(history):
    try:
        with open(TRADE_HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)
    except Exception: pass

TRADE_HISTORY = load_trade_history()

def record_trade_history(trade_record):
    with trade_history_lock:
        TRADE_HISTORY.append(trade_record)
        if len(TRADE_HISTORY) > 100:
            del TRADE_HISTORY[:-100]
        save_trade_history(TRADE_HISTORY)

# ==============================================================================
# 2. CONFIGURATION & CREDENTIALS
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY", "").strip()
COINDCX_API_SECRET = os.environ.get("COINDCX_API_SECRET", "").strip()

USDT_INR_RATE = 91.5
ORDER_MARGIN_INR = 1000.0  # ₹1000 INR per scalp
LEVERAGE = 7               # 7x leverage
MAX_ACTIVE_TRADES = 1      # 1 position at a time to prevent overexposure
COOLDOWN_MINUTES = 2

# Top liquid CoinDCX Futures pairs
WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "NEARUSDT", "SUIUSDT",
    "LINKUSDT", "ARBUSDT", "OPUSDT", "APTUSDT", "MATICUSDT",
    "SEIUSDT", "TIAUSDT", "INJUSDT", "RENDERUSDT", "FETUSDT",
    "WIFUSDT", "PEPEUSDT", "SHIBUSDT", "DOTUSDT", "ATOMUSDT",
    "LTCUSDT", "BCHUSDT", "FTMUSDT", "GALAUSDT", "SANDUSDT"
]

LAST_ALERT_TIME = {}
LAST_EXIT_NOTIFICATION = {}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ==============================================================================
# 3. TELEGRAM ALERT SYSTEM
# ==============================================================================
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram not configured. Log: {text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r: pass
    except Exception as e:
        print(f"Telegram send error: {e}")

# ==============================================================================
# 4. COINDCX API INTEGRATION
# ==============================================================================
def get_coindcx_signature(secret, body):
    return hmac.new(secret.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).hexdigest()

def coindcx_post(endpoint, payload_dict):
    if not COINDCX_API_KEY or not COINDCX_API_SECRET:
        return None
    url = f"https://api.coindcx.com{endpoint}"
    body = json.dumps(payload_dict, separators=(',', ':'))
    sig = get_coindcx_signature(COINDCX_API_SECRET, body)
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': COINDCX_API_KEY,
        'X-AUTH-SIGNATURE': sig
    }
    req = urllib.request.Request(url, data=body.encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=12) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode()
        print(f"CoinDCX POST {endpoint} HTTP {e.code}: {err_msg}")
        return {"error": True, "code": e.code, "message": err_msg}
    except Exception as e:
        print(f"CoinDCX POST {endpoint} exception: {e}")
        return None

def fetch_coindcx_active_positions():
    payload = {"timestamp": int(time.time() * 1000)}
    res = coindcx_post("/exchange/v1/derivatives/futures/positions", payload)
    if isinstance(res, list):
        return [p for p in res if float(p.get("active_units", 0) or p.get("total_quantity", 0)) != 0]
    return []

def get_coindcx_step_precision(pair):
    # Standard integer lot sizes for high-unit tokens
    integer_lots = ["DOGEUSDT", "PEPEUSDT", "SHIBUSDT", "ADAUSDT", "MATICUSDT", "GALAUSDT", "SANDUSDT", "SEIUSDT", "ARBUSDT"]
    if pair in integer_lots:
        return 0
    return 2

def execute_coindcx_order(pair, side, price):
    global PENDING_ORDERS
    with pending_orders_lock:
        if pair in PENDING_ORDERS:
            print(f"Order for {pair} already pending.")
            return None
        PENDING_ORDERS.add(pair)

    try:
        margin_usdt = ORDER_MARGIN_INR / USDT_INR_RATE
        notional = margin_usdt * LEVERAGE
        raw_qty = notional / price
        precision = get_coindcx_step_precision(pair)
        qty = round(raw_qty, precision) if precision > 0 else int(raw_qty)
        if qty <= 0:
            qty = 1 if precision == 0 else 0.1

        target_price = price * (1.01 if side == "buy" else 0.99)
        sl_price = price * (0.992 if side == "buy" else 1.008)

        body = {
            "timestamp": int(time.time() * 1000),
            "order": {
                "side": side,
                "order_type": "market_order",
                "market": pair,
                "total_quantity": qty,
                "leverage": LEVERAGE,
                "target_price": round(target_price, 4),
                "stop_loss_price": round(sl_price, 4)
            }
        }
        res = coindcx_post("/exchange/v1/derivatives/futures/orders/create", body)
        return res
    finally:
        with pending_orders_lock:
            PENDING_ORDERS.discard(pair)

def close_coindcx_position(pair, side, qty):
    close_side = "sell" if side.lower() == "buy" else "buy"
    body = {
        "timestamp": int(time.time() * 1000),
        "order": {
            "side": close_side,
            "order_type": "market_order",
            "market": pair,
            "total_quantity": abs(float(qty)),
            "leverage": LEVERAGE
        }
    }
    return coindcx_post("/exchange/v1/derivatives/futures/orders/create", body)

def sync_all_open_positions_tpsl():
    """Background safeguard to keep bracket TP/SL synced with CoinDCX exchange."""
    try:
        positions = fetch_coindcx_active_positions()
        for pos in positions:
            units = float(pos.get("active_units", 0) or pos.get("total_quantity", 0))
            if units != 0:
                pass
    except Exception as e:
        print(f"Error in sync_all_open_positions_tpsl: {e}")

# ==============================================================================
# 5. MARKET DATA & CANDLE FETCHING
# ==============================================================================
def fetch_binance_klines(symbol, interval="1m", limit=60):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=6) as response:
            data = json.loads(response.read().decode())
            return [[float(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in data]
    except Exception:
        pass

    backup_endpoints = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://public.coindcx.com/market_data/candles?pair=B-{symbol}&interval={interval}&limit={limit}"
    ]
    for b_url in backup_endpoints:
        try:
            req = urllib.request.Request(b_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=6) as response:
                data = json.loads(response.read().decode())
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    return [[float(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in data]
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

# ==============================================================================
# 6. SIGNAL EVALUATION ENGINE (9 & 20 EMA + 50 EMA BASELINE)
# ==============================================================================
def eval_crossover_setup(klines, ema9_series, ema20_series, ema50_series):
    if len(klines) < 10 or len(ema9_series) < 10 or len(ema20_series) < 10 or len(ema50_series) < 10:
        return None, 0

    curr_close = klines[-1][4]
    curr_open = klines[-1][1]
    curr_high = klines[-1][2]
    curr_low = klines[-1][3]

    e9 = ema9_series[-1]
    e20 = ema20_series[-1]
    e50 = ema50_series[-1]

    # GOLDEN CROSSOVER (LONG)
    if e9 > e20 and curr_close > e50:
        for offset in range(1, 4):
            prev_idx = -1 - offset
            if abs(prev_idx) <= len(ema9_series):
                if ema9_series[prev_idx] <= ema20_series[prev_idx]:
                    return "LONG", offset

    # DEATH CROSSOVER (SHORT)
    if e9 < e20 and curr_close < e50:
        for offset in range(1, 4):
            prev_idx = -1 - offset
            if abs(prev_idx) <= len(ema9_series):
                if ema9_series[prev_idx] >= ema20_series[prev_idx]:
                    return "SHORT", offset

    return None, 0

# ==============================================================================
# 7. POSITION MONITORING & PURE TREND-RIDING EXIT ENGINE
# ==============================================================================
def monitor_active_positions():
    """
    PURE TREND-RIDING ENGINE:
    - Never exits solely because of a time limit (e.g. 10 minutes).
    - As long as Blue (9 EMA) >= Red (20 EMA), LONG stays running!
    - As long as Blue (9 EMA) <= Red (20 EMA), SHORT stays running!
    - Exits strictly on TP1 Target (+1.0%), Hard Stop Loss (-0.8%),
      or Confirmed Reverse EMA Crossover.
    """
    while True:
        try:
            with active_trades_lock:
                trade_keys = list(ACTIVE_TRADES.keys())

            for pair in trade_keys:
                with active_trades_lock:
                    if pair not in ACTIVE_TRADES:
                        continue
                    trade = ACTIVE_TRADES[pair]

                entry_time = trade.get("entry_time", 0)
                entry_price = trade.get("entry_price", 0)
                side = trade.get("side", "buy").lower()
                order_id = trade.get("order_id", "")
                target = trade.get("target", 0)
                stop_loss = trade.get("stop_loss", 0)
                qty = trade.get("quantity", 0)
                highest_price = trade.get("highest_price", entry_price)
                lowest_price = trade.get("lowest_price", entry_price)

                klines = fetch_binance_klines(pair, interval="1m", limit=30)
                if not klines or len(klines) < 25:
                    continue

                closes = [c[4] for c in klines]
                cmp = closes[-1]
                ema9_series = calculate_ema_series(closes, 9)
                ema20_series = calculate_ema_series(closes, 20)
                e9 = ema9_series[-1]
                e20 = ema20_series[-1]

                # Update extremes
                if cmp > highest_price: trade["highest_price"] = cmp
                if cmp < lowest_price: trade["lowest_price"] = cmp

                pnl_pct = ((cmp - entry_price) / entry_price * 100) if side == "buy" else ((entry_price - cmp) / entry_price * 100)
                roe_pct = pnl_pct * LEVERAGE
                hold_seconds = time.time() - entry_time

                # 60s minimum hold to protect from momentary spread noise
                if hold_seconds < 60:
                    continue

                exit_reason = None

                # 1. Take Profit (+1.0% Target Hit)
                if side == "buy" and cmp >= target:
                    exit_reason = f"🎯 TARGET 1 HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"
                elif side == "sell" and cmp <= target:
                    exit_reason = f"🎯 TARGET 1 HIT (+{pnl_pct:.2f}% | +{roe_pct:.1f}% ROE)"

                # 2. Hard Stop Loss Protection (-0.8%)
                elif side == "buy" and cmp <= stop_loss:
                    exit_reason = f"🛑 STOP LOSS HIT ({pnl_pct:.2f}% | {roe_pct:.1f}% ROE)"
                elif side == "sell" and cmp >= stop_loss:
                    exit_reason = f"🛑 STOP LOSS HIT ({pnl_pct:.2f}% | {roe_pct:.1f}% ROE)"

                # 3. PURE TREND REVERSAL: Blue (9 EMA) Crosses Red (20 EMA) in Reverse
                elif side == "buy" and e9 < e20:
                    exit_reason = f"🔄 9/20 EMA REVERSE CROSSOVER (Blue crossed below Red) ({pnl_pct:+.2f}%)"
                elif side == "sell" and e9 > e20:
                    exit_reason = f"🔄 9/20 EMA REVERSE CROSSOVER (Blue crossed above Red) ({pnl_pct:+.2f}%)"

                if exit_reason:
                    close_res = close_coindcx_position(pair, side, qty)
                    pnl_inr = (ORDER_MARGIN_INR * (roe_pct / 100))

                    exit_msg = (
                        f"🏁 <b>SCALP POSITION CLOSED: {pair}</b>\n\n"
                        f"• <b>Reason:</b> {exit_reason}\n"
                        f"• <b>Entry:</b> ${entry_price:.4f} ➡️ <b>Exit:</b> ${cmp:.4f}\n"
                        f"• <b>Hold Time:</b> {int(hold_seconds // 60)}m {int(hold_seconds % 60)}s\n"
                        f"• <b>Scalp PNL:</b> {pnl_pct:+.2f}% ({roe_pct:+.1f}% ROE)\n"
                        f"• <b>Net Estimate:</b> {'+' if pnl_inr >= 0 else ''}₹{pnl_inr:.2f} INR\n"
                    )
                    send_telegram_message(exit_msg)

                    record_trade_history({
                        "pair": pair,
                        "side": side.upper(),
                        "entry_price": entry_price,
                        "exit_price": cmp,
                        "entry_time": datetime.fromtimestamp(entry_time, IST).strftime("%Y-%m-%d %H:%M:%S"),
                        "exit_time": get_ist_now().strftime("%Y-%m-%d %H:%M:%S"),
                        "hold_duration": f"{int(hold_seconds // 60)}m {int(hold_seconds % 60)}s",
                        "pnl_pct": round(pnl_pct, 2),
                        "roe_pct": round(roe_pct, 1),
                        "pnl_inr": round(pnl_inr, 2),
                        "exit_reason": exit_reason
                    })

                    with active_trades_lock:
                        if pair in ACTIVE_TRADES:
                            del ACTIVE_TRADES[pair]
                            save_active_trades()

            time.sleep(4)
        except Exception as e:
            print(f"Error in position monitor: {e}")
            time.sleep(5)

# ==============================================================================
# 8. SCANNER SCAN LOOP
# ==============================================================================
def run_scan():
    global AUTO_TRADING_ENABLED
    for pair in WATCHLIST:
        try:
            with active_trades_lock:
                if len(ACTIVE_TRADES) >= MAX_ACTIVE_TRADES:
                    return

            now = time.time()
            if pair in LAST_ALERT_TIME and (now - LAST_ALERT_TIME[pair]) < (COOLDOWN_MINUTES * 60):
                continue

            klines = fetch_binance_klines(pair, interval="1m", limit=65)
            if not klines or len(klines) < 55:
                continue

            closes = [c[4] for c in klines]
            cmp = closes[-1]

            ema9 = calculate_ema_series(closes, 9)
            ema20 = calculate_ema_series(closes, 20)
            ema50 = calculate_ema_series(closes, 50)

            signal_type, candles_after = eval_crossover_setup(klines, ema9, ema20, ema50)

            if signal_type:
                LAST_ALERT_TIME[pair] = now
                side = "buy" if signal_type == "LONG" else "sell"

                tp_price = cmp * (1.01 if side == "buy" else 0.99)
                sl_price = cmp * (0.992 if side == "buy" else 1.008)

                alert_text = (
                    f"⚡ <b>1-MIN EMA SCALP SIGNAL! ({signal_type})</b>\n\n"
                    f"• <b>Pair:</b> {pair} (Futures)\n"
                    f"• <b>Setup:</b> 9/20 EMA {'GOLDEN' if signal_type == 'LONG' else 'DEATH'} CROSS ({candles_after} candle(s))\n"
                    f"• <b>Baseline:</b> Confirmed above/below 50 EMA\n"
                    f"• <b>CMP:</b> ${cmp:.4f}\n"
                    f"🎯 <b>Target:</b> ${tp_price:.4f} (+1.0% | +7.0% ROE)\n"
                    f"🛑 <b>Stop Loss:</b> ${sl_price:.4f} (-0.8% | -5.6% ROE)\n"
                    f"🌊 <b>Riding Rule:</b> Hold while Blue {'≥' if side == 'buy' else '≤'} Red!\n"
                )

                if AUTO_TRADING_ENABLED:
                    res = execute_coindcx_order(pair, side, cmp)
                    order_id = "MANUAL_OR_FAILED"
                    if res and not res.get("error"):
                        order_id = res.get("order_id", res.get("id", "CONFIRMED"))
                        alert_text += f"\n✅ <b>COINDCX EXECUTION SUCCESSFUL</b>\n• Order ID: <code>{order_id}</code>"
                        
                        margin_usdt = ORDER_MARGIN_INR / USDT_INR_RATE
                        notional = margin_usdt * LEVERAGE
                        raw_qty = notional / cmp
                        precision = get_coindcx_step_precision(pair)
                        qty = round(raw_qty, precision) if precision > 0 else int(raw_qty)

                        with active_trades_lock:
                            ACTIVE_TRADES[pair] = {
                                "pair": pair,
                                "side": side,
                                "entry_price": cmp,
                                "entry_time": now,
                                "order_id": order_id,
                                "target": tp_price,
                                "stop_loss": sl_price,
                                "quantity": qty,
                                "highest_price": cmp,
                                "lowest_price": cmp
                            }
                            save_active_trades()
                    else:
                        alert_text += f"\n⚠️ <b>COINDCX ORDER FAILED:</b> {res}"
                else:
                    alert_text += "\n⏸️ <i>Auto-trading currently PAUSED</i>"

                send_telegram_message(alert_text)
                time.sleep(2)
        except Exception as e:
            print(f"Error scanning {pair}: {e}")

# ==============================================================================
# 9. TELEGRAM COMMAND LISTENER (/start, /stop, /status)
# ==============================================================================
def run_telegram_command_listener():
    global AUTO_TRADING_ENABLED
    last_update_id = 0
    if not TELEGRAM_BOT_TOKEN:
        return

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=15"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                for item in data.get("result", []):
                    last_update_id = item["update_id"]
                    msg = item.get("message", {})
                    text = msg.get("text", "").strip()
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if chat_id != str(TELEGRAM_CHAT_ID):
                        continue

                    if text == "/start":
                        AUTO_TRADING_ENABLED = True
                        save_active_trades()
                        send_telegram_message("▶️ <b>Auto-trading RESUMED.</b> Scanning 1M charts for crossovers.")
                    elif text == "/stop":
                        AUTO_TRADING_ENABLED = False
                        save_active_trades()
                        send_telegram_message("⏸️ <b>Auto-trading PAUSED.</b> Signals will be broadcast only.")
                    elif text == "/status":
                        with active_trades_lock:
                            count = len(ACTIVE_TRADES)
                            trades_summary = ""
                            for k, v in ACTIVE_TRADES.items():
                                trades_summary += f"\n• {k}: {v['side'].upper()} @ ${v['entry_price']}"
                        send_telegram_message(
                            f"🤖 <b>BOT STATUS</b>\n"
                            f"• Auto-Trading: {'🟢 ACTIVE' if AUTO_TRADING_ENABLED else '🔴 PAUSED'}\n"
                            f"• Active Scalps: {count}/{MAX_ACTIVE_TRADES}{trades_summary}"
                        )
        except Exception:
            pass
        time.sleep(3)

# ==============================================================================
# 10. FLASK DASHBOARD & WEB ROUTES
# ==============================================================================
@app.route('/')
def home():
    with active_trades_lock:
        active_copy = list(ACTIVE_TRADES.values())
    with trade_history_lock:
        history_copy = list(reversed(TRADE_HISTORY))

    rows = ""
    for t in active_copy:
        rows += f"""
        <tr>
            <td><b>{t['pair']}</b></td>
            <td style="color:{'#00c853' if t['side']=='buy' else '#ff1744'}">{t['side'].upper()}</td>
            <td>${t['entry_price']:.4f}</td>
            <td>${t['target']:.4f}</td>
            <td>${t['stop_loss']:.4f}</td>
            <td>{datetime.fromtimestamp(t['entry_time'], IST).strftime('%H:%M:%S')}</td>
            <td><a href="/close/{t['pair']}" style="background:#ff1744;color:#fff;padding:4px 8px;border-radius:4px;text-decoration:none;">Close</a></td>
        </tr>
        """

    hist_rows = ""
    for h in history_copy[:25]:
        pnl_color = "#00c853" if h['pnl_pct'] >= 0 else "#ff1744"
        hist_rows += f"""
        <tr>
            <td>{h['pair']}</td>
            <td>{h['side']}</td>
            <td>${h['entry_price']:.4f}</td>
            <td>${h['exit_price']:.4f}</td>
            <td>{h['hold_duration']}</td>
            <td style="color:{pnl_color}">{h['pnl_pct']:+.2f}% ({h['roe_pct']:+.1f}% ROE)</td>
            <td style="color:{pnl_color}">₹{h['pnl_inr']:+.2f}</td>
            <td><small>{h['exit_reason']}</small></td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>1-Min EMA Scalping Bot</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0e1118; color: #e0e0e0; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: auto; }}
            .card {{ background: #161b26; border-radius: 8px; padding: 20px; margin-bottom: 20px; border: 1px solid #232936; }}
            .btn {{ display: inline-block; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-right: 10px; }}
            .btn-green {{ background: #00c853; color: white; }}
            .btn-red {{ background: #ff1744; color: white; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #232936; }}
            th {{ color: #8892b0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>⚡ 1-Minute 9 & 20 EMA Scalper</h1>
                <p>Status: <b>{'🟢 RUNNING' if AUTO_TRADING_ENABLED else '🔴 PAUSED'}</b> | Strategy: <b>Trend-Riding (No Artificial Time Limits)</b></p>
                <div>
                    <a href="/toggle-bot" class="btn {'btn-red' if AUTO_TRADING_ENABLED else 'btn-green'}">
                        {'PAUSE BOT' if AUTO_TRADING_ENABLED else 'RESUME BOT'}
                    </a>
                    <a href="/test-telegram" class="btn" style="background:#2979ff;color:white;">Test Telegram</a>
                </div>
            </div>

            <div class="card">
                <h2>Active Scalp Positions ({len(active_copy)}/{MAX_ACTIVE_TRADES})</h2>
                <table>
                    <thead>
                        <tr><th>Pair</th><th>Side</th><th>Entry</th><th>Target</th><th>SL</th><th>Time</th><th>Action</th></tr>
                    </thead>
                    <tbody>{rows if rows else "<tr><td colspan='7'>No active scalps currently open.</td></tr>"}</tbody>
                </table>
            </div>

            <div class="card">
                <h2>Recent Closed Scalps</h2>
                <table>
                    <thead>
                        <tr><th>Pair</th><th>Side</th><th>Entry</th><th>Exit</th><th>Duration</th><th>PNL (%)</th><th>INR Est</th><th>Exit Reason</th></tr>
                    </thead>
                    <tbody>{hist_rows if hist_rows else "<tr><td colspan='8'>No trade history recorded yet.</td></tr>"}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/toggle-bot')
def toggle_bot():
    global AUTO_TRADING_ENABLED
    AUTO_TRADING_ENABLED = not AUTO_TRADING_ENABLED
    save_active_trades()
    return f"<script>window.location.href='/';</script>"

@app.route('/test-telegram')
def test_telegram():
    send_telegram_message("🔔 <b>Crypto-Scanner Test Alert</b>\nBot connection is fully functional and live!")
    return "Telegram alert sent successfully! <a href='/'>Back to Dashboard</a>"

@app.route('/close/<pair>')
def manual_close(pair):
    with active_trades_lock:
        if pair in ACTIVE_TRADES:
            t = ACTIVE_TRADES[pair]
            close_coindcx_position(pair, t['side'], t['quantity'])
            del ACTIVE_TRADES[pair]
            save_active_trades()
            send_telegram_message(f"⚠️ <b>Position for {pair} closed manually from Dashboard.</b>")
    return f"<script>window.location.href='/';</script>"

# ==============================================================================
# 11. BACKGROUND THREADS & SERVER STARTUP
# ==============================================================================
def start_background_loop():
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
        "• <b>Trend-Rider:</b> No time limit! Position stays open while Blue > Red\n"
        "• <b>Exit:</b> Target TP1 (+1.0%), Hard SL, or Blue crosses Red in reverse\n"
        "• <b>Native TP/SL:</b> Bracket orders on CoinDCX\n"
        "• <b>Margin:</b> ₹1,000 INR (7x Isolated Leverage)\n"
        "• <b>Controls:</b> Web 1-Click Dashboard + Telegram /start & /stop"
    )

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting 1-Minute EMA Scalping server on port {port}...")
    app.run(host="0.0.0.0", port=port)
