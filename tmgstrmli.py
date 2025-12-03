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
    except Exception:
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
except Exception:
    pass

INDEX_SYMBOLS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYJR", "CNXFINANCE", "CNXMIDCAP"
}


def get_option_chain(symbol: str):
    symbol = symbol.upper()
    if symbol in INDEX_SYMBOLS:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"

    try:
        r = SESSION.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

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
    df = df.dropna(subset=["Strike Price"])

    return df.sort_values("Strike Price").reset_index(drop=True)


# ======================================================
# OTM STRIKE SELECTION (BASED ON CLOSE PRICE)
# ======================================================
def get_otm_strikes(df: pd.DataFrame, close_price: float):
    """
    OTM definition (as per your example):
      - CALL OTM: first 2 strikes ABOVE close price
      - PUT  OTM: first 2 strikes BELOW close price (nearest below)
    e.g. close = 250 -> Call OTM 255,260 | Put OTM 245,240
    """
    d = df.sort_values("Strike Price")
    strikes = d["Strike Price"].values

    if len(strikes) == 0:
        return d.iloc[0:0], d.iloc[0:0], None

    # Approx ATM = strike closest to close price (just for reference)
    atm_strike = strikes[np.argmin(np.abs(strikes - close_price))]

    # CALL OTM = strikes ABOVE close, take first 2
    call_otm = d[d["Strike Price"] > close_price].head(2)

    # PUT OTM = strikes BELOW close, take last 2
    put_otm = d[d["Strike Price"] < close_price].tail(2)

    return call_otm, put_otm, atm_strike


# ======================================================
# SYMBOL LIST
# ======================================================
ALL_SYMBOLS = [
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


# ======================================================
# UI AREA
# ======================================================
st.markdown("### Select Symbols")

colA, colB = st.columns([3, 1])

with colA:
    user_selected = st.multiselect("Choose Symbols", sorted(ALL_SYMBOLS), [])

with colB:
    select_all = st.checkbox("Select All")

if select_all:
    user_selected = sorted(ALL_SYMBOLS)

decay_threshold = st.number_input(
    "OI Decay % Threshold (≤ this value)",
    min_value=-100.0,
    max_value=0.0,
    value=-30.0,
    step=1.0,
)

run_scan = st.button("🚀 Run Scan Now")

# ======================================================
# MAIN LOGIC
# ======================================================
results = []

if run_scan:
    if not user_selected:
        st.warning("No symbols selected.")
    else:
        for sym in user_selected:
            close_price = get_close_price(sym)
            if close_price is None:
                # skip if TV doesn't give close
                continue

            oc = get_option_chain(sym)
            if oc is None or oc.empty:
                continue

            # OTM strikes based on close price
            call_otm, put_otm, atm = get_otm_strikes(oc, close_price)

            # Apply decay filter on those specific OTM strikes
            call_ok = call_otm[
                (call_otm["CE_OI_Change_%"].notna()) &
                (call_otm["CE_OI_Change_%"] <= decay_threshold)
            ].copy()

            put_ok = put_otm[
                (put_otm["PE_OI_Change_%"].notna()) &
                (put_ok := put_otm)["PE_OI_Change_%"] <= decay_threshold  # small trick var
            ].copy()

            # Append only matching rows
            if not call_ok.empty:
                call_ok["Symbol"] = sym
                call_ok["Side"] = "CALL_OTM"
                call_ok["Close_Price"] = close_price
                call_ok["ATM_Approx"] = atm
                results.append(call_ok)

            if not put_ok.empty:
                put_ok["Symbol"] = sym
                put_ok["Side"] = "PUT_OTM"
                put_ok["Close_Price"] = close_price
                put_ok["ATM_Approx"] = atm
                results.append(put_ok)

        # SHOW ONLY MATCHING RESULTS
        if results:
            final = pd.concat(results, ignore_index=True)
            final = final.sort_values(["Symbol", "Side", "Strike Price"])

            st.success(f"Found {len(final)} matching OTM rows.")
            st.dataframe(
                final[
                    [
                        "Symbol",
                        "Side",
                        "Close_Price",
                        "ATM_Approx",
                        "Strike Price",
                        "CE_OI_Change_%",
                        "CE_OI",
                        "PE_OI_Change_%",
                        "PE_OI",
                    ]
                ]
            )

            # Excel Download
            buffer = BytesIO()
            final.to_excel(buffer, index=False)
            buffer.seek(0)
            st.download_button(
                "📥 Download Excel With Matching OTM Strikes",
                buffer,
                "oi_decay_otm_results.xlsx",
            )
        else:
            st.warning("No OTM strikes met the decay condition for selected symbols.")
