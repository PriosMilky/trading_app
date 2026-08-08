from flask import Flask, render_template, request, jsonify
import requests
import pandas as pd
import numpy as np

app = Flask(__name__)

API_KEY = "1dbf605aa40443a0a5dc2a3db3daedbc"
SYMBOLS = {
    "USD/JPY": {"name": "Yen Jepang (USDJPY)", "mode": "BREAKOUT", "sl_mult": 1.0},
    "GBP/USD": {"name": "Poundsterling (GBPUSD)", "mode": "BREAKOUT", "sl_mult": 1.0},
    "XAU/USD": {"name": "Emas (XAUUSD)", "mode": "RETEST", "sl_mult": 1.0},
    "EUR/USD": {"name": "Euro (EURUSD)", "mode": "RETEST", "sl_mult": 1.0}
}

RISK_REWARD_RATIO = 1.0

def fetch_data(symbol, interval="30min", size=200):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={size}&apikey={API_KEY}"
    try:
        res = requests.get(url, timeout=15).json()
        if "values" not in res:
            return None
        df = pd.DataFrame(res["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)
        return df.sort_values("datetime").reset_index(drop=True)
    except Exception:
        return None

def analyze_symbol(symbol, config):
    df = fetch_data(symbol)
    if df is None or len(df) < 50:
        return {"symbol": symbol, "name": config["name"], "signal": "NEUTRAL", "reason": "Data tidak cukup"}

    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    
    # TR & ATR
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift(1)), abs(df["low"] - df["close"].shift(1)))
    )
    df["atr"] = df["tr"].rolling(14).mean()

    # Swing points
    df["is_swing_high"] = (df["high"].shift(2) > df["high"].shift(3)) & (df["high"].shift(2) > df["high"].shift(4)) & \
                          (df["high"].shift(2) > df["high"].shift(1)) & (df["high"].shift(2) > df["high"])
    df["is_swing_low"] = (df["low"].shift(2) < df["low"].shift(3)) & (df["low"].shift(2) < df["low"].shift(4)) & \
                         (df["low"].shift(2) < df["low"].shift(1)) & (df["low"].shift(2) < df["low"])

    recent_swing_high = df[df["is_swing_high"]]["high"].iloc[-1] if not df[df["is_swing_high"]].empty else None
    recent_swing_low = df[df["is_swing_low"]]["low"].iloc[-1] if not df[df["is_swing_low"]].empty else None

    if not recent_swing_high or not recent_swing_low:
        return {"symbol": symbol, "name": config["name"], "signal": "NEUTRAL", "reason": "Swing point tidak ditemukan"}

    current = df.iloc[-1]
    close_p = current["close"]
    ema_200 = current["ema_200"]
    ema_20 = current["ema_20"]
    atr = current["atr"]

    fvg_bull = df.iloc[-2]["low"] > df.iloc[-4]["high"]
    fvg_bear = df.iloc[-4]["low"] > df.iloc[-2]["high"]

    mode = config["mode"]
    sl_mult = config["sl_mult"]

    # BREAKOUT MODE (USD/JPY, GBP/USD)
    if mode == "BREAKOUT":
        if (close_p > recent_swing_high) and fvg_bull and (close_p > ema_200):
            sl = recent_swing_low - (sl_mult * atr)
            tp = close_p + (RISK_REWARD_RATIO * (close_p - sl))
            return {
                "symbol": symbol, "name": config["name"], "signal": "BUY", 
                "price": close_p, "sl": round(sl, 4), "tp": round(tp, 4),
                "reason": "Bullish BOS + FVG di atas EMA 200",
                "ema20": round(ema_20, 4), "ema200": round(ema_200, 4)
            }

        elif (close_p < recent_swing_low) and fvg_bear and (close_p < ema_200):
            sl = recent_swing_high + (sl_mult * atr)
            tp = close_p - (RISK_REWARD_RATIO * (sl - close_p))
            return {
                "symbol": symbol, "name": config["name"], "signal": "SELL", 
                "price": close_p, "sl": round(sl, 4), "tp": round(tp, 4),
                "reason": "Bearish BOS + FVG di bawah EMA 200",
                "ema20": round(ema_20, 4), "ema200": round(ema_200, 4)
            }

    # RETEST MODE (XAU/USD, EUR/USD)
    elif mode == "RETEST":
        for offset in range(1, 6):
            if len(df) <= offset + 3:
                break
            prev = df.iloc[-offset]
            prev_fvg_bull = df.iloc[-(offset+1)]["low"] > df.iloc[-(offset+3)]["high"]
            prev_fvg_bear = df.iloc[-(offset+3)]["low"] > df.iloc[-(offset+1)]["high"]

            if (prev["close"] > recent_swing_high) and prev_fvg_bull and (prev["close"] > prev["ema_200"]):
                trigger_level = df.iloc[-(offset+1)]["low"]
                if current["low"] <= trigger_level:
                    entry_p = current["low"]
                    sl = recent_swing_low - (sl_mult * atr)
                    tp = entry_p + (RISK_REWARD_RATIO * (entry_p - sl))
                    return {
                        "symbol": symbol, "name": config["name"], "signal": "BUY", 
                        "price": entry_p, "sl": round(sl, 4), "tp": round(tp, 4),
                        "reason": "Retest Area FVG / Mitigasi Bullish",
                        "ema20": round(ema_20, 4), "ema200": round(ema_200, 4)
                    }

            if (prev["close"] < recent_swing_low) and prev_fvg_bear and (prev["close"] < prev["ema_200"]):
                trigger_level = df.iloc[-(offset+1)]["high"]
                if current["high"] >= trigger_level:
                    entry_p = current["high"]
                    sl = recent_swing_high + (sl_mult * atr)
                    tp = entry_p - (RISK_REWARD_RATIO * (sl - entry_p))
                    return {
                        "symbol": symbol, "name": config["name"], "signal": "SELL", 
                        "price": entry_p, "sl": round(sl, 4), "tp": round(tp, 4),
                        "reason": "Retest Area FVG / Mitigasi Bearish",
                        "ema20": round(ema_20, 4), "ema200": round(ema_200, 4)
                    }

    return {
        "symbol": symbol, "name": config["name"], "signal": "WAIT", 
        "price": close_p, "sl": "-", "tp": "-", 
        "reason": "Tidak ada konfirmasi sinyal (Pasar Wait & See)",
        "ema20": round(ema_20, 4), "ema200": round(ema_200, 4)
    }

@app.route("/")
def index():
    return render_template("index.html", assets=SYMBOLS)

@app.route("/generate", methods=["POST"])
def generate():
    selected_asset = request.form.get("asset")
    
    if selected_asset not in SYMBOLS:
        return "<div class='alert alert-danger'>Aset tidak valid.</div>"
    
    config = SYMBOLS[selected_asset]
    analysis = analyze_symbol(selected_asset, config)
    
    signal = analysis.get("signal", "WAIT")
    if "BUY" in signal:
        action = "BUY"
        action_color = "success"
    elif "SELL" in signal:
        action = "SELL"
        action_color = "danger"
    else:
        action = "WAIT"
        action_color = "secondary"

    # Kalkulasi Pips & Cent (Khusus jika ada sinyal BUY / SELL)
    pips_tp, pips_sl = 0, 0
    profit_cent, loss_cent = 0, 0
    lot_size = 0.1  # Default 0.1 Lot Cent

    if action in ["BUY", "SELL"] and isinstance(analysis.get("sl"), (int, float)):
        entry = analysis["price"]
        sl = analysis["sl"]
        tp = analysis["tp"]
        
        # Pengali Pips berdasarkan jenis instrumen
        pip_multiplier = 100 if "JPY" in selected_asset else (10 if "XAU" in selected_asset else 10000)
        
        # Hitung Pips
        pips_tp = round(abs(tp - entry) * pip_multiplier, 1)
        pips_sl = round(abs(entry - sl) * pip_multiplier, 1)
        
        # Hitung Nilai Cent (1 Pips @ 0.1 Lot Cent = ~$0.10 / 10 Cent)
        profit_cent = round(pips_tp * 10, 2)
        loss_cent = round(pips_sl * 10, 2)

    return render_template(
        "components/recommendation.html",
        asset=selected_asset,
        entry_price=analysis.get("price", "-"),
        action=action,
        action_color=action_color,
        sl=analysis.get("sl", "-"),
        tp=analysis.get("tp", "-"),
        reason=analysis.get("reason", "Tidak ada konfirmasi sinyal"),
        pips_tp=pips_tp,
        profit_cent=profit_cent,
        pips_sl=pips_sl,
        loss_cent=loss_cent,
        lot_size=lot_size,
        ema20=analysis.get("ema20", "-"),
        ema200=analysis.get("ema200", "-"),
        rsi="N/A"
    )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)