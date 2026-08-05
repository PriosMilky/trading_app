import requests
import pandas as pd
import numpy as np

API_KEY = "1dbf605aa40443a0a5dc2a3db3daedbc"
SYMBOLS = {
    "USD/JPY": {"name": "Yen Jepang (USDJPY)", "mode": "BREAKOUT", "sl_mult": 1.0},
    "GBP/USD": {"name": "Poundsterling (GBPUSD)", "mode": "BREAKOUT", "sl_mult": 1.0},
    "XAU/USD": {"name": "Emas (XAUUSD)", "mode": "RETEST", "sl_mult": 1.0},
    "EUR/USD": {"name": "Euro (EURUSD)", "mode": "RETEST", "sl_mult": 1.0}
}

RISK_REWARD_RATIO = 1.0

def fetch_data(symbol, interval, size=2000):
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

def backtest_hybrid(symbol, config):
    df = fetch_data(symbol, "30min", 2000)
    if df is None or len(df) < 200:
        return None

    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift(1)), abs(df["low"] - df["close"].shift(1)))
    )
    df["atr"] = df["tr"].rolling(14).mean()

    df["is_swing_high"] = (df["high"].shift(2) > df["high"].shift(3)) & (df["high"].shift(2) > df["high"].shift(4)) & \
                          (df["high"].shift(2) > df["high"].shift(1)) & (df["high"].shift(2) > df["high"])
    df["is_swing_low"] = (df["low"].shift(2) < df["low"].shift(3)) & (df["low"].shift(2) < df["low"].shift(4)) & \
                         (df["low"].shift(2) < df["low"].shift(1)) & (df["low"].shift(2) < df["low"])

    trades = []
    in_trade = False
    trade_type = None
    sl_price, tp_price = 0, 0
    recent_swing_high, recent_swing_low = None, None

    pending_signal = None  # Menyimpan sinyal retest
    pending_timer = 0

    for i in range(10, len(df) - 1):
        current = df.iloc[i]

        if df.iloc[i]["is_swing_high"]:
            recent_swing_high = df.iloc[i-2]["high"]
        if df.iloc[i]["is_swing_low"]:
            recent_swing_low = df.iloc[i-2]["low"]

        # 1. Kelola Posisi Aktif
        if in_trade:
            if trade_type == "BUY":
                if current["low"] <= sl_price:
                    trades.append({"result": "LOSS"})
                    in_trade = False
                elif current["high"] >= tp_price:
                    trades.append({"result": "WIN"})
                    in_trade = False

            elif trade_type == "SELL":
                if current["high"] >= sl_price:
                    trades.append({"result": "LOSS"})
                    in_trade = False
                elif current["low"] <= tp_price:
                    trades.append({"result": "WIN"})
                    in_trade = False

        # 2. Cek Eksekusi Retest jika ada Sinyal Menggantung
        if not in_trade and pending_signal:
            pending_timer += 1
            if pending_timer > 6:  # Sinyal expired jika tidak retest dalam 6 candle (3 jam)
                pending_signal = None
            else:
                if pending_signal["type"] == "BUY" and current["low"] <= pending_signal["trigger_level"]:
                    in_trade = True
                    trade_type = "BUY"
                    entry_p = current["low"]
                    sl_price = pending_signal["sl"]
                    tp_price = entry_p + (RISK_REWARD_RATIO * (entry_p - sl_price))
                    pending_signal = None
                elif pending_signal["type"] == "SELL" and current["high"] >= pending_signal["trigger_level"]:
                    in_trade = True
                    trade_type = "SELL"
                    entry_p = current["high"]
                    sl_price = pending_signal["sl"]
                    tp_price = entry_p - (RISK_REWARD_RATIO * (sl_price - entry_p))
                    pending_signal = None

        # 3. Scan Sinyal Baru
        if not in_trade and not pending_signal and recent_swing_high and recent_swing_low:
            close_p = current["close"]
            ema_200 = current["ema_200"]
            atr = current["atr"]
            next_open = df.iloc[i+1]["open"]

            fvg_bull = df.iloc[i-1]["low"] > df.iloc[i-3]["high"]
            fvg_bear = df.iloc[i-3]["low"] > df.iloc[i-1]["high"]

            # Bullish Setup
            if (close_p > recent_swing_high) and fvg_bull and (close_p > ema_200):
                sl = recent_swing_low - (config["sl_mult"] * atr)
                if config["mode"] == "BREAKOUT":
                    in_trade = True
                    trade_type = "BUY"
                    sl_price = sl
                    tp_price = next_open + (RISK_REWARD_RATIO * (next_open - sl_price))
                else:  # Mode RETEST: Tunggu harga retrace ke EMA 200 / FVG Low
                    pending_signal = {"type": "BUY", "trigger_level": df.iloc[i-1]["low"], "sl": sl}
                    pending_timer = 0

            # Bearish Setup
            elif (close_p < recent_swing_low) and fvg_bear and (close_p < ema_200):
                sl = recent_swing_high + (config["sl_mult"] * atr)
                if config["mode"] == "BREAKOUT":
                    in_trade = True
                    trade_type = "SELL"
                    sl_price = sl
                    tp_price = next_open - (RISK_REWARD_RATIO * (sl_price - next_open))
                else:  # Mode RETEST
                    pending_signal = {"type": "SELL", "trigger_level": df.iloc[i-1]["high"], "sl": sl}
                    pending_timer = 0

    results_df = pd.DataFrame(trades)
    if results_df.empty:
        return {"Symbol": symbol, "Nama": config["name"], "Total Trade": 0, "WIN": 0, "Loss": 0, "Win Rate (%)": 0.0, "Expectancy (R)": 0.0}

    total_trades = len(results_df)
    wins = len(results_df[results_df["result"] == "WIN"])
    losses = len(results_df[results_df["result"] == "LOSS"])
    win_rate = (wins / total_trades) * 100
    expectancy = ((wins / total_trades) * RISK_REWARD_RATIO) - ((losses / total_trades) * 1.0)

    return {
        "Symbol": symbol,
        "Nama": config["name"],
        "Total Trade": total_trades,
        "WIN": wins,
        "Loss": losses,
        "Win Rate (%)": round(win_rate, 2),
        "Expectancy (R)": round(expectancy, 2)
    }

def main():
    print("\n============================================================")
    print("    BACKTEST HYBRID (BREAKOUT FOR MAJORS & RETEST FOR XAU/EUR)")
    print("============================================================\n")
    
    summary_data = []
    for symbol, config in SYMBOLS.items():
        res = backtest_hybrid(symbol, config)
        if res:
            summary_data.append(res)
            
    summary_df = pd.DataFrame(summary_data)
    total_trades_all = summary_df["Total Trade"].sum()
    total_wins_all = summary_df["WIN"].sum()
    total_losses_all = summary_df["Loss"].sum()
    overall_win_rate = (total_wins_all / total_trades_all * 100) if total_trades_all > 0 else 0
    overall_expectancy = ((total_wins_all / total_trades_all) * RISK_REWARD_RATIO) - ((total_losses_all / total_trades_all) * 1.0) if total_trades_all > 0 else 0

    print(summary_df.to_string(index=False))
    print("-" * 60)
    print(f"TOTAL PORTOFOLIO   : {total_trades_all} Transaksi")
    print(f"WIN RATE GABUNGAN  : {overall_win_rate:.2f}%")
    print(f"EXPECTANCY/TRADE   : {overall_expectancy:+.2f} R")
    print("============================================================\n")

if __name__ == "__main__":
    main()