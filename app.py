import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from sklearn.ensemble import RandomForestClassifier

st.set_page_config(page_title="PKPro AI Backtest Screener", page_icon="🎯", layout="wide")

# Custom Dark UI
st.markdown("""
    <style>
    .stApp { background-color: #0b141a; color: #e1e7ec; }
    .header-box {
        background-color: #121e24;
        padding: 14px 20px;
        border-radius: 10px;
        border: 1px solid #1f2e35;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .neon-text { color: #00d09c; font-weight: bold; font-size: 22px; }
    .rr-badge { background: #1a2a32; padding: 6px 12px; border-radius: 6px; border: 1px solid #00d09c; color: #ffb703; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="header-box">
    <div class="neon-text">🎯 PKPro AI Screener + 1:2 R:R & Backtester</div>
    <div class="rr-badge">Built-in ATR SL/Target + Historical Win Rate</div>
</div>
""", unsafe_allow_html=True)

# युनिव्हर्स लोड करणे
@st.cache_data(ttl=86400)
def get_stock_universe(basket_type):
    if basket_type == "Nifty 50":
        url = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
    elif basket_type == "Nifty Next 50":
        url = "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv"
    else:
        url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    try:
        df = pd.read_csv(url)
        return [f"{sym}.NS" for sym in df["Symbol"].tolist()]
    except:
        return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "LT.NS", "TATAMOTORS.NS"]

# साइडबार पॅरामीटर्स
st.sidebar.header("⚙️ रिस्क मॅनेजमेंट (R:R)")
universe_choice = st.sidebar.selectbox("स्टॉक युनिव्हर्स", ["Nifty 50", "Nifty Next 50", "Nifty 500"], index=0)
rr_ratio = st.sidebar.selectbox("Risk : Reward Ratio", [1.5, 2.0, 2.5, 3.0], index=1)
atr_multiplier = st.sidebar.slider("Stop-Loss ATR Multiplier", 1.0, 2.5, 1.5, step=0.25)
min_ai_prob = st.sidebar.slider("किमान AI Confidence Score (%)", 50, 90, 60, step=5)
min_win_rate = st.sidebar.slider("किमान Backtest Win Rate (%)", 30, 80, 50, step=5)

# बॅकटिस्टिंग आणि प्रेडिक्शन इंजिन
def process_stock_with_backtest(symbol):
    try:
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty or len(df) < 150:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # इंडिकेटर्स आणि ATR (Stop-Loss साठी)
        df["EMA_9"] = ta.ema(df["Close"], length=9)
        df["EMA_21"] = ta.ema(df["Close"], length=21)
        df["RSI"] = ta.rsi(df["Close"], length=14)
        df["ATR"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)
        df["Vol_SMA"] = df["Volume"].rolling(20).mean()
        df["Vol_Ratio"] = df["Volume"] / df["Vol_SMA"]
        df["Return_1d"] = df["Close"].pct_change()
        df["EMA_Spread"] = (df["EMA_9"] - df["EMA_21"]) / df["Close"]

        # टार्गेट: पुढील ५ दिवसांत शेअर वाढेल का?
        df["Target"] = np.where(df["Close"].shift(-5) > df["Close"] * 1.025, 1, 0)
        data = df.dropna().copy()
        if len(data) < 100:
            return None

        features = ["RSI", "Vol_Ratio", "Return_1d", "EMA_Spread"]

        # १. मॉडेल ट्रेनिंग
        train_split = int(len(data) * 0.7)
        train_data = data.iloc[:train_split]
        test_data = data.iloc[train_split:].copy()

        model = RandomForestClassifier(n_estimators=30, max_depth=5, random_state=42)
        model.fit(train_data[features], train_data["Target"])

        # २. हिस्टोरिकल बॅकटिस्टिंग (मागील ३०% डेटावर ट्रेड्स तपासणे)
        test_data["AI_Prob"] = model.predict_proba(test_data[features])[:, 1]
        
        trades = []
        for i in range(len(test_data) - 10):
            row = test_data.iloc[i]
            if row["AI_Prob"] >= (min_ai_prob / 100):
                entry_price = row["Close"]
                risk_amount = row["ATR"] * atr_multiplier
                sl_price = entry_price - risk_amount
                target_price = entry_price + (risk_amount * rr_ratio)

                # पुढील १० दिवसांत काय झाले ते तपासणे
                future_window = test_data.iloc[i+1 : i+11]
                hit_target = (future_window["High"] >= target_price).any()
                hit_sl = (future_window["Low"] <= sl_price).any()

                if hit_target and not hit_sl:
                    trades.append(1) # Win
                elif hit_sl and not hit_target:
                    trades.append(0) # Loss
                elif hit_target and hit_sl:
                    # कोणती पातळी आधी लागली?
                    target_idx = (future_window["High"] >= target_price).idxmax()
                    sl_idx = (future_window["Low"] <= sl_price).idxmax()
                    trades.append(1 if target_idx < sl_idx else 0)

        total_trades = len(trades)
        win_rate = (sum(trades) / total_trades * 100) if total_trades > 0 else 0

        # ३. आजच्या ताज्या कँडलवर लाइव्ह सिग्नल
        latest_candle = data[features].iloc[[-1]]
        curr_prob = model.predict_proba(latest_candle)[0][1] * 100

        curr_close = float(data["Close"].iloc[-1])
        curr_atr = float(data["ATR"].iloc[-1])
        
        sl = round(curr_close - (curr_atr * atr_multiplier), 2)
        target = round(curr_close + ((curr_atr * atr_multiplier) * rr_ratio), 2)

        # फिल्टर निकष
        if curr_prob >= min_ai_prob and win_rate >= min_win_rate and total_trades >= 3:
            return {
                "Symbol": symbol.replace(".NS", ""),
                "LTP (₹)": round(curr_close, 2),
                "Stop-Loss (₹)": sl,
                "Target (₹)": target,
                "R:R": f"1:{rr_ratio}",
                "AI Score": f"{round(curr_prob, 1)}%",
                "Backtest Win Rate": f"{round(win_rate, 1)}%",
                "Backtest Trades": total_trades
            }
    except Exception:
        return None
    return None

stocks = get_stock_universe(universe_choice)
st.info(f"निवड: *{universe_choice}* ({len(stocks)} शेअर्स) | Risk-Reward: *1:{rr_ratio}*")

if st.button("🚀 AI Backtest & R:R Scan सुरू करा"):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    with ThreadPoolExecutor(max_workers=14) as executor:
        futures = {executor.submit(process_stock_with_backtest, sym): sym for sym in stocks}
        completed = 0
        total = len(stocks)

        for future in as_completed(futures):
            completed += 1
            res = future.result()
            if res:
                results.append(res)
            progress_bar.progress(completed / total)
            status_text.text(f"बॅकटिस्टिंग आणि स्कॅनिंग सुरू आहे: {completed}/{total}...")

    status_text.empty()
    progress_bar.empty()

    if results:
        res_df = pd.DataFrame(results)
        res_df = res_df.sort_values(by="Backtest Win Rate", ascending=False)
        
        st.success(f"यशोदर (Profitable Setup) शेअर्स सापडले: {len(res_df)}")
        
        csv_data = res_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 रिझल्ट CSV डाउनलोड", csv_data, "ai_rr_backtest_results.csv", "text/csv")

        st.dataframe(
            res_df.style.map(
                lambda x: "color: #00d09c; font-weight: bold;" if "%" in str(x) and float(str(x).replace("%","")) >= 60 else "",
                subset=["Backtest Win Rate"]
            ),
            use_container_width=True
        )
    else:
        st.warning("दिलेल्या Win Rate % किंवा R:R निकषांमध्ये सध्या कोणताही शेअर बसत नाही. फिल्टर्स शिथिल करा.")
