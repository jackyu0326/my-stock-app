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
    
    # 建立進度條
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
            score =
