import streamlit as st
import pandas as pd
import requests
from tvDatafeed import TvDatafeed, Interval
from io import StringIO

st.set_page_config(page_title="OI Decay Scanner", layout="wide")

st.title("📉 %OI Decay Scanner — ITM 1–2 Strikes (CALL & PUT)")

# -------------------------------------------------------
# tvDatafeed login
# -------------------------------------------------------
username = "GauravSinghYadav"
password = "Eric$1234"

try:
    tv = TvDatafeed(username=username, password=password)
except:
    st.error("❌ TV login failed — check credentials")
    st.stop()

# -------------------------------------------------------
# Symbol selection
# -------------------------------------------------------
symbols = sorted([
    'BANKNIFTY','NIFTY','FINNIFTY','CNXFINANCE','CNXMIDCAP',
    'RELIANCE','ICICIBANK','HDFCBANK','SBIN','TATAMOTORS',
    'TCS','INFY','AXISBANK','HCLTECH','LT','ITC'
])

selected_symbols = st.multiselect("Select Symbols", symbols, default=["NIFTY","BANKNIFTY"])

DECAY_LIMIT = st.number_input("Decay % Threshold (Default -30%)", -100, 0, -30)

# -------------------------------------------------------
# Fetch Close Price
# -------------------------------------------------------
def get_close(symbol):
    try:
        df = tv.get_hist(symbol=symbol, exchange='NSE', interval=Interval.in_daily, n_bars=2)
        return float(df.close.iloc[-1])
    except:
        return None

# -------------------------------------------------------
# Fetch Option Chain (Without Selenium)
# -------------------------------------------------------
def get_option_chain(symbol):
    url = f"https://www.niftytrader.in/nse-option-chain/{symbol}"
    response = requests.get(url)

    if response.status_code != 200:
        return None

    try:
        df = pd.read_html(StringIO(response.text))[0]
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except:
        return None

# -------------------------------------------------------
# Extract Clean OI Columns
# -------------------------------------------------------
def process_oc(df):
    df['Strike'] = pd.to_numeric(df['Strike Price'].astype(str).str.replace(",", ""), errors='coerce')

    df['CE_OI_%'] = df['OI (Chg %)'].astype(str).str.extract(r"\((.*?)\)").iloc[:,0]
    df['PE_OI_%'] = df['OI (Chg %).1'].astype(str).str.extract(r"\((.*?)\)").iloc[:,0]

    df['CE_OI_%'] = pd.to_numeric(df['CE_OI_%'].str.replace("%",""), errors="ignore")
    df['PE_OI_%'] = pd.to_numeric(df['PE_OI_%'].str.replace("%",""), errors="ignore")

    df = df.dropna(subset=["Strike"])
    return df

# -------------------------------------------------------
# ITM 1–2 Strike Filter Logic
# -------------------------------------------------------
def filter_itm_strikes(df, close):
    df = df.sort_values("Strike")

    # nearest ATM
    atm = df.iloc[(df["Strike"] - close).abs().argsort()].iloc[0]["Strike"]

    # ITM CALL = strikes BELOW LTP
    # ITM PUT = strikes ABOVE LTP  
    itm_calls = df[df.Strike < close].tail(2)     # ITM 1–2 CALL
    itm_puts  = df[df.Strike > close].head(2)     # ITM 1–2 PUT

    return itm_calls, itm_puts, atm

# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
final_output = []

for sym in selected_symbols:
    st.subheader(f"📌 {sym}")

    close_price = get_close(sym)
    if close_price is None:
        st.error(f"❌ Could not fetch close price for {sym}")
        continue

    df = get_option_chain(sym)
    if df is None:
        st.error(f"❌ Option chain not found for {sym}")
        continue

    df = process_oc(df)
    itm_calls, itm_puts, atm = filter_itm_strikes(df, close_price)

    st.write(f"**Close Price:** {close_price} | **ATM Strike:** {atm}")

    # Filter decay
    calls_filtered = itm_calls[itm_calls['CE_OI_%'] <= DECAY_LIMIT]
    puts_filtered  = itm_puts[itm_puts['PE_OI_%'] <= DECAY_LIMIT]

    st.write("### 📉 ITM CALL (1–2 Strikes) — Decay Filter")
    st.dataframe(calls_filtered)

    st.write("### 📉 ITM PUT (1–2 Strikes) — Decay Filter")
    st.dataframe(puts_filtered)

    # Combine to save later
    calls_filtered["Symbol"] = sym
    puts_filtered["Symbol"]  = sym
    final_output.append(calls_filtered)
    final_output.append(puts_filtered)

# -------------------------------------------------------
# Save Excel
# -------------------------------------------------------
if final_output:
    result = pd.concat(final_output, ignore_index=True)
    st.download_button(
        label="📥 Download Excel",
        data=result.to_excel(index=False),
        file_name="oi_decay_filtered.xlsx"
    )
