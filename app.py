import streamlit as st
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

# --- 網頁設定 ---
st.set_page_config(page_title="美股戰情室 Pro", layout="wide")
st.title('🇺🇸 美股 AI 戰情室 Pro')

# 定義關注清單
WATCHLIST = ["GOOG", "AAPL", "NVDA", "BRK-B", "MSFT", "AMZN", "META", "TSLA", "AMD", "TSM", "AVGO", "INTC"]

# --- 0. 智慧代碼搜尋引擎 ---
@st.cache_data(ttl=3600)
def search_symbol_yahoo(query):
    if not query: return None
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=1&newsCount=0"
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        if 'quotes' in data and len(data['quotes']) > 0:
            best_match = data['quotes'][0]
            return best_match.get('symbol'), best_match.get('longname')
    except:
        pass
    return None, None

# --- 1. 核心工具：本益比計算機 (TSM 修正版) ---
@st.cache_data(ttl=3600)
def get_pe_ratio_robust(ticker_symbol, current_price):
    stock = yf.Ticker(ticker_symbol)
    pe = None
    
    # [步驟 1] 優先嘗試官方屬性
    try:
        info = stock.info
        if info:
            if info.get('trailingPE'): return info['trailingPE']
            elif info.get('forwardPE'): return info['forwardPE']
    except:
        info = {}

    # [步驟 2] 手動計算
    try:
        # A. 匯率處理
        stock_currency = info.get('currency', 'USD')
        fin_currency = info.get('financialCurrency', stock_currency)
        
        # TSM 強制修正
        if ticker_symbol == 'TSM' and fin_currency == 'USD': fin_currency = 'TWD'

        exchange_rate = 1.0
        if stock_currency != fin_currency:
            try:
                currency_pair = f"{fin_currency}=X"
                rate_data = yf.Ticker(currency_pair).history(period="1d")
                if not rate_data.empty:
                    rate = rate_data['Close'].iloc[-1]
                    if rate > 0: exchange_rate = rate
            except:
                if ticker_symbol == 'TSM': exchange_rate = 32.5 

        # B. 抓取財報 EPS
        stmt = stock.quarterly_income_stmt
        if stmt.empty: stmt = stock.income_stmt
        
        if not stmt.empty:
            possible_names = ['Basic EPS', 'Diluted EPS', 'BasicEPS']
            eps_row = None
            for idx in stmt.index:
                for name in possible_names:
                    if name.lower() in str(idx).lower():
                        eps_row = stmt.loc[idx]
                        break
                if eps_row is not None: break
            
            if eps_row is not None:
                vals = [v for v in eps_row.values if pd.notna(v) and v != 0]
                ttm_eps_raw = sum(vals[:4]) if len(vals) >= 4 else (vals[0] * 4 if len(vals) > 0 else 0)

                if ttm_eps_raw > 0:
                    # TSM 預設換股倍率
                    adr_multiplier = 5.0 if ticker_symbol == 'TSM' else 1.0
                    
                    # 計算 EPS (換成美元)
                    ttm_eps_adj = (ttm_eps_raw * adr_multiplier) / exchange_rate
                    
                    if ttm_eps_adj > 0:
                        temp_pe = current_price / ttm_eps_adj
                        
                        # [TSM 關鍵修正]
                        # 如果算出來 PE < 10 (例如 5.7)，代表我們多乘了一次 5 倍
                        # 或是 Yahoo 已經給了我們 ADR 的 EPS
                        if ticker_symbol == 'TSM' and temp_pe < 10:
                            pe = temp_pe * 5.0  # 還原正常值
                        else:
                            pe = temp_pe

        # [步驟 3] 最終防呆
        if pe is not None and pe < 5: pe = None
            
    except:
        pass

    return pe

# --- 2. 批次數據抓取 ---
@st.cache_data(ttl=300)
def get_market_data(tickers):
    data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False)
    return data

# --- 3. 產生總表 ---
def generate_summary_table(data, tickers):
    summary_list = []
    progress_bar = st.progress(0, text="分析中...")
    
    for i, t in enumerate(tickers):
        try:
            progress_bar.progress((i + 1) / len(tickers), text=f"正在分析 {t}...")
            if t not in data.columns.levels[0]: continue
            
            df = data[t].copy()
            if df.empty: continue

            current_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            change_pct = (current_price - prev_price) / prev_price * 100
            volume = df['Volume'].iloc[-1]
            
            df['RSI'] = ta.rsi(df['Close'], length=14)
            rsi = df['RSI'].iloc[-1] if pd.notna(df['RSI'].iloc[-1]) else 50
            ma_50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else current_price
            
            pe = get_pe_ratio_robust(t, current_price)
            
            score = 0
            if rsi < 30: score += 3
            elif rsi > 70: score -= 2
            else: score += 1
            
            if current_price > ma_50: score += 3
            else: score -= 1
            
            pe_str = "N/A"
            if pe:
                pe_str = f"{pe:.1f}"
                if pe < 25: score += 4
                elif pe > 60: score -= 2
                else: score += 2
            else:
                score += 1

            if score >= 7: suggestion = "🟢 強力買進"
            elif score >= 4: suggestion = "🟡 觀望/持有"
            else: suggestion = "🔴 建議賣出"

            summary_list.append({
                "代碼": t,
                "現價": current_price,
                "漲跌幅": change_pct / 100,
                "RSI": rsi,
                "本益比 (PE)": pe_str,
                "AI 建議": suggestion,
                "綜合評分": score,
                "成交量": volume
            })
        except: continue
            
    progress_bar.empty()
    return pd.DataFrame(summary_list)

# --- 主程式 ---

with st.spinner('正在連線交易所...'):
    market_data = get_market_data(WATCHLIST)

if not market_data.empty:
    st.subheader("📊 AI 投資建議總表")
    df_summary = generate_summary_table(market_data, WATCHLIST)
    
    st.dataframe(
        df_summary.style.format({
            "現價": "${:.2f}",
            "漲跌幅": "{:+.2%}",
            "RSI": "{:.1f}",
            "成交量": "{:,.0f}",
            "綜合評分": "{:.0f}"
        }).map(lambda x: 'color: green' if x > 0 else 'color: red', subset=['漲跌幅'])
          .map(lambda x: 'background-color: #d4edda' if '買進' in str(x) else ('background-color: #f8d7da' if '賣出' in str(x) else ''), subset=['AI 建議']),
        use_container_width=True,
        hide_index=True
    )
else:
    st.error("無法取得數據，請稍後再試。")

st.divider()

col1, col2 = st.columns([1, 3])

with col1:
    st.subheader("🔍 個股深度分析")
    input_mode = st.radio("選擇模式", ["清單選股", "🔍 智慧搜尋"], horizontal=True)
    
    target_ticker = ""
    if input_mode == "清單選股":
        target_ticker = st.selectbox("選擇股票", WATCHLIST)
    else:
        user_input = st.text_input("輸入代碼或公司名 (如: Qualcomm)", "QCOM")
        if user_input:
            u_upper = user_input.upper().strip()
            if u_upper in WATCHLIST:
                target_ticker = u_upper
            else:
                check = yf.Ticker(u_upper)
                try:
                    if not check.history(period="5d").empty: target_ticker = u_upper
                    else: raise Exception()
                except:
                    with st.spinner(f"搜尋 '{user_input}'..."):
                        found, fname = search_symbol_yahoo(user_input)
                        if found:
                            st.success(f"🔍 已修正為: **{found}** ({fname})")
                            target_ticker = found
                        else:
                            st.error("找不到股票")

with col2:
    if target_ticker:
        if target_ticker in WATCHLIST and target_ticker in market_data.columns.levels[0]:
            df = market_data[target_ticker].copy()
        else:
            try:
                stock_temp = yf.Ticker(target_ticker)
                df = stock_temp.history(period="1y")
            except: df = pd.DataFrame()

        if not df.empty:
            current_price = df['Close'].iloc[-1]
            pe = get_pe_ratio_robust(target_ticker, current_price)
            df['RSI'] = ta.rsi(df['Close'], length=14)
            ma50 = df['Close'].rolling(50).mean()
            current_rsi = df['RSI'].iloc[-1]
            current_ma50 = ma50.iloc[-1] if not pd.isna(ma50.iloc[-1]) else 0

            st.markdown(f"## {target_ticker} - 現價: **${current_price:.2f}**")

            reasons = []
            if current_rsi < 30: reasons.append(f"✅ **RSI**: {current_rsi:.1f} (超賣)")
            elif current_rsi > 70: reasons.append(f"⚠️ **RSI**: {current_rsi:.1f} (超買)")
            else: reasons.append(f"ℹ️ **RSI**: {current_rsi:.1f} (中性)")

            if current_price > current_ma50: reasons.append(f"✅ **均線**: 股價 > 50MA (多頭)")
            else: reasons.append(f"⚠️ **均線**: 股價 < 50MA (轉弱)")

            if pe:
                if pe < 25: reasons.append(f"✅ **P/E**: {pe:.1f} (合理)")
                elif pe > 60: reasons.append(f"⚠️ **P/E**: {pe:.1f} (偏高)")
                else: reasons.append(f"ℹ️ **P/E**: {pe:.1f} (正常)")
            else: reasons.append("⚠️ **P/E**: 無數據")

            with st.expander("📊 查看詳細分析報告", expanded=True):
                for r in reasons: st.write(r)

            titles = (f'{target_ticker} K線圖', '成交量')
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05, subplot_titles=titles)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='Price'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=ma50, line=dict(color='orange', width=1.5), name='50 MA'), row=1, col=1)
            colors = ['green' if o < c else 'red' for o, c in zip(df['Open'], df['Close'])]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
            fig.update_layout(height=500, xaxis_rangeslider_visible=False, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
