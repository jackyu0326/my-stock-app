import streamlit as st
import yfinance as yf
import pandas_ta as ta
import requests

# 設定網頁標題
st.set_page_config(page_title="美股 AI 信心儀表板", layout="centered")

st.title('美股 AI 信心值分析儀表板')

# --- 關鍵修改：定義一個有快取功能的抓資料函數 ---
# ttl=300 代表資料會暫存 300秒 (5分鐘)，期間內不會重複抓取
@st.cache_data(ttl=300)
def get_stock_data(ticker_symbol):
    try:
        # 1. 偽裝成瀏覽器 (騙過 Yahoo 的簡單防爬機制)
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        })
        
        # 2. 抓取資料
        stock = yf.Ticker(ticker_symbol, session=session)
        
        # 抓取歷史資料 (過去6個月)
        df = stock.history(period="6mo")
        
        if df.empty:
            return None, None, "抓取不到歷史股價，請確認代碼是否正確。"
            
        # 抓取基本資料 (如果抓不到 info，嘗試用 fast_info)
        info = stock.info
        
        # 有時候 info 會因為被擋而抓不到，做個簡單的備案
        if not info or 'currentPrice' not in info:
            # 嘗試用 fast_info (yfinance 的另一個屬性)
            current_price = stock.fast_info.last_price
            # 建構一個簡易的 info 字典
            info = {'currentPrice': current_price, 'trailingPE': None}
        
        return df, info, None
        
    except Exception as e:
        return None, None, str(e)

# --- 主程式 ---

ticker = st.text_input('請輸入美股代碼 (例如: AAPL, NVDA)', 'AAPL').upper()

if ticker:
    # 呼叫上面寫好的函數
    with st.spinner(f'正在分析 {ticker} ... (若資料過舊會自動更新)'):
        df, info, error_msg = get_stock_data(ticker)

    if error_msg:
        st.error(f"發生錯誤: {error_msg}")
        st.caption("提示: 如果出現 Rate limited，請稍等幾分鐘後再試。")
    elif df is not None:
        # 取得當前價格
        current_price = info.get('currentPrice', df['Close'].iloc[-1])
        st.metric(label="當前股價", value=f"${current_price:.2f}")

        # --- 核心邏輯：計算信心值 ---
        confidence_score = 0
        reasons = []

        # 邏輯 A: RSI 指標
        df['RSI'] = ta.rsi(df['Close'], length=14)
        current_rsi = df['RSI'].iloc[-1]
        
        if current_rsi < 30:
            confidence_score += 40
            reasons.append(f"✅ RSI 過低 ({current_rsi:.1f})，處於超賣區，反彈機率高")
        elif current_rsi > 70:
            confidence_score -= 20
            reasons.append(f"⚠️ RSI 過高 ({current_rsi:.1f})，處於超買區，風險高")
        else:
            confidence_score += 10
            reasons.append(f"ℹ️ RSI 中性 ({current_rsi:.1f})")

        # 邏輯 B: 本益比 (若抓不到數據則忽略)
        pe_ratio = info.get('trailingPE')
        if pe_ratio and pe_ratio is not None:
            if pe_ratio < 25: 
                confidence_score += 30
                reasons.append(f"✅ 本益比 ({pe_ratio:.1f}) 處於合理區間")
            elif pe_ratio > 50:
                 reasons.append(f"⚠️ 本益比 ({pe_ratio:.1f}) 偏高，需注意估值修正")
            else:
                reasons.append(f"ℹ️ 本益比 ({pe_ratio:.1f})")
        else:
             reasons.append("ℹ️ 無法取得本益比數據，略過此項評分")
        
        # 邏輯 C: 股價位置
        ma_50 = df['Close'].rolling(50).mean().iloc[-1]
        if current_price > ma_50:
            confidence_score += 30
            reasons.append("✅ 股價位於 50日均線之上，趨勢偏多")

        # --- 顯示結果 ---
        st.subheader(f"🤖 購入信心分數: {confidence_score} / 100")
        
        if confidence_score >= 70:
            st.success("評級: 強力買入 (Strong Buy)")
        elif confidence_score >= 40:
            st.warning("評級: 觀望 / 持有 (Hold)")
        else:
            st.error("評級: 不建議購入 (Sell/Avoid)")

        with st.expander("查看分析細節", expanded=True):
            for reason in reasons:
                st.write(reason)

        st.line_chart(df['Close'])
