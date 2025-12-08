import streamlit as st
import yfinance as yf
import pandas_ta as ta
import pandas as pd

# 設定網頁標題
st.set_page_config(page_title="美股 AI 信心儀表板", layout="centered")
st.title('美股 AI 信心值分析儀表板')

# --- 1. 核心數據抓取函數 (含三層備援機制) ---
@st.cache_data(ttl=300)
def get_stock_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # A. 抓取歷史價格 (技術面用)
        df = stock.history(period="6mo")
        if df.empty:
            return None, None, "抓取不到歷史股價，請確認代碼是否正確。"
            
        # B. 抓取基本資料 (嘗試多種來源)
        info = {}
        
        # 1. 取得目前股價 (最優先使用 fast_info，最準且不被擋)
        try:
            current_price = stock.fast_info.last_price
        except:
            current_price = df['Close'].iloc[-1]
        
        info['currentPrice'] = current_price

        # 2. 取得/計算 本益比 (PE Ratio) - 這是您原本卡關的地方
        pe_ratio = None
        
        # 方法一：直接嘗試從 info 拿 (最近常失敗，但還是試試)
        try:
            raw_info = stock.info
            if raw_info and 'trailingPE' in raw_info and raw_info['trailingPE'] is not None:
                pe_ratio = raw_info['trailingPE']
            elif raw_info and 'forwardPE' in raw_info and raw_info['forwardPE'] is not None:
                pe_ratio = raw_info['forwardPE'] # 如果沒有過去PE，用未來PE頂替
        except:
            pass
        
        # 方法二：如果方法一失敗，手動計算 (Price / TTM EPS)
        if pe_ratio is None:
            try:
                # 抓取季報 (Income Statement)
                financials = stock.quarterly_income_stmt
                if not financials.empty:
                    # 尋找 'Basic EPS' 這一列
                    # 不同公司名稱可能微調，模糊搜尋
                    eps_row = financials.loc[financials.index.str.contains('Basic EPS', case=False, na=False)]
                    
                    if not eps_row.empty:
                        # 取最近 4 季的 EPS 加總 (= TTM EPS)
                        last_4_quarters_eps = eps_row.iloc[0, :4].sum()
                        if last_4_quarters_eps > 0:
                            pe_ratio = current_price / last_4_quarters_eps
            except Exception as e:
                print(f"手動計算 PE 失敗: {e}")

        info['trailingPE'] = pe_ratio

        return df, info, None
        
    except Exception as e:
        return None, None, str(e)

# --- 2. 股票選擇介面 ---
default_stocks = ["GOOG", "AAPL", "NVDA", "BRK-B", "MSFT", "AMZN", "META", "TSLA", "AMD", "TSM", "AVGO"]
col1, col2 = st.columns([2, 1])
with col1:
    selection = st.selectbox("📝 請選擇股票：", ["請選擇..."] + default_stocks + ["🔍 自行輸入代碼"])

ticker = ""
if selection == "🔍 自行輸入代碼":
    with col2:
        ticker = st.text_input("輸入代碼", "INTC").upper()
elif selection != "請選擇...":
    ticker = selection

# --- 3. 分析與顯示邏輯 ---
if ticker:
    st.markdown(f"### 正在分析: **{ticker}**")
    
    with st.spinner(f'正在讀取數據並計算信心值...'):
        df, info, error_msg = get_stock_data(ticker)

    if error_msg:
        st.error(f"發生錯誤: {error_msg}")
    elif df is not None:
        current_price = info.get('currentPrice', 0)
        st.metric(label="當前股價 (USD)", value=f"${current_price:.2f}")

        confidence_score = 0
        reasons = []

        # [指標 1] RSI (技術面)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        if not df['RSI'].empty:
            current_rsi = df['RSI'].iloc[-1]
            if current_rsi < 30:
                confidence_score += 40
                reasons.append(f"✅ RSI 過低 ({current_rsi:.1f})，處於超賣區")
            elif current_rsi > 70:
                confidence_score -= 20
                reasons.append(f"⚠️ RSI 過高 ({current_rsi:.1f})，處於超買區")
            else:
                confidence_score += 10
                reasons.append(f"ℹ️ RSI 中性 ({current_rsi:.1f})")

        # [指標 2] 本益比 (基本面) - 這裡現在保證會有值，或是優雅跳過
        pe_ratio = info.get('trailingPE')
        
        if pe_ratio is not None:
            # 針對科技股稍微放寬標準
            if pe_ratio < 25: 
                confidence_score += 30
                reasons.append(f"✅ 本益比 ({pe_ratio:.1f}) 處於合理/低估區間")
            elif pe_ratio > 60:
                 reasons.append(f"⚠️ 本益比 ({pe_ratio:.1f}) 偏高，溢價風險大")
            else:
                reasons.append(f"ℹ️ 本益比 ({pe_ratio:.1f}) 屬於正常範圍")
        else:
             # 真的算不出來時，給一個基本分，不要讓它變 0 分
             confidence_score += 10 
             reasons.append("⚠️ 無法取得本益比數據 (可能為虧損公司)，暫不列入評分")
        
        # [指標 3] 均線 (趨勢面)
        if len(df) > 50:
            ma_50 = df['Close'].rolling(50).mean().iloc[-1]
            if current_price > ma_50:
                confidence_score += 30
                reasons.append("✅ 股價位於 50日均線之上 (多頭趨勢)")
            else:
                reasons.append("⚠️ 股價跌破 50日均線 (趨勢轉弱)")

        # --- 顯示結果 ---
        st.divider()
        st.subheader(f"🤖 購入信心分數: {int(confidence_score)} / 100")
        st.progress(max(0, min(100, int(confidence_score))))

        if confidence_score >= 70:
            st.success("評級: 強力買入 (Strong Buy)")
        elif confidence_score >= 40:
            st.warning("評級: 觀望 / 持有 (Hold)")
        else:
            st.error("評級: 不建議購入 (Sell/Avoid)")

        with st.expander("查看詳細分析理由", expanded=True):
            for reason in reasons:
                st.write(reason)

        st.line_chart(df['Close'])
