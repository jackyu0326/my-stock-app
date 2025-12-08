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

# --- 1. 核心工具：本益比計算機 (含 TSM/ADR 強力修復) ---
@st.cache_data(ttl=3600)
def get_pe_ratio_robust(ticker_symbol, current_price):
    stock = yf.Ticker(ticker_symbol)
    pe = None
    
    # [步驟 1] 優先嘗試官方屬性 (Trailing & Forward)
    # Forward PE 通常在 Trailing PE 失敗時還能抓得到
    try:
        info = stock.info
        if info:
            if info.get('trailingPE'):
                return info['trailingPE']
            elif info.get('forwardPE'):
                return info['forwardPE']
    except:
        info = {}

    # [步驟 2] 手動計算 (強力備援)
    try:
        # A. 判斷幣別與 ADR 修正
        stock_currency = info.get('currency', 'USD')
        fin_currency = info.get('financialCurrency', stock_currency)
        
        # --- TSM 專屬暴力修復補丁 ---
        # 如果 yfinance 抓不到 TSM 的幣別資訊，我們手動告訴它
        if ticker_symbol == 'TSM' and fin_currency == 'USD': 
            fin_currency = 'TWD'
        # ---------------------------

        exchange_rate = 1.0
        
        # 抓取匯率
        if stock_currency != fin_currency:
            try:
                currency_pair = f"{fin_currency}=X" # 例如 TWD=X
                rate_data = yf.Ticker(currency_pair).history(period="1d")
                if not rate_data.empty:
                    rate = rate_data['Close'].iloc[-1]
                    if rate > 0:
                        exchange_rate = rate
            except:
                # 如果抓不到匯率，針對 TSM 給一個粗略預設值 (避免除以 1 導致算錯)
                if ticker_symbol == 'TSM': exchange_rate = 32.5 

        # B. 抓取財報 EPS
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
                # 取最近 4 季 EPS 加總
                vals = eps_row.values
                vals = [v for v in vals if pd.notna(v) and v != 0]
                
                ttm_eps_raw = 0
                if len(vals) >= 4:
                    ttm_eps_raw = sum(vals[:4])
                elif len(vals) > 0:
                    ttm_eps_raw = vals[0] * 4

                if ttm_eps_raw > 0:
                    # [ADR 換股修正]
                    # TSM ADR 代表 5 股台股，所以 EPS 要先 * 5
                    adr_multiplier = 1.0
                    if ticker_symbol == 'TSM':
                        adr_multiplier = 5.0
                    
                    # 計算公式: (原始EPS * ADR倍率) / 匯率
                    ttm_eps_adj = (ttm_eps_raw * adr_multiplier) / exchange_rate
                    
                    if ttm_eps_adj > 0:
                        pe = current_price / ttm_eps_adj

        # [步驟 3] 最終防呆 (Sanity Check)
        # 如果算出來還是 < 5 (除了嚴重虧損，不太可能)，嘗試最後一招：可能是匯率忘了除
        if pe is not None and pe < 5:
            # 啟發式修正：如果 PE 只有 3.5，乘上 30 倍匯率變成 105，雖然偏高但比較合理?
            # 這裡保守一點，如果真的算不出來，就回傳 None，避免誤導
            # 但針對 TSM，如果我們上面的修正有效，應該不會掉入這裡
            pe = None
            
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

            # E. 建議
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
            # 準備數據
            current_price = df['Close'].iloc[-1]
            pe = get_pe_ratio_robust(target_ticker, current_price)
            df['RSI'] = ta.rsi(df['Close'], length=14)
            ma50 = df['Close'].rolling(50).mean()
            current_rsi = df['RSI'].iloc[-1]
            current_ma50 = ma50.iloc[-1] if not pd.isna(ma50.iloc[-1]) else 0

            st.markdown(f"## {target_ticker} - 現價: **${current_price:.2f}**")

            # --- 詳細分析報告 ---
            reasons = []
            
            # RSI 分析
            if current_rsi < 30:
                reasons.append(f"✅ **RSI 技術面**: 數值為 {current_rsi:.1f} (超賣區)，短線反彈機率高。")
            elif current_rsi > 70:
                reasons.append(f"⚠️ **RSI 技術面**: 數值為 {current_rsi:.1f} (超買區)，過熱風險高。")
            else:
                reasons.append(f"ℹ️ **RSI 技術面**: 數值為 {current_rsi:.1f} (中性)，無極端訊號。")

            # 均線分析
            if current_price > current_ma50:
                reasons.append(f"✅ **均線趨勢**: 股價高於 50MA (${current_ma50:.2f})，呈現多頭排列。")
            else:
                reasons.append(f"⚠️ **均線趨勢**: 股價跌破 50MA (${current_ma50:.2f})，走勢轉弱。")

            # 本益比分析
            if pe:
                if pe < 25:
                    reasons.append(f"✅ **估值 (P/E)**: 本益比 {pe:.1f} 倍，處於合理/低估區間。")
                elif pe > 60:
                    reasons.append(f"⚠️ **估值 (P/E)**: 本益比 {pe:.1f} 倍，估值相對較高。")
                else:
                    reasons.append(f"ℹ️ **估值 (P/E)**: 本益比 {pe:.1f} 倍，屬於正常範圍。")
            else:
                reasons.append("⚠️ **估值**: 無法取得有效本益比數據。")

            with st.expander("📊 點擊查看 AI 詳細分析報告 (RSI、均線、本益比)", expanded=True):
                for r in reasons:
                    st.write(r)

            # --- 繪圖區 ---
            titles = (f'{target_ticker} K線圖', '成交量')
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True, 
                row_heights=[0.7, 0.3], vertical_spacing=0.05,
                subplot_titles=titles
            )

            candle = go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'], name='Price'
            )
            fig.add_trace(candle, row=1, col=1)
            
            ma_line = go.Scatter(
                x=df.index, y=ma50, 
                line=dict(color='orange', width=1.5), name='50 MA'
            )
            fig.add_trace(ma_line, row=1, col=1)

            colors = ['green' if o < c else 'red' for o, c in zip(df['Open'], df['Close'])]
            volume_bar = go.Bar(
                x=df.index, y=df['Volume'], 
                marker_color=colors, name='Volume'
            )
            fig.add_trace(volume_bar, row=2, col=1)

            fig.update_layout(height=500, xaxis_rangeslider_visible=False, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
