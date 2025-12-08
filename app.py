import streamlit as st
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 網頁設定 ---
st.set_page_config(page_title="美股戰情室 Pro", layout="wide")
st.title('🇺🇸 美股 AI 戰情室 Pro')

# 定義關注清單
WATCHLIST = ["GOOG", "AAPL", "NVDA", "BRK-B", "MSFT", "AMZN", "META", "TSLA", "AMD", "TSM", "AVGO", "INTC"]

# --- 1. 核心工具：本益比計算機 ---
@st.cache_data(ttl=3600)
def get_pe_ratio_robust(ticker_symbol, current_price):
    stock = yf.Ticker(ticker_symbol)
    pe = None
    
    # 方法 A: 嘗試官方屬性
    try:
        if stock.info and stock.info.get('trailingPE'):
            return stock.info['trailingPE']
    except:
        pass

    # 方法 B: 手動挖季報
    try:
        stmt = stock.quarterly_income_stmt
        if stmt.empty:
            stmt = stock.income_stmt
        
        if not stmt.empty:
            possible_names = ['Basic EPS', 'Diluted EPS', 'BasicEPS', 'DilutedEPS']
            eps_row = None
            for idx in stmt.index:
                for name in possible_names:
                    if name.lower() in str(idx).lower():
                        eps_row = stmt.loc[idx]
                        break
                if eps_row is not None:
                    break
            
            if eps_row is not None:
                vals = eps_row.values
                vals = [v for v in vals if pd.notna(v) and v != 0]
                if len(vals) >= 4:
                    ttm_eps = sum(vals[:4])
                elif len(vals) > 0:
                    ttm_eps = vals[0] * 4
                else:
                    ttm_eps = 0

                if ttm_eps > 0:
                    pe = current_price / ttm_eps
    except:
        pass

    return pe

# --- 2. 批次數據抓取 ---
@st.cache_data(ttl=300)
def get_market_data(tickers):
    data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False)
    return data

# --- 3. 產生 AI 建議總表 ---
def generate_summary_table(data, tickers):
    summary_list = []
    
    progress_bar = st.progress(0, text="分析中...")
    
    for i, t in enumerate(tickers):
        try:
            progress_bar.progress((i + 1) / len(tickers), text=f"正在分析 {t}...")
            
            if t not in data.columns.levels[0]:
                continue
            
            df = data[t].copy()
            if df.empty: continue

            # A. 基礎數據
            current_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            change_pct = (current_price - prev_price) / prev_price * 100
            volume = df['Volume'].iloc[-1]
            
            # B. 技術指標
            df['RSI'] = ta.rsi(df['Close'], length=14)
            rsi = df['RSI'].iloc[-1] if pd.notna(df['RSI'].iloc[-1]) else 50
            ma_50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else current_price
            
            # C. 基本面
            pe = get_pe_ratio_robust(t, current_price)
            
            # D. AI 評分
            score = 0
            
            # RSI 評分
            if rsi < 30: score += 3
            elif rsi > 70: score -= 2
            else: score += 1
            
            # 均線評分
            if current_price > ma_50: score += 3
            else: score -= 1
            
            # PE 評分
            pe_str = "N/A"
            if pe:
                pe_str = f"{pe:.1f}"
                if pe < 25: score += 4
                elif pe > 60: score -= 2
                else: score += 2
            else:
                score += 1

            # E. 產生建議
            if score >= 7:
                suggestion = "🟢 強力買進"
            elif score >= 4:
                suggestion = "🟡 觀望/持有"
            else:
                suggestion = "🔴 建議賣出"

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
            
        except Exception as e:
            continue
            
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
    selected_ticker = st.selectbox("選擇股票", ["請選擇..."] + WATCHLIST + ["自行輸入"])
    target_ticker = ""
    if selected_ticker == "自行輸入":
        target_ticker = st.text_input("輸入代碼", "PLTR").upper()
    elif selected_ticker != "請選擇...":
        target_ticker = selected_ticker

with col2:
    if target_ticker:
        if target_ticker in WATCHLIST and target_ticker in market_data.columns.levels[0]:
            df = market_data[target_ticker].copy()
        else:
            try:
                stock_temp = yf.Ticker(target_ticker)
                df = stock_temp.history(period="1y")
            except:
                df = pd.DataFrame()

        if not df.empty:
            current_price = df['Close'].iloc[-1]
            pe = get_pe_ratio_robust(target_ticker, current_price)
            df['RSI'] = ta.rsi(df['Close'], length=14)
            
            st.markdown(f"## {target_ticker} - 現價: **${current_price:.2f}**")
            
            if pe:
                st.info(f"📊 經計算，目前本益比 (P/E) 約為：**{pe:.2f}**")
            else:
                st.warning("⚠️ 無法取得有效本益比數據")

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                row_heights=[0.7, 0.3], vertical_spacing=0.05,
                                subplot_titles=(f'{target_ticker} K線圖', '成交量'))

            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'],
                                         low=df['Low'], close=df['Close'], name
