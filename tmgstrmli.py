import streamlit as st
import pandas as pd
import numpy as np
import requests
from io import BytesIO
from tvDatafeed import TvDatafeed, Interval

# ======================================================
# STREAMLIT CONFIG
# ======================================================
st.set_page_config(page_title="OI Decay OTM Scanner", layout="wide")
st.title("📉 %OI Decay Scanner — OTM 1–2 Strikes (CALL & PUT)")
st.caption("Close Price: TradingView | Option Chain: NSE JSON API")

# ======================================================
# TVDATAFEED (NO LOGIN)
# ======================================================
try:
    tv = TvDatafeed()
except Exception as e:
    st.error(f"tvDatafeed initialization failed: {e}")
    st.stop()


def get_close_price(symbol: str):
    """Close price ONLY from TV datafeed."""
    try:
        df = tv.get_hist(symbol=symbol, exchange='NSE', interval=Interval.in_daily, n_bars=2)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except:
        return None
    return None


# ======================================================
# NSE OPTION CHAIN JSON
# ======================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/"
}

SESSION = requests.Session()
try:
    SESSION.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
except:
    pass


SYMBOLS = [
    'BANKNIFTY','CNXFINANCE','CNXMIDCAP','NIFTY','NIFTYJR','360ONE','ABB','ABCAPITAL',
    'ADANIENSOL','ADANIENT','ADANIGREEN','ADANIPORTS','ALKEM','AMBER','AMBUJACEM','ANGELONE',
    'APLAPOLLO','APOLLOHOSP','ASHOKLEY','ASIANPAINT','ASTRAL','AUBANK','AUROPHARMA','AXISBANK',
    'BAJAJ_AUTO','BAJAJFINSV','BAJFINANCE','BANDHANBNK','BANKBARODA','BANKINDIA','BDL','BEL',
    'BHARATFORG','BHARTIARTL','BHEL','BIOCON','BLUESTARCO','BOSCHLTD','BPCL','BRITANNIA','BSE',
    'CAMS','CANBK','CDSL','CGPOWER','CHOLAFIN','CIPLA','COALINDIA','COFORGE','COLPAL','CONCOR',
    'CROMPTON','CUMMINSIND','CYIENT','DABUR','DALBHARAT','DELHIVERY','DIVISLAB','DIXON','DLF',
    'DMART','DRREDDY','EICHERMOT','EXIDEIND','FEDERALBNK','GAIL','GLENMARK','GODREJCP','GRASIM',
    'HAL','HAVELLS','HCLTECH','HDFCAMC','HDFCBANK','HDFCLIFE','HEROMOTOCO','HFCL','HINDALCO',
    'HINDPETRO','HINDUNILVR','ICICIBANK','ICICIGI','ICICIPRULI','IDEA','IDFCFIRSTB','IEX','IGL',
    'INDHOTEL','INDIANB','INDIGO','INDUSINDBK','INFY','IOC','IRCTC','IRFC','ITC','JINDALSTEL',
    'JSWSTEEL','JUBLFOOD','KOTAKBANK','KFINTECH','KPITTECH','LICI','LT','LTIM','LUPIN',
    'MANAPPURAM','MARICO','MARUTI','MAXHEALTH','MCX','MUTHOOTFIN','NAUKRI','NATIONALUM',
    'NESTLEIND','NMDC','NTPC','NYKAA','ONGC','PAGEIND','PAYTM','PFC','PIDILITIND','PIIND','PNB',
    'POLYCAB','POWERGRID','PRESTIGE','RECLTD','RELIANCE','RVNL','SAIL','SBICARD','SBIN','SIEMENS',
    'SONACOMS','SRF','SUNPHARMA','SUPREMEIND','SUZLON','TATACHEM','TATACONSUM','TATAMOTORS',
    'TATAPOWER','TATASTEEL','TATATECH','TCS','TECHM','TIINDIA','TITAN','TORNTPOWER','TRENT',
    'TVSMOTOR','ULTRACEMCO','UNIONBANK','UPL','VEDL','VOLTAS','WIPRO','YESBANK','ZYDUSLIFE'
]


def get_option_chain(symbol: str, return_raw=False):
    """
    return_raw=True → returns raw JSON dict with CE/PE including Greeks
    return_raw=False → returns simplified DF with strikes + OI change
    """
    symbol = symbol.upper()
    if symbol in INDEX_SYMBOLS:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"

    try:
        r = SESSION.get(url, headers=HEADERS, timeout=15)
        data = r.json()
    except:
        return None

    if return_raw:
        return data  # FULL JSON FOR GREEKS VIEW

    # Normal condensed OC for scanning
    oc = data.get("records", {}).get("data", [])
    rows = []

    for d in oc:
        strike = d.get("strikePrice")
        if not strike:
            continue

        row = {"Strike Price": float(strike)}

        ce = d.get("CE", {})
        pe = d.get("PE", {})

        row["CE_OI_Change_%"] = ce.get("pchangeinOpenInterest")
        row["CE_OI"] = ce.get("openInterest")
        row["PE_OI_Change_%"] = pe.get("pchangeinOpenInterest")
        row["PE_OI"] = pe.get("openInterest")

        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return None

    df["CE_OI_Change_%"] = pd.to_numeric(df["CE_OI_Change_%"], errors="coerce")
    df["PE_OI_Change_%"] = pd.to_numeric(df["PE_OI_Change_%"], errors="coerce")
    return df.sort_values("Strike Price").reset_index(drop=True)


# ======================================================
# Extract FULL GREEKS TABLE
# ======================================================
def build_full_chain_table(raw_json):
    """
    Build a complete table of all available Greeks + OI + prices for CE & PE.
    """
    rows = []
    for item in raw_json.get("records", {}).get("data", []):
        strike = item.get("strikePrice")
        if strike is None:
            continue

        ce = item.get("CE", {})
        pe = item.get("PE", {})

        row = {
            "Strike": strike,
            "CE_LTP": ce.get("lastPrice"),
            "CE_OI": ce.get("openInterest"),
            "CE_Change_OI": ce.get("changeinOpenInterest"),
            "CE_pChange_OI": ce.get("pchangeinOpenInterest"),
            "CE_IV": ce.get("impliedVolatility"),
            "CE_Delta": ce.get("delta"),
            "CE_Vega": ce.get("vega"),
            "CE_Gamma": ce.get("gamma"),
            "CE_Theta": ce.get("theta"),

            "PE_LTP": pe.get("lastPrice"),
            "PE_OI": pe.get("openInterest"),
            "PE_Change_OI": pe.get("changeinOpenInterest"),
            "PE_pChange_OI": pe.get("pchangeinOpenInterest"),
            "PE_IV": pe.get("impliedVolatility"),
            "PE_Delta": pe.get("delta"),
            "PE_Vega": pe.get("vega"),
            "PE_Gamma": pe.get("gamma"),
            "PE_Theta": pe.get("theta"),
        }

        rows.append(row)

    df = pd.DataFrame(rows)
    return df.sort_values("Strike").reset_index(drop=True)


# ======================================================
# OTM STRIKE SELECTION (BASED ON CLOSE PRICE)
# ======================================================
def get_otm_strikes(df: pd.DataFrame, close_price: float):
    df = df.sort_values("Strike Price")
    strikes = df["Strike Price"].values

    atm = strikes[np.argmin(np.abs(strikes - close_price))]

    call_otm = df[df["Strike Price"] > close_price].head(2)
    put_otm = df[df["Strike Price"] < close_price].tail(2)

    return call_otm, put_otm, atm


# ======================================================
# SYMBOL LIST
# ======================================================
ALL_SYMBOLS = [
    # (same symbol list as previous response)
]


# ======================================================
# UI AREA
# ======================================================
st.markdown("### Select Symbols")

colA, colB = st.columns([3, 1])

with colA:
    selected = st.multiselect("Choose Symbols", sorted(ALL_SYMBOLS), [])

with colB:
    sel_all = st.checkbox("Select All")

if sel_all:
    selected = sorted(ALL_SYMBOLS)

decay_threshold = st.number_input(
    "OI Decay % Threshold (≤)",
    min_value=-100.0,
    max_value=0.0,
    value=-30.0,
)

run = st.button("🚀 Run Scan")

# ======================================================
# MAIN LOGIC
# ======================================================
results = []

if run:
    # ───────────────────────────────────────────────
    # CASE 1 → Single Symbol → Show Full Option Chain + OTM Scan
    # ───────────────────────────────────────────────
    if len(selected) == 1:
        sym = selected[0]

        st.header(f"📌 FULL OPTION CHAIN — {sym}")

        # TV Close Price
        close_price = get_close_price(sym)
        if close_price:
            st.subheader(f"Close Price: {close_price}")
        else:
            st.error("Close Price not available from TV")
            st.stop()

        raw_json = get_option_chain(sym, return_raw=True)
        if raw_json is None:
            st.error("Option Chain Not Available")
            st.stop()

        # Show FULL TABLE with Greeks
        full_table = build_full_chain_table(raw_json)
        st.dataframe(full_table, use_container_width=True)

        st.markdown("---")
        st.subheader("OTM 1–2 Decay Filter Scan Output")

        # also run the decay scanner for single stock
        compact_df = get_option_chain(sym)
        call_otm, put_otm, atm = get_otm_strikes(compact_df, close_price)

        call_ok = call_otm[call_otm["CE_OI_Change_%"] <= decay_threshold]
        put_ok = put_otm[put_otm["PE_OI_Change_%"] <= decay_threshold]

        if not call_ok.empty or not put_ok.empty:
            final = pd.concat([call_ok, put_ok], ignore_index=True)
            st.dataframe(final)
        else:
            st.info("No OTM strikes meeting decay threshold.")

        st.stop()

    # ───────────────────────────────────────────────
    # CASE 2 → MULTIPLE SELECTED SYMBOLS → Run batch scan only
    # ───────────────────────────────────────────────
    for sym in selected:
        close_price = get_close_price(sym)
        if close_price is None:
            continue

        oc = get_option_chain(sym)
        if oc is None:
            continue

        call_otm, put_otm, atm = get_otm_strikes(oc, close_price)

        call_ok = call_otm[call_otm["CE_OI_Change_%"] <= decay_threshold]
        put_ok = put_otm[put_otm["PE_OI_Change_%"] <= decay_threshold]

        if not call_ok.empty:
            call_ok["Symbol"] = sym
            call_ok["Side"] = "CALL_OTM"
            results.append(call_ok)

        if not put_ok.empty:
            put_ok["Symbol"] = sym
            put_ok["Side"] = "PUT_OTM"
            results.append(put_ok)

    if results:
        final = pd.concat(results, ignore_index=True)
        final = final.sort_values(["Symbol", "Strike Price"])

        st.success(f"Found {len(final)} matching OTM rows.")
        st.dataframe(final)

        buffer = BytesIO()
        final.to_excel(buffer, index=False)
        buffer.seek(0)
        st.download_button("📥 Download Excel", buffer, "otm_decay_results.xlsx")

    else:
        st.warning("No OTM strike matched the decay condition.")
