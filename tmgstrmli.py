import streamlit as st
import pandas as pd
import numpy as np
import requests
from io import StringIO, BytesIO

# ======================================================
# STREAMLIT CONFIG
# ======================================================
st.set_page_config(
    page_title="OI Decay ITM Scanner",
    layout="wide",
)

st.title("📉 % OI Decay Scanner — ITM 1–2 Strikes (CALL & PUT)")
st.caption("ATM selection based on close price (NSE) + Option Chain from NiftyTrader")

# ======================================================
# NSE FETCH HELPERS (UNOFFICIAL, BE CAREFUL FOR COMMERCIAL USE)
# ======================================================

NSE_HEADERS = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/79.0.3945.79 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
}

def nsefetch_json(url: str):
    """
    Helper similar to widely-used NSE scrapers:
    - First try direct JSON GET
    - If that fails, get homepage + retry (to set cookies)
    """
    try:
        resp = requests.get(url, headers=NSE_HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        try:
            with requests.Session() as s:
                s.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
                resp = s.get(url, headers=NSE_HEADERS, timeout=10)
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return None

def get_close_price(symbol: str):
    """
    Get close/ltp for symbol.
    1️⃣ Try derivative quote (for F&O / indices) -> underlyingValue
    2️⃣ Fallback to equity quote -> priceInfo.lastPrice
    """
    symbol = symbol.upper().strip()

    # Try derivative (works for indices + F&O stocks)
    der_url = f"https://www.nseindia.com/api/quote-derivative?symbol={symbol}"
    data = nsefetch_json(der_url)
    if isinstance(data, dict):
        uv = data.get("underlyingValue")
        if uv is not None:
            try:
                return float(uv)
            except Exception:
                pass

    # Fallback to equity quote
    eq_url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
    data = nsefetch_json(eq_url)
    if isinstance(data, dict):
        price_info = data.get("priceInfo") or data.get("priceinfo") or {}
        lp = price_info.get("lastPrice")
        if lp is not None:
            try:
                return float(lp)
            except Exception:
                pass

    return None

# ======================================================
# NIFTYTRADER OPTION CHAIN SCRAPER
# ======================================================

NT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.niftytrader.in/",
}

def fetch_option_chain_niftytrader(symbol: str):
    """
    Fetch the main option-chain table from NiftyTrader HTML and return as cleaned DataFrame.
    """
    url = f"https://www.niftytrader.in/nse-option-chain/{symbol.upper()}"
    try:
        resp = requests.get(url, headers=NT_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        st.warning(f"{symbol}: Failed to fetch option chain page ({e})")
        return None

    try:
        tables = pd.read_html(resp.text)
    except ValueError:
        st.warning(f"{symbol}: No tables found on NiftyTrader page.")
        return None

    if not tables:
        st.warning(f"{symbol}: No tables parsed from NiftyTrader.")
        return None

    df = tables[0]

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join([str(x) for x in col if str(x) != "nan"]).strip()
            for col in df.columns.values
        ]
    else:
        df.columns = [str(c).strip() for c in df.columns]

    # ---- Strike Price ----
    strike_col = None
    for col in df.columns:
        if "strike" in col.lower():
            strike_col = col
            break

    if strike_col is None:
        st.warning(f"{symbol}: Could not find 'Strike' column.")
        return None

    # Extract numeric strike
    strike_series = (
        df[strike_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.extract(r"(\d+\.?\d*)")[0]
    )
    df["Strike Price"] = pd.to_numeric(strike_series, errors="coerce")

    # ---- OI Change % columns (CE, PE) ----
    oi_cols = [c for c in df.columns if "oi" in c.lower() and "%" in c.lower()]
    if len(oi_cols) >= 2:
        ce_oi_col, pe_oi_col = oi_cols[0], oi_cols[1]
    else:
        # fallback to earlier known names
        ce_oi_col = "OI (Chg %)"
        pe_oi_col = "OI (Chg %).1"
        if ce_oi_col not in df.columns or pe_oi_col not in df.columns:
            st.warning(f"{symbol}: Could not locate CE/PE OI (Chg %) columns.")
            return None

    df["CE_OI_Change_%"] = (
        df[ce_oi_col]
        .astype(str)
        .str.extract(r"\((.*?)\)")[0]
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    df["PE_OI_Change_%"] = (
        df[pe_oi_col]
        .astype(str)
        .str.extract(r"\((.*?)\)")[0]
        .str.replace("%", "", regex=False)
        .str.strip()
    )

    df["CE_OI_Change_%"] = pd.to_numeric(df["CE_OI_Change_%"], errors="coerce")
    df["PE_OI_Change_%"] = pd.to_numeric(df["PE_OI_Change_%"], errors="coerce")

    df = df.dropna(subset=["Strike Price"])

    return df

# ======================================================
# ITM 1–2 STRIKES SELECTION (BASED ON CLOSE PRICE)
# ======================================================

def get_itm_strikes(df: pd.DataFrame, close_price: float):
    """
    From full OC table, return:
      - 2 ITM CALL strikes (nearest below close)
      - 2 ITM PUT strikes (nearest above close)
    Also returns ATM strike for reference.
    """
    d = df.copy()
    d = d.sort_values("Strike Price").reset_index(drop=True)

    strikes = d["Strike Price"].values
    if len(strikes) == 0:
        return pd.DataFrame(), pd.DataFrame(), None

    # ATM (closest to close)
    atm_idx = int(np.argmin(np.abs(strikes - close_price)))
    atm_strike = strikes[atm_idx]

    # ITM CALL = strikes BELOW close (2 closest)
    call_mask = strikes < close_price
    call_strikes = strikes[call_mask]
    if len(call_strikes) > 0:
        # Take last 2
        call_itm_strikes = call_strikes[-2:]
        itm_call_df = d[d["Strike Price"].isin(call_itm_strikes)]
    else:
        itm_call_df = d.iloc[0:0]  # empty

    # ITM PUT = strikes ABOVE close (2 closest)
    put_mask = strikes > close_price
    put_strikes = strikes[put_mask]
    if len(put_strikes) > 0:
        put_itm_strikes = put_strikes[:2]
        itm_put_df = d[d["Strike Price"].isin(put_itm_strikes)]
    else:
        itm_put_df = d.iloc[0:0]

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

col_sel, col_thr = st.columns([2, 1])

with col_sel:
    selected_symbols = st.multiselect(
        "Select Symbols to Scan",
        options=sorted(ALL_SYMBOLS),
        default=["NIFTY", "BANKNIFTY", "RELIANCE"]
    )

with col_thr:
    decay_threshold = st.number_input(
        "Decay % Threshold (<= this value)",
        min_value=-100.0,
        max_value=0.0,
        value=-30.0,
        step=1.0
    )

run_button = st.button("🚀 Run Scan")

# ======================================================
# MAIN SCAN
# ======================================================

all_rows = []  # for Excel export

if run_button:
    if not selected_symbols:
        st.warning("Please select at least one symbol.")
    else:
        for sym in selected_symbols:
            with st.spinner(f"Scanning {sym}..."):
                close_price = get_close_price(sym)
                if close_price is None:
                    st.error(f"{sym}: Could not fetch close price from NSE.")
                    continue

                oc_df = fetch_option_chain_niftytrader(sym)
                if oc_df is None or oc_df.empty:
                    st.error(f"{sym}: Could not fetch/parse option chain.")
                    continue

                itm_calls_df, itm_puts_df, atm_strike = get_itm_strikes(oc_df, close_price)

                st.subheader(f"📌 {sym}")
                st.write(
                    f"**Close Price (NSE)**: `{close_price}` &nbsp;&nbsp; "
                    f"**ATM Strike (approx)**: `{atm_strike}`"
                )

                # Apply decay filter
                calls_filtered = itm_calls_df[
                    (itm_calls_df["CE_OI_Change_%"].notna()) &
                    (itm_calls_df["CE_OI_Change_%"] <= decay_threshold)
                ].copy()
                puts_filtered = itm_puts_df[
                    (itm_puts_df["PE_OI_Change_%"].notna()) &
                    (itm_puts_df["PE_OI_Change_%"] <= decay_threshold)
                ].copy()

                calls_filtered["Symbol"] = sym
                calls_filtered["Side"] = "CALL_ITM"
                puts_filtered["Symbol"] = sym
                puts_filtered["Side"] = "PUT_ITM"

                # Keep only key columns + original for inspection
                display_cols = [
                    "Symbol", "Side", "Strike Price",
                    "CE_OI_Change_%", "PE_OI_Change_%"
                ]
                extra_cols = [c for c in oc_df.columns if c not in display_cols]
                display_cols_full = display_cols + extra_cols

                st.markdown("**📉 ITM CALL (1–2 strikes) with OI Decay filter**")
                if calls_filtered.empty:
                    st.info("No ITM CALL strikes meeting decay condition.")
                else:
                    st.dataframe(calls_filtered[display_cols_full])
                    all_rows.append(calls_filtered)

                st.markdown("**📉 ITM PUT (1–2 strikes) with OI Decay filter**")
                if puts_filtered.empty:
                    st.info("No ITM PUT strikes meeting decay condition.")
                else:
                    st.dataframe(puts_filtered[display_cols_full])
                    all_rows.append(puts_filtered)

        # ==============================
        # EXCEL DOWNLOAD
        # ==============================
        if all_rows:
            final_df = pd.concat(all_rows, ignore_index=True)

            buffer = BytesIO()
            final_df.to_excel(buffer, index=False)
            buffer.seek(0)

            st.success(f"Scan completed. {len(final_df)} rows matched.")
            st.download_button(
                label="📥 Download Filtered ITM OI Decay Data (Excel)",
                data=buffer,
                file_name="oi_decay_itm_filtered.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("No strikes met the decay condition across selected symbols.")
