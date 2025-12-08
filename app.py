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

# --- 1. 核心工具：超級強韌的本益比計算機 ---
@st.cache_data(ttl=3600) # 本益比數據快取 1 小時 (不用一直抓)
def get_pe_ratio_robust(ticker_symbol, current_price):
    """
    嘗試各種方法抓取本益比，如果都失敗，就去財報裡挖 EPS 自己算。
    """
    stock = yf.Ticker(ticker_symbol)
    pe = None
    
    # 方法 A: 嘗試官方屬性 (最快，但常失敗)
    try:
        if stock.info and stock.info.get('trailingPE'):
            return stock.info['trailingPE']
    except:
        pass

    # 方法 B: 手動挖季報 (Quarterly Financials)
    try:
        # 抓取損益表
        stmt = stock.quarterly_income_stmt
        if stmt.empty:
            stmt = stock.income_stmt # 如果沒季報，抓年報
        
        if not stmt.empty:
            # 尋找各種可能的 EPS 欄位名稱 (Yahoo 欄位名常變)
            possible_names = ['Basic EPS', 'Diluted EPS', 'BasicEPS', 'DilutedEPS']
            eps_row = None
            
            # 模糊搜尋
            for idx in stmt.index:
                for name in possible_names:
                    if name.lower() in str(idx).lower():
                        eps_row = stmt.loc[idx]
                        break
                if eps_row is not None:
                    break
            
            if eps_row is not None:
                # 取最近 4 季 (或最近 1 年) 的 EPS 加總
                # 這裡做簡單處理：如果是季報取前4欄，年報取前1欄
                vals = eps_row.values
                vals = [v for v in vals if pd.notna(v) and v != 0] # 過濾掉空值
                
                if len(vals) >= 4:
                    ttm_eps = sum(vals[:4])
                elif len(vals) > 0:
                    ttm_eps = vals[0] * (4 if len(stmt.columns) > 2 else 1) # 粗略估算
                else:
                    ttm_eps = 0

                if ttm_eps > 0:
                    pe = current_price / ttm_eps
    except Exception as e:
        # print(f"手動計算 PE 失敗 ({ticker_symbol}): {e}")
        pass

    return pe

# --- 2. 批次數據抓取 (含技術指標計算) ---
@st.cache_data(ttl=300)
def get_market_data(tickers):
    # 下載 1 年歷史數據
    data = yf.download(tickers, period="1y", group_by='ticker', auto_adjust=True, progress=False)
    return data

# --- 3. 產生 AI 建議總表 ---
def generate_summary_table(data, tickers):
    summary_list = []
    
    # 進度條 (因為要算本益比，會跑一下)
    progress_bar = st.progress(0, text="正在分析市場數據...")
    
    for i, t in enumerate(tickers):
        try:
            # 處理進度
            progress_bar.progress((i + 1) / len(tickers), text=f"正在分析 {t}...")
            
            # 取得該股歷史數據
            if t not in data.columns.levels[0]:
                continue
                
            df = data[t].copy()
            if df.empty: 
                continue

            # --- A. 基礎數據 ---
            current_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            change_pct = (current_price - prev_price) / prev_price * 100
            volume = df['Volume'].iloc[-1]
            
            # --- B. 技術指標 (RSI & MA) ---
            # 計算 RSI
            df['RSI'] = ta.rsi(df['Close'], length=14)
            rsi = df['RSI'].iloc[-1] if pd.notna(df['RSI'].iloc[-1]) else 50
            
            # 計算均線
            ma_50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else current_price
            
            # --- C. 基本面 (PE) ---
            pe = get_pe_ratio_robust(t, current_price)
            
            # --- D. AI 評分邏輯 (滿分 10 分) ---
            score = 0
            reasons = []
            
            # 1. RSI (權重 3分)
            if rsi < 30: score += 3 # 超賣，買進訊號
            elif rsi > 70: score -= 2 # 超買，賣出訊號
            else: score += 1
            
            # 2. 均線 (權重 3分)
            if current_price > ma_50: score += 3 # 多頭
            else: score -= 1 # 空頭
            
            # 3. 本益比 (權重 4分)
            pe_str = "N/A"
            if pe:
                pe_str = f"{pe:.1f}"
                if pe < 25: score += 4
                elif pe > 60: score -= 2
                else: score += 2
            else:
                score += 1 # 沒數據給基本分
            
            # --- E. 產生建議 ---
            if score >= 7:
                suggestion = "🟢 強力買進"
            elif score >= 4:
                suggestion = "🟡 觀望/持有"
            else:
                suggestion = "🔴
