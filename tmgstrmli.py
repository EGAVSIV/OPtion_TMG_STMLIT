import streamlit as st
import pandas as pd
import numpy as np
import requests
from io import StringIO, BytesIO
from tvDatafeed import TvDatafeed, Interval

st.set_page_config(page_title="OI Decay ITM Scanner", layout="wide")
st.title("📉 %OI Decay Scanner — ITM 1–2 Strikes (CALL & PUT)")
st.caption("Close Price: TradingView | Option Chain: NiftyTrader")

# ======================================================
# TVDATAFEED (NO LOGIN MODE)
# ======================================================
try:
    tv = TvDatafeed()          # No Login (works on Streamlit Cloud)
except:
    st.error("tvDatafeed failed to initialize.")
    st.stop()

def get_close_price(symbol: str):
    """Fetch last close price via TradingView NSE."""
    try:
        df = tv.get_hist(symbol=symbol, exchange='NSE', interval=Interval.in_daily, n_bars=2)
        return float(df["close"].iloc[-1])
    except Exception:
        return None

# ======================================================
# NIFTYTRADER OPTION CHAIN SCRAPER
# ======================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.niftytrader.in/"
}

def get_option_chain(symbol):
    url = f"https://www.niftytrader.in/nse-option-chain/{symbol.upper()}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        df = pd.read_html(StringIO(r.text))[0]
    except Exception:
        return None

    df.columns = [str(c).strip() for c in df.columns]

    # Strike extraction
    df["Strike Price"] = (
        df["Strike Price"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.extract(r"(\d+\.?\d*)")[0]
    )
    df["Strike Price"] = pd.to_numeric(df["Strike Price"], errors="coerce")

    # Extract CE/PE % OI
    df["CE_OI_%"] = (
        df["OI (Chg %)"].astype(str)
        .str.extract(r"\((.*?)\)")[0]
        .str.replace("%","", regex=False)
    )
    df["PE_OI_%"] = (
        df["OI (Chg %).1"].astype(str)
        .str.extract(r"\((.*?)\)")[0]
        .str.replace("%","", regex=False)
    )

    df["CE_OI_%"] = pd.to_numeric(df["CE_OI_%"], errors="coerce")
    df["PE_OI_%"] = pd.to_numeric(df["PE_OI_%"], errors="coerce")

    df = df.dropna(subset=["Strike Price"])
    return df

# ======================================================
# ITM 1–2 STRIKE LOGIC
# ======================================================
def get_itm_strikes(df, close_price):
    d = df.sort_values("Strike Price")

    strikes = d["Strike Price"].values
    atm_strike = strikes[np.argmin(np.abs(strikes - close_price))]

    # ITM CALL → strike BELOW close
    itm_calls = d[d["Strike Price"] < close_price].tail(2)

    # ITM PUT → strike ABOVE close
    itm_puts = d[d["Strike Price"] > close_price].head(2)

    return itm_calls, itm_puts, atm_strike

# ======================================================
# SYMBOL LIST
# ======================================================
SYMBOLS = [
    "NIFTY", "BANKNIFTY", "FINNIFTY",
    "RELIANCE", "SBIN", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "TATAMOTORS"
]

selected_symbols = st.multiselect("Select Symbols", SYMBOLS, default=["NIFTY","BANKNIFTY"])
decay_limit = st.number_input("OI Decay % Threshold", -100, 0, -30)

run = st.button("🚀 Run Scan")

# ======================================================
# MAIN LOGIC
# ======================================================
all_results = []

if run:
    for sym in selected_symbols:
        st.subheader(f"📌 {sym}")

        # FETCH CLOSE PRICE (TVDF)
        close_price = get_close_price(sym)
        if close_price is None:
            st.error(f"❌ TV Close Price not found for {sym}")
            continue

        st.write(f"**Close Price (TV)**: `{close_price}`")

        # FETCH OPTION CHAIN
        oc = get_option_chain(sym)
        if oc is None or oc.empty:
            st.error(f"❌ Option Chain not available for {sym}")
            continue

        # ITM FILTER
        itm_calls, itm_puts, atm = get_itm_strikes(oc, close_price)

        st.write(f"**ATM Strike**: `{atm}`")

        # APPLY % DECAY FILTER
        call_filtered = itm_calls[itm_calls["CE_OI_%"] <= decay_limit].copy()
        put_filtered  = itm_puts[itm_puts["PE_OI_%"] <= decay_limit].copy()

        call_filtered["Symbol"] = sym
        put_filtered["Symbol"]  = sym

        st.markdown("### 📉 ITM CALL (1–2 strikes)")
        st.dataframe(call_filtered)

        st.markdown("### 📉 ITM PUT (1–2 strikes)")
        st.dataframe(put_filtered)

        if not call_filtered.empty:
            all_results.append(call_filtered)

        if not put_filtered.empty:
            all_results.append(put_filtered)

    # EXPORT EXCEL
    if all_results:
        final = pd.concat(all_results, ignore_index=True)
        buffer = BytesIO()
        final.to_excel(buffer, index=False)
        buffer.seek(0)

        st.download_button(
            label="📥 Download Excel",
            data=buffer,
            file_name="ITM_OI_decay_filtered.xlsx"
        )
    else:
        st.warning("No results found for selected symbols.")
