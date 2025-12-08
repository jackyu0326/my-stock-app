import streamlit as st
import yfinance as yf
import pandas_ta as ta

# 設定網頁標題
st.set_page_config(page_title="美股 AI 信心儀表板", layout="centered")
st.title('美股 AI 信心值分析儀表板')

# --- 1. 定義數據抓取函數 (維持原本的防擋機制) ---
@st.cache_data(ttl=300) # 資料暫存 5分鐘
def get_stock_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # 抓取歷史資料
        df = stock.history(period="6mo")
        
        if df.empty:
            return None, None, "抓取不到歷史股價，請確認代碼是否正確。"
            
        # 抓取基本資料 (容錯處理)
        try:
            info = stock.info
        except Exception:
            info = {}
        
        # 確保有當前價格
        if not info or 'currentPrice' not in info:
            try:
                current_price = stock.fast_info.last_price
                info['currentPrice'] = current_price
                info['trailingPE'] = None 
            except:
                info['currentPrice'] = df['Close'].iloc[-1]
                info['trailingPE'] = None

        return df, info, None
        
    except Exception as e:
        return None, None, str(e)

# --- 2. 新增：股票選擇介面 ---

# 定義預設清單
default_stocks = [
    "GOOG", "AAPL", "NVDA", "BRK-B", 
    "MSFT", "AMZN", "META", "TSLA", 
    "AMD", "TSM", "AVGO", "ORCL"
]

# 建立兩欄佈局 (選單左邊，輸入框右邊或是隱藏)
col1, col2 = st.columns([2, 1])

with col1:
    # 下拉選單
    selection = st.selectbox(
        "📝 請選擇股票：", 
        ["請選擇..."] + default_stocks + ["🔍 自行輸入代碼"]
    )

ticker = ""

# 根據選擇決定 ticker
if selection == "🔍 自行輸入代碼":
    with col2:
        user_input = st.text_input("輸入代碼", "INTC")
        ticker = user_input.upper()
elif selection != "請選擇...":
    ticker = selection

# --- 3. 主程式邏輯 (開始分析) ---

if ticker:
    # 顯示目前分析的對象
    st.markdown(f"### 正在分析: **{ticker}**")
    
    with st.spinner(f'正在讀取數據並計算信心值...'):
        df, info, error_msg = get_stock_data(ticker)

    if error_msg:
        st.error(f"發生錯誤: {error_msg}")
    elif df is not None:
        # 取得數據
        current_price = info.get('currentPrice', 0)
        
        # 使用美觀的指標卡顯示價格
        st.metric(label="當前股價 (USD)", value=f"${current_price:.2f}")

        # --- 信心值邏輯 ---
        confidence_score = 0
        reasons = []

        # A. RSI
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

        # B. 本益比
        pe_ratio = info.get('trailingPE')
        if pe_ratio and pe_ratio is not None:
            if pe_ratio < 25: 
                confidence_score += 30
                reasons.append(f"✅ 本益比 ({pe_ratio:.1f}) 合理")
            elif pe_ratio > 60: # 科技股容忍度調高一點
                 reasons.append(f"⚠️ 本益比 ({pe_ratio:.1f}) 偏高")
            else:
                reasons.append(f"ℹ️ 本益比 ({pe_ratio:.1f})")
        else:
             reasons.append("ℹ️ 無法取得本益比數據，略過評分")
        
        # C. 均線
        if len(df) > 50:
            ma_50 = df['Close'].rolling(50).mean().iloc[-1]
            if current_price > ma_50:
                confidence_score += 30
                reasons.append("✅ 股價位於 50日均線之上 (多頭趨勢)")
            else:
                reasons.append("⚠️ 股價跌破 50日均線 (趨勢轉弱)")

        # --- 顯示結果 ---
        st.divider()
        st.subheader(f"🤖 購入信心分數: {confidence_score} / 100")
        
        # 進度條視覺化
        st.progress(max(0, min(100, confidence_score)))

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
