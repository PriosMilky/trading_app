from flask import Flask, render_template, request
from twelvedata import TDClient
import pandas as pd

app = Flask(__name__)

# Masukkan API Key Twelve Data milikmu di sini
TD_API_KEY = "1dbf605aa40443a0a5dc2a3db3daedbc"
td = TDClient(apikey=TD_API_KEY)

ASSETS = {
    'XAUUSD (Emas Spot)': 'XAU/USD',
    'EURUSD': 'EUR/USD',
    'GBPUSD': 'GBP/USD',
    'USDJPY': 'USD/JPY'
}

@app.route('/')
def index():
    return render_template('index.html', assets=ASSETS)

@app.route('/generate', methods=['POST'])
def generate():
    asset_name = request.form.get('asset')
    lot_size = float(request.form.get('lot', 0.10)) # Default 0.10 Lot Cent
    symbol = ASSETS.get(asset_name, 'XAU/USD')

    try:
        # Interval 15min khusus Twelve Data
        ts = td.time_series(symbol=symbol, interval="15min", outputsize=200)
        df = ts.as_pandas().iloc[::-1]
        
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)

        # 1. EMA 20 & EMA 200
        df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()

        # 2. ATR 14 untuk Pengukur Jarak Scalping 15M
        high_low = df['high'] - df['low']
        high_cp = (df['high'] - df['close'].shift()).abs()
        low_cp = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()

        latest = df.iloc[-1]
        entry_price = round(latest['close'], 2)
        ema20 = round(latest['EMA_20'], 2)
        ema200 = round(latest['EMA_200'], 2)
        atr = round(latest['ATR'], 2)

        action = "WAIT"
        action_color = "secondary"
        sl, tp, pips_sl, pips_tp = 0, 0, 0, 0
        profit_usd, loss_usd = 0.0, 0.0
        reason = ""

        # Pengali ATR Scalping (SL 1.0x ATR, TP 2.0x ATR)
        if entry_price > ema20 and ema20 > ema200:
            action = "BUY"
            action_color = "success"
            sl = round(entry_price - (1.0 * atr), 2)
            tp = round(entry_price + (0.5 * atr), 2)
            
            pips_sl = int(round((entry_price - sl) * 100))
            pips_tp = int(round((tp - entry_price) * 100))
            
            loss_usd = round(pips_sl * (lot_size * 0.1), 2)
            profit_usd = round(pips_tp * (lot_size * 0.1), 2)
            
            reason = "Struktur Scalping Bullish (15M): Harga di atas EMA 20 & EMA 20 di atas EMA 200."

        elif entry_price < ema20 and ema20 < ema200:
            action = "SELL"
            action_color = "danger"
            sl = round(entry_price + (1.0 * atr), 2)
            tp = round(entry_price - (0.5 * atr), 2)
            
            pips_sl = int(round((sl - entry_price) * 100))
            pips_tp = int(round((entry_price - tp) * 100))
            
            loss_usd = round(pips_sl * (lot_size * 0.1), 2)
            profit_usd = round(pips_tp * (lot_size * 0.1), 2)
            
            reason = "Struktur Scalping Bearish (15M): Harga di bawah EMA 20 & EMA 20 di bawah EMA 200."
            
        else:
            reason = "Pasar 15M sedang konsolidasi/sideways. Belum ada momentum scalping."

        return render_template(
            'components/recommendation.html',
            asset=asset_name,
            entry_price=entry_price,
            action=action,
            action_color=action_color,
            sl=sl,
            tp=tp,
            pips_sl=pips_sl,
            pips_tp=pips_tp,
            profit_usd=profit_usd,
            loss_usd=loss_usd,
            lot_size=lot_size,
            profit_cent=int(profit_usd * 100),
            loss_cent=int(loss_usd * 100),
            ema20=ema20,
            ema200=ema200,
            reason=reason
        )

    except Exception as e:
        return f"<div class='alert alert-danger text-center'>Gagal mengambil data: {str(e)}</div>"

if __name__ == '__main__':
    app.run(debug=True, port=5000)