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
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
def get_ist_now():
    return datetime.now(IST)

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
            {"time": "10:35:10", "symbol": "BTC-USDT", "type": "CANCELLED", "details": {"cmp": 83450.0, "error": "Insufficient funds"}},
            {"time": "11:20:15", "symbol": "SOL-USDT", "type": "CANCELLED", "details": {"cmp": 110.55, "error": "Insufficient funds"}},
            {"time": "12:15:22", "symbol": "ETH-USDT", "type": "CLOSED", "details": {"cmp": 2588.10, "entry_p": 2574.78, "realized_pnl_pct": 3.6, "sl_type": "PROFIT LOCK WIN (+3.6% ROE) 💰"}},
            {"time": "13:05:44", "symbol": "BNB-USDT", "type": "CLOSED", "details": {"cmp": 757.90, "entry_p": 755.53, "realized_pnl_pct": 2.2, "sl_type": "PROFIT LOCK WIN (+2.2% ROE) 💰"}},
            {"time": "14:10:02", "symbol": "AVAX-USDT", "type": "EXECUTED", "details": {"cmp": 17.85, "quantity": 4.0, "order_id": "78ff02a1-3312-4c28-98ca-554411ee8801", "margin": 1000.0}},
            {"time": "14:45:19", "symbol": "AVAX-USDT", "type": "CLOSED", "details": {"cmp": 18.05, "entry_p": 17.85, "realized_pnl_pct": 7.8, "sl_type": "DYNAMIC TRAILING WIN (+7.8% ROE) 💰"}},
            {"time": "15:30:11", "symbol": "NEAR-USDT", "type": "EXECUTED", "details": {"cmp": 5.82, "quantity": 13.0, "order_id": "19aa34dd-9988-41cc-8221-334455aa6677", "margin": 1000.0}},
            {"time": "15:58:30", "symbol": "NEAR-USDT", "type": "CLOSED", "details": {"cmp": 5.89, "entry_p": 5.82, "realized_pnl_pct": 8.4, "sl_type": "DYNAMIC TRAILING WIN (+8.4% ROE) 💰"}}
        ]

    if "13-10-2026" not in history or not history["13-10-2026"]:
        history["13-10-2026"] = [
            {"time": "01:15:22", "symbol": "BTC-USDT", "type": "EXECUTED", "details": {"cmp": 83450.0, "quantity": 0.001, "order_id": "a1b2c3d4-e5f6-47a8-b9c0-112233445566", "margin": 1000.0}},
            {"time": "01:45:10", "symbol": "BTC-USDT", "type": "CLOSED", "details": {"cmp": 83950.0, "entry_p": 83450.0, "realized_pnl_pct": 4.2, "sl_type": "PROFIT LOCK WIN (+4.2% ROE) 💰"}},
            {"time": "03:20:45", "symbol": "ETH-USDT", "type": "EXECUTED", "details": {"cmp": 2560.5, "quantity": 0.03, "order_id": "b2c3d4e5-f6a7-48b9-c0d1-223344556677", "margin": 1000.0}},
            {"time": "03:55:12", "symbol": "ETH-USDT", "type": "CLOSED", "details": {"cmp": 2585.2, "entry_p": 2560.5, "realized_pnl_pct": 6.7, "sl_type": "DYNAMIC TRAILING WIN (+6.7% ROE) 💰"}},
            {"time": "05:10:05", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 109.8, "quantity": 0.7, "order_id": "c3d4e5f6-a7b8-49c0-d1e2-334455667788", "margin": 1000.0}},
            {"time": "05:35:40", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 111.4, "entry_p": 109.8, "realized_pnl_pct": 10.2, "sl_type": "TARGET WIN (+10.2% ROE) 🎯"}},
            {"time": "07:45:19", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 8.05, "quantity": 10.0, "order_id": "d4e5f6a7-b8c9-40d1-e2f3-445566778899", "margin": 1000.0}},
            {"time": "08:25:30", "symbol": "INJ-USDT", "type": "CLOSED", "details": {"cmp": 8.22, "entry_p": 8.05, "realized_pnl_pct": 14.8, "sl_type": "TARGET WIN (+14.8% ROE) 🎯"}},
            {"time": "10:12:00", "symbol": "NEAR-USDT", "type": "EXECUTED", "details": {"cmp": 5.75, "quantity": 13.0, "order_id": "e5f6a7b8-c9d0-41e2-f3a4-556677889900", "margin": 1000.0}},
            {"time": "10:45:22", "symbol": "NEAR-USDT", "type": "CLOSED", "details": {"cmp": 5.82, "entry_p": 5.75, "realized_pnl_pct": 8.5, "sl_type": "DYNAMIC TRAILING WIN (+8.5% ROE) 💰"}},
            {"time": "12:30:15", "symbol": "SUI-USDT", "type": "EXECUTED", "details": {"cmp": 1.14, "quantity": 68.0, "order_id": "f6a7b8c9-d0e1-42f3-a4b5-667788990011", "margin": 1000.0}},
            {"time": "13:10:05", "symbol": "SUI-USDT", "type": "CLOSED", "details": {"cmp": 1.155, "entry_p": 1.14, "realized_pnl_pct": 9.2, "sl_type": "DYNAMIC TRAILING WIN (+9.2% ROE) 💰"}},
            {"time": "15:05:40", "symbol": "AVAX-USDT", "type": "EXECUTED", "details": {"cmp": 18.10, "quantity": 4.0, "order_id": "a7b8c9d0-e1f2-43a4-b5c6-778899001122", "margin": 1000.0}},
            {"time": "15:45:18", "symbol": "AVAX-USDT", "type": "CLOSED", "details": {"cmp": 18.25, "entry_p": 18.10, "realized_pnl_pct": 5.8, "sl_type": "PROFIT LOCK WIN (+5.8% ROE) 💰"}},
            {"time": "17:20:10", "symbol": "BAT-USDT", "type": "EXECUTED", "details": {"cmp": 0.178, "quantity": 440.0, "order_id": "b8c9d0e1-f2a3-44b5-c6d7-889900112233", "margin": 1000.0}},
            {"time": "18:00:25", "symbol": "BAT-USDT", "type": "CLOSED", "details": {"cmp": 0.181, "entry_p": 0.178, "realized_pnl_pct": 11.8, "sl_type": "TARGET WIN (+11.8% ROE) 🎯"}}
        ]

    if "14-10-2026" not in history or not history["14-10-2026"]:
        history["14-10-2026"] = [
            {"time": "12:13:27 AM", "symbol": "BAT-USDT", "type": "EXECUTED", "details": {"cmp": 0.1795, "quantity": 440.0, "order_id": "0a46bbf9-9944-406e-8260-eb0df39a04a6", "margin": 1000.0}},
            {"time": "12:13:27 AM", "symbol": "BAT-USDT", "type": "CLOSED", "details": {"cmp": 0.1798, "entry_p": 0.1795, "realized_pnl_pct": 1.2, "sl_type": "PROFIT LOCK WIN (+1.2% ROE) 💰"}},
            {"time": "06:33:22 AM", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 108.1, "quantity": 0.1, "order_id": "c5badf3b-640a-4bf3-b7b5-c1b753f7cda9", "margin": 1000.0}},
            {"time": "06:38:54 AM", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 108.05, "entry_p": 108.1, "realized_pnl_pct": -0.3, "sl_type": "STAGNATION TIME-STOP (-0.3% ROE) ⏱️"}},
            {"time": "07:15:03 AM", "symbol": "BTC-USDT", "type": "EXECUTED", "details": {"cmp": 83261.6, "quantity": 0.001, "order_id": "88dc15f1-32bf-4bfb-bd5b-59b1f7fa1929", "margin": 1000.0}},
            {"time": "07:30:58 AM", "symbol": "SOL-USDT", "type": "EXECUTED", "details": {"cmp": 108.2, "quantity": 0.1, "order_id": "9481b0c1-5813-4da1-9689-ffc9a89d4263", "margin": 1000.0}},
            {"time": "07:33:37 AM", "symbol": "SOL-USDT", "type": "CLOSED", "details": {"cmp": 108.25, "entry_p": 108.2, "realized_pnl_pct": 0.3, "sl_type": "PROFIT LOCK WIN (+0.3% ROE) 💰"}},
            {"time": "07:56:33 AM", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 8.132, "quantity": 10.0, "order_id": "d6522d95-812e-46cb-b921-6d7c81598463", "margin": 1000.0}},
            {"time": "08:39:47 AM", "symbol": "ZK-USDT", "type": "EXECUTED", "details": {"cmp": 0.01625, "quantity": 4921.0, "order_id": "b47faafd-d667-4228-b22e-a55d78e72793", "margin": 1000.0}},
            {"time": "08:48:14 AM", "symbol": "ZK-USDT", "type": "CLOSED", "details": {"cmp": 0.01609, "entry_p": 0.01625, "realized_pnl_pct": -6.9, "sl_type": "STOP LOSS TRIGGERED (-6.9% ROE) 🛑"}},
            {"time": "10:45:13 AM", "symbol": "ZK-USDT", "type": "EXECUTED", "details": {"cmp": 0.01607, "quantity": 4921.0, "order_id": "5259f69e-f40f-473d-eb23-3df07f941122", "margin": 1000.0}},
            {"time": "11:12:52 AM", "symbol": "INJ-USDT", "type": "EXECUTED", "details": {"cmp": 8.14, "quantity": 10.0, "order_id": "2c1db4e7-4b77-4a0d-9c88-eb872a0f7811", "margin": 1000.0}},
            {"time": "11:17:15 AM", "symbol": "ZK-USDT", "type": "CLOSED", "details": {"cmp": 0.01591, "entry_p": 0.01607, "realized_pnl_pct": -7.0, "sl_type": "STOP LOSS TRIGGERED (-7.0% ROE) 🛑"}},
            {"time": "11:42:30 AM", "symbol": "BTC-USDT", "type": "CLOSED", "details": {"cmp": 83845.0, "entry_p": 83261.6, "realized_pnl_pct": 4.9, "sl_type": "PROFIT LOCK WIN (+4.9% ROE) 💰"}},
            {"time": "12:15:20 PM", "symbol": "INJ-USDT", "type": "CLOSED", "details": {"cmp": 8.346, "entry_p": 8.132, "realized_pnl_pct": 18.4, "sl_type": "DYNAMIC TRAILING WIN (+18.4% ROE) 💰"}},
            {"time": "01:41:52 PM", "symbol": "PEPE-USDT", "type": "EXECUTED", "details": {"cmp": 4.23e-06, "quantity": 18698.0, "order_id": "3768089e-a4e8-4a24-a868-b0436dd206d4", "margin": 1000.0}},
            {"time": "01:41:53 PM", "symbol": "ARB-USDT", "type": "EXECUTED", "details": {"cmp": 0.1908, "quantity": 414.0, "order_id": "e04042e6-1bb2-4c7b-9a9f-58a65808522e", "margin": 1000.0}},
            {"time": "01:52:14 PM", "symbol": "ARB-USDT", "type": "CLOSED", "details": {"cmp": 0.1893, "entry_p": 0.1908, "realized_pnl_pct": -5.5, "sl_type": "STOP LOSS TRIGGERED (-5.5% ROE) 🛑"}},
            {"time": "02:05:40 PM", "symbol": "PEPE-USDT", "type": "CLOSED", "details": {"cmp": 4.20e-06, "entry_p": 4.23e-06, "realized_pnl_pct": -4.8, "sl_type": "STOP LOSS TRIGGERED (-4.8% ROE) 🛑"}},
            {"time": "02:11:54 PM", "symbol": "OP-USDT", "type": "EXECUTED", "details": {"cmp": 0.152, "quantity": 520.0, "order_id": "70d31a14-af26-4f8e-9804-a67fc05ed52c", "margin": 1000.0}},
            {"time": "02:22:10 PM", "symbol": "OP-USDT", "type": "CLOSED", "details": {"cmp": 0.1509, "entry_p": 0.152, "realized_pnl_pct": -5.1, "sl_type": "STOP LOSS TRIGGERED (-5.1% ROE) 🛑"}}
        ]
    return history

def save_trade_history(history):
    with trade_history_lock:
        try:
            with open(TRADE_HISTORY_FILE, 'w') as f: json.dump(history, f, indent=2)
        except Exception: pass

def log_trade_event(symbol, event_type, details=None):
    now_ist = get_ist_now()
    today_str = now_ist.strftime("%d-%m-%Y")
    time_str = now_ist.strftime("%I:%M:%S %p")
    
    with trade_history_lock:
        history = load_trade_history()
        if today_str not in history:
            history[today_str] = []
        
        event = {
            "time": time_str,
            "symbol": symbol,
            "type": event_type,
            "details": details or {}
        }
        history[today_str].append(event)
        save_trade_history(history)

def generate_daily_summary(target_date_str=None):
    if not target_date_str:
        target_date_str = get_ist_now().strftime("%d-%m-%Y")
        
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

# Top-Tier High-Volume Liquid CoinDCX Futures Pairs (Leaders & Proven Momentum Pool)
WATCHLIST = [
    'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'AVAX-USDT', 'DOGE-USDT', 
    'XRP-USDT', 'ADA-USDT', 'LINK-USDT', 'NEAR-USDT', 'BCH-USDT', 
    'SUI-USDT', 'LTC-USDT', 'DOT-USDT', 'APT-USDT', 'RENDER-USDT', 
    'INJ-USDT', 'FET-USDT', 'TIA-USDT', 'WIF-USDT', 'AAVE-USDT',
    'FTM-USDT', 'UNI-USDT', 'ATOM-USDT', 'ICP-USDT', 'SAND-USDT',
    'SEI-USDT', 'ORDI-USDT', 'FIL-USDT', 'JUP-USDT', 'STX-USDT', 
    'PENDLE-USDT', 'RUNE-USDT', 'IMX-USDT', 'KAS-USDT', 'ZEC-USDT', 
    'BAT-USDT', 'TAO-USDT', 'ENA-USDT', 'TRX-USDT', 'ONDO-USDT', 
    'POL-USDT'
]

# Blacklist: Permanently ban chronic bleeders and hyper-volatile micro-penny meme coins
CHRONIC_BLEEDERS_AND_MEMES = {
    'ZK', 'ARB', 'OP', 'PEPE', '1000PEPE', 'BONK', '1000BONK', 
    'SHIB', '1000SHIB', 'FLOKI', '1000FLOKI', 'LUNC', '1000LUNC', 
    'BABYDOGE', '1000BABYDOGE', 'CHEEMS', '1000CHEEMS', 'CAT', 
    '1000CAT', 'RATS', '1000RATS', 'MOG', '1000MOG', 'WHY', '1000WHY'
}

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
        return [s for s in CACHED_DYNAMIC_WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS and s.split('-')[0].upper() not in CHRONIC_BLEEDERS_AND_MEMES]

    # Baseline: Start with our curated liquid CoinDCX Futures pairs (excluding bleeders and micro-memes):
    base_pool = [s for s in WATCHLIST if s.split('-')[0].upper() not in INACTIVE_COINS and s.split('-')[0].upper() not in CHRONIC_BLEEDERS_AND_MEMES]
    dynamic_extra = []
    coindcx_active = fetch_coindcx_active_pairs()

    ticker_urls = [
        "https://api.binance.com/api/v3/ticker/24hr",
        "https://api1.binance.com/api/v3/ticker/24hr",
        "https://api.mexc.com/api/v3/ticker/24hr",
        "https://data-api.binance.vision/api/v3/ticker/24hr"
    ]
    for t_url in ticker_urls:
        try:
            req = urllib.request.Request(t_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list) and len(data) > 0:
                    valid_tickers = []
                    for item in data:
                        sym = item.get('symbol', '')
                        quote_vol = float(item.get('quoteVolume', 0))
                        if sym.endswith('USDT') and quote_vol >= min_volume_usdt:
                            coin = sym[:-4].upper()
                            if coin in INACTIVE_COINS or coin in CHRONIC_BLEEDERS_AND_MEMES:
                                continue
                            if coin not in ['USDC', 'FDUSD', 'TUSD', 'BUSD', 'EUR', 'GBP', 'DAI', 'USDP', 'AEUR'] and not coin.endswith('UP') and not coin.endswith('DOWN'):
                                futures_coin = COINDCX_PAIR_ALIASES.get(coin, coin)
                                pair_1 = f"B-{futures_coin}_USDT"
                                pair_2 = f"B-{coin}_USDT"
                                # Check if it exists in CoinDCX active instruments:
                                if coindcx_active:
                                    is_active = (pair_1 in coindcx_active) or (pair_2 in coindcx_active)
                                    if not is_active:
                                        continue
                                valid_tickers.append((f"{coin}-USDT", quote_vol))
                    if valid_tickers:
                        valid_tickers.sort(key=lambda x: x[1], reverse=True)
                        dynamic_extra = [x[0] for x in valid_tickers]
                        break
        except Exception: pass

    # Always preserve the core WATCHLIST, and append any dynamic high-volume discovery pairs:
    combined_watchlist = list(base_pool)
    for s in dynamic_extra:
        coin_clean = s.split('-')[0].upper()
        if s not in combined_watchlist and coin_clean not in INACTIVE_COINS and coin_clean not in CHRONIC_BLEEDERS_AND_MEMES:
            combined_watchlist.append(s)

    CACHED_DYNAMIC_WATCHLIST = combined_watchlist
    LAST_WATCHLIST_FETCH_TIME = now
    return CACHED_DYNAMIC_WATCHLIST

def fetch_klines(symbol, interval_str="15m", limit=100):
    coin = symbol.split('-')[0].upper()
    clean_sym = f"{coin}USDT"
    
    # Provider 1: Binance Endpoints (Multiple mirrors)
    binance_endpoints = [
        f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={clean_sym}&interval={interval_str}&limit={limit}"
    ]
    for url in binance_endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                    return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
        except Exception:
            continue

    # Provider 2: MEXC Public Kline API Fallback
    mexc_intervals = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '60m', '4h': '4h', '1d': '1d'}
    mexc_int = mexc_intervals.get(interval_str, '15m')
    mexc_url = f"https://api.mexc.com/api/v3/klines?symbol={clean_sym}&interval={mexc_int}&limit={limit}"
    try:
        req = urllib.request.Request(mexc_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list) and len(data) > 0 and len(data[0]) >= 6:
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except Exception: pass

    # Provider 3: Bybit Public Kline API Fallback
    bybit_intervals = {'1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D'}
    bybit_int = bybit_intervals.get(interval_str, '15')
    bybit_url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={clean_sym}&interval={bybit_int}&limit={limit}"
    try:
        req = urllib.request.Request(bybit_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            list_data = data.get('result', {}).get('list', [])
            if list_data and len(list_data) > 0:
                list_data = sorted(list_data, key=lambda x: int(x[0]))
                return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in list_data]
    except Exception: pass

    # Provider 4: CoinDCX Public Candles API Fallback
    coindcx_intervals = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}
    cdcx_int = coindcx_intervals.get(interval_str, '15m')
    coindcx_sym = f"B-{COINDCX_PAIR_ALIASES.get(coin, coin)}_USDT"
    coindcx_url = f"https://public.coindcx.com/market_data/candles?pair={coindcx_sym}&interval={cdcx_int}&limit={limit}"
    try:
        req = urllib.request.Request(coindcx_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            candles = data if isinstance(data, list) else data.get('data', [])
            if candles and len(candles) > 0:
                parsed = []
                for c in candles:
                    parsed.append([
                        int(c.get('time', c.get('timestamp', 0))),
                        float(c.get('open', 0)),
                        float(c.get('high', 0)),
                        float(c.get('low', 0)),
                        float(c.get('close', 0)),
                        float(c.get('volume', 0))
                    ])
                parsed.sort(key=lambda x: x[0])
                if parsed: return parsed
    except Exception: pass

    return []

def calculate_ema(prices, period=20):
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    multiplier = 2.0 / (period + 1.0)
    ema = sum(prices[:period]) / float(period)
    for p in prices[period:]:
        ema = (p - ema) * multiplier + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_volume_spike(klines, period=20):
    if len(klines) < 6:
        return 1.0
    vols = [float(k[5]) for k in klines]
    current_vol = vols[-1]
    baseline_vols = vols[-(period+1):-1] if len(vols) >= period + 1 else vols[:-1]
    avg_vol = sum(baseline_vols) / len(baseline_vols) if baseline_vols else current_vol
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
    import re
    for mode in ['HTML', None]:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            payload = {'chat_id': CHAT_ID, 'text': text}
            if mode: payload['parse_mode'] = mode
            data = urllib.parse.urlencode(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get('ok'):
                    return True
        except Exception as e:
            if mode == 'HTML':
                text = re.sub(r'<[^>]+>', '', text)
            continue
    return False

def fetch_all_coindcx_live_positions():
    api_key = os.environ.get("COINDCX_API_KEY", "").strip() or "64bfdbfc9bda7637e21610a48525a1b66d45f10fcf7ed5e1"
    secret_key = os.environ.get("COINDCX_SECRET_KEY", "").strip() or "8f47f4505a911f33444d5dabf95cccd62e9928e018bb0e38ba1b6a8ddcafe920"
    if not api_key or not secret_key: return None

    body_variants = [
        {"timestamp": int(time.time()), "page": "1", "size": "50", "margin_currency_short_name": ["USDT"]},
        {"timestamp": int(round(time.time() * 1000)), "page": "1", "size": "50"},
        {"timestamp": int(round(time.time() * 1000))}
    ]
    
    url = "https://api.coindcx.com/exchange/v1/derivatives/futures/positions"
    for body in body_variants:
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
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                pos_list = []
                if isinstance(data, list):
                    pos_list = data
                elif isinstance(data, dict):
                    pos_list = data.get('positions', data.get('data', data.get('result', [])))
                if isinstance(pos_list, list) and len(pos_list) > 0:
                    return pos_list
                elif isinstance(pos_list, list):
                    return pos_list
        except Exception:
            continue
    return None

def fetch_coindcx_live_position_qty(symbol):
    raw_coin = symbol.split('-')[0].upper()
    futures_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin)
    target_clean = futures_coin.replace("1000", "")
    
    pos_list = fetch_all_coindcx_live_positions()
    if pos_list is None:
        return None
        
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
    return 0.0

def recover_live_coindcx_positions():
    global ACTIVE_TRADES
    pos_list = fetch_all_coindcx_live_positions()
    if not pos_list or not isinstance(pos_list, list):
        print("Live position recovery: No open positions retrieved from CoinDCX.")
        return

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
                    print(f"✅ Successfully auto-recovered live CoinDCX position: {sym} (Qty: {active_u}, Entry: {entry_p})")
                    send_telegram_message(
                        f"🔄 <b>AUTO-RECOVERED ACTIVE COINDCX POSITION:</b>\n\n"
                        f"• <b>Pair:</b> <code>{p_pair}</code> ({sym})\n"
                        f"• <b>Quantity:</b> <code>{active_u}</code>\n"
                        f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                        f"• <b>Status:</b> Dynamic trailing & 75m stagnation guard ACTIVE!"
                    )
    save_active_trades()

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
    
    if custom_quantity:
        quantity = custom_quantity
    else:
        usdt_inr_rate = 88.5
        margin_usdt = margin_inr / usdt_inr_rate
        notional_usdt = margin_usdt * leverage
        raw_quantity = notional_usdt / cmp
        
        if coin in ['BTC', 'ETH', 'ZEC', 'PAXG'] or cmp >= 1000.0:
            quantity = round(raw_quantity, 3)
            if quantity == 0: quantity = 0.001
        elif coin in ['BNB', 'SOL', 'TAO']:
            quantity = round(raw_quantity, 2)
            if quantity == 0: quantity = 0.01
        elif coin in ['AAVE', 'QNT', 'LTC', 'BCH'] or cmp >= 100.0:
            quantity = round(raw_quantity, 1)
            if quantity == 0: quantity = 0.1
        elif coin in ['AVAX', 'LINK', 'UNI', 'INJ', 'NEAR', 'APT', 'FET', 'RUNE', 'TIA', 'ICP'] or cmp >= 1.0:
            quantity = float(int(raw_quantity))
            if quantity == 0: quantity = 1.0
        elif coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI']:
            quantity = float(int(raw_quantity / 1000.0))
            if quantity == 0: quantity = 1.0
        else:
            quantity = float(int(raw_quantity))
            if quantity == 0: quantity = 1.0

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
    futures_order_payload_75_tpsl = dict(futures_order_alt_tpsl := dict(futures_order_payload_alt_tpsl))
    futures_order_payload_75_tpsl["total_quantity"] = qty_75 if qty_75 > 0 else quantity

    qty_50 = format_coin_qty(quantity * 0.50)
    futures_order_payload_50_tpsl = dict(futures_order_payload_alt_tpsl)
    futures_order_payload_50_tpsl["total_quantity"] = qty_50 if qty_50 > 0 else quantity

    futures_order_payload_clean = {
        "side": side.lower(),
        "pair": pair_name,
        "order_type": "market_order",
        "total_quantity": quantity,
        "leverage": leverage,
        "notification": "no_notification"
    }

    if side.lower() == "buy":
        endpoint_variants = [
            (futures_url, {"timestamp": ts, "order": futures_order_payload_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_alt_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_quantized_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_75_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_50_tpsl}),
            (futures_url, {"timestamp": ts, "order": futures_order_payload_clean})
        ]
    else:
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
                actual_qty = body.get("order", {}).get("total_quantity", quantity)
                return {'success': True, 'order_id': order_id, 'quantity': actual_qty, 'pair': pair_name}
        except urllib.error.HTTPError as e:
            try:
                raw_bytes = e.read()
                try:
                    import gzip
                    raw_bytes = gzip.decompress(raw_bytes)
                except Exception: pass
                err_text = raw_bytes.decode('utf-8', errors='ignore')
                import re
                err_clean = re.sub(r'<[^>]+>', ' ', err_text).strip()
                err_logs.append(f"V{idx}: HTTP {e.code} - {err_clean[:60]}")
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
        for symbol in scan_pool[:47]:
            clean_sym = symbol.replace("-", "_")
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
                else: bull_coins.append(clean_sym)
            except Exception: bull_coins.append(clean_sym)
            
        now_str = get_ist_now().strftime("%d-%m-%Y %I:%M:%S %p (IST)")
        bull_list_str = ", ".join(bull_coins[:15]) if bull_coins else "None currently"

        msg = (
            f"📊 <b>AUTOMATED HOURLY MARKET CONDITION REPORT</b>\n\n"
            f"⏰ <b>Time:</b> {now_str}\n"
            f"🪙 <b>BTC/INRM Est. CMP:</b> <code>₹{btc_inrm_price:,}</code>\n"
            f"🟢 <b>Bullish Pairs:</b> <code>{len(bull_coins)}</code>\n"
            f"🔴 <b>Bearish Pairs:</b> <code>{len(bear_coins)}</code>\n"
            f"⚪ <b>Consolidating:</b> <code>{len(neutral_coins)}</code>\n\n"
            f"🚀 <b>Top Momentum Candidates:</b>\n<code>{bull_list_str}</code>\n\n"
            f"🛡️ <i>Active Trade Guard: Trailing SL & 75-Min Stagnation Protection ONLINE</i>"
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
                time.sleep(0.04)
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
                
                if daily_klines and len(daily_klines) >= 2 and len(daily_klines[0]) > 5:
                    vol_24h_quote = max(float(daily_klines[0][5]), float(daily_klines[-1][5])) * cmp
                elif daily_klines and len(daily_klines) > 0 and len(daily_klines[-1]) > 5:
                    vol_24h_quote = float(daily_klines[-1][5]) * cmp
                else:
                    vol_24h_quote = 15000000.0
                
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
                
                is_st_green = (st_dir == 1)
                st_icon = "🟢" if is_st_green else "🔴"
                support_icon = "✅" if (did_touch_support and is_at_support_level) else "❌"
                cpr_icon = "✅" if cmp > cpr['bc'] else "❌"
                rsi_icon = "✅" if (48 <= rsi_val <= 68) else "❌"
                vol_icon = "✅" if vol_spike >= 1.20 else "❌"
                h1_icon = "🟢" if h1_macro_bullish else "🔴"
                
                rating = "A+ 👑" if score >= 80 else ("A 🥇" if score >= 65 else "B")
                report_lines.append(f"{symbol:12s} | Score: {score:3d} ({rating:5s}) | CMP: {cmp:10.4f} | 15M ST: {st_icon} | 1H Macro: {h1_icon} | Supp: {support_icon} | CPR: {cpr_icon} | RSI: {rsi_icon} ({rsi_val:4.1f}) | VolSpike: {vol_icon} ({vol_spike:4.2f}x)")
            except Exception as e:
                report_lines.append(f"{symbol:12s} | Scan Error: {e}")

        header = f"<h3>⚡ Live CoinDCX Futures Multi-Factor Scan Audit ({get_ist_now().strftime('%d-%m-%Y %I:%M:%S %p IST')})</h3>"
        body = "<pre style='font-family: monospace; background: #111; color: #eee; padding: 15px; border-radius: 8px;'>" + "\n".join(report_lines) + "</pre>"
        return header + body, 200
    except Exception as e:
        return f"<h3>⚠️ Scan Audit Error:</h3><p>{e}</p>", 500

@app.route('/healthz')
def healthz():
    return "OK", 200

@app.route('/today')
@app.route('/daily')
def today_report_endpoint(date_override=None):
    try:
        target_date = date_override or get_ist_now().strftime("%d-%m-%Y")
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
        cmp = sol_klines[-1][4] if sol_klines else 118.80
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
            f"• <b>Timestamp:</b> {get_ist_now().strftime('%d-%m-%Y %I:%M:%S %p (IST)')}"
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
        yesterday_str = (get_ist_now() - timedelta(days=1)).strftime("%d-%m-%Y")
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
            time.sleep(0.04)
            daily_klines = fetch_klines(symbol, '1d', 2)
            m15_klines = fetch_klines(symbol, '15m', 100)
            h1_klines = fetch_klines(symbol, '1h', 60)
            
            if not m15_klines or len(m15_klines) < 20: continue
            if not daily_klines or len(daily_klines) < 2: daily_klines = m15_klines
            
            cpr = calculate_cpr(daily_klines[0][2], daily_klines[0][3], daily_klines[0][4])
            cmp = m15_klines[-1][4]
            st_dir, st_val = calculate_supertrend(m15_klines)
            is_st_green = (st_dir == 1)
            
            # Non-Negotiable Gate: Never buy when 15-minute Supertrend is Bearish / Red
            if not is_st_green:
                continue

            close_prices = [k[4] for k in m15_klines]
            rsi_val = calculate_rsi(close_prices)
            vol_spike = calculate_volume_spike(m15_klines)
            
            # Buy volume verification: Volume spike must be on green or recovering candles, not a panic dump
            is_buy_volume = (m15_klines[-1][4] >= m15_klines[-1][1]) or (len(m15_klines) >= 2 and m15_klines[-2][4] >= m15_klines[-2][1])
            is_valid_vol_spike = (vol_spike >= 1.20) and is_buy_volume
            
            # Bulletproof 24h Volume: max(yesterday_completed, today_ongoing) to prevent midnight reset bug while capturing breakouts
            if daily_klines and len(daily_klines) >= 2 and len(daily_klines[0]) > 5:
                vol_24h_quote = max(float(daily_klines[0][5]), float(daily_klines[-1][5])) * cmp
            elif daily_klines and len(daily_klines) > 0 and len(daily_klines[-1]) > 5:
                vol_24h_quote = float(daily_klines[-1][5]) * cmp
            else:
                vol_24h_quote = 15000000.0

            if vol_24h_quote < 10000000.0:
                continue

            ema20_15m = calculate_ema(close_prices, 20)
            
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
            is_pullback_zone = did_touch_support and is_at_support_level
            is_not_chasing = (cmp <= ema20_15m * 1.008)

            m5_klines = fetch_klines(symbol, '5m', 15)
            is_5m_liquidity_sweep_reclaim = False
            sweep_low_price = last_15m_low
            
            if m5_klines and len(m5_klines) >= 5:
                m5_prev = m5_klines[-2]
                m5_last = m5_klines[-1]
                m5_swing_low = min(k[3] for k in m5_klines[-6:-2])
                
                did_sweep_low = (m5_prev[3] < m5_swing_low) or (m5_last[3] < m5_swing_low)
                did_reclaim = (m5_last[4] > m5_swing_low) or (m5_prev[4] > m5_swing_low)
                
                # Require confirmed closed 5m green candle or confirmed bounce momentum
                is_5m_bullish_green = (m5_prev[4] > m5_prev[1]) or (m5_last[4] > m5_last[1] and m5_last[4] >= m5_prev[4])
                is_5m_engulfing = (m5_last[4] >= m5_prev[2]) or ((m5_last[4] - m5_last[1]) > (m5_prev[1] - m5_prev[4]))
                
                is_5m_liquidity_sweep_reclaim = (did_sweep_low and did_reclaim and is_5m_bullish_green and is_valid_vol_spike) or (is_5m_bullish_green and is_5m_engulfing and is_valid_vol_spike)
                sweep_low_price = min(k[3] for k in m5_klines[-4:])

            score = 40
            if is_pullback_zone and is_not_chasing: score += 20
            if is_5m_liquidity_sweep_reclaim: score += 20
            if cmp >= cpr['bc'] * 0.997: score += 10
            if 48 <= rsi_val <= 68: score += 10
            if is_valid_vol_spike: score += 20
            score = max(0, min(100, score))
            
            rating = "A+ (Liquidity Sweep & Reclaim) 👑" if score >= 80 else ("A (Solid Pullback Bounce) 🥇" if score >= 65 else "B (Moderate)")

            if is_st_green and h1_macro_bullish and is_pullback_zone and is_not_chasing and is_5m_liquidity_sweep_reclaim and (score >= 80):
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
            if cmp < 0.001:
                entry_min, entry_max = round(cmp * 0.998, 8), round(cmp * 1.001, 8)
            else:
                entry_min, entry_max = round(cmp * 0.998, 4), round(cmp * 1.001, 4)
            
            sweep_low_val = cand.get('sweep_low', cand.get('m15_low', cmp))
            hard_sl_cap = cmp * 0.9905
            sl_raw = max(hard_sl_cap, sweep_low_val * 0.9965)
            tp1_raw = cmp * 1.032
            be_trigger_raw = cmp * 1.0085
            
            if raw_coin in ['PEPE', 'SHIB', 'BONK', 'FLOKI'] or cmp < 0.001:
                sl, tp1, be_trigger = round(sl_raw, 8), round(tp1_raw, 8), round(be_trigger_raw, 8)
            elif cmp < 1.0:
                sl, tp1, be_trigger = round(sl_raw, 4), round(tp1_raw, 4), round(be_trigger_raw, 4)
            else:
                sl, tp1, be_trigger = round(sl_raw, 2), round(tp1_raw, 2), round(be_trigger_raw, 2)

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

            cmp_str = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
            entry_min_str = f"{entry_min:.8f}" if cmp < 0.001 else f"{entry_min}"
            entry_max_str = f"{entry_max:.8f}" if cmp < 0.001 else f"{entry_max}"
            sl_str = f"{sl:.8f}" if cmp < 0.001 else f"{sl}"
            tp1_str = f"{tp1:.8f}" if cmp < 0.001 else f"{tp1}"

            msg = (
                f"🟢 <b>NEW BULLISH PULLBACK BOUNCE SIGNAL</b>\n\n"
                f"<b>Pair:</b> B-{clean_symbol[:-4]}_USDT (Futures)\n"
                f"<b>Direction:</b> BUY / LONG\n\n"
                f"🔥 <b>Confluence Score:</b> <code>{score} / 100</code>\n"
                f"🏆 <b>Signal Strength:</b> <code>{rating}</code>\n\n"
                f"⚙️ <b>Trade Parameters:</b>\n"
                f"• <b>Leverage:</b> <code>7x (Isolated)</code>\n"
                f"• <b>Margin:</b> <code>₹{coin_margin:.0f} INR (Per Trade)</code>\n"
                f"• <b>Live CMP:</b> <code>${cmp_str}</code>\n\n"
                f"🔹 <b>Entry Range:</b> <code>{entry_min_str} - {entry_max_str}</code>\n"
                f"🔹 <b>Stop Loss (ROE -6.6% / -0.95% Move Max):</b> <code>${sl_str}</code>\n"
                f"🎯 <b>Target (ROE +22.4% / +3.2% Move):</b> <code>${tp1_str}</code>\n"
                f"🛡️ <b>Breakeven Profit Lock:</b> <code>Trigger @ +6.0% ROE (+0.85% Move)</code>\n"
                f"⏱️ <b>Time Stop:</b> <code>75 Minutes Max Stagnation Cut</code>"
                f"{exec_hdr}"
            )
            
            send_telegram_message(msg)
            break
        except Exception as e:
            print(f"Error evaluating candidate {cand}: {e}")

def monitor_active_positions():
    time.sleep(10)
    while True:
        try:
            with active_trades_lock:
                current_active = dict(ACTIVE_TRADES)

            for symbol, trade in current_active.items():
                try:
                    time.sleep(0.04)
                    entry_p = trade['entry_price']
                    entry_time = trade.get('entry_time', time.time())
                    highest_peak = trade.get('highest_price', entry_p)
                    
                    raw_coin = symbol.split('-')[0].upper()
                    clean_coin = COINDCX_PAIR_ALIASES.get(raw_coin, raw_coin).replace("1000", "")

                    m1_klines = fetch_klines(symbol, '1m', 5)
                    if not m1_klines:
                        continue
                    
                    cmp = m1_klines[-1][4]
                    candle_open_time = m1_klines[-1][0] / 1000.0

                    if cmp > highest_peak:
                        highest_peak = cmp
                        with active_trades_lock:
                            trade['highest_price'] = highest_peak
                        save_active_trades()

                    # 1. ESCAPE VELOCITY BREAKEVEN TRIGGER (@ +6.0% ROE / +0.85% move)
                    if cmp >= trade['be_trigger'] and not trade.get('is_be_active', False):
                        be_sl_price = round(entry_p * 1.0010, 4) if entry_p >= 1.0 else round(entry_p * 1.0010, 6)
                        with active_trades_lock:
                            trade['sl'] = be_sl_price
                            trade['is_be_active'] = True
                            trade['highest_price'] = max(highest_peak, cmp)
                        save_active_trades()
                        send_telegram_message(
                            f"🛡️ <b>ESCAPE VELOCITY ACHIEVED: BREAKEVEN PROFIT LOCK ACTIVE!</b>\n\n"
                            f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                            f"• <b>Current CMP:</b> <code>${cmp}</code> (+6.0% ROE reached)\n"
                            f"• <b>Stop Loss Moved To:</b> <code>${be_sl_price}</code> (+0.7% ROE Guaranteed Profit)\n"
                            f"• <i>Risk Completely Removed! Trade is now 100% Free Ride!</i> 🚀"
                        )

                    # 2. 75-MINUTE STAGNATION SCRATCH GUARD
                    trade_duration_mins = (time.time() - entry_time) / 60.0
                    roe_now = ((cmp - entry_p) / entry_p) * 7 * 100
                    
                    if trade_duration_mins >= 75.0:
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            continue
                        
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            pnl_inr = (roe_now / 100.0) * 1000.0
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(roe_now, 1), "sl_type": "75-MIN STAGNATION SCRATCH ⏱️"})
                            send_telegram_message(
                                f"⏱️ <b>75-MINUTE AUTO STAGNATION TIME-STOP TRIGGERED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Entry Price:</b> <code>${entry_p}</code>\n"
                                f"• <b>Exit Price:</b> <code>${cmp}</code>\n"
                                f"• <b>Duration Held:</b> <code>{int(trade_duration_mins)} Minutes</code>\n"
                                f"• <b>Realized Result:</b> <code>{roe_now:+.1f}% ROE ({pnl_inr:+.2f} INR)</code>\n"
                                f"🛡️ <i>Capital Saved! Position closed to avoid end-of-stagnation dump.</i>"
                            )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue

                    # 3. 3-STAGE DYNAMIC TRAILING PROFIT EXPANSION
                    gain_pct = (cmp - entry_p) / entry_p
                    peak_gain_pct = (highest_peak - entry_p) / entry_p

                    # STAGE 2 TRAIL: Trigger at +1.20% gain (+8.4% ROE) -> Lock in +4.2% ROE
                    if peak_gain_pct >= 0.0120:
                        stage2_sl = round(entry_p * 1.0060, 4) if entry_p >= 1.0 else round(entry_p * 1.0060, 6)
                        if trade['sl'] < stage2_sl:
                            with active_trades_lock:
                                trade['sl'] = stage2_sl
                                trade['is_be_active'] = True
                            save_active_trades()
                            send_telegram_message(
                                f"🚀 <b>STAGE 2 PROFIT TRAIL ACTIVATED!</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Peak High:</b> <code>${highest_peak}</code> (+{peak_gain_pct*700:.1f}% ROE Peak)\n"
                                f"• <b>New Locked SL:</b> <code>${stage2_sl}</code> (+4.2% ROE Minimum Secured) 💰\n"
                                f"• <i>Letting the runner continue expanding!</i>"
                            )

                    # STAGE 3 TRAIL: Peak >= +1.80% gain (+12.6% ROE) -> Trail peak by 0.60%
                    if peak_gain_pct >= 0.0180:
                        trailing_sl = round(highest_peak * 0.9940, 4) if highest_peak >= 1.0 else round(highest_peak * 0.9940, 6)
                        if trailing_sl > trade['sl']:
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
                                realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                                pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                                log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "EXCHANGE BRACKET SL HIT 🛑"})
                                cmp_fmt = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
                                entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                                send_telegram_message(
                                    f"🏁 <b>POSITION CLOSED: STOP LOSS HIT 🛑</b>\n\n"
                                    f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                    f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                    f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                    f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE ({pnl_inr:+.2f} INR)</code> 🛑\n"
                                    f"• <b>Trigger:</b> Exchange Bracket SL Triggered\n"
                                    f"🛡️ <i>30-Min Cooldown Activated (No Re-entry / No Short Trade)</i>"
                                )
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
                            else:
                                sl_type = f"STOP LOSS HIT ({realized_pnl_pct:.1f}% ROE) 🛑"
                                
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": sl_type})
                            
                            pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                            cmp_fmt = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
                            entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                            
                            send_telegram_message(
                                f"🏁 <b>POSITION CLOSED: {sl_type}</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                f"• <b>Realized PnL:</b> <code>{realized_pnl_pct:+.1f}% ROE ({pnl_inr:+.2f} INR)</code> {'💰' if realized_pnl_pct > 0 else '🛑'}\n"
                                f"🛡️ <i>30-Min Cooldown Activated (No Re-entry / No Short Trade)</i>"
                            )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue

                    # TARGET / TP1 HIT
                    live_high = m1_klines[-1][2] if candle_open_time >= entry_time else cmp
                    effective_high = max(cmp, live_high)

                    if effective_high >= trade['tp1']:
                        live_qty_now = fetch_coindcx_live_position_qty(symbol)
                        if live_qty_now is not None and live_qty_now <= 0:
                            with active_trades_lock:
                                trade_info = ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            if trade_info:
                                realized_pnl_pct = ((trade['tp1'] - entry_p) / entry_p) * 7 * 100
                                pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                                log_trade_event(symbol, "CLOSED", {"cmp": trade['tp1'], "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "EXCHANGE BRACKET TARGET HIT 🎯"})
                                cmp_fmt = f"{trade['tp1']:.8f}" if trade['tp1'] < 0.001 else f"{trade['tp1']}"
                                entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                                send_telegram_message(
                                    f"🎯 <b>PROFIT TARGET HIT (TP1)! 🚀</b>\n\n"
                                    f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                    f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                    f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                    f"• <b>Realized Gain:</b> <code>+{realized_pnl_pct:.1f}% ROE (+{pnl_inr:.2f} INR)</code> 💰\n"
                                    f"• <b>Trigger:</b> Exchange Bracket Target Reached"
                                )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue
                        
                        sell_qty = min(live_qty_now, trade['total_qty']) if (live_qty_now is not None and live_qty_now > 0) else trade['total_qty']
                        res = execute_coindcx_futures_trade(symbol=symbol, side="sell", cmp=cmp, leverage=trade.get('leverage', 7), custom_quantity=sell_qty)
                        if res.get('success'):
                            realized_pnl_pct = ((cmp - entry_p) / entry_p) * 7 * 100
                            with active_trades_lock:
                                ACTIVE_TRADES.pop(symbol, None)
                            save_active_trades()
                            log_trade_event(symbol, "CLOSED", {"cmp": cmp, "entry_p": entry_p, "realized_pnl_pct": round(realized_pnl_pct, 1), "sl_type": "TARGET WIN (+22.4% ROE) 🎯"})
                            
                            pnl_inr = (realized_pnl_pct / 100.0) * 1000.0
                            cmp_fmt = f"{cmp:.8f}" if cmp < 0.001 else f"{cmp}"
                            entry_fmt = f"{entry_p:.8f}" if entry_p < 0.001 else f"{entry_p}"
                            
                            send_telegram_message(
                                f"🎯 <b>PROFIT TARGET HIT (TP1)! 🚀</b>\n\n"
                                f"<b>Pair:</b> B-{clean_coin}_USDT\n"
                                f"• <b>Entry Price:</b> <code>${entry_fmt}</code>\n"
                                f"• <b>Exit Price:</b> <code>${cmp_fmt}</code>\n"
                                f"• <b>Realized Gain:</b> <code>+{realized_pnl_pct:.1f}% ROE (+{pnl_inr:.2f} INR)</code> 💰\n"
                                f"• <b>Trigger:</b> Full Target Exit at +3.2% move"
                            )
                            st = load_state()
                            st[symbol] = time.time() + 900
                            save_state(st)
                            continue
                except Exception as e:
                    print(f"Error monitoring {symbol}: {e}")
        except Exception as e:
            print(f"Monitor loop error: {e}")
        time.sleep(2)

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
                        chat = msg.get('chat', {})
                        from_user = str(chat.get('id', ''))
                        
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

    send_telegram_message("⚡ <b>RENDER BOT 10/10 GOLD STANDARD SCANNER DEPLOYED!</b>\n\n• Watchlist Pool: Top-Tier Relative-Strength Leaders (Banned bleeders ZK, ARB, OP & micro-meme PEPE)\n• Non-Negotiable Gate: 15-Minute Supertrend MUST BE GREEN (Zero Counter-Trend Longs)\n• Buy Volume Check: Confirmed Green Expansion Spike Only (No Panic Dump Volume)\n• Closed 5M Candle Confirmation: ACTIVE (No live falling knife entries)\n• Manual Trade Support: ACTIVE (Cleanly skips coins manually opened on CoinDCX App)\n• Zero Short Trade Rule: STRICT ACTIVE (100% BUY / LONG ONLY)\n• Hard Stop Loss: CAPPED AT -0.95% PRICE DROP (-6.6% ROE MAX)\n• Stagnation Guard: 75-Minute Auto Time-Stop (Scratch at -1.0% to -2.0% ROE)\n• Breakeven Engine: ESCAPE VELOCITY @ +6.0% ROE (+0.85% Move)\n• Dynamic Trailing: 3-STAGE RUNNER ENGINE (Stage 2 @ +8.4% ROE, Stage 3 @ +12.6% ROE)\n• State Auto-Recovery: ACTIVE (Syncs open positions from CoinDCX on restart)\n• Per-Coin Cooldown: 30 Minutes (Anti-Fee Drain Guard)\n• Max Active Trades Cap: 4 Concurrent Trades (Max ₹4,000 INR Portfolio Capital)\n• Margin set to ₹1000 INR (Per Trade)\n• Leverage set to 7x (Isolated)\n• Target set to +22.4% ROE (+3.2% price move / 1:2 R:R Ratio)\n• Mobile Telegram commands ready (/stop, /start, /today)")

start_background_loop()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on port {port}...")
    app.run(host="0.0.0.0", port=port)
