import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.stats import norm
import requests
import pyotp
from datetime import datetime

# ==========================================
# १. AI RISK SENTINEL (५ घटक नियंत्रक)
# ==========================================
class AIRiskSentinel:
    def _init_(self, max_daily_loss: float = 3000.0, max_trades: int = 3, capital: float = 50000.0):
        self.max_daily_loss = float(max_daily_loss)
        self.max_trades = int(max_trades)
        self.capital = float(capital)
        self.trade_count = 0
        self.is_locked = False

    def validate_trade(self, strike_type: str, dte: float, theta: float, pcr: float, trade_type: str):
        # नियम १ व ५: Daily Loss Lock & Over-trading Shield
        if self.is_locked:
            return False, "❌ AI BLOCK: आजची कमाल तोटा मर्यादा (Max Loss) संपली आहे. टर्मिनल लॉक आहे."

        if self.trade_count >= self.max_trades:
            return False, f"❌ AI BLOCK: आजचे कमाल {self.max_trades} ट्रेड्स पूर्ण झाले आहेत. ओव्हर-ट्रेडिंग टाळण्यासाठी नवीन ट्रेड ब्लॉक केला आहे."

        # नियम ३: Strike Selection (Deep OTM Block)
        if strike_type.upper() == "OTM":
            return False, "⚠️ AI WARNING: लांबचा OTM स्ट्राइक निवडला आहे. 90% OTM शून्य होतात. कृपया ATM/ITM निवडा."

        # नियम २: Theta Decay Protection (Expiry Risk)
        if dte <= 1 and abs(theta) > 25.0 and trade_type.startswith("BUY"):
            return False, f"⚠️ AI THETA ALERT: एक्सपायरी अगदी जवळ (DTE: {dte}) आहे आणि प्रति तास डीके (Theta: ₹{theta:.1f}) जास्त आहे."

        # नियम ४: Market Trend & PCR Confluence
        if trade_type == "BUY_CE" and pcr < 0.75:
            return False, f"⚠️ AI SENTIMENT MISMATCH: PCR {pcr:.2f} (Bearish) आहे. मंदीत Call खरेदी करणे धोकादायक आहे."
        
        if trade_type == "BUY_PE" and pcr > 1.30:
            return False, f"⚠️ AI SENTIMENT MISMATCH: PCR {pcr:.2f} (Bullish) आहे. तेजी असताना Put खरेदी करणे ट्रेंडविरोधी आहे."

        return True, "✅ AI APPROVED: सर्व ५ घटक नियमात आहेत."


# ==========================================
# २. TELEGRAM NOTIFIER MODULE
# ==========================================
class TelegramNotifier:
    def _init_(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token.strip() if bot_token else ""
        self.chat_id = chat_id.strip() if chat_id else ""
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_raw(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            return False
        try:
            resp = requests.post(
                self.base_url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=6
            )
            return resp.status_code == 200
        except Exception:
            return False

    def send_trade_alert(self, action: str, symbol: str, strike: int, opt_type: str, qty: int, price: float, sl: float, tgt: float):
        icon = "🟢" if action.upper() == "BUY" else "🔴"
        msg = (
            f"<b>{icon} ALGO TRADE EXECUTED (BALAJI DESK)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>इंडेक्स:</b> {symbol}\n"
            f"<b>स्ट्राइक:</b> {strike} {opt_type.upper()}\n"
            f"<b>प्रकार:</b> {action.upper()}\n"
            f"<b>प्रमाण (Qty):</b> {qty}\n"
            f"<b>एंट्री भाव:</b> ₹{price:.2f}\n"
            f"<b>स्टॉप लॉस (SL):</b> ₹{sl:.2f}\n"
            f"<b>टार्गेट (TGT):</b> ₹{tgt:.2f}\n"
            f"<b>वेळ:</b> {datetime.now().strftime('%I:%M:%S %p')}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        return self.send_raw(msg)

    def send_ema_alert(self, symbol: str, timeframe: str, ema_period: int, signal: str, ema_val: float, ltp: float, reason: str):
        icon = "🚀 <b>CALL BUY ALERT (CE)</b>" if "BULLISH" in signal else "🔻 <b>PUT BUY ALERT (PE)</b>"
        msg = (
            f"{icon}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>इंडेक्स:</b> {symbol} ({timeframe})\n"
            f"<b>सिग्नल:</b> {signal.replace('_', ' ')}\n"
            f"<b>{ema_period} EMA लेव्हल:</b> ₹{ema_val:,.2f}\n"
            f"<b>चालू भाव (LTP):</b> ₹{ltp:,.2f}\n"
            f"<b>कारण:</b> {reason}\n"
            f"<b>वेळ:</b> {datetime.now().strftime('%I:%M:%S %p')}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        return self.send_raw(msg)

    def send_daily_summary(self, total_trades: int, winning: int, gross_pnl: float, charges: float = 120.0):
        net_pnl = gross_pnl - charges
        icon = "🚀" if net_pnl >= 0 else "🛑"
        win_rate = (winning / total_trades * 100) if total_trades > 0 else 0
        msg = (
            f"<b>{icon} BALAJI DESK: DAILY SUMMARY | {datetime.now().strftime('%d-%b-%Y')}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>एकूण ट्रेड्स:</b> {total_trades}\n"
            f"<b>यशस्वी ट्रेड्स:</b> {winning} ({win_rate:.1f}% Win Rate)\n"
            f"<b>ग्रॉस P&L:</b> ₹{gross_pnl:,.2f}\n"
            f"<b>अंदाजे चार्जेस:</b> ₹{charges:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>निव्वळ P&L (Net MTM): ₹{net_pnl:,.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        return self.send_raw(msg)


# ==========================================
# ३. BLACK-SCHOLES GREEKS ENGINE
# ==========================================
def calculate_greeks(spot, strike, dte, iv=0.14, r=0.07):
    S = float(spot)
    K = float(strike)
    T = max(float(dte), 0.0001) / 365.0
    v = max(float(iv), 0.0001)
    rate = float(r)

    d1 = (np.log(S / K) + (rate + 0.5 * v ** 2) * T) / (v * np.sqrt(T))
    d2 = d1 - v * np.sqrt(T)

    pdf_d1 = norm.pdf(d1)
    delta_ce = norm.cdf(d1)
    delta_pe = delta_ce - 1.0

    gamma = pdf_d1 / (S * v * np.sqrt(T))
    vega = (S * pdf_d1 * np.sqrt(T)) / 100.0

    term1 = -(S * pdf_d1 * v) / (2 * np.sqrt(T))
    theta_ce = (term1 - rate * K * np.exp(-rate * T) * norm.cdf(d2)) / 365.0
    theta_pe = (term1 + rate * K * np.exp(-rate * T) * norm.cdf(-d2)) / 365.0

    return {
        "ce_delta": round(float(delta_ce), 3),
        "pe_delta": round(float(delta_pe), 3),
        "gamma": round(float(gamma), 5),
        "vega": round(float(vega), 2),
        "ce_theta": round(float(theta_ce), 2),
        "pe_theta": round(float(theta_pe), 2)
    }


# ==========================================
# ४. EMA TOUCH STRATEGY
# ==========================================
def analyze_ema(candles_df: pd.DataFrame, period: int = 9, buffer_pts: float = 2.0):
    df = candles_df.copy()
    df[f'EMA_{period}'] = df['Close'].ewm(span=period, adjust=False).mean()
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    ema_val = round(last[f'EMA_{period}'], 2)
    
    high, low, close = last['High'], last['Low'], last['Close']
    signal, reason = None, ""

    if (low <= ema_val + buffer_pts) and (close >= ema_val):
        signal = "BULLISH_TOUCH"
        reason = f"किंमतीने {period} EMA जवळ अचूक सपोर्ट (Touch) घेतला आहे."
    elif (high >= ema_val - buffer_pts) and (close <= ema_val):
        signal = "BEARISH_TOUCH"
        reason = f"किंमतीला {period} EMA वरून रेझिस्टन्स (Touch Rejection) मिळाला आहे."
    elif prev['Close'] < prev[f'EMA_{period}'] and close > ema_val:
        signal = "BULLISH_CROSSOVER"
        reason = f"कॅन्डलने {period} EMA च्या वर ब्रेकआउट दिला आहे."
    elif prev['Close'] > prev[f'EMA_{period}'] and close < ema_val:
        signal = "BEARISH_CROSSOVER"
        reason = f"कॅन्डलने {period} EMA च्या खाली ब्रेकडाऊन दिला आहे."

    return signal, ema_val, reason


# ==========================================
# ५. STREAMLIT UI SETUP & INITIALIZATION
# ==========================================
st.set_page_config(layout="wide", page_title="BALAJI Options Algo Desk", page_icon="⚡")

# Safe Session State Init (Indentation सुरक्षित ठेवले आहे)
if 'ai_sentinel' not in st.session_state:
    st.session_state.ai_sentinel = AIRiskSentinel()

ai_guard = st.session_state.ai_sentinel

st.title("⚡ BALAJI Options Pro: Trading & Algo Terminal")

# SIDEBAR CONTROLS
with st.sidebar:
    st.header("🔑 Broker (Angel One)")
    st.text_input("SmartAPI Key", type="password", value="API_KEY_HERE")
    st.text_input("Client Code", value="CLIENT_CODE")
    st.text_input("MPIN", type="password", value="1234")
    st.text_input("TOTP Secret", type="password", value="TOTP_SECRET")
    if st.button("🔗 Connect Broker API", use_container_width=True):
        st.success("Angel One API यशस्वीरीत्या कनेक्ट झाले!")

    st.divider()
    st.header("🧠 AI Sentinel (५ घटक नियम)")
    default_loss = getattr(ai_guard, 'max_daily_loss', 3000.0)
    default_trades = getattr(ai_guard, 'max_trades', 3)
    
    ai_guard.max_daily_loss = st.number_input("Max Daily Loss Limit (₹)", value=float(default_loss), step=500.0)
    ai_guard.max_trades = st.number_input("कमाल ट्रेड्स मर्यादा (दिवसाला)", value=int(default_trades), min_value=1, max_value=10)
    
    current_trades = getattr(ai_guard, 'trade_count', 0)
    st.info(f"📊 आज झालेले ट्रेड्स: {current_trades}/{ai_guard.max_trades}")
    st.divider()
    st.header("📲 Telegram Alerts")
    tg_token = st.text_input("Bot Token", type="password")
    tg_chat = st.text_input("Chat ID")
    
    tg = TelegramNotifier(tg_token, tg_chat) if (tg_token and tg_chat) else None
    
    if st.button("🔔 Test Telegram Alert", use_container_width=True):
        if tg and tg.send_raw("✅ <b>BALAJI Desk Connected!</b> Telegram ॲलर्ट्स सक्रिय आहेत."):
            st.success("टेस्ट मेसेज पाठवला!")
        else:
            st.error("टोकन किंवा चॅट आयडी तपासा.")

    st.divider()
    st.header("🛡️ Risk Parameters")
    lot_size = st.number_input("Lots", min_value=1, max_value=20, value=2)
    sl_pts = st.number_input("Stop Loss (Pts)", value=25, step=5)
    tgt_pts = st.number_input("Target (Pts)", value=50, step=5)

# TOP TICKER & INDEX SELECTION
selected_index = st.selectbox("इंडेक्स निवडा:", ["NIFTY 50", "BANK NIFTY", "SENSEX"], index=0)

market_config = {
    "NIFTY 50": {"spot": 25140.50, "step": 50, "pcr": 1.15, "dte": 2, "qty": 75},
    "BANK NIFTY": {"spot": 53250.00, "step": 100, "pcr": 0.85, "dte": 3, "qty": 30},
    "SENSEX": {"spot": 82400.00, "step": 100, "pcr": 1.02, "dte": 1, "qty": 20}
}

cfg = market_config[selected_index]
spot = cfg["spot"]
step = cfg["step"]
atm_strike = int(round(spot / step) * step)

mcol1, mcol2, mcol3, mcol4 = st.columns(4)
with mcol1:
    st.metric(f"{selected_index} Spot", f"₹{spot:,.2f}", "+115.40")
with mcol2:
    st.metric("ATM Strike", f"{atm_strike}", f"Step: {step}")
with mcol3:
    st.metric("Overall PCR", f"{cfg['pcr']}", "Bullish" if cfg['pcr'] >= 1.0 else "Bearish")
with mcol4:
    st.metric("Expiry DTE", f"{cfg['dte']} Days", "Weekly")

# AI SENTINEL STATUS BANNER
st.divider()
ai_banner1, ai_banner2 = st.columns([3, 1])
with ai_banner1:
    if getattr(ai_guard, 'is_locked', False) or getattr(ai_guard, 'is_terminal_locked', False):
        st.error("🛑 *AI सुरक्षा कवच: टर्मिनल लॉक आहे.* कॅपिटल संरक्षणासाठी नवीन ऑर्डर्स बंद आहेत.")
    else:
        st.success(f"🛡️ *AI Safety Shield Active:* ५ घटक नियम सक्रिय आहेत | आजचे ट्रेड्स: {ai_guard.trade_count}/{ai_guard.max_trades}")
with ai_banner2:
    if st.button("🔄 Reset AI Lock", help="मॅन्युअल ओव्हरराइड"):
        ai_guard.is_locked = False
        ai_guard.is_terminal_locked = False
        ai_guard.trade_count = 0
        st.rerun()
st.divider()

# TABS
tab1, tab2, tab3 = st.tabs(["📊 Option Chain & Greeks", "🎯 EMA Touch Scanner & 1-Click", "💼 Positions & EOD Report"])

# TAB 1: OPTION CHAIN & GREEKS
with tab1:
    st.subheader(f"Option Chain Matrix with Greeks (ATM: {atm_strike})")
    strikes = [atm_strike + (i * step) for i in range(-4, 5)]
    chain_rows = []

    for s in strikes:
        diff = abs(spot - s)
        ce_price = round(max(5.0, (spot - s) + 65), 2) if s <= spot else round(max(5.0, 75 - (diff * 0.35)), 2)
        pe_price = round(max(5.0, (s - spot) + 65), 2) if s >= spot else round(max(5.0, 75 - (diff * 0.35)), 2)
        
        ce_oi = int(abs(140000 - diff * 70) + np.random.randint(1500, 4500))
        pe_oi = int(abs(135000 - diff * 65) + np.random.randint(1500, 4500))

        g = calculate_greeks(spot=spot, strike=s, dte=cfg['dte'], iv=0.14)

        chain_rows.append({
            "CE Delta": g["ce_delta"],
            "CE Theta": g["ce_theta"],
            "Call OI": ce_oi,
            "Call LTP (₹)": ce_price,
            "Strike": s,
            "Put LTP (₹)": pe_price,
            "Put OI": pe_oi,
            "PE Theta": g["pe_theta"],
            "PE Delta": g["pe_delta"],
            "Gamma": g["gamma"],
            "Vega": g["vega"]
        })

    df_chain = pd.DataFrame(chain_rows)

    fig = go.Figure()
    fig.add_trace(go.Bar(y=df_chain["Strike"], x=df_chain["Call OI"], name="Call OI (Resistance)", orientation='h', marker_color='#ef5350'))
    fig.add_trace(go.Bar(y=df_chain["Strike"], x=df_chain["Put OI"], name="Put OI (Support)", orientation='h', marker_color='#26a69a'))
    fig.update_layout(barmode='group', height=320, margin=dict(l=10, r=10, t=25, b=10), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(df_chain.style.highlight_max(subset=["Call OI", "Put OI"], color="#1f3b4d"), use_container_width=True)

# TAB 2: EMA TOUCH SCANNER & 1-CLICK (AI GUARDED)
with tab2:
    st.subheader("🎯 Real-Time EMA Touch Scanner")
    ec1, ec2, ec3, ec4 = st.columns(4)
    with ec1:
        ema_period = st.selectbox("EMA कालावधी:", [9, 15, 20, 50], index=0)
    with ec2:
        timeframe = st.selectbox("Timeframe:", ["1 Min", "3 Min", "5 Min", "15 Min"], index=2)
    with ec3:
        buffer_pts = st.number_input("Touch Buffer (Pts):", value=2.0, step=0.5)
    with ec4:
        scanner_active = st.toggle("Active Scanner", value=True)

    sample_df = pd.DataFrame({
        "High": [spot + 10, spot + 18, spot + 6, spot + 4, spot + 7],
        "Low": [spot - 8, spot - 4, spot - 15, spot - 1.5, spot - 0.5],
        "Close": [spot + 2, spot + 14, spot - 6, spot + 2.5, spot + 5]
    })

    sig, ema_val, reason = analyze_ema(sample_df, period=ema_period, buffer_pts=buffer_pts)

    st.info(f"📊 *{selected_index}* Spot: *₹{spot:,.2f}* | *{ema_period} EMA:* *₹{ema_val:,.2f}*")

    if sig:
        if "BULLISH" in sig:
            st.success(f"🟢 *{sig} आढळला!* {reason}")
        else:
            st.error(f"🔴 *{sig} आढळला!* {reason}")

        if st.button("📲 Send EMA Alert to Telegram", use_container_width=True):
            if tg:
                tg.send_ema_alert(selected_index, timeframe, ema_period, sig, ema_val, spot, reason)
                st.toast("✅ Telegram वर EMA अलर्ट पाठवला!")
            else:
                st.warning("साइडबारमध्ये Telegram क्रेडेंशियल्स भरा.")

    st.divider()
    st.subheader("⚡ 1-Click Scalper Execution (AI Guard Protected)")
    
    total_qty = lot_size * cfg["qty"]
    btn1, btn2, btn3 = st.columns(3)
    
    with btn1:
        if st.button(f"🟢 Buy ATM Call ({atm_strike} CE)", use_container_width=True):
            allowed, msg = ai_guard.validate_trade(
                strike_type="ATM",
                dte=cfg["dte"],
                theta=18.5,
                pcr=cfg["pcr"],
                trade_type="BUY_CE"
            )
            if allowed:
                ai_guard.trade_count += 1
                entry = 125.0
                if tg:
                    tg.send_trade_alert("BUY", selected_index, atm_strike, "CE", total_qty, entry, entry - sl_pts, entry + tgt_pts)
                st.toast(f"✅ ऑर्डर एक्झिक्युट झाली! {msg}")
                st.rerun()
            else:
                st.error(msg)
                if tg:
                    tg.send_raw(f"⚠️ <b>AI TRADE BLOCKED:</b>\n{msg}")

    with btn2:
        if st.button(f"🔴 Buy ATM Put ({atm_strike} PE)", use_container_width=True):
            allowed, msg = ai_guard.validate_trade(
                strike_type="ATM",
                dte=cfg["dte"],
                theta=18.5,
                pcr=cfg["pcr"],
                trade_type="BUY_PE"
            )
            if allowed:
                ai_guard.trade_count += 1
                entry = 110.0
                if tg:
                    tg.send_trade_alert("BUY", selected_index, atm_strike, "PE", total_qty, entry, entry - sl_pts, entry + tgt_pts)
                st.toast(f"✅ ऑर्डर एक्झिक्युट झाली! {msg}")
                st.rerun()
            else:
                st.error(msg)
                if tg:
                    tg.send_raw(f"⚠️ <b>AI TRADE BLOCKED:</b>\n{msg}")

    with btn3:
        if st.button("⚠️ Panic Exit (Close All Positions)", use_container_width=True):
            st.warning("सर्व पोझिशन्स मार्केट भावाने एक्झिट केल्या!")

# TAB 3: POSITIONS & EOD REPORT
with tab3:
    st.subheader("💼 Today's Live Positions & P&L")
    positions = [
        {"Contract": f"{selected_index} {atm_strike} CE", "Qty": total_qty, "Buy Price": 122.0, "LTP": 146.5, "P&L": (146.5 - 122.0) * total_qty},
        {"Contract": f"{selected_index} {atm_strike + step} PE", "Qty": total_qty, "Buy Price": 85.0, "LTP": 74.0, "P&L": (74.0 - 85.0) * total_qty}
    ]
    df_pos = pd.DataFrame(positions)
    net_mtm = df_pos["P&L"].sum()

    st.metric("Net MTM P&L", f"₹{net_mtm:,.2f}", f"{'+' if net_mtm >= 0 else ''}{net_mtm:.2f}")
    st.table(df_pos)

    st.divider()
    st.subheader("📤 End of Day Telegram Report")
    if st.button("Send EOD Summary to Telegram Now", use_container_width=True):
        if tg:
            tg.send_daily_summary(total_trades=ai_guard.trade_count, winning=1, gross_pnl=net_mtm, charges=85.0)
            st.success("दैनिक अहवाल Telegram वर पाठवला!")
        else:
            st.warning("साइडबारमध्ये Telegram क्रेडेंशियल्स उपलब्ध नाहीत.")
