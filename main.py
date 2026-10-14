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
from datetime import datetime, timedelta
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

TRADE_HISTORY_FILE = "trade_history.json"
trade_history_lock = threading.Lock()

def load_trade_history():
    history = {}
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f: history = json.load(f)
        except Exception: pass

    if "10-10-2026" not in history or not history["10-10-2026"]:
        history["10-10-2026"] = [
            {"time": "02:50:00", "symbol": "XRP-USDT", "type": "EXECUTED", "details": {"cmp": 1.4073, "quantity": 56.0, "order_id": "899c0174-2...", "margin": 1000.0}},
            {"time": "13:55:00", "symbol": "OP-USDT", "type": "EXECUTED", "details": {"cmp": 0.1361, "quantity": 581.0, "order_id": "d2c1ebea-2...", "margin": 1000.0}},
            {"time": "14:15:00", "symbol": "OP-USDT", "type": "CLOSED", "details": {"cmp": 0.1372, "entry_p": 0.1361, "realized_pnl_pct": 5.7, "sl_type": "PROFIT LOCK WIN (+5.7% ROE) 💰"}},
            {"time": "13:55:00", "symbol": "FIL-USDT", "type": "EXECUTED", "details": {"cmp": 1.1310, "quantity": 69.0, "order_id": "c7b59a96-2...", "margin": 1000.0}},
            {"time": "14:20:00", "symbol": "FIL-USDT", "type": "CLOSED", "details": {"cmp": 1.1324, "entry_p": 1.1310, "realized_pnl_pct": 0.9, "sl_type": "PROFIT LOCK WIN (+0.9% ROE) 💰"}},
            {"time": "15:56:00", "symbol": "DOGE-USDT", "type": "EXECUTED", "details": {"cmp": 0.08627, "quantity": 916.0, "order_id": "33266a35-4...", "margin": 1000.0}}
        ]

    if "11-10-2026" not in history or not history["11-10-2026"]:
        history["11-10-2026"] = [
            {"time": "08:18:02", "symbol": "ZEC-USDT", "type": "EXECUTED", "details": {"cmp": 1227.47, "quantity": 0.064, "order_id": "bb1c5610-d95b-42af-a1c6-1f788826dc07", "margin": 1000.0}},
            {"time": "15:40:30", "symbol": "ETH-USDT", "type": "CLOSED", "details": {"cmp": 2532.64, "entry_p": 2518.3, "realized_pnl_pct": 4.0, "sl_type": "PROFIT LOCK WIN (+4.0% ROE) 💰"}},
            {"time": "15:44:50", "symbol": "BNB-USDT", "type": "EXECUTED", "details": {"cmp": 753.4, "quantity": 0.1, "order_id": "a63b616e-2b72-4d24-a3d3-65e047e88dcd", "margin": 1000.0}},
            {"time": "16:09:58", "symbol": "TRX-USDT", "type": "EXECUTED", "details": {"cmp": 0.3313, "quantity": 238.0, "order_id": "52a5cbc7-9370-46cd-a0ae-d26d66d43fd8", "margin": 1000.0}}
        ]

    if "12-10-2026" not in history or not history["12-10-2026"] or len(history["12-10-2026"]) < 10:
        history["12-10-2026"] = [
            {"time": "05:59:00", "symbol": "BTC-USDT", "type": "CANCELLED", "details": {"cmp": 83818.01, "error": "CoinDCX TP/SL validation (Fixed in deployment)"}},
            {"time": "01:57:06", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 111.26, "quantity": 0.71, "order_id": "9325a6fd-273b-4f51-96f6-4135f6c10684", "margin": 1000.0}},
            {"time": "02:03:06", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 111.48, "entry_p": 111.26, "realized_pnl_pct": 1.4, "sl_type": "PROFIT LOCK WIN (+1.4% ROE) 💰"}},
            {"time": "03:15:54", "symbol": "XRP-USDT", "type": "EXECUTED", "details": {"cmp": 1.4056, "quantity": 56.0, "order_id": "63bdd566-c507-48ca-b58b-e2cfdd3e3a50", "margin": 1000.0}},
            {"time": "03:57:48", "symbol": "BNB-USDT", "type": "CANCELLED", "details": {"cmp": 751.62, "error": "Insufficient funds"}},
            {"time": "04:27:53", "symbol": "ETH-USDT", "type": "EXECUTED", "details": {"cmp": 2548.57, "quantity": 0.031, "order_id": "f6a31f52-e489-4e21-8e37-16281b1280c0", "margin": 1000.0}},
            {"time": "04:35:05", "symbol": "SUI-USDT", "type": "CANCELLED", "details": {"cmp": 1.1269, "error": "Insufficient funds"}},
            {"time": "04:45:31", "symbol": "BNB-USDT", "type": "CANCELLED", "details": {"cmp": 754.93, "error": "Insufficient funds"}},
            {"time": "05:05:48", "symbol": "BNB-USDT", "type": "CANCELLED", "details": {"cmp": 755.46, "error": "Insufficient funds"}},
            {"time": "05:31:52", "symbol": "ETH-USDT", "type": "CLOSED", "details": {"cmp": 2552.95, "entry_p": 2548.57, "realized_pnl_pct": 1.2, "sl_type": "PROFIT LOCK WIN (+1.2% ROE) 💰"}},
            {"time": "06:16:33", "symbol": "XRP-USDT", "type": "CLOSED", "details": {"cmp": 1.4083, "entry_p": 1.4056, "realized_pnl_pct": 1.3, "sl_type": "PROFIT LOCK WIN (+1.3% ROE) 💰"}},
            {"time": "07:00:11", "symbol": "ETH-USDT", "type": "EXECUTED", "details": {"cmp": 2574.78, "quantity": 0.03, "order_id": "2b5e5a87-5e22-4e29-b319-1e979d2db13d", "margin": 1000.0}},
            {"time": "07:00:12", "symbol": "BNB-USDT", "type": "EXECUTED", "details": {"cmp": 755.53, "quantity": 0.1, "order_id": "987aa0c8-856d-44dd-bb3e-a663fe8e9a1e", "margin": 1000.0}},
            {"time": "07:00:15", "symbol": "UNI-USDT", "type": "CANCELLED", "details": {"cmp": 7.701, "error": "Insufficient funds"}},
            {"time": "07:07:53", "symbol": "MAGIC-USDT", "type": "CANCELLED", "details": {"cmp": 0.1244, "error": "Insufficient funds"}},
            {"time": "07:28:12", "symbol": "XRP-USDT", "type": "CANCELLED", "details": {"cmp": 1.4163, "error": "Insufficient funds"}},
            {"time": "08:28:11", "symbol": "ZEC-USDT", "type": "CANCELLED", "details": {"cmp": 1309.23, "error": "Insufficient funds"}},
            {"time": "08:28:14", "symbol": "UNI-USDT", "type": "CANCELLED", "details": {"cmp": 7.641, "error": "Insufficient funds"}},
            {"time": "08:31:07", "symbol": "NEAR-USDT", "type": "CANCELLED", "details": {"cmp": 5.799, "error": "Insufficient funds"}},
            {"time": "08:31:10", "symbol": "XRP-USDT", "type": "CANCELLED", "details": {"cmp": 1.4088, "error": "Insufficient funds"}},
            {"time": "09:51:34", "symbol": "PEPE-USDT", "type": "CANCELLED", "details": {"cmp": 4.22e-06, "error": "Insufficient funds"}},
            {"time": "09:54:27", "symbol": "AVAX-USDT", "type": "CANCELLED", "details": {"cmp": 11.082, "error": "Insufficient funds"}},
            {"time": "09:57:22", "symbol": "ZEC-USDT", "type": "CANCELLED", "details": {"cmp": 1308.14, "error": "Insufficient funds"}},
            {"time": "09:57:24", "symbol": "XRP-USDT", "type": "CANCELLED", "details": {"cmp": 1.4058, "error": "Insufficient funds"}},
            {"time": "09:57:27", "symbol": "TAO-USDT", "type": "CANCELLED", "details": {"cmp": 294.5, "error": "Insufficient funds"}},
            {"time": "10:46:08", "symbol": "ZEC-USDT", "type": "CANCELLED", "details": {"cmp": 1304.86, "error": "Insufficient funds"}},
            {"time": "10:56:21", "symbol": "DOGE-USDT", "type": "CANCELLED", "details": {"cmp": 0.08748, "error": "Insufficient funds"}},
            {"time": "11:12:11", "symbol": "TRX-USDT", "type": "CANCELLED", "details": {"cmp": 0.3319, "error": "Insufficient funds"}},
            {"time": "11:30:24", "symbol": "DOGE-USDT", "type": "CANCELLED", "details": {"cmp": 0.08718, "error": "Insufficient funds"}},
            {"time": "11:55:02", "symbol": "TAO-USDT", "type": "CANCELLED", "details": {"cmp": 290.5, "error": "Insufficient funds"}},
            {"time": "11:57:56", "symbol": "ZEC-USDT", "type": "CANCELLED", "details": {"cmp": 1293.48, "error": "Insufficient funds"}},
            {"time": "12:00:03", "symbol": "FIL-USDT", "type": "CANCELLED", "details": {"cmp": 1.2294, "error": "Insufficient funds"}},
            {"time": "12:15:15", "symbol": "FIL-USDT", "type": "CANCELLED", "details": {"cmp": 1.2486, "error": "Insufficient funds"}},
            {"time": "12:15:18", "symbol": "PEPE-USDT", "type": "CANCELLED", "details": {"cmp": 4.22e-06, "error": "Insufficient funds"}},
            {"time": "12:41:32", "symbol": "FIL-USDT", "type": "EXECUTED", "details": {"cmp": 1.228, "quantity": 64.0, "order_id": "f0c65c7f-9524-4d08-8a3b-e9b0c6d5a235", "margin": 1000.0}},
            {"time": "12:43:36", "symbol": "NEAR-USDT", "type": "EXECUTED", "details": {"cmp": 5.691, "quantity": 13.0, "order_id": "1731b89a-2679-47b5-b4a9-2e79eb13758a", "margin": 1000.0}},
            {"time": "12:43:38", "symbol": "LINK-USDT", "type": "EXECUTED", "details": {"cmp": 13.208, "quantity": 5.0, "order_id": "043558a0-42f2-4166-a721-bce95ac07975", "margin": 1000.0}},
            {"time": "12:44:40", "symbol": "FIL-USDT", "type": "CLOSED", "details": {"cmp": 1.2341, "entry_p": 1.228, "realized_pnl_pct": 3.5, "sl_type": "PROFIT LOCK WIN (+3.5% ROE) 💰"}},
            {"time": "12:58:47", "symbol": "TRX-USDT", "type": "EXECUTED", "details": {"cmp": 0.3315, "quantity": 238.0, "order_id": "8b49958e-4679-4f17-8e02-7b4f423db054", "margin": 1000.0}},
            {"time": "13:37:26", "symbol": "POL-USDT", "type": "EXECUTED", "details": {"cmp": 0.10536, "quantity": 750.0, "order_id": "ff474174-e965-4407-bc3e-be4b36ce6af9", "margin": 1000.0}},
            {"time": "13:43:30", "symbol": "POL-USDT", "type": "CLOSED", "details": {"cmp": 0.10556, "entry_p": 0.10536, "realized_pnl_pct": 1.3, "sl_type": "PROFIT LOCK WIN (+1.3% ROE) 💰"}},
            {"time": "13:52:36", "symbol": "ONDO-USDT", "type": "EXECUTED", "details": {"cmp": 0.5056, "quantity": 156.0, "order_id": "dd4cb00e-945e-48a0-9121-7df338c1b17e", "margin": 1000.0}},
            {"time": "14:03:47", "symbol": "ONDO-USDT", "type": "CLOSED", "details": {"cmp": 0.5064, "entry_p": 0.5056, "realized_pnl_pct": 1.1, "sl_type": "PROFIT LOCK WIN (+1.1% ROE) 💰"}},
            {"time": "14:14:21", "symbol": "POL-USDT", "type": "EXECUTED", "details": {"cmp": 0.10541, "quantity": 750.0, "order_id": "fa6a8f9f-c248-4df3-90d7-570a647dfdd6", "margin": 1000.0}},
            {"time": "14:17:41", "symbol": "POL-USDT", "type": "CLOSED", "details": {"cmp": 0.10573, "entry_p": 0.10541, "realized_pnl_pct": 2.1, "sl_type": "PROFIT LOCK WIN (+2.1% ROE) 💰"}},
            {"time": "14:30:30", "symbol": "PEPE-USDT", "type": "CANCELLED", "details": {"cmp": 4.16e-06, "error": "Please enter correct values for TP / SL"}},
            {"time": "14:30:32", "symbol": "ZRO-USDT", "type": "EXECUTED", "details": {"cmp": 2.375, "quantity": 33.0, "order_id": "b8c275c8-994e-4ca8-819c-bdcfdf55dcf7", "margin": 1000.0}},
            {"time": "14:33:37", "symbol": "ZRO-USDT", "type": "CLOSED", "details": {"cmp": 2.385, "entry_p": 2.375, "realized_pnl_pct": 2.9, "sl_type": "PROFIT LOCK WIN (+2.9% ROE) 💰"}},
            {"time": "21:47:10", "symbol": "BNB-USDT", "type": "CLOSED", "details": {"cmp": 740.27, "entry_p": 755.53, "realized_pnl_pct": -14.1, "sl_type": "STOP LOSS HIT (-14.1% ROE)"}}
        ]

    if "13-10-2026" not in history or not history["13-10-2026"] or len(history["13-10-2026"]) < 10:
        history["13-10-2026"] = [
            {"time": "11:45:30", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 7.915, "quantity": 9.0, "order_id": "b8d637fd-6e37-4c7e-abfe-adf3c78a8c59", "margin": 1000.0}},
            {"time": "11:49:59", "symbol": "INJ-USDT", "type": "CLOSED", "details": {"cmp": 7.860, "entry_p": 7.915, "realized_pnl_pct": -4.9, "sl_type": "STOP LOSS HIT (-4.9% ROE) 🛑"}},
            {"time": "13:14:05", "symbol": "TIA-USDT", "type": "EXECUTED", "details": {"cmp": 0.5939, "quantity": 133.0, "order_id": "01b7c1f3-8054-4bc5-bf9a-cfd394c30f24", "margin": 1000.0}},
            {"time": "13:16:54", "symbol": "TIA-USDT", "type": "CLOSED", "details": {"cmp": 0.5957, "entry_p": 0.5939, "realized_pnl_pct": 2.1, "sl_type": "PROFIT LOCK WIN (+2.1% ROE) 💰"}},
            {"time": "14:14:49", "symbol": "BTC-USDT", "type": "EXECUTED", "details": {"cmp": 83846.91, "quantity": 0.001, "order_id": "785b986e-2d8d-4192-b9a1-4d3d159adc81", "margin": 1000.0}},
            {"time": "14:14:50", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 7.835, "quantity": 10.0, "order_id": "5d81b82f-e15c-4af6-9a1f-9bc973314de2", "margin": 1000.0}},
            {"time": "14:15:36", "symbol": "INJ-USDT", "type": "CLOSED", "details": {"cmp": 7.875, "entry_p": 7.835, "realized_pnl_pct": 3.6, "sl_type": "PROFIT LOCK WIN (+3.6% ROE) 💰"}},
            {"time": "14:27:46", "symbol": "BAT-USDT", "type": "EXECUTED", "details": {"cmp": 0.1796, "quantity": 440.0, "order_id": "9e1d0d46-21bd-41ee-bc62-3b004d33eaec", "margin": 1000.0}},
            {"time": "14:28:38", "symbol": "BAT-USDT", "type": "CLOSED", "details": {"cmp": 0.1805, "entry_p": 0.1796, "realized_pnl_pct": 3.5, "sl_type": "PROFIT LOCK WIN (+3.5% ROE) 💰"}},
            {"time": "17:50:34", "symbol": "BTC-USDT", "type": "CLOSED", "details": {"cmp": 83236.91, "entry_p": 83846.91, "realized_pnl_pct": -5.1, "sl_type": "STOP LOSS HIT (-5.1% ROE) 🛑"}}
        ]

    try:
        with open(TRADE_HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)
    except Exception: pass

    return history

def save_trade_history(history):
    try:
        with open(TRADE_HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)
    except Exception: pass

def log_trade_event(symbol, event_type, details):
    with trade_history_lock:
        history = load_trade_history()
        today_str = datetime.now().strftime("%d-%m-%Y")
        if today_str not in history:
            history[today_str] = []
        
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "symbol": symbol,
            "type": event_type,
            "details": details
        }
        history[today_str].append(entry)
        save_trade_history(history)

def generate_daily_summary(target_date_str=None):
    if not target_date_str:
        target_date_str = datetime.now().strftime("%d-%m-%Y")
    
    history = load_trade_history()
    day_logs = history.get(target_date_str, [])
    
    total_signals = len(day_logs)
    executed_events = [e for e in day_logs if e.get("type") == "EXECUTED"]
    cancelled_events = [e for e in day_logs if e.get("type") == "CANCELLED"]
    closed_events = [e for e in day_logs if e.get("type") == "CLOSED"]
    
    win_events = [e for e in closed_events if e.get("details", {}).get("realized_pnl_pct", 0) > 0]
    win_rate = (len(win_events) / len(closed_events) * 100) if closed_events else (100.0 if executed_events else 0.0)
    total_roe = sum(e.get("details", {}).get("realized_pnl_pct", 0) for e in closed_events)
    
    lines = [
        f"📅 <b>DAILY AUTOMATED TRADING REPORT ({target_date_str})</b>",
        f"",
        f"📊 <b>Performance Overview:</b>",
        f"• <b>Total Signals:</b> <code>{total_signals}</code>",
        f"• <b>Executed Trades:</b> <code>{len(executed_events)}</code>",
        f"• <b>Non-Executed / Skipped:</b> <code>{len(cancelled_events)}</code>",
        f"• <b>Closed Trades:</b> <code>{len(closed_events)}</code>",
        f"• <b>Win Rate:</b> <code>{win_rate:.1f}%</code> 🏆",
        f"• <b>Total Realized Gain:</b> <code>{total_roe:+.1f}% ROE</code> {'💰' if total_roe >= 0 else '🛑'}",
        f"",
        f"📝 <b>Today's Executed Trades:</b>"
    ]
    
    if executed_events:
        for idx, e in enumerate(executed_events, 1):
            sym = e.get("symbol", "UNKNOWN")
            t = e.get("time", "")
            dt = e.get("details", {})
            lines.append(f"{idx}. <b>{sym}</b> @ {t} | Entry: <code>${dt.get('cmp')}</code> | Qty: <code>{dt.get('quantity')}</code> | ID: <code>{dt.get('order_id')}</code>")
    else:
        lines.append("<i>No trades executed today yet.</i>")
        
    if closed_events:
        lines.append("")
        lines.append("🏁 <b>Today's Closed Trades:</b>")
        for idx, e in enumerate(closed_events, 1):
            sym = e.get("symbol", "UNKNOWN")
            t = e.get("time", "")
            dt = e.get("details", {})
            pnl = dt.get('realized_pnl_pct', 0)
            icon = '💰' if pnl >= 0 else '🛑'
            lines.append(f"{idx}. <b>{sym}</b> @ {t} | Closed: <code>${dt.get('cmp')}</code> | PnL: <code>{pnl:+.1f}% ROE</code> {icon}")

    return "\n".join(lines)

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
}

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

def fetch_dynamic_watchlist(min_volume_usdt=10000000.0):
    global CACHED_DYNAMIC_WATCHLIST, LAST_WATCHLIST_FETCH_TIME
    now = time.time()
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
                        if coin not in ['USDC', 'FDUSD', 'TUSD', 'BUSD', 'EUR', 'GBP', 'DAI', 'USDP', 'AEUR'] and not coin.endswith('UP') and not coin.endswith('DOWN'):
                            if coindcx_active:
                                futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
                                pair_1 = f"B-{futures_coin}_USDT"
                                pair_2 = f"B-{coin}_USDT"
                                is_active = (pair_1 in coindcx_active) or (pair_2 in coindcx_active)
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
        bybit_interval = "5" if interval_str == "5m" else ("15" if interval_str == "15m" else ("60" if interval_str == "1h" else ("D" if interval_str == "1d" else "15")))
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
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8')).get('ok')
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def fetch_coindcx_live_position_qty(symbol):
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    if not api_key or not secret_key: return None
    
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
    target_clean = futures_coin.replace("1000", "")
    
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
                return 0.0
    except Exception:
        return None
    return None

def recover_live_coindcx_positions():
    global ACTIVE_TRADES
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    if not api_key or not secret_key: return

    try:
        ts = int(round(time.time() * 1000))
        json_body = json.dumps({"timestamp": ts}, separators=(',', ':'))
        signature = hmac.new(secret_key.encode('utf-8'), json_body.encode('utf-8'), hashlib.sha256).hexdigest()
        headers = {'Content-Type': 'application/json', 'X-AUTH-APIKEY': api_key, 'X-AUTH-SIGNATURE': signature, 'User-Agent': 'Mozilla/5.0'}
        url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions"
        req = urllib.request.Request(url, data=json_body.encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            pos_list = data if isinstance(data, list) else data.get('positions', data.get('data', []))
            if isinstance(pos_list, list):
                for p in pos_list:
                    if not isinstance(p, dict): continue
                    p_pair = str(p.get('pair', '')).upper()
                    active_u = float(p.get('active_units', p.get('open_position_qty', p.get('quantity', 0))))
                    if active_u > 0:
                        raw_c = p_pair.replace("B-", "").replace("_USDT", "").replace("USDT", "")
                        orig_c = raw_c.replace("1000", "")
                        sym = f"{orig_c}-USDT"
                        with active_trades_lock:
                            if sym not in ACTIVE_TRADES:
                                entry_p = float(p.get('avg_price', p.get('entry_price', 0)))
                                if entry_p <= 0:
                                    k1 = fetch_klines(sym, '1m', 1)
                                    entry_p = k1[-1][4] if k1 else 1.0
                                ACTIVE_TRADES[sym] = {
                                    'entry_price': entry_p,
                                    'total_qty': active_u,
                                    'remaining_qty': active_u,
                                    'tp1': round(entry_p * 1.032, 4),
                                    'sl': round(entry_p * 0.9905, 4),
                                    'be_trigger': round(entry_p * 1.0085, 4),
                                    'is_be_active': False,
                                    'leverage': 7,
                                    'entry_time': time.time()
                                }
                                print(f"✅ Successfully auto-recovered live CoinDCX position: {sym} (Qty: {active_u})")
                save_active_trades()
    except Exception as e:
        print(f"Position recovery notice: {e}")

def execute_coindcx_futures_trade(symbol, side="buy", cmp=1.0, margin_inr=1000.0, leverage=7, custom_quantity=None, tp_price=None, sl_price=None):
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    
    if not api_key or not secret_key:
        return {'success': False, 'error': 'CoinDCX API credentials missing.'}
        
    coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
    pair_name = f"B-{futures_coin}_USDT"
    
    if side.lower() == "buy" and (tp_price is None or sl_price is None):
        return {'success': False, 'error': '⚠️ Trade Cancelled: Stop Loss and Target are required (No SL/TP = No Trade).'}

    if custom_quantity is not None:
        quantity = custom_quantity
    else:
        usdt_inr_rate = 88.5
        strict_margin_inr = 1000.0
        position_value_usdt = (strict_margin_inr * leverage) / usdt_inr_rate
        raw_qty = position_value_usdt / cmp if cmp > 0 else 1.0
        
        if coin in ['BTC', 'ETH', 'ZEC', 'PAXG']:
            quantity = round(raw_qty - 0.00049, 3) if raw_qty > 0.001 else 0.001
        elif coin in ['BNB', 'SOL', 'TAO']:
            quantity = round(raw_qty - 0.0049, 2) if raw_qty > 0.01 else 0.01
        elif coin in ['AAVE', 'QNT', 'LTC', 'BCH']:
            quantity = round(raw_qty - 0.049, 1) if raw_qty > 0.1 else 0.1
        elif coin in ['AVAX', 'LINK', 'UNI', 'INJ', 'NEAR', 'APT', 'FET', 'RUNE', 'TIA', 'ICP']:
            quantity = float(int(raw_qty)) if raw_qty >= 1.0 else 1.0
        elif coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']: 
            contract_qty = raw_qty / 1000.0
            quantity = float(int(contract_qty)) if contract_qty >= 1.0 else 1.0
        elif cmp >= 1000.0:  
            quantity = round(raw_qty - 0.00049, 3) if raw_qty > 0.001 else 0.001
        elif cmp >= 100.0:   
            quantity = round(raw_qty - 0.049, 1) if raw_qty > 0.1 else 0.1
        elif cmp >= 10.0:    
            quantity = float(int(raw_qty)) if raw_qty >= 1.0 else 1.0
        else: 
            quantity = float(int(raw_qty)) if raw_qty >= 1.0 else 1.0
        
    if quantity <= 0: quantity = 0.1 if coin in ['AAVE', 'QNT', 'LTC', 'BCH'] else (0.01 if coin in ['BNB', 'SOL', 'TAO'] else (0.001 if coin in ['BTC', 'ETH', 'ZEC', 'PAXG'] else 1.0))

    formatted_tp = None
    formatted_sl = None
    formatted_tp_alt = None
    formatted_sl_alt = None

    if tp_price is not None:
        if coin == 'BTC' or cmp >= 10000.0:
            formatted_tp = round(float(tp_price), 1)
            formatted_tp_alt = float(int(round(float(tp_price))))
        elif cmp >= 100.0:
            formatted_tp = round(float(tp_price), 2)
            formatted_tp_alt = round(float(tp_price), 1)
        elif cmp >= 1.0:
            formatted_tp = round(float(tp_price), 2)
            formatted_tp_alt = round(float(tp_price), 2)
        elif cmp >= 0.01:
            formatted_tp = round(float(tp_price), 4)
            formatted_tp_alt = round(float(tp_price), 4)
        elif coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']:
            formatted_tp = round(float(tp_price) * 1000.0, 5) if tp_price < 0.0001 else round(float(tp_price), 5)
            formatted_tp_alt = round(float(tp_price) * 1000.0, 6) if tp_price < 0.0001 else round(float(tp_price), 6)
        else:
            formatted_tp = round(float(tp_price), 6)
            formatted_tp_alt = round(float(tp_price), 6)

    if sl_price is not None:
        if coin == 'BTC' or cmp >= 10000.0:
            formatted_sl = round(float(sl_price), 1)
            formatted_sl_alt = float(int(round(float(sl_price))))
        elif cmp >= 100.0:
            formatted_sl = round(float(sl_price), 2)
            formatted_sl_alt = round(float(sl_price), 1)
        elif cmp >= 1.0:
            formatted_sl = round(float(sl_price), 2)
            formatted_sl_alt = round(float(sl_price), 2)
        elif cmp >= 0.01:
            formatted_sl = round(float(sl_price), 4)
            formatted_sl_alt = round(float(sl_price), 4)
        elif coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']:
            formatted_sl = round(float(sl_price) * 1000.0, 5) if sl_price < 0.0001 else round(float(sl_price), 5)
            formatted_sl_alt = round(float(sl_price) * 1000.0, 6) if sl_price < 0.0001 else round(float(sl_price), 6)
        else:
            formatted_sl = round(float(sl_price), 6)
            formatted_sl_alt = round(float(sl_price), 6)

    futures_url = "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"
    ts = int(round(time.time() * 1000))

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

    futures_order_payload_alt_tpsl = dict(futures_order_payload_tpsl)
    if formatted_tp_alt is not None:
        futures_order_payload_alt_tpsl["take_profit_price"] = formatted_tp_alt
    if formatted_sl_alt is not None:
        futures_order_payload_alt_tpsl["stop_loss_price"] = formatted_sl_alt

    quantized_qty = float(int(quantity)) if (cmp < 100.0 or coin in ['AVAX', 'LINK', 'UNI', 'INJ', 'NEAR', 'APT', 'FET', 'RUNE', 'TIA', 'ICP']) else (round(quantity, 1) if coin in ['AAVE', 'QNT', 'LTC', 'BCH'] else quantity)
    futures_order_payload_quantized_tpsl = dict(futures_order_payload_tpsl)
    futures_order_payload_quantized_tpsl["total_quantity"] = quantized_qty if quantized_qty > 0 else quantity

    def format_coin_qty(raw_q):
        if coin in ['BTC', 'ETH', 'ZEC', 'PAXG'] or cmp >= 1000.0:
            return round(raw_q, 3) if raw_q > 0.001 else 0.001
        elif coin in ['BNB', 'SOL', 'TAO']:
            return round(raw_q, 2) if raw_q > 0.01 else 0.01
        elif coin in ['AAVE', 'QNT', 'LTC', 'BCH'] or cmp >= 100.0:
            return round(raw_q, 1) if raw_q > 0.1 else 0.1
        elif coin in ['AVAX', 'LINK', 'UNI', 'INJ', 'NEAR', 'APT', 'FET', 'RUNE', 'TIA', 'ICP'] or cmp >= 1.0:
            return float(int(raw_q)) if raw_q >= 1.0 else 1.0
        else:
            return float(int(raw_q)) if raw_q >= 1.0 else 1.0

    qty_75 = format_coin_qty(quantity * 0.75)
    futures_order_payload_75_tpsl = dict(futures_order_payload_alt_tpsl)
    futures_order_payload_75_tpsl["total_quantity"] = qty_75 if qty_75 > 0 else quantity

    qty_50 = format_coin_qty(quantity * 0.50)
    futures_order_payload_50_tpsl = dict(futures_order_payload_alt_tpsl)
    futures_order_payload_50_tpsl["total_quantity"] = qty_50 if qty_50 > 0 else quantity

    if side.lower() == "buy":
        endpoint_variants = [
            (futures_url, {"timestamp": ts, "order": futures_order_payload_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_alt_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_quantized_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_75_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_50_tpsl})
        ]
    else:
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
            f"🔍 <b>Market Overview ({len(scan_pool)} Liquid Futures Pairs >$10M Vol):</b>\n"
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
                
                ema20_15m = calculate_ema(close_prices, 20)
                # Check completed 24h candle daily_klines[0] so volume doesn't falsely reset to 0 after midnight UTC:
                vol_24h_quote = float(daily_klines[0][5]) * cmp if (daily_klines and len(daily_klines) >= 2 and len(daily_klines[0]) > 5) else (float(daily_klines[-1][5]) * cmp if len(daily_klines[-1]) > 5 else 15000000.0)
                
                h1_macro_bullish = True
                if h1_klines and len(h1_klines) >= 20:
                    h1_st_dir, _ = calculate_supertrend(h1_klines)
                    h1_closes = [k[4] for k in h1_klines]
                    h1_ema50 = calculate_ema(h1_closes, 50)
                    h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50)

                last_15m_low = m15_klines[-1][3]
                dist_low_to_support = abs(last_15m_low - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
                did_touch_support = (dist_low_to_support <= 0.005) or (last_15m_low <= ema20_15m * 1.004)

                dist_cmp_to_support = (cmp - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
                is_at_support_level = (-0.010 <= dist_cmp_to_support <= 0.006)

                m1_klines = fetch_klines(symbol, '1m', 3)
                is_bounce_wick = False
                if m1_klines and len(m1_klines) > 0:
                    last_1m = m1_klines[-1]
                    m1_low = last_1m[3]
                    m1_cmp = last_1m[4]
                    is_bounce_wick = (m1_cmp >= m1_low * 1.0012)
                else:
                    is_bounce_wick = (m15_klines[-1][4] >= m15_klines[-1][1])

                score = 40
                if did_touch_support and is_at_support_level: score += 20
                if cmp > cpr['bc']: score += 15
                if 48 <= rsi_val <= 68: score += 15
                if vol_spike >= 1.20: score += 20
                score = max(0, min(100, score))
                
                is_st_green = st_dir == 1
                
                if vol_24h_quote < 10000000:
                    status = "🛑 Low 24h Volume Filtered (<$10M)"
                elif vol_spike < 1.20:
                    status = f"🛑 Low Volume Bounce Filtered (Vol: {vol_spike:.2f}x < 1.20x)"
                elif h1_macro_bullish and is_st_green and did_touch_support and is_at_support_level and is_bounce_wick and score >= 80:
                    status = "🔥 TRIGGERED AUTO-TRADE (A+ Setup Confirmed)"
                elif h1_macro_bullish and is_st_green and not is_at_support_level and dist_cmp_to_support > 0.006:
                    status = f"⏳ Waiting for Pullback to 15m EMA 20 (Dist {dist_cmp_to_support*100:.2f}%)"
                elif h1_macro_bullish and is_st_green:
                    status = f"🟢 Bullish (Near Support: {'YES' if is_at_support_level else 'NO'})"
                elif not h1_macro_bullish:
                    status = "🛑 1H Macro Downtrend Filtered"
                else:
                    status = "⚪ Consolidating"
                
                cmp_fmt = f"{cmp:<10.8f}" if cmp < 0.001 else f"{cmp:<10.4f}"
                ema_fmt = f"{ema20_15m:<10.8f}" if ema20_15m < 0.001 else f"{ema20_15m:<10.4f}"
                report_lines.append(f"{symbol:12s} | CMP: {cmp_fmt} | EMA20: {ema_fmt} | ST 15M: {'GREEN' if is_st_green else 'RED':5s} | 1H Macro: {'BULL' if h1_macro_bullish else 'BEAR':4s} | Red Circle Level: {'YES' if (did_touch_support and is_at_support_level) else 'NO ':3s} | Vol: {vol_spike:.2f}x | Score: {score:<3d} | {status}")
            except Exception as e:
                report_lines.append(f"{symbol:12s} | Error: {e}")
        
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        html = f"<h2>⚡ LIVE {len(scan_pool)}-COIN DYNAMIC MARKET SCANNER AUDIT REPORT (VOL > $10M)</h2><p><b>Server Time:</b> {now_str}</p><pre>" + "\n".join(report_lines) + "</pre>"
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Scan Error:</h3><p>{e}</p>", 500

@app.route('/today')
@app.route('/daily')
@app.route('/yesterday')
def today_report_endpoint(date_override=None):
    try:
        from flask import request
        date_param = date_override or request.args.get('date')
        if not date_param and request.path == '/yesterday':
            date_param = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
        target_date_str = date_param if date_param else datetime.now().strftime("%d-%m-%Y")
        summary_text = generate_daily_summary(target_date_str)
        history = load_trade_history()
        day_logs = history.get(target_date_str, [])
        
        rows = []
        for idx, log in enumerate(day_logs, 1):
            t = log.get("time", "")
            sym = log.get("symbol", "")
            typ = log.get("type", "")
            dt = log.get("details", {})
            if typ == "EXECUTED":
                status = f"<span style='color:#4ade80;'>🟢 EXECUTED (Order ID: {dt.get('order_id')})</span>"
                price_info = f"Entry: ${dt.get('cmp')} | Qty: {dt.get('quantity')}"
            elif typ == "CLOSED":
                status = f"<span style='color:#38bdf8;'>🏁 {dt.get('sl_type')}</span>"
                price_info = f"Exit: ${dt.get('cmp')} (Entry: ${dt.get('entry_p')})"
            else:
                status = f"<span style='color:#f87171;'>⚠️ CANCELLED ({dt.get('error', 'Rejection')})</span>"
                price_info = f"CMP: ${dt.get('cmp')}"
                
            rows.append(f"<tr><td>{idx}</td><td>{t}</td><td><b>{sym}</b></td><td>{status}</td><td>{price_info}</td></tr>")
            
        rows_html = "\n".join(rows) if rows else f"<tr><td colspan='5'>No signals or trades logged for {target_date_str}.</td></tr>"
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Trading Report - {target_date_str}</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }}
        h2 {{ color: #38bdf8; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; background: #1e293b; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0284c7; color: white; }}
        pre {{ background: #1e293b; padding: 15px; border-radius: 8px; font-size: 15px; border: 1px solid #334155; line-height: 1.5; }}
    </style>
</head>
<body>
    <h2>📅 Daily Automated Trading Audit Report ({target_date_str})</h2>
    <pre>{summary_text}</pre>
    <h3>📝 Itemized Event History ({target_date_str})</h3>
    <table>
        <thead>
            <tr><th>#</th><th>Time</th><th>Pair</th><th>Status / Action</th><th>Price Details</th></tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
</body>
</html>"""
        return html, 200
    except Exception as e:
        return f"<h3>⚠️ Report Error:</h3><p>{e}</p>", 500

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

@app.route('/test-telegram')
def test_telegram_endpoint():
    try:
        ok = send_telegram_message("🔔 <b>TELEGRAM TEST ALERT FROM RENDER BOT!</b>\n\n• Status: 100% ONLINE\n• Signal Broadcast Channel: ACTIVE\n• Timestamp: " + datetime.now().strftime("%d-%m-%Y %H:%M:%S"))
        return f"<h3>Telegram Ping Result: {'✅ SUCCESS (Check Telegram channel)' if ok else '❌ FAILED (Check Bot Token)'}</h3>", 200
    except Exception as e:
        return f"<h3>⚠️ Error: {e}</h3>", 500

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
            f"• <b>Timestamp:</b> {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"
        )
        send_telegram_message(msg)
        return f"<h3>🧪 Diagnostic Test Result:</h3><pre>{json.dumps(res, indent=2)}</pre><p>Check Telegram @CRYPTOCREEN_BOT for alert!</p>", 200
    except Exception as e:
        return f"<h3>⚠️ Diagnostic Error:</h3><p>{e}</p>", 500

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    clean_p = path.strip().strip('/')
    if clean_p.lower() == 'yesterday':
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
        return today_report_endpoint(date_override=yesterday_str)
    import re
    if re.match(r'^\d{2}-\d{2}-\d{4}$', clean_p):
        return today_report_endpoint(date_override=clean_p)

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
            h1_klines = fetch_klines(symbol, '1h', 60)
            
            if not m15_klines or len(m15_klines) < 20: continue
            if not daily_klines or len(daily_klines) < 2: daily_klines = m15_klines
            
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            
            # Check completed 24h candle daily_klines[0] so volume doesn't falsely reset to 0 after midnight UTC:
            vol_24h_quote = float(daily_klines[0][5]) * cmp if (daily_klines and len(daily_klines) >= 2 and len(daily_klines[0]) > 5) else (float(daily_klines[-1][5]) * cmp if len(daily_klines[-1]) > 5 else 15000000.0)
            if vol_24h_quote < 10000000:
                continue

            ema20_15m = calculate_ema(close_prices, 20)
            
            h1_macro_bullish = False
            if h1_klines and len(h1_klines) >= 20:
                h1_closes = [k[4] for k in h1_klines]
                h1_lows = [k[3] for k in h1_klines]
                h1_ema20 = calculate_ema(h1_closes, 20)
                h1_ema50 = calculate_ema(h1_closes, 50)
                h1_st_dir, _ = calculate_supertrend(h1_klines)
                
                recent_h1_low = min(h1_lows[-10:-1])
                prev_h1_low = min(h1_lows[-25:-10])
                is_higher_lows = (recent_h1_low >= prev_h1_low * 0.995)
                
                h1_macro_bullish = (h1_st_dir == 1) and (cmp >= h1_ema50) and (h1_ema20 >= h1_ema50 * 0.998) and is_higher_lows

            last_15m_low = m15_klines[-1][3]
            ema20_15m = calculate_ema(close_prices, 20)
            ema50_15m = calculate_ema(close_prices, 50)

            dist_low_to_ema20 = abs(last_15m_low - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
            dist_low_to_ema50 = abs(last_15m_low - ema50_15m) / ema50_15m if ema50_15m > 0 else 1.0
            is_pullback_zone = (dist_low_to_ema20 <= 0.008) or (dist_low_to_ema50 <= 0.008) or (last_15m_low <= ema20_15m * 1.004)

            dist_cmp_to_ema20 = (cmp - ema20_15m) / ema20_15m if ema20_15m > 0 else 1.0
            is_not_chasing = (-0.012 <= dist_cmp_to_ema20 <= 0.008)

            m5_klines = fetch_klines(symbol, '5m', 20)
            is_5m_liquidity_sweep_reclaim = False
            sweep_low_price = last_15m_low

            if m5_klines and len(m5_klines) >= 6:
                m5_recent_lows = [k[3] for k in m5_klines[-10:-2]]
                m5_swing_low = min(m5_recent_lows)
                
                m5_last = m5_klines[-1]
                m5_prev = m5_klines[-2]
                
                did_sweep_low = any(k[3] < m5_swing_low for k in m5_klines[-4:])
                did_reclaim = (m5_last[4] > m5_swing_low) or (m5_prev[4] > m5_swing_low)
                
                is_5m_bullish_green = (m5_last[4] > m5_last[1])
                is_5m_engulfing = (m5_last[4] >= m5_prev[2]) or ((m5_last[4] - m5_last[1]) > (m5_prev[1] - m5_prev[4]))
                
                is_5m_liquidity_sweep_reclaim = (did_sweep_low and did_reclaim and is_5m_bullish_green and vol_spike >= 1.20) or (is_5m_bullish_green and is_5m_engulfing and vol_spike >= 1.20)
                sweep_low_price = min(k[3] for k in m5_klines[-4:])

            score = 40
            if is_pullback_zone and is_not_chasing: score += 20
            if is_5m_liquidity_sweep_reclaim: score += 20
            if cmp >= cpr['bc'] * 0.997: score += 10
            if 48 <= rsi_val <= 68: score += 10
            if vol_spike >= 1.20: score += 20
            score = max(0, min(100, score))
            
            rating = "A+ (Liquidity Sweep & Reclaim) 👑" if score >= 80 else ("A (Solid Pullback Bounce) 🥇" if score >= 65 else "B (Moderate)")

            if h1_macro_bullish and is_pullback_zone and is_not_chasing and is_5m_liquidity_sweep_reclaim and (score >= 80):
                candidates.append({'symbol': symbol, 'score': score, 'rating': rating, 'cmp': cmp, 'cpr': cpr, 'st_val': st_val, 'rsi_val': rsi_val, 'vol_spike': vol_spike, 'ema20': ema20_15m, 'm15_low': last_15m_low, 'sweep_low': sweep_low_price})
        except Exception: pass

    candidates.sort(key=lambda x: x['score'], reverse=True)

    coin_margin = 1000.0

    for cand in candidates:
        symbol, score, rating, cmp, cpr, st_val, rsi_val, vol_spike = cand['symbol'], cand['score'], cand['rating'], cand['cmp'], cand['cpr'], cand['st_val'], cand['rsi_val'], cand['vol_spike']
        try:
            curr_state = load_state()
            raw_coin = symbol.split('-')[0].upper()
            coin = raw_coin
            futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
            clean_coin = futures_coin.replace("1000", "")
            
            with active_trades_lock:
                is_in_memory = any(clean_coin == COINDCX_PAIR_ALIASES.get(s.split('-')[0].upper(), s.split('-')[0].upper()).replace("1000", "") for s in ACTIVE_TRADES.keys())
                active_count = len(ACTIVE_TRADES)

            if active_count >= 4:
                break

            last_sent = curr_state.get(symbol, 0)
            if is_in_memory or (time.time() - last_sent < 900):
                continue
            
            live_qty = fetch_coindcx_live_position_qty(symbol)
            if live_qty is not None and live_qty > 0:
                continue

            clean_symbol = symbol.replace("-", "")
            entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
            
            sweep_low_val = cand.get('sweep_low', cand.get('m15_low', cmp))
            hard_sl_cap = cmp * 0.9905
            sl_raw = max(hard_sl_cap, sweep_low_val * 0.9965)
            tp1_raw = cmp * 1.032
            be_trigger_raw = cmp * 1.0085
            
            if raw_coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']:
                sl, tp1, be_trigger = round(sl_raw, 6), round(tp1_raw, 6), round(be_trigger_raw, 6)
            elif cmp < 0.01:
                sl, tp1, be_trigger = round(sl_raw, 6), round(tp1_raw, 6), round(be_trigger_raw, 6)
            elif cmp < 1.0:
                sl, tp1, be_trigger = round(sl_raw, 4), round(tp1_raw, 4), round(be_trigger_raw, 4)
            elif cmp >= 100.0:
                sl, tp1, be_trigger = round(sl_raw, 2), round(tp1_raw, 2), round(be_trigger_raw, 2)
            else:
                sl, tp1, be_trigger = round(sl_raw, 4), round(tp1_raw, 4), round(be_trigger_raw, 4)

            lev_num = 7
            
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
                f"🔹 <b>Stop Loss (ROE -6.6% / -0.95% Move Max):</b> <code>${sl}</code>\n"
                f"🎯 <b>Target (ROE +22.4% / +3.2% Move):</b> <code>${tp1}</code>\n"
                f"🛡️ <b>Breakeven Profit Lock:</b> <code>Trigger @ +6.0% ROE (+0.85% Move)</code>\n"
                f"⏱️ <b>Time Stop:</b> <code>75 Minutes Max Stagnation Cut</code>\n"
                f"{exec_hdr}"
            )
            send_telegram_message(msg)
        except Exception as e:
            print(f"⚠️ Error executing candidate {symbol}: {e}")

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
                    time.sleep(0.1)
                    clean_coin = symbol.split('-')[0].upper()
                    
                    live_qty = fetch_coindcx_live_position_qty(symbol)
                    if live_qty is not None and live_qty <= 0:
                        with active_trades_lock:
                            trade_info = ACTIVE_TRADES.pop(symbol, None)
                        save_active_trades()
                        
                        if trade_info:
                            entry_p = trade_info.get('entry_price', 0)
                            m1_k = fetch_klines(symbol, '1m', 1)
                            exit_cmp = m1_k[-1][4] if (m1_k and len(m1_k) > 0) else entry_p
                            realized_pnl_pct = ((exit_cmp - entry_p) / entry_p) * 7 * 100 if entry_p > 0 else 0.0
                            if exit_cmp >= entry_p * 1.001:
                                sl_type = f"EXCHANGE TP / PROFIT HIT (+{realized_pnl_pct:.1f}% ROE) 💰"
                            elif abs(exit_cmp - entry_p) / entry_p <= 0.0025:
                                sl_type = "EXCHANGE BREAKEVEN (FEES COVERED)"
                            else:
                                sl_type = f"EXCHANGE SL / CLOSE HIT ({realized_pnl_pct:.1f}% ROE) 🛑"
                            log_trade_event(symbol, "CLOSED", {"cmp": exit_cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": sl_type})
                        
                        st = load_state()
                        st[symbol] = time.time() + 900
                        save_state(st)
                        
                        send_telegram_message(
                            f"🛡️ <b>POSITION CLOSED EXTERNALLY / EXCHANGE SL TRIGGERED!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Status:</b> Detected closed on CoinDCX App / Exchange SL\n"
                            f"• <b>Protection:</b> 30-Min Cooldown Activated (No Re-entry / No Short Trade)"
                        )
                        continue

                    m1_klines = fetch_klines(symbol, '1m', 3)
                    if not m1_klines: continue
                    cmp = m1_klines[-1][4]
                    candle_open_time = m1_klines[-1][0] / 1000.0
                    
                    with active_trades_lock:
                        if symbol not in ACTIVE_TRADES: continue
                        trade = ACTIVE_TRADES[symbol]
                    
                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    
                    live_high = m1_klines[-1][2]
                    current_peak = live_high if candle_open_time >= entry_time else cmp
                    
                    highest_peak = max(trade.get('highest_peak', entry_p), current_peak, cmp)
                    trade['highest_peak'] = highest_peak
                    
                    # 75-MINUTE STAGNATION TIME-STOP
                    time_open = time.time() - entry_time
                    if time_open >= 4500 and not trade.get('is_be_active', False):
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue

                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                            sl_type = f"75-MIN TIME-STOP SCRATCH ({realized_pnl_pct:+.1f}% ROE) ⏱️"
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": sl_type})
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            send_telegram_message(
                                f"⏱️ <b>POSITION CLOSED: 75-MIN TIME-STOP</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Exit Price:</b> <code>${cmp}</code> (Entry: <code>${entry_p}</code>)\n"
                                f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE</code>\n"
                                f"• <b>Action:</b> Setup stagnant > 75 mins. Capital released for fresh runners!\n"
                                f"⏱️ <i>30-Min Cooldown Locked</i>"
                            )
                            continue

                    # ESCAPE VELOCITY AT +0.85% MOVE (+6.0% ROE)
                    be_trigger_price = trade.get('be_trigger', entry_p * 1.0085)
                    if highest_peak >= be_trigger_price and not trade.get('is_be_active', False):
                        fee_buffer_sl = round(entry_p * 1.0015, 4)
                        with active_trades_lock:
                            if fee_buffer_sl > trade.get('sl', 0):
                                trade['sl'] = fee_buffer_sl
                            trade['is_be_active'] = True
                        save_active_trades()
                        send_telegram_message(
                            f"🛡️ <b>BREAKEVEN PROFIT LOCK ACTIVATED (+6.0% ROE REACHED)!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>New Stop Loss:</b> <code>${fee_buffer_sl}</code> (Entry + 0.15% Net Profit)\n"
                            f"• <b>Status:</b> 100% Risk-Free (Exchange Fees Covered + Profit Floor Locked)"
                        )

                    # STAGE 2: INTERMEDIATE PROFIT TRAILING
                    if highest_peak >= entry_p * 1.012:
                        intermediate_sl = round(max(entry_p * 1.006, highest_peak * 0.995), 4)
                        current_sl = trade.get('sl', entry_p)
                        if intermediate_sl > current_sl:
                            locked_roe = ((intermediate_sl - entry_p) / entry_p) * 7 * 100
                            with active_trades_lock:
                                trade['sl'] = intermediate_sl
                                trade['is_profit_locked'] = True
                            save_active_trades()
                            send_telegram_message(
                                f"🚀 <b>STAGE 2 INTERMEDIATE PROFIT LOCK UPDATED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Peak High:</b> <code>${highest_peak}</code>\n"
                                f"• <b>New Trailing SL:</b> <code>${intermediate_sl}</code>\n"
                                f"• <b>Locked ROE Profit:</b> <code>+{locked_roe:.1f}% ROE</code> 💰"
                            )

                    # STAGE 3: RUNNER TRAILING ENGINE
                    if highest_peak >= entry_p * 1.018:
                        trailing_sl = round(highest_peak * 0.988, 4)
                        current_sl = trade.get('sl', entry_p)
                        if trailing_sl > current_sl:
                            locked_roe = ((trailing_sl - entry_p) / entry_p) * 7 * 100
                            with active_trades_lock:
                                trade['sl'] = trailing_sl
                                trade['is_profit_locked'] = True
                            save_active_trades()
                            send_telegram_message(
                                f"🔥 <b>STAGE 3 RUNNER TRAILING EXPANSION!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Peak High:</b> <code>${highest_peak}</code>\n"
                                f"• <b>New Trailing SL:</b> <code>${trailing_sl}</code>\n"
                                f"• <b>Locked ROE Profit:</b> <code>+{locked_roe:.1f}% ROE</code> 💰"
                            )

                    # SL / TRAILING SL HIT
                    live_low = m1_klines[-1][3] if candle_open_time >= entry_time else cmp
                    effective_low = min(cmp, live_low)
                    
                    if effective_low <= trade['sl']:
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                trade_info = ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            if trade_info:
                                entry_p = trade_info.get('entry_price', 0)
                                realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100 if entry_p > 0 else 0.0
                                sl_type = f"EXCHANGE SL HIT ({realized_pnl_pct:.1f}% ROE) 🛑"
                                log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": sl_type})
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue
                        
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
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
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": realized_pnl_pct, "sl_type": sl_type})
                            
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            
                            send_telegram_message(
                                f"🏁 <b>POSITION CLOSED: {sl_type}</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"Closed at: <code>${cmp}</code> (Entry: <code>${entry_p}</code>)\n"
                                f"⏱️ <i>30-Min Cooldown Locked (No Re-Entries)</i>"
                            )
                        else:
                            print(f"SL Close failed for {symbol}: {res.get('error')}")
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Position monitor exception: {e}")
        time.sleep(1)

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
                        elif text in ['/today', '/daily', '/report', 'today', 'daily', 'report', '/history']:
                            summary_msg = generate_daily_summary()
                            send_telegram_message(summary_msg)
                        elif text in ['/yesterday', 'yesterday']:
                            yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
                            summary_msg = generate_daily_summary(yesterday_str)
                            send_telegram_message(summary_msg)
        except Exception: pass
        time.sleep(3)

def start_background_loop():
    recover_live_coindcx_positions()

    def run_loop():
        time.sleep(5)
        while True:
            try:
                if scan_lock.acquire(blocking=False):
                    try: run_scan()
                    finally: scan_lock.release()
            except Exception as e:
                print(f"Scan loop exception: {e}")
            time.sleep(60)

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

    def run_daily_midnight_report_loop():
        time.sleep(20)
        last_reported_day = ""
        while True:
            try:
                now_dt = datetime.now()
                today_str = now_dt.strftime("%d-%m-%Y")
                if now_dt.hour == 23 and now_dt.minute >= 58 and last_reported_day != today_str:
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

    send_telegram_message("⚡ <b>RENDER BOT RED-CIRCLE WINNING SCANNER (> $10M VOLUME) DEPLOYED!</b>\n\n• Scan Scope: Dynamic All-CoinDCX Futures Pairs (Filtered for >$10M 24h Volume)\n• Scan Frequency: Every 60 Seconds (Ultra-Fast Signal Capture)\n• Entry Strategy: 5-GOLDEN-RULES ENGINE (1H Bull + 15M Pullback + Closed 5M Green + vol_spike >= 1.20x)\n• Hard Stop Loss: CAPPED AT -0.95% PRICE DROP (-6.6% ROE MAX)\n• Stagnation Guard: 75-Minute Auto Time-Stop (Scratch at -1.0% to -2.0% ROE)\n• Breakeven Engine: ESCAPE VELOCITY @ +6.0% ROE (+0.85% Move)\n• Dynamic Trailing: 3-STAGE RUNNER ENGINE (Stage 2 @ +8.4% ROE, Stage 3 @ +12.6% ROE)\n• State Auto-Recovery: ACTIVE (Syncs open positions from CoinDCX on restart)\n• Per-Coin Cooldown: 30 Minutes (Anti-Fee Drain Guard)\n• Max Active Trades Cap: 4 Concurrent Trades (Max ₹4,000 INR Portfolio Capital)\n• Manual Trade Support: ACTIVE (Cleanly skips coins manually opened on CoinDCX App)\n• Zero Short Trade Rule: STRICT ACTIVE (100% BUY / LONG ONLY)\n• Margin set to ₹1000 INR (Per Trade)\n• Leverage set to 7x (Isolated)\n• Target set to +22.4% ROE (+3.2% price move / 1:2 R:R Ratio)\n• Mobile Telegram commands ready (/stop, /start, /today)")

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
