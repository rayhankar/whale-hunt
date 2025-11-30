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

# ================= SAYFA AYARLARI =================
st.set_page_config(
    page_title="AI Futures Cloud", 
    page_icon="🎰", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# CSS: Tasarım
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { color: #00ff00; }
    .bot-log { 
        font-family: 'Courier New', monospace; 
        font-size: 12px; 
        color: #00ff00; 
        background-color: #000; 
        padding: 10px; 
        border-radius: 5px; 
        height: 300px; 
        overflow-y: scroll; 
        border: 1px solid #333;
    }
    div.stButton > button:first-child { border-color: #ff4b4b; color: white; }
    div.stButton > button:hover { background-color: #ff4b4b; color: white; }
</style>
""", unsafe_allow_html=True)

# ================= 1. FUTURES BOT SINIFI =================
class FuturesCloudBot:
    def __init__(self):
        self.initial_balance = 1000
        self.leverage = 10
        self.trade_pct = 5.0
        
        self.take_profit = 50.0
        self.stop_loss = 20.0
        
        self.margin_mode = True
        self.margin_trigger = 15.0
        self.add_amount_pct = 100.0
        self.max_adds = 3
        
        if 'bot_state' not in st.session_state:
            st.session_state.bot_state = {
                'balance': self.initial_balance,
                'portfolio': {}, 
                'logs': [f"[{datetime.now().strftime('%H:%M')}] ☁️ Bot Başlatıldı. Bakiye: {self.initial_balance}$"]
            }
    
    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.bot_state['logs'].insert(0, f"[{timestamp}] {message}")
        if len(st.session_state.bot_state['logs']) > 100:
            st.session_state.bot_state['logs'] = st.session_state.bot_state['logs'][:100]

    def get_total_equity(self, current_prices):
        state = st.session_state.bot_state
        unrealized_pnl = 0
        used_margin = 0
        
        for sym, dat in state['portfolio'].items():
            price = current_prices.get(sym, dat['entry'])
            raw_pnl_pct = ((price - dat['entry']) / dat['entry'])
            position_size = dat['margin'] * self.leverage
            pnl_amount = position_size * raw_pnl_pct
            
            unrealized_pnl += pnl_amount
            used_margin += dat['margin']
            
        return state['balance'] + used_margin + unrealized_pnl

    def add_margin(self, symbol, current_price):
        state = st.session_state.bot_state
        data = state['portfolio'][symbol]
        
        if data['adds_count'] >= self.max_adds: return False
            
        add_amount = data['margin'] * (self.add_amount_pct / 100.0)
        
        if state['balance'] < add_amount:
            self.log(f"⚠️ Yetersiz Bakiye: {symbol}")
            return False

        old_coins = data['amount_coins']
        new_purchasing_power = add_amount * self.leverage
        new_coins = new_purchasing_power / current_price
        
        total_coins = old_coins + new_coins
        new_entry = ((data['entry'] * old_coins) + (current_price * new_coins)) / total_coins
        
        state['balance'] -= add_amount
        data['margin'] += add_amount
        data['amount_coins'] = total_coins
        data['entry'] = new_entry
        data['adds_count'] += 1
        
        self.log(f"♻️ MARJİN EKLENDİ: {symbol} | Yeni Ort: {new_entry:.4f}")
        return True

    def manual_sell(self, symbol, current_price):
        state = st.session_state.bot_state
        if symbol in state['portfolio']:
            data = state['portfolio'][symbol]
            position_size = data['amount_coins'] * current_price
            entry_val = data['amount_coins'] * data['entry']
            pnl = position_size - entry_val
            
            return_amount = data['margin'] + pnl
            state['balance'] += return_amount
            del state['portfolio'][symbol]
            
            self.log(f"MANUEL KAPATMA: {symbol} | PnL: ${pnl:.2f}")
            return True
        return False

    def check_portfolio(self, current_prices):
        state = st.session_state.bot_state
        portfolio = state['portfolio']
        to_sell = []

        for symbol, data in portfolio.items():
            if symbol not in current_prices: continue
            current_price = current_prices[symbol]
            
            raw_change = (current_price - data['entry']) / data['entry']
            lev_pct = raw_change * self.leverage * 100
            
            sell = False
            reason = ""
            
            if lev_pct >= self.take_profit:
                sell = True; reason = f"✅ TP ALINDI (%{lev_pct:.2f})"
            elif lev_pct <= -self.margin_trigger:
                if self.margin_mode and data['adds_count'] < self.max_adds:
                    self.add_margin(symbol, current_price)
                    continue
                if lev_pct <= -self.stop_loss:
                    sell = True; reason = f"🛑 STOP OUT (%{lev_pct:.2f})"
            
            if sell:
                position_value = data['amount_coins'] * current_price
                entry_value = data['amount_coins'] * data['entry']
                pnl_amount = position_value - entry_value
                
                return_val = data['margin'] + pnl_amount
                if return_val < 0: return_val = 0
                
                state['balance'] += return_val
                self.log(f"OTO ÇIKIŞ: {symbol} | {reason} | Net: ${pnl_amount:.2f}")
                to_sell.append(symbol)
        
        for sym in to_sell: del portfolio[sym]

    def execute_buy(self, symbol, price, reason, total_equity):
        state = st.session_state.bot_state
        if symbol in state['portfolio']: return
        
        margin_amount = total_equity * (self.trade_pct / 100.0)
        margin_amount = min(margin_amount, state['balance'])
        
        if margin_amount < 10: return

        pos_size_usdt = margin_amount * self.leverage
        amount_coins = pos_size_usdt / price
        
        state['balance'] -= margin_amount
        state['portfolio'][symbol] = {
            'entry': price,
            'margin': margin_amount,
            'amount_coins': amount_coins,
            'leverage': self.leverage,
            'adds_count': 0,
            'reason': reason,
            'ts': datetime.now()
        }
        self.log(f"LONG ({self.leverage}x): {symbol} | Marjin: ${margin_amount:.1f}")

bot = FuturesCloudBot()

# ================= 2. ANALİZ MOTORU & HAFIZA =================
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

# ================= 3. VERİ ÇEKME FONKSİYONLARI =================
HEADERS = {'User-Agent': 'Mozilla/5.0'}

@st.cache_data(ttl=5)
def get_market_data(exchange, min_vol_m):
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr" if exchange == "BINANCE" else "https://api.mexc.com/api/v3/ticker/24hr"
        # BIST Engeli
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
    bot.leverage = st.slider("Kaldıraç (x)", 1, 20, 10)
    bot.trade_pct = st.slider("İşlem Başı Bakiye (%)", 1, 50, 10)
    
    st.divider()
    st.subheader("🛡️ Kurtarma")
    bot.margin_mode = st.checkbox("Ekleme Modu Açık", value=True)
    bot.margin_trigger = st.number_input("Ekleme Tetikleyicisi (%)", value=15.0)
    bot.add_amount_pct = st.number_input("Ekleme Miktarı (%)", value=100.0)
    bot.max_adds = st.number_input("Max Ekleme Hakkı", value=3)
    
    st.divider()
    bot.take_profit = st.number_input("TP (Kâr Al %)", value=50.0)
    bot.stop_loss = st.number_input("SL (Stop %)", value=30.0)
    min_vol_m = st.number_input("Min Hacim ($M)", value=1)

# ================= 5. ANA EKRAN =================
st.title("☁️ AI Futures Cloud Bot")

metrics_container = st.empty()
content_container = st.empty()

state = st.session_state.bot_state

# ================= 6. ANA DÖNGÜ =================
if 'last_run' not in st.session_state:
    st.session_state.last_run = time.time()

df = get_market_data(exchange, min_vol_m)

if not df.empty:
    current_prices = dict(zip(df['symbol'], df['lastPrice']))
    total_equity = bot.get_total_equity(current_prices)
    
    # 1. METRİKLER (HATA DÜZELTİLDİ)
    with metrics_container.container():
        c1, c2, c3 = st.columns(3)
        diff = total_equity - bot.initial_balance
        c1.metric("TOPLAM VARLIK", f"${total_equity:.2f}", delta=f"{diff:.2f}")
        c2.metric("NAKİT", f"${state['balance']:.2f}")
        
        # Hesaplama
        margin = total_equity * (bot.trade_pct / 100)
        power = margin * bot.leverage
        c3.metric("GELECEK İŞLEM GÜCÜ", f"${power:.0f}")

    # 2. İÇERİK
    with content_container.container():
        tab1, tab2, tab3 = st.tabs(["📊 PİYASA", "💼 PORTFÖY", "📜 LOGLAR"])
        
        if bot_active:
            bot.check_portfolio(current_prices)

        df_view = df.sort_values(by='priceChangePercent', ascending=False).head(15)
        tech_list = []
        for _, row in df_view.iterrows():
            rsi, rvol = get_technical(row['symbol'], exchange)
            tech_list.append({'rsi': rsi, 'rvol': rvol})
        
        tech_df = pd.DataFrame(tech_list, index=df_view.index)
        full_df = pd.concat([df_view, tech_df], axis=1)
        hafizayi_guncelle(full_df)

        # TAB 1
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

        # TAB 2
        with tab2:
            if state['portfolio']:
                cols = st.columns([2, 2, 2, 2, 2])
                cols[0].markdown("**Coin**")
                cols[1].markdown("**Yatırılan**")
                cols[2].markdown("**Güncel**")
                cols[3].markdown("**PnL**")
                cols[4].markdown("**Sat**")
                st.divider()

                for sym, dat in list(state['portfolio'].items()):
                    curr = current_prices.get(sym, dat['entry'])
                    invested = dat.get('margin', dat.get('invested', 0))
                    
                    # PnL Gösterimi
                    raw_change = (curr - dat['entry']) / dat['entry']
                    lev_pct = raw_change * dat['leverage'] * 100
                    pnl_color = "green" if lev_pct >= 0 else "red"

                    with st.container():
                        cc = st.columns([2, 2, 2, 2, 2])
                        cc[0].text(f"{sym} ({dat['leverage']}x)")
                        cc[1].text(f"${invested:.1f}")
                        cc[2].text(f"{curr:.4f}")
                        cc[3].markdown(f":{pnl_color}[%{lev_pct:.2f}]")
                        if cc[4].button(f"KAPAT", key=f"btn_{sym}"):
                            bot.manual_sell(sym, curr)
                            st.rerun()
            else:
                st.info("Açık işlem yok.")

        # TAB 3
        with tab3:
            log_html = "<br>".join(state['logs'])
            st.markdown(f"<div class='bot-log'>{log_html}</div>", unsafe_allow_html=True)

else:
    st.warning("Veri bekleniyor... (API Bağlantısı)")

if bot_active:
    time.sleep(refresh_rate)
    st.rerun()
else:
    if st.button("Manuel Yenile"):
        st.rerun()
