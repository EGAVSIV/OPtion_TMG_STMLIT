import streamlit as st
import pandas as pd
import numpy as np
import requests
from io import BytesIO
from tvDatafeed import TvDatafeed, Interval
import altair as alt

# ======================================================
# STREAMLIT CONFIG
# ======================================================
st.set_page_config(page_title="OI + Greeks OTM Scanner", layout="wide")
st.title("📉 OTM %OI Decay + Full Option Chain (Greeks, Heatmap, Charts)")
st.caption("Close Price: TradingView (tvDatafeed) | Option Chain & Greeks: NSE JSON API")

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
        df = tv.get_hist(symbol=symbol, exchange="NSE", interval=Interval.in_daily, n_bars=2)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        return None
    return None


# ======================================================
# NSE OPTION CHAIN JSON
# ======================================================
# ==== NSE SESSION FIX ====
# ======================================================
# NSE OPTION CHAIN (STABLE VERSION)
# ======================================================

import requests
import streamlit as st

# ---------- HEADERS (Verified Working Feb 2025) ----------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
    "Origin": "https://www.nseindia.com",
    "Host": "www.nseindia.com",
    "Connection": "keep-alive",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

SESSION = requests.Session()


# ---------- ALWAYS CALL THIS ONLY ONCE AT START ----------
def initialize_nse_session():
    """Fetch homepage ONLY once to load cookies."""
    try:
        SESSION.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
    except Exception:
        pass


# ---------- CACHED WRAPPER: Prevents repeated NSE hits ----------
@st.cache_data(ttl=90)
def cached_oc(symbol: str):
    return _fetch_raw_oc(symbol)


# ---------- REAL NSE FETCH FUNCTION ----------
def _fetch_raw_oc(symbol: str):
    """
    Handles:
    - Equity + Index
    - 403 blocks
    - HTML fallback
    - Cookie refresh retry
    """

    symbol = symbol.upper().strip()

    # Select NSE endpoint
    if symbol in {
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
        "NIFTYJR", "CNXFINANCE", "CNXMIDCAP"
    }:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    else:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"

    # ---- FIRST REQUEST ----
    try:
        r = SESSION.get(url, headers=HEADERS, timeout=12)
    except Exception:
        return None

    # If NSE returned HTML instead of JSON → retry once
    if "<html" in r.text.lower():
        # refresh cookies
        try:
            SESSION.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
        except:
            pass

        # retry
        try:
            r = SESSION.get(url, headers=HEADERS, timeout=12)
        except:
            return None

        if "<html" in r.text.lower():
            return None

    # Parse JSON safely
    try:
        data = r.json()
        if "records" not in data:
            return None
        if "data" not in data["records"]:
            return None
        return data
    except Exception:
        return None


# ---------- PUBLIC FUNCTION CALLED BY MAIN APP ----------
def fetch_oc_json(symbol: str):
    """
    Use cached version to avoid repeated calls & NSE blocks.
    """
    return cached_oc(symbol)


# ---------- EXPIRY LIST ----------
def get_expiry_list(symbol: str):
    data = fetch_oc_json(symbol)
    if not data:
        return []
    rec = data.get("records", {})
    return rec.get("expiryDates", [])



def build_compact_chain_table(oc_json, expiry: str | None):
    """
    Build compact table for scan:
      Strike Price, CE_OI_Change_%, CE_OI, PE_OI_Change_%, PE_OI
    Filtered by selected expiry if provided.
    """
    if not oc_json:
        return None

    all_data = oc_json.get("records", {}).get("data", [])
    if expiry:
        data_list = [d for d in all_data if d.get("expiryDate") == expiry]
        if not data_list:
            data_list = all_data  # fallback if expiry not present
    else:
        data_list = all_data

    rows = []
    for d in data_list:
        strike = d.get("strikePrice")
        if strike is None:
            continue

        ce = d.get("CE", {})
        pe = d.get("PE", {})

        row = {
            "Strike Price": float(strike),
            "CE_OI_Change_%": ce.get("pchangeinOpenInterest"),
            "CE_OI": ce.get("openInterest"),
            "PE_OI_Change_%": pe.get("pchangeinOpenInterest"),
            "PE_OI": pe.get("openInterest"),
        }
        rows.append(row)

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["CE_OI_Change_%"] = pd.to_numeric(df["CE_OI_Change_%"], errors="coerce")
    df["PE_OI_Change_%"] = pd.to_numeric(df["PE_OI_Change_%"], errors="coerce")
    df["Strike Price"] = pd.to_numeric(df["Strike Price"], errors="coerce")

    df = df.dropna(subset=["Strike Price"])
    return df.sort_values("Strike Price").reset_index(drop=True)


def build_full_chain_table(oc_json, expiry: str | None):
    """
    Full chain with Greeks, OI, prices for CE & PE.
    Used for Greeks view, charts, heatmap.
    """
    if not oc_json:
        return None

    all_data = oc_json.get("records", {}).get("data", [])
    if expiry:
        data_list = [d for d in all_data if d.get("expiryDate") == expiry]
        if not data_list:
            data_list = all_data
    else:
        data_list = all_data

    rows = []
    for item in data_list:
        strike = item.get("strikePrice")
        if strike is None:
            continue

        ce = item.get("CE", {}) or {}
        pe = item.get("PE", {}) or {}

        row = {
            "Strike": float(strike),
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

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.sort_values("Strike").reset_index(drop=True)
    return df


# ======================================================
# OTM STRIKE SELECTION (BASED ON CLOSE PRICE)
# ======================================================
def get_otm_strikes(df: pd.DataFrame, close_price: float):
    """
    OTM definition:
      - CALL OTM: first 2 strikes ABOVE close price
      - PUT OTM : first 2 strikes BELOW close price (nearest)
    """
    if df is None or df.empty:
        return df.iloc[0:0], df.iloc[0:0], None

    d = df.sort_values("Strike Price")
    strikes = d["Strike Price"].values
    if len(strikes) == 0:
        return d.iloc[0:0], d.iloc[0:0], None

    atm_strike = strikes[np.argmin(np.abs(strikes - close_price))]

    call_otm = d[d["Strike Price"] > close_price].head(2)
    put_otm = d[d["Strike Price"] < close_price].tail(2)

    return call_otm, put_otm, atm_strike


# ======================================================
# STYLING & PLOTS
# ======================================================
def style_greeks(df: pd.DataFrame, iv_spike: float, iv_crush: float):
    """Highlight CE_IV / PE_IV cells for spike/crush."""
    def highlight(row):
        styles = []
        for col in df.columns:
            style = ""
            if col in ["CE_IV", "PE_IV"]:
                val = row[col]
                if pd.notna(val):
                    if val >= iv_spike:
                        style = "background-color: rgba(0,255,0,0.3);"  # spike (green)
                    elif val <= iv_crush:
                        style = "background-color: rgba(255,0,0,0.3);"  # crush (red)
            styles.append(style)
        return styles
    return df.style.apply(highlight, axis=1)


def plot_oi_bars(df: pd.DataFrame, title: str):
    """OI bar chart for CE & PE vs Strike."""
    base = df[["Strike", "CE_OI", "PE_OI"]].copy()
    base = base.melt(id_vars="Strike", value_vars=["CE_OI", "PE_OI"],
                     var_name="Side", value_name="OI")
    chart = (
        alt.Chart(base)
        .mark_bar()
        .encode(
            x=alt.X("Strike:O", sort=None),
            y=alt.Y("OI:Q"),
            color="Side:N",
            tooltip=["Strike", "Side", "OI"],
        )
        .properties(title=title, height=300)
    )
    st.altair_chart(chart, use_container_width=True)


def plot_ltp_chart(df: pd.DataFrame, title: str):
    """Combined CE/PE LTP vs Strike line chart."""
    base = df[["Strike", "CE_LTP", "PE_LTP"]].copy()
    base = base.melt(id_vars="Strike", value_vars=["CE_LTP", "PE_LTP"],
                     var_name="Side", value_name="LTP")

    chart = (
        alt.Chart(base)
        .mark_line(point=True)
        .encode(
            x=alt.X("Strike:O", sort=None),
            y=alt.Y("LTP:Q"),
            color="Side:N",
            tooltip=["Strike", "Side", "LTP"],
        )
        .properties(title=title, height=300)
    )
    st.altair_chart(chart, use_container_width=True)


def plot_greek_heatmap(df: pd.DataFrame, title: str):
    """Heatmap of Greeks vs Strike."""
    greek_cols = ["CE_Delta", "CE_Gamma", "CE_Vega", "CE_Theta",
                  "PE_Delta", "PE_Gamma", "PE_Vega", "PE_Theta"]
    heat_df = df[["Strike"] + greek_cols].melt(
        id_vars="Strike", value_vars=greek_cols,
        var_name="Greek", value_name="Value"
    )

    chart = (
        alt.Chart(heat_df.dropna(subset=["Value"]))
        .mark_rect()
        .encode(
            x=alt.X("Strike:O", sort=None),
            y=alt.Y("Greek:N"),
            color=alt.Color("Value:Q", scale=alt.Scale(scheme="blues")),
            tooltip=["Strike", "Greek", "Value"],
        )
        .properties(title=title, height=300)
    )
    st.altair_chart(chart, use_container_width=True)


# ======================================================
# SYMBOL LIST
# ======================================================
ALL_SYMBOLS = [
    "BANKNIFTY", "CNXFINANCE", "CNXMIDCAP", "NIFTY", "NIFTYJR", "360ONE", "ABB",
    "ABCAPITAL", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS", "ALKEM",
    "AMBER", "AMBUJACEM", "ANGELONE", "APLAPOLLO", "APOLLOHOSP", "ASHOKLEY",
    "ASIANPAINT", "ASTRAL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ_AUTO",
    "BAJAJFINSV", "BAJFINANCE", "BANDHANBNK", "BANKBARODA", "BANKINDIA", "BDL",
    "BEL", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BLUESTARCO", "BOSCHLTD",
    "BPCL", "BRITANNIA", "BSE", "CAMS", "CANBK", "CDSL", "CGPOWER", "CHOLAFIN",
    "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR", "CROMPTON", "CUMMINSIND",
    "CYIENT", "DABUR", "DALBHARAT", "DELHIVERY", "DIVISLAB", "DIXON", "DLF",
    "DMART", "DRREDDY", "EICHERMOT", "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK",
    "GODREJCP", "GRASIM", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HFCL", "HINDALCO", "HINDPETRO", "HINDUNILVR",
    "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "IGL",
    "INDHOTEL", "INDIANB", "INDIGO", "INDUSINDBK", "INFY", "IOC", "IRCTC", "IRFC",
    "ITC", "JINDALSTEL", "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "KFINTECH",
    "KPITTECH", "LICI", "LT", "LTIM", "LUPIN", "MANAPPURAM", "MARICO", "MARUTI",
    "MAXHEALTH", "MCX", "MUTHOOTFIN", "NAUKRI", "NATIONALUM", "NESTLEIND", "NMDC",
    "NTPC", "NYKAA", "ONGC", "PAGEIND", "PAYTM", "PFC", "PIDILITIND", "PIIND",
    "PNB", "POLYCAB", "POWERGRID", "PRESTIGE", "RECLTD", "RELIANCE", "RVNL",
    "SAIL", "SBICARD", "SBIN", "SIEMENS", "SONACOMS", "SRF", "SUNPHARMA",
    "SUPREMEIND", "SUZLON", "TATACHEM", "TATACONSUM", "TATAMOTORS", "TATAPOWER",
    "TATASTEEL", "TATATECH", "TCS", "TECHM", "TIINDIA", "TITAN", "TORNTPOWER",
    "TRENT", "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UPL", "VEDL", "VOLTAS",
    "WIPRO", "YESBANK", "ZYDUSLIFE",
]

# ======================================================
# UI AREA
# ======================================================
st.markdown("### Selection & Filters")

col_sel, col_opts = st.columns([3, 2])

with col_sel:
    selected_symbols = st.multiselect("Choose Symbols", sorted(ALL_SYMBOLS), [])
    select_all = st.checkbox("Select All Symbols")
    if select_all:
        selected_symbols = sorted(ALL_SYMBOLS)

with col_opts:
    decay_threshold = st.number_input(
        "OI Decay % Threshold (≤)",
        min_value=-100.0,
        max_value=0.0,
        value=-30.0,
        step=1.0,
    )
    iv_spike = st.number_input("IV Spike ≥", min_value=0.0, max_value=300.0, value=50.0)
    iv_crush = st.number_input("IV Crush ≤", min_value=0.0, max_value=300.0, value=10.0)
    show_greeks_all = st.checkbox("Show Greeks Table & Charts for all symbols")


# Expiry selection (based on first selected symbol)
selected_expiry = None
if selected_symbols:
    base_symbol = selected_symbols[0]
    expiry_list = get_expiry_list(base_symbol)
    if expiry_list:
        selected_expiry = st.selectbox(
            f"Select Expiry (applies where available, base: {base_symbol})",
            options=expiry_list,
            index=0,
        )
    else:
        st.info("Could not fetch expiry list for base symbol; using all expiries.")
        selected_expiry = None

run_scan = st.button("🚀 Run Scan")

# ======================================================
# MAIN LOGIC
# ======================================================
if run_scan:
    if not selected_symbols:
        st.warning("Please select at least one symbol.")
    elif len(selected_symbols) == 1:
        # ============================
        # SINGLE SYMBOL MODE
        # ============================
        sym = selected_symbols[0]
        close_price = get_close_price(sym)
        if close_price is None:
            st.error(f"{sym}: Close price not available from TV.")
        else:
            st.subheader(f"📌 {sym} — Close Price (TV): {close_price}")

            oc_json = fetch_oc_json(sym)
            if not oc_json:
                st.error(f"{sym}: Option chain not available from NSE.")
            else:
                # Full chain with Greeks
                full_chain = build_full_chain_table(oc_json, selected_expiry)
                if full_chain is None or full_chain.empty:
                    st.error("No option-chain rows for selected expiry.")
                else:
                    st.markdown("### 🧮 Full Option Chain with Greeks")
                    st.dataframe(
                        style_greeks(full_chain, iv_spike, iv_crush),
                        use_container_width=True,
                    )

                    st.markdown("### 📊 Open Interest (CE vs PE)")
                    plot_oi_bars(full_chain, f"{sym} — OI by Strike")

                    st.markdown("### 📈 Combined CE/PE LTP vs Strike")
                    plot_ltp_chart(full_chain, f"{sym} — LTP by Strike")

                    st.markdown("### 🔥 Greeks Heatmap")
                    plot_greek_heatmap(full_chain, f"{sym} — Greeks Heatmap")

                # OTM decay scan for same symbol
                compact_df = build_compact_chain_table(oc_json, selected_expiry)
                if compact_df is not None and not compact_df.empty:
                    call_otm, put_otm, atm = get_otm_strikes(compact_df, close_price)
                    st.markdown("---")
                    st.subheader("🎯 OTM 1–2 Decay Filter Scan")

                    call_ok = call_otm[
                        (call_otm["CE_OI_Change_%"].notna())
                        & (call_otm["CE_OI_Change_%"] <= decay_threshold)
                    ].copy()
                    put_ok = put_otm[
                        (put_otm["PE_OI_Change_%"].notna())
                        & (put_otm["PE_OI_Change_%"] <= decay_threshold)
                    ].copy()

                    if not call_ok.empty or not put_ok.empty:
                        call_ok["Side"] = "CALL_OTM"
                        put_ok["Side"] = "PUT_OTM"
                        final_single = pd.concat(
                            [call_ok, put_ok], ignore_index=True
                        ).sort_values("Strike Price")
                        st.dataframe(final_single, use_container_width=True)
                    else:
                        st.info("No OTM strikes meeting decay threshold for this symbol.")
    else:
        # ============================
        # MULTI-SYMBOL MODE
        # ============================
        all_results = []

        for sym in selected_symbols:
            close_price = get_close_price(sym)
            if close_price is None:
                continue

            oc_json = fetch_oc_json(sym)
            if not oc_json:
                continue

            compact_df = build_compact_chain_table(oc_json, selected_expiry)
            if compact_df is None or compact_df.empty:
                continue

            call_otm, put_otm, atm = get_otm_strikes(compact_df, close_price)

            call_ok = call_otm[
                (call_otm["CE_OI_Change_%"].notna())
                & (call_otm["CE_OI_Change_%"] <= decay_threshold)
            ].copy()
            put_ok = put_otm[
                (put_otm["PE_OI_Change_%"].notna())
                & (put_otm["PE_OI_Change_%"] <= decay_threshold)
            ].copy()

            if not call_ok.empty:
                call_ok["Symbol"] = sym
                call_ok["Side"] = "CALL_OTM"
                call_ok["Close_Price"] = close_price
                call_ok["ATM_Approx"] = atm
                all_results.append(call_ok)

            if not put_ok.empty:
                put_ok["Symbol"] = sym
                put_ok["Side"] = "PUT_OTM"
                put_ok["Close_Price"] = close_price
                put_ok["ATM_Approx"] = atm
                all_results.append(put_ok)

            # Full Greeks/Charts per symbol if toggle ON
            if show_greeks_all:
                full_chain = build_full_chain_table(oc_json, selected_expiry)
                if full_chain is not None and not full_chain.empty:
                    with st.expander(f"📊 Full Chain + Greeks — {sym}"):
                        st.dataframe(
                            style_greeks(full_chain, iv_spike, iv_crush),
                            use_container_width=True,
                        )
                        plot_oi_bars(full_chain, f"{sym} — OI by Strike")
                        plot_ltp_chart(full_chain, f"{sym} — LTP by Strike")
                        plot_greek_heatmap(full_chain, f"{sym} — Greeks Heatmap")

        if all_results:
            final = pd.concat(all_results, ignore_index=True)
            final = final.sort_values(["Symbol", "Side", "Strike Price"])
            st.success(f"Found {len(final)} matching OTM rows.")
            st.dataframe(final, use_container_width=True)

            buf = BytesIO()
            final.to_excel(buf, index=False)
            buf.seek(0)
            st.download_button(
                "📥 Download OTM Decay Scan Excel",
                buf,
                "otm_decay_scan_results.xlsx",
            )
        else:
            st.warning("No OTM strikes met the decay condition across symbols.")
