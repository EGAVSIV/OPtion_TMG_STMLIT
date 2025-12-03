import streamlit as st
import pandas as pd
import numpy as np
import requests
from io import BytesIO
from tvDatafeed import TvDatafeed, Interval

# ======================================================
# STREAMLIT CONFIG
# ======================================================
st.set_page_config(page_title="OI Decay ITM Scanner", layout="wide")
st.title("📉 %OI Decay Scanner — ITM 1–2 Strikes (CALL & PUT)")
st.caption("Close Price: TradingView (tvDatafeed) | Option Chain: NSE JSON API")

# ======================================================
# TVDATAFEED (NO-LOGIN MODE)
# ======================================================
try:
    tv = TvDatafeed()  # no username/password → works on Streamlit Cloud (limited symbols)
except Exception as e:
    st.error(f"tvDatafeed failed to initialize: {e}")
    st.stop()


def get_close_price(symbol: str):
    """
    Get last close price from TradingView (NSE).
    Only TV is used for close price as requested.
    """
    symbol = symbol.upper().strip()
    try:
        df = tv.get_hist(
            symbol=symbol,
            exchange="NSE",
            interval=Interval.in_daily,
            n_bars=2,
        )
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        return None
    return None


# ======================================================
# NSE OPTION CHAIN (OFFICIAL JSON API)
# ======================================================
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/",
}


# create a session once
_session = requests.Session()
# warm-up call to set cookies
try:
    _session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
except Exception:
    pass


INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYJR",
    "CNXFINANCE",
    "CNXMIDCAP",
}


def get_option_chain(symbol: str) -> pd.DataFrame | None:
    """
    Fetch option chain from NSE JSON:
      - indices:  /api/option-chain-indices?symbol=...
      - equities: /api/option-chain-equities?symbol=...
    Returns a DataFrame with at least:
        Strike Price, CE_OI_Change_%, PE_OI_Change_%, CE_OI, PE_OI
    """
    symbol = symbol.upper().strip()

    if symbol in INDEX_SYMBOLS:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"

    try:
        r = _session.get(url, headers=NSE_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.warning(f"{symbol}: Failed to fetch option chain JSON from NSE ({e})")
        return None

    records = data.get("records", {})
    oc_data = records.get("data", [])

    rows = []
    for entry in oc_data:
        strike = entry.get("strikePrice")
        if strike is None:
            continue

        row = {"Strike Price": float(strike)}

        ce = entry.get("CE")
        pe = entry.get("PE")

        if isinstance(ce, dict):
            row["CE_OI_Change_%"] = ce.get("pchangeinOpenInterest")
            row["CE_OI"] = ce.get("openInterest")
        else:
            row["CE_OI_Change_%"] = np.nan
            row["CE_OI"] = np.nan

        if isinstance(pe, dict):
            row["PE_OI_Change_%"] = pe.get("pchangeinOpenInterest")
            row["PE_OI"] = pe.get("openInterest")
        else:
            row["PE_OI_Change_%"] = np.nan
            row["PE_OI"] = np.nan

        rows.append(row)

    if not rows:
        return None

    df = pd.DataFrame(rows)

    # drop rows with no strike
    df = df.dropna(subset=["Strike Price"])

    # ensure numeric
    df["Strike Price"] = pd.to_numeric(df["Strike Price"], errors="coerce")
    df["CE_OI_Change_%"] = pd.to_numeric(df["CE_OI_Change_%"], errors="coerce")
    df["PE_OI_Change_%"] = pd.to_numeric(df["PE_OI_Change_%"], errors="coerce")

    # remove duplicates by strike (keep last)
    df = df.sort_values("Strike Price").drop_duplicates("Strike Price", keep="last")

    return df.reset_index(drop=True)


# ======================================================
# ITM 1–2 STRIKE SELECTION
# ======================================================
def get_itm_strikes(df: pd.DataFrame, close_price: float):
    """
    From full option-chain DF, returns:
      - 2 ITM CALL strikes (nearest below close)
      - 2 ITM PUT strikes (nearest above close)
      - ATM strike used
    """
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame(), None

    d = df.sort_values("Strike Price").reset_index(drop=True)
    strikes = d["Strike Price"].values

    if len(strikes) == 0:
        return d.iloc[0:0], d.iloc[0:0], None

    # ATM = strike closest to close_price
    atm_idx = int(np.argmin(np.abs(strikes - close_price)))
    atm_strike = strikes[atm_idx]

    # ITM CALL = strikes BELOW close (take last 2)
    itm_call_df = d[d["Strike Price"] < close_price].tail(2)

    # ITM PUT = strikes ABOVE close (take first 2)
    itm_put_df = d[d["Strike Price"] > close_price].head(2)

    return itm_call_df, itm_put_df, atm_strike


# ======================================================
# SYMBOL LIST (YOUR ORIGINAL LIST)
# ======================================================
ALL_SYMBOLS = [
    'BANKNIFTY','CNXFINANCE','CNXMIDCAP','NIFTY','NIFTYJR',
    '360ONE','ABB','ABCAPITAL','ADANIENSOL','ADANIENT','ADANIGREEN',
    'ADANIPORTS','ALKEM','AMBER','AMBUJACEM','ANGELONE','APLAPOLLO',
    'APOLLOHOSP','ASHOKLEY','ASIANPAINT','ASTRAL','AUBANK','AUROPHARMA',
    'AXISBANK','BAJAJ_AUTO','BAJAJFINSV','BAJFINANCE','BANDHANBNK',
    'BANKBARODA','BANKINDIA','BDL','BEL','BHARATFORG','BHARTIARTL',
    'BHEL','BIOCON','BLUESTARCO','BOSCHLTD','BPCL','BRITANNIA','BSE',
    'CAMS','CANBK','CDSL','CGPOWER','CHOLAFIN','CIPLA','COALINDIA',
    'COFORGE','COLPAL','CONCOR','CROMPTON','CUMMINSIND','CYIENT','DABUR',
    'DALBHARAT','DELHIVERY','DIVISLAB','DIXON','DLF','DMART','DRREDDY',
    'EICHERMOT','ETERNAL','EXIDEIND','FEDERALBNK','FORTIS','GAIL',
    'GLENMARK','GMRAIRPORT','GODREJCP','GODREJPROP','GRASIM','HAL',
    'HAVELLS','HCLTECH','HDFCAMC','HDFCBANK','HDFCLIFE','HEROMOTOCO',
    'HFCL','HINDALCO','HINDPETRO','HINDUNILVR','HINDZINC','HUDCO',
    'ICICIBANK','ICICIGI','ICICIPRULI','IDEA','IDFCFIRSTB','IEX','IGL',
    'IIFL','INDHOTEL','INDIANB','INDIGO','INDUSINDBK','INDUSTOWER',
    'INFY','INOXWIND','IOC','IRCTC','IREDA','IRFC','ITC','JINDALSTEL',
    'JIOFIN','JSWENERGY','JSWSTEEL','JUBLFOOD','KALYANKJIL','KAYNES',
    'KEI','KFINTECH','KOTAKBANK','KPITTECH','LAURUSLABS','LICHSGFIN',
    'LICI','LODHA','LT','LTF','LTIM','LUPIN','M&M','MANAPPURAM',
    'MANKIND','MARICO','MARUTI','MAXHEALTH','MAZDOCK','MCX','MFSL',
    'MOTHERSON','MPHASIS','MUTHOOTFIN','NATIONALUM','NAUKRI','NBCC',
    'NCC','NESTLEIND','NHPC','NMDC','NTPC','NUVAMA','NYKAA',
    'OBEROIRLTY','OFSS','OIL','ONGC','PAGEIND','PATANJALI','PAYTM',
    'PERSISTENT','PETRONET','PFC','PGEL','PHOENIXLTD','PIDILITIND',
    'PIIND','PNB','PNBHOUSING','POLICYBZR','POLYCAB','POWERGRID',
    'PPLPHARMA','PRESTIGE','RBLBANK','RECLTD','RELIANCE','RVNL','SAIL',
    'SAMMAANCAP','SBICARD','SBILIFE','SBIN','SHREECEM','SHRIRAMFIN',
    'SIEMENS','SOLARINDS','SONACOMS','SRF','SUNPHARMA','SUPREMEIND',
    'SUZLON','SYNGENE','TATACHEM','TATACONSUM','TATAELXSI','TATAMOTORS',
    'TATAPOWER','TATASTEEL','TATATECH','TCS','TECHM','TIINDIA',
    'TITAGARH','TITAN','TORNTPHARM','TORNTPOWER','TRENT','TVSMOTOR',
    'ULTRACEMCO','UNIONBANK','UNITDSPR','UNOMINDA','UPL','VBL','VEDL',
    'VOLTAS','WIPRO','YESBANK','ZYDUSLIFE'
]

# ======================================================
# UI CONTROLS
# ======================================================
col1, col2 = st.columns([2, 1])

with col1:
    selected_symbols = st.multiselect(
        "Select Symbols to Scan",
        options=sorted(ALL_SYMBOLS),
        default=["NIFTY", "BANKNIFTY", "HDFCBANK"]
    )

with col2:
    decay_threshold = st.number_input(
        "Decay % Threshold (≤ this value)",
        min_value=-100.0,
        max_value=0.0,
        value=-30.0,
        step=1.0,
        help="Filter CE/PE where % change in OI (pchangeinOpenInterest) is <= this value."
    )

run_scan = st.button("🚀 Run Scan")

# ======================================================
# MAIN SCAN
# ======================================================
all_results = []

if run_scan:
    if not selected_symbols:
        st.warning("Please select at least one symbol.")
    else:
        for sym in selected_symbols:
            st.markdown("---")
            st.subheader(f"📌 {sym}")

            # 1) CLOSE PRICE FROM TVDATAFEED
            close_price = get_close_price(sym)
            if close_price is None:
                st.error(f"❌ Could not fetch close price from tvDatafeed for {sym}")
                continue

            st.write(f"**Close Price (TV / NSE):** `{close_price}`")

            # 2) OPTION CHAIN FROM NSE
            oc_df = get_option_chain(sym)
            if oc_df is None or oc_df.empty:
                st.error(f"❌ Option Chain not available from NSE for {sym}")
                continue

            # 3) ITM STRIKES (1–2 CALL & PUT)
            itm_calls, itm_puts, atm_strike = get_itm_strikes(oc_df, close_price)

            st.write(f"**Approx. ATM Strike:** `{atm_strike}`")

            # 4) APPLY DECAY FILTER
            calls_filtered = itm_calls[
                (itm_calls["CE_OI_Change_%"].notna()) &
                (itm_calls["CE_OI_Change_%"] <= decay_threshold)
            ].copy()
            puts_filtered = itm_puts[
                (itm_puts["PE_OI_Change_%"].notna()) &
                (itm_puts["PE_OI_Change_%"] <= decay_threshold)
            ].copy()

            calls_filtered["Symbol"] = sym
            calls_filtered["Side"] = "CALL_ITM"
            puts_filtered["Symbol"] = sym
            puts_filtered["Side"] = "PUT_ITM"

            st.markdown("### 📉 ITM CALL (1–2 strikes) with OI Decay filter")
            if calls_filtered.empty:
                st.info("No ITM CALL strikes meeting decay condition.")
            else:
                st.dataframe(
                    calls_filtered[
                        ["Symbol", "Side", "Strike Price", "CE_OI_Change_%", "CE_OI", "PE_OI_Change_%", "PE_OI"]
                    ]
                )
                all_results.append(calls_filtered)

            st.markdown("### 📉 ITM PUT (1–2 strikes) with OI Decay filter")
            if puts_filtered.empty:
                st.info("No ITM PUT strikes meeting decay condition.")
            else:
                st.dataframe(
                    puts_filtered[
                        ["Symbol", "Side", "Strike Price", "CE_OI_Change_%", "CE_OI", "PE_OI_Change_%", "PE_OI"]
                    ]
                )
                all_results.append(puts_filtered)

        # 5) EXCEL DOWNLOAD
        if all_results:
            final_df = pd.concat(all_results, ignore_index=True)

            buffer = BytesIO()
            final_df.to_excel(buffer, index=False)
            buffer.seek(0)

            st.success(f"Scan completed. {len(final_df)} rows matched conditions across all symbols.")
            st.download_button(
                label="📥 Download Filtered ITM OI Decay Data (Excel)",
                data=buffer,
                file_name="oi_decay_itm_filtered.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.warning("No strikes met the decay condition for the selected symbols.")
