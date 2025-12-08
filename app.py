import streamlit as st
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# --- 網頁設定 ---
st.set_page_config(page_title="美股戰情室", layout="wide") # 改為 wide 寬螢幕模式
st.title('🇺🇸 美股 AI 戰情室')

# 定義預設關注清單
WATCHLIST = ["GOOG", "AAPL", "NVDA", "BRK-B", "MSFT", "AMZN", "META", "TSLA", "AMD", "TSM", "AVGO"]

# --- 1. 批次數據抓取 (解決 Rate Limit 的關鍵) ---
@st.cache_data(ttl=300) # 快取 5 分鐘
def get_batch_data(tickers_list):
    # 一次抓取所有股票過去 1 年的數據 (用來算 52週範圍)
    # group_by='ticker' 讓資料結構更好處理
    data = yf.download(tickers_list, period="1y", group_by='ticker', auto_adjust=True, progress=False)
    return data

@st.cache_data(ttl=300)
def get_single_stock_extra(ticker):
    # 針對單一股票抓取更詳細的「基本面」數據 (PE, EPS)
    # 這是最容易被擋的部分，所以單獨拆開，失敗也不影響總表
    try:
        stock = yf.Ticker(ticker)
        # 優先使用 fast_info
        info = {}
        try:
            info['marketCap'] = stock.fast_info.market_cap
        except:
            info['marketCap'] = None
            
        # 嘗試抓取 PE (手動計算備援)
        pe_ratio = None
        try:
            # 嘗試官方接口
            if stock.info and 'trailingPE' in stock.info and stock.info['trailingPE']:
                pe_ratio = stock.info['trailingPE']
            # 手動計算備援
            if pe_ratio is None:
                current_price = stock.fast_info.last_price
                financials = stock.quarterly_income_stmt
                if not financials.empty:
                    # 模糊搜尋 EPS 欄位
                    eps_row = financials.loc[financials.index.str.contains('Basic EPS', case=False, na=False)]
                    if not eps_row.empty:
                        ttm_eps = eps_row.iloc[0, :4].sum() # 近四季總和
                        if ttm_eps > 0:
                            pe_ratio = current_price / ttm_eps
        except:
            pass
            
        return pe_ratio, info
    except:
        return None, {}

# --- 2. 建立總表數據 ---
def create_summary_dataframe(data, tickers):
    summary_list = []
    
    for t in tickers:
        try:
            # 取得該股票的 DataFrame
            df = data[t]
            if df.empty:
                continue
            
            # 取得最新一筆資料
            last_day = df.iloc[-1]
            prev_day = df.iloc[-2]
            
            # 計算數據
            price = last_day['Close']
            change = price - prev_day['Close']
            pct_change = (change / prev_day['Close']) * 100
            volume = last_day['Volume']
            
            # 52 週範圍
            year_high = df['High'].max()
            year_low = df['Low'].min()
            
            # 加入列表
            summary_list.append({
                "代碼": t,
                "現價": price,
                "漲跌幅 (%)": pct_change,
                "成交量": volume,
                "52週最低": year_low,
                "52週最高": year_high
            })
        except Exception as e:
            continue
            
    return pd.DataFrame(summary_list)

# --- 主程式區塊 ---

# 1. 載入總表數據
with st.spinner('正在連線交易所取得最新報價...'):
    batch_data = get_batch_data(WATCHLIST)

if not batch_data.empty:
    # 製作並顯示總表
    st.subheader("📊 市場即時概況")
    df_summary = create_summary_dataframe(batch_data, WATCHLIST)
    
    # 格式化顯示 (讓表格變漂亮)
    st.dataframe(
        df_summary.style.format({
            "現價": "${:.2f}",
            "漲跌幅 (%)": "{:+.2f}%", # 顯示正負號
            "成交量": "{:,.0f}",      # 加千分位逗號
            "52週最低": "${:.2f}",
            "52週最高": "${:.2f}"
        }).background_gradient(subset=['漲跌幅 (%)'], cmap='RdYlGn', vmin=-3, vmax=3), # 漲跌幅上色
        use_container_width=True,
        hide_index=True
    )
else:
    st.error("無法取得市場數據，請稍後再試。")

st.divider()

# 2. 單一個股深入分析
col1, col2 = st.columns([1, 3])

with col1:
    st.subheader("🔍 個股分析")
    # 選單
    selected_ticker = st.selectbox("選擇股票", ["請選擇..."] + WATCHLIST + ["自行輸入"])
    
    target_ticker = ""
    if selected_ticker == "自行輸入":
        target_ticker = st.text_input("輸入代碼", "INTC").upper()
    elif selected_ticker != "請選擇...":
        target_ticker = selected_ticker

# 右側顯示區
with col2:
    if target_ticker:
        # 如果剛剛的批次資料有包含這個股票，直接拿來用 (省流量)
        if target_ticker in WATCHLIST and not batch_data.empty:
            df = batch_data[target_ticker].copy()
        else:
            # 如果是自行輸入的冷門股，才單獨去抓
            try:
                stock_temp = yf.Ticker(target_ticker)
                df = stock_temp.history(period="1y")
            except:
                df = pd.DataFrame()

        if not df.empty:
            # 取得額外基本面 (PE)
            pe_ratio, extra_info = get_single_stock_extra(target_ticker)
            current_price = df['Close'].iloc[-1]
            
            # --- 信心值計算邏輯 ---
            confidence_score = 0
            reasons = []

            # 1. RSI
            df['RSI'] = ta.rsi(df['Close'], length=14)
            rsi = df['RSI'].iloc[-1]
            if rsi < 30:
                confidence_score += 40
                reasons.append(f"✅ RSI 過低 ({rsi:.1f})，超賣")
            elif rsi > 70:
                confidence_score -= 20
                reasons.append(f"⚠️ RSI 過高 ({rsi:.1f})，超買")
            else:
                confidence_score += 10
                reasons.append(f"ℹ️ RSI 中性 ({rsi:.1f})")

            # 2. PE Ratio
            if pe_ratio:
                if pe_ratio < 25:
                    confidence_score += 30
                    reasons.append(f"✅ 本益比 ({pe_ratio:.1f}) 合理")
                elif pe_ratio > 60:
                    reasons.append(f"⚠️ 本益比 ({pe_ratio:.1f}) 偏高")
                else:
                    reasons.append(f"ℹ️ 本益比 ({pe_ratio:.1f})")
            else:
                confidence_score += 10
                reasons.append("ℹ️ 無本益比數據 (可能虧損)")

            # 3. 均線
            ma_50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) > 50 else 0
            if current_price > ma_50:
                confidence_score += 30
                reasons.append("✅ 股價在 50日均線上 (多頭)")
            else:
                reasons.append("⚠️ 股價跌破 50日均線")

            # --- 顯示標頭資訊 ---
            st.markdown(f"## {target_ticker} - 現價: **${current_price:.2f}**")
            
            # 信心分數條
            score_col, chart_col = st.columns([1, 2])
            
            st.progress(max(0, min(100, int(confidence_score))))
            if confidence_score >= 70:
                st.success(f"評分: {confidence_score} (強力買入)")
            elif confidence_score >= 40:
                st.warning(f"評分: {confidence_score} (觀望持有)")
            else:
                st.error(f"評分: {confidence_score} (不建議)")
                
            with st.expander("查看分析理由"):
                for r in reasons:
                    st.write(r)

            # --- 專業圖表 (Plotly) ---
            # 建立雙子圖 (上圖：K線, 下圖：成交量)
            fig = make_subplots(
                rows=2, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.05, 
                row_heights=[0.7, 0.3],
                subplot_titles=(f'{target_ticker} 走勢圖', '成交量')
            )

            # 上圖：K線圖 (Candlestick)
            fig.add_trace(go.Candlestick(
                x=df.index,
                open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'],
                name='Price'
            ), row=1, col=1)
            
            # 加入 50MA 線
            fig.add_trace(go.Scatter(
                x=df.index, y=df['Close'].rolling(50).mean(), 
                line=dict(color='orange', width=1), 
                name='50 MA'
            ), row=1, col=1)

            # 下圖：成交量 (Volume)
            # 根據漲跌變色 (漲=紅, 跌=綠 - 台股習慣，美股習慣相反，這裡用美股習慣：漲=綠/白, 跌=紅)
            colors = ['green' if row['Open'] - row['Close'] <= 0 else 'red' for index, row in df.iterrows()]
            fig.add_trace(go.Bar(
                x=df.index, y=df['Volume'],
                marker_color=colors,
                name='Volume'
            ), row=2, col=1)

            # 調整版面
            fig.update_layout(
                xaxis_rangeslider_visible=False, # 隱藏下方預設的滑桿
                height=500,
                margin=dict(l=20, r=20, t=40, b=20),
                showlegend=False
            )

            st.plotly_chart(fig, use_container_width=True)

        else:
            st.error("找不到該股票數據。")
