import streamlit as st
import requests
import pandas as pd
import numpy as np
import time
import sys
import subprocess
from datetime import datetime

# --- KÜTÜPHANE KONTROL ---
try:
    import yfinance as yf
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
    import yfinance as yf

# ================= SAYFA AYARLARI (EN ÜSTTE OLMALI) =================
st.set_page_config(
    page_title="AI Bot Cloud", 
    page_icon="☁️", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# CSS: Bulut için optimize edilmiş tasarım
st.markdown("""
<style>
    /* Ana Arka Plan */
    .stApp { background-color: #0e1117; }
    
    /* Metrik Renkleri */
    div[data-testid="stMetricValue"] { color: #00ff00; }
    
    /* Log Alanı Tasarımı */
    .bot-log { 
        font-family: 'Courier New', monospace; 
        font-size: 12px; 
        color: #00ff00; 
        background-color: #000; 
        padding: 10px; 
        border-radius: 5px; 
        height: 250px; 
        overflow-y: scroll; 
        border: 1px solid #333;
    }
    
    /* Butonlar */
    div.stButton > button:first-child { border-color: #ff4b4b; color: white; }
    div.stButton > button:hover { background-color: #ff4b4b; color: white; }
    
    /* Tablo Başlıkları */
    thead tr th:first-child { display:none }
    tbody th { display:none }
</style>
""", unsafe_allow_html=True)

# ================= 1. BOT SINIFI =================
class CloudBot:
    def __init__(self):
        self.initial_balance = 1000
        self.trade_pct = 10.0
        self.take_profit = 3.0
        self.stop_loss = 2.0
        
        if 'bot_state' not in st.session_state:
            st.session_state.bot_state = {
                'balance': self.initial_balance,
                'portfolio': {}, 
                'logs': [f"[{datetime.now().strftime('%H:%M')}] ☁️ Bulut Bot Başlatıldı. Bakiye: {self.initial_balance}$"]
            }
    
    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        # Logları session state'e ekle (Print yerine buraya)
        st.session_state.bot_state['logs'].insert(0, f"[{timestamp}] {message}")
        if len(st.session_state.bot_state['logs']) > 100:
            st.session_state.bot_state['logs'] = st.session_state.bot_state['logs'][:100]

    def get_total_equity(self, current_prices):
        state = st.session_state.bot_state
        portfolio_val = 0
        for sym, dat in state['portfolio'].items():
            price = current_prices.get(sym, dat['entry'])
            portfolio_val += (dat['amount'] * price)
        return state['balance'] + portfolio_val

    def manual_sell(self, symbol, current_price):
        state = st.session_state.bot_state
        if symbol in state['portfolio']:
            data = state['portfolio'][symbol]
            revenue = data['amount'] * current_price
            profit = revenue - (data['amount'] * data['entry'])
            state['balance'] += revenue
            del state['portfolio'][symbol]
            self.log(f"MANUEL SATIŞ: {symbol} | Kâr: ${profit:.2f}")
            return True
        return False

    def check_portfolio(self, current_prices):
        state = st.session_state.bot_state
        portfolio = state['portfolio']
        to_sell = []

        for symbol, data in portfolio.items():
            if symbol not in current_prices: continue
            current_price = current_prices[symbol]
            pnl_pct = ((current_price - data['entry']) / data['entry']) * 100
            
            sell = False
            reason = ""
            
            if pnl_pct >= self.take_profit:
                sell = True; reason = f"✅ KAR AL (TP): %{pnl_pct:.2f}"
            elif pnl_pct <= -self.stop_loss:
                sell = True; reason = f"🛑 STOP OL (SL): %{pnl_pct:.2f}"
            
            if sell:
                revenue = data['amount'] * current_price
                profit = revenue - (data['amount'] * data['entry'])
                state['balance'] += revenue
                self.log(f"OTO SATIŞ: {symbol} | {reason} | Kâr: ${profit:.2f}")
                to_sell.append(symbol)
        
        for sym in to_sell: del portfolio[sym]

    def execute_buy(self, symbol, price, reason, total_equity):
        state = st.session_state.bot_state
        if symbol in state['portfolio']: return
        
        target_amount = total_equity * (self.trade_pct / 100.0)
        trade_amount = min(target_amount, state['balance'])
        
        if trade_amount < 10: return

        amount = trade_amount / price
        state['balance'] -= trade_amount
        state['portfolio'][symbol] = {
            'entry': price,
            'amount': amount,
            'reason': reason,
            'invested': trade_amount,
            'ts': datetime.now()
        }
        self.log(f"ALIM: {symbol} | Tutar: ${trade_amount:.1f} | Fiyat: {price}")

bot = CloudBot()

# ================= 2. ANALİZ MOTORU =================
HISTORY_SIZE = 6 
if 'history' not in st.session_state: st.session_state.history = {} 

def hafizayi_guncelle(df_tech):
    for index, row in df_tech.iterrows():
        sym = row['symbol']
        data_point = {'lastPrice': row['lastPrice'], 'quoteVolume': row['quoteVolume'], 'rvol': row.get('rvol', 0)}
        if sym not in st.session_state.history: st.session_state.history[sym] = []
        st.session_state.history[sym].append(data_point)
        if len(st.session_state.history[sym]) > HISTORY_SIZE: st.session_state.history[sym].pop(0)

def analiz_motoru(symbol, current_data):
    if symbol not in st.session_state.history: return "Veri Bekleniyor...", "neutral"
    history = st.session_state.history[symbol]
    if len(history) < 2: return "İzleniyor...", "neutral"

    prices = [h['lastPrice'] for h in history] + [current_data['lastPrice']]
    volumes = [h['quoteVolume'] for h in history] + [current_data['quoteVolume']]
    rvols = [h['rvol'] for h in history] + [current_data['rvol']]
    
    rvol_now = rvols[-1]
    price_chg = (prices[-1] - prices[-2]) / prices[-2] * 100 if prices[-2] > 0 else 0

    if rvol_now > 3.0 and price_chg > 1.0: return "🚀 BREAKOUT", "bullish"
    if len(volumes) >= 3 and volumes[-1] > volumes[-2] > volumes[-3] and price_chg > 0.3: return "🔥 MOMENTUM", "bullish"
    if rvol_now > 5.0 and abs(price_chg) < 0.5: return "🐋 BALİNA", "bullish"
    
    if price_chg > 0 and rvol_now < 0.8: return "⚠️ ZAYIF", "bearish"
    if price_chg < -1.0 and rvol_now > 2.0: return "🩸 DUMP", "bearish"

    return "Stabil", "neutral"

# ================= 3. VERİ ÇEKME =================
HEADERS = {'User-Agent': 'Mozilla/5.0'}
@st.cache_data(ttl=5)
def get_market_data(exchange, min_vol_m):
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr" if exchange == "BINANCE" else "https://api.mexc.com/api/v3/ticker/24hr"
        if exchange == "BIST": return pd.DataFrame()
        r = requests.get(url, headers=HEADERS, timeout=5)
        df = pd.DataFrame(r.json())
        df = df[df['symbol'].str.endswith('USDT') & ~df['symbol'].str.contains('UP|DOWN|BEAR|BULL')]
        cols = ['lastPrice', 'priceChangePercent', 'quoteVolume']
        df[cols] = df[cols].astype(float)
        return df[df['quoteVolume'] > (min_vol_m * 1000000)]
    except: return pd.DataFrame()

def get_technical(symbol, exchange):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
        if exchange == "MEXC": url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=60m&limit=50"
        r = requests.get(url, headers=HEADERS, timeout=2)
        if r.status_code != 200: return 0, 0
        df = pd.DataFrame(r.json()).iloc[:, [4, 5]].astype(float)
        df.columns = ['close', 'volume']
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain/loss))).iloc[-1]
        curr = df['volume'].iloc[-1]
        avg = df['volume'].iloc[-2:-22:-1].mean()
        rvol = curr / avg if avg > 0 else 0
        return rsi, rvol
    except: return 0, 0

# ================= 4. ARAYÜZ (SOL PANEL) =================
with st.sidebar:
    st.header("⚙️ Bot Ayarları")
    bot_active = st.checkbox("🤖 OTO AL-SAT AKTİF", value=False)
    exchange = st.selectbox("Borsa", ["BINANCE", "MEXC"])
    refresh_rate = st.selectbox("Hız (Sn)", [15, 30, 60], index=1)
    
    st.divider()
    st.subheader("💰 Strateji")
    bot.trade_pct = st.slider("İşlem Başı Bakiye (%)", 1, 50, 10)
    bot.take_profit = st.number_input("Kâr Al (TP %)", value=3.0)
    bot.stop_loss = st.number_input("Zarar Kes (SL %)", value=2.0)
    min_vol_m = st.number_input("Min Hacim ($M)", value=1)
    
    # Durum Göstergesi
    if bot_active:
        st.success("Bot Çalışıyor...")
    else:
        st.warning("Bot Durduruldu")

# ================= 5. ANA EKRAN (SAĞ PANEL) =================
st.title("☁️ AI Cloud Trader")

# Metrikler Alanı (Sabit Kalacak)
metrics_container = st.empty()
# İçerik Alanı (Değişecek)
content_container = st.empty()

state = st.session_state.bot_state

# ================= 6. ANA DÖNGÜ =================
# Streamlit Cloud'da 'while True' yerine 'st.rerun' kullanmak daha sağlıklıdır
# ancak canlı akış için kontrollü döngü kuruyoruz.

if 'last_run' not in st.session_state:
    st.session_state.last_run = time.time()

# Veri Çekme
df = get_market_data(exchange, min_vol_m)

if not df.empty:
    current_prices = dict(zip(df['symbol'], df['lastPrice']))
    total_equity = bot.get_total_equity(current_prices)
    
    # 1. METRİKLERİ GÜNCELLE
    with metrics_container.container():
        c1, c2, c3 = st.columns(3)
        diff = total_equity - bot.initial_balance
        c1.metric("TOPLAM VARLIK", f"${total_equity:.2f}", delta=f"{diff:.2f}")
        c2.metric("NAKİT", f"${state['balance']:.2f}")
        c3.metric("GELECEK İŞLEM", f"${(total_equity * bot.trade_pct / 100):.1f}")

    # 2. İÇERİĞİ GÜNCELLE
    with content_container.container():
        tab1, tab2, tab3 = st.tabs(["📊 PİYASA", "💼 PORTFÖY", "📜 LOGLAR"])
        
        # Bot Kontrolleri
        if bot_active:
            bot.check_portfolio(current_prices)

        # Analiz Verileri
        df_view = df.sort_values(by='priceChangePercent', ascending=False).head(15)
        tech_list = []
        for _, row in df_view.iterrows():
            rsi, rvol = get_technical(row['symbol'], exchange)
            tech_list.append({'rsi': rsi, 'rvol': rvol})
        
        tech_df = pd.DataFrame(tech_list, index=df_view.index)
        full_df = pd.concat([df_view, tech_df], axis=1)
        hafizayi_guncelle(full_df)

        # --- SEKME 1: PİYASA ---
        with tab1:
            display_data = []
            for _, row in full_df.iterrows():
                ai_msg, ai_status = analiz_motoru(row['symbol'], row)
                
                if bot_active and ai_status == "bullish" and row['rsi'] < 70:
                    bot.execute_buy(row['symbol'], row['lastPrice'], ai_msg, total_equity)
                
                icon = "🟢" if ai_status == "bullish" else "⚪"
                display_data.append({
                    "Coin": row['symbol'].replace("USDT",""),
                    "Fiyat": row['lastPrice'],
                    "Değişim %": row['priceChangePercent'],
                    "RVOL": row['rvol'],
                    "RSI": row['rsi'],
                    "Sinyal": f"{icon} {ai_msg}"
                })
            st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)

        # --- SEKME 2: PORTFÖY ---
        with tab2:
            if state['portfolio']:
                # Başlık
                cols = st.columns([2, 2, 2, 2, 2])
                cols[0].markdown("**Coin**")
                cols[1].markdown("**Yatırılan**")
                cols[2].markdown("**Güncel**")
                cols[3].markdown("**PnL**")
                cols[4].markdown("**Sat**")
                st.divider()

                for sym, dat in list(state['portfolio'].items()):
                    curr = current_prices.get(sym, dat['entry'])
                    invested = dat.get('invested', dat['amount'] * dat['entry'])
                    current_val = dat['amount'] * curr
                    pnl = ((curr - dat['entry']) / dat['entry']) * 100
                    pnl_color = "green" if pnl >= 0 else "red"

                    with st.container():
                        cc = st.columns([2, 2, 2, 2, 2])
                        cc[0].text(sym)
                        cc[1].text(f"${invested:.1f}")
                        cc[2].text(f"${current_val:.1f}")
                        cc[3].markdown(f":{pnl_color}[%{pnl:.2f}]")
                        if cc[4].button(f"SAT", key=f"btn_{sym}"):
                            bot.manual_sell(sym, curr)
                            st.rerun()
            else:
                st.info("Açık işlem yok. Bot tarıyor...")

        # --- SEKME 3: LOGLAR ---
        with tab3:
            log_html = "<br>".join(state['logs'])
            st.markdown(f"<div class='bot-log'>{log_html}</div>", unsafe_allow_html=True)

else:
    st.warning("Veri bekleniyor... (API Bağlantısı Kuruluyor)")

# 7. YENİLEME MEKANİZMASI (Bulut Dostu)
if bot_active:
    time.sleep(refresh_rate)
    st.rerun()
else:
    if st.button("Manuel Yenile"):
        st.rerun()