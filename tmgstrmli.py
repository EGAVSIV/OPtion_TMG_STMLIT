# app.py
import time
from io import BytesIO
import requests
import pandas as pd
import numpy as np
import streamlit as st
from tvDatafeed import TvDatafeed, Interval
import altair as alt

# ======================================================
# STREAMLIT CONFIG
# ======================================================
st.set_page_config(page_title="OI + Greeks OTM Scanner", layout="wide")
st.title("📉 OTM %OI Decay + Full Option Chain (Greeks, Heatmap, Charts)")
st.caption("Close Price: TradingView (tvDatafeed) | Option Chain & Greeks: NiftyTrader API")

# ======================================================
# tvDatafeed (no-login)
# ======================================================
try:
    tv = TvDatafeed()
except Exception as e:
    tv = None
    st.warning(f"tvDatafeed initialization failed: {e} — close prices may not be available.")

@st.cache_data(ttl=60)
def get_close_price(symbol: str):
    """Close price ONLY from TV datafeed (cached)."""
    if tv is None:
        return None
    try:
        df = tv.get_hist(symbol=symbol, exchange="NSE", interval=Interval.in_daily, n_bars=2)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        return None
    return None

# ======================================================
# NiftyTrader Option Chain Fetch (replaces NSE)
# ======================================================
NT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.niftytrader.in/",
}

# Adjust TTLs as needed — 30s keeps app responsive but reduces calls
@st.cache_data(ttl=30)
def fetch_nt_oc(symbol: str):
    """
    Fetch Option Chain from NiftyTrader API.
    Returns parsed JSON dict on success, else None.
    """
    symbol = symbol.upper().strip()
    url = f"https://www.niftytrader.in/api/optionchain/live?symbol={symbol}"
    try:
        r = requests.get(url, headers=NT_HEADERS, timeout=10)
        r.raise_for_status()
        js = r.json()
        # NiftyTrader returns {"status":"success", "data": {...}} on success in tests
        if isinstance(js, dict) and js.get("status") in ("success", True, "ok"):
            return js
        # Some variants may contain data directly
        if isinstance(js, dict) and "data" in js:
            return js
        return None
    except Exception:
        return None

def get_expiry_list(symbol: str):
    """Extract expiry list from NiftyTrader response (or return [])."""
    js = fetch_nt_oc(symbol)
    if not js:
        return []
    try:
        # common key paths
        data = js.get("data", {})
        # expiryList or expiryList may be key
        exps = data.get("expiryList") or data.get("expiryDates") or []
        # normalize: ensure list of strings
        return [str(x) for x in exps] if exps else []
    except Exception:
        return []

def build_full_chain_table_nt(symbol: str, expiry: str | None):
    """
    Build full OC DataFrame (CE+PE) from NiftyTrader structure.
    If expiry is None, include all expiries returned by the API.
    """
    js = fetch_nt_oc(symbol)
    if not js:
        return None

    data = js.get("data", {})
    chain = data.get("optionChain") or data.get("options") or []
    rows = []

    for item in chain:
        item_exp = item.get("expiryDate") or item.get("expiry")
        if expiry and item_exp != expiry:
            continue

        # strike price may be numeric or string
        try:
            strike = float(item.get("strikePrice") or item.get("strike") or item.get("strike_price"))
        except Exception:
            continue

        ce = item.get("CE") or item.get("call") or {}
        pe = item.get("PE") or item.get("put") or {}

        # safe getters with multiple possible keys used by different providers
        def safe_get(o, *keys):
            for k in keys:
                if isinstance(o, dict) and k in o:
                    return o.get(k)
            return None

        row = {
            "Strike": strike,
            # CE
            "CE_LTP": safe_get(ce, "LTP", "lastPrice", "last_price"),
            "CE_OI": safe_get(ce, "OI", "openInterest"),
            "CE_Change_OI": safe_get(ce, "changeOI", "changeinOpenInterest"),
            "CE_pChange_OI": safe_get(ce, "pchangeOI", "pchangeinOpenInterest"),
            "CE_IV": safe_get(ce, "IV", "impliedVolatility"),
            "CE_Delta": safe_get(ce, "delta"),
            "CE_Vega": safe_get(ce, "vega"),
            "CE_Gamma": safe_get(ce, "gamma"),
            "CE_Theta": safe_get(ce, "theta"),
            # PE
            "PE_LTP": safe_get(pe, "LTP", "lastPrice", "last_price"),
            "PE_OI": safe_get(pe, "OI", "openInterest"),
            "PE_Change_OI": safe_get(pe, "changeOI", "changeinOpenInterest"),
            "PE_pChange_OI": safe_get(pe, "pchangeOI", "pchangeinOpenInterest"),
            "PE_IV": safe_get(pe, "IV", "impliedVolatility"),
            "PE_Delta": safe_get(pe, "delta"),
            "PE_Vega": safe_get(pe, "vega"),
            "PE_Gamma": safe_get(pe, "gamma"),
            "PE_Theta": safe_get(pe, "theta"),
        }
        rows.append(row)

    if not rows:
        return None

    df = pd.DataFrame(rows)
    # normalize numeric columns where possible
    numcols = ["Strike", "CE_LTP", "CE_OI", "CE_Change_OI", "CE_pChange_OI", "CE_IV",
               "CE_Delta", "CE_Vega", "CE_Gamma", "CE_Theta",
               "PE_LTP", "PE_OI", "PE_Change_OI", "PE_pChange_OI", "PE_IV",
               "PE_Delta", "PE_Vega", "PE_Gamma", "PE_Theta"]
    for c in numcols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("Strike").reset_index(drop=True)

def build_compact_chain_table_nt(symbol: str, expiry: str | None):
    """
    Build compact OTM-scan table from NiftyTrader response:
    Strike Price, CE_OI_Change_%, CE_OI, PE_OI_Change_%, PE_OI
    """
    js = fetch_nt_oc(symbol)
    if not js:
        return None

    data = js.get("data", {})
    chain = data.get("optionChain") or data.get("options") or []
    rows = []

    for item in chain:
        item_exp = item.get("expiryDate") or item.get("expiry")
        if expiry and item_exp != expiry:
            continue

        try:
            strike = float(item.get("strikePrice") or item.get("strike") or item.get("strike_price"))
        except Exception:
            continue

        ce = item.get("CE") or item.get("call") or {}
        pe = item.get("PE") or item.get("put") or {}

        rows.append({
            "Strike Price": strike,
            "CE_OI_Change_%": ce.get("pchangeOI") or ce.get("pchangeinOpenInterest") or None,
            "CE_OI": ce.get("OI") or ce.get("openInterest") or None,
            "PE_OI_Change_%": pe.get("pchangeOI") or pe.get("pchangeinOpenInterest") or None,
            "PE_OI": pe.get("OI") or pe.get("openInterest") or None,
        })

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["CE_OI_Change_%"] = pd.to_numeric(df["CE_OI_Change_%"], errors="coerce")
    df["PE_OI_Change_%"] = pd.to_numeric(df["PE_OI_Change_%"], errors="coerce")
    df["Strike Price"] = pd.to_numeric(df["Strike Price"], errors="coerce")
    df = df.dropna(subset=["Strike Price"])
    return df.sort_values("Strike Price").reset_index(drop=True)

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
# STYLING & PLOTS (same as before)
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
    try:
        return df.style.apply(highlight, axis=1)
    except Exception:
        return df

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
    # guard for missing columns
    available = [c for c in greek_cols if c in df.columns]
    if not available:
        st.info("No Greek values found for heatmap.")
        return

    heat_df = df[["Strike"] + available].melt(
        id_vars="Strike", value_vars=available,
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
# SYMBOL LIST (unchanged; exact names you provided)
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
# UI AREA (keeps same layout as your original)
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
    per_symbol_delay = st.number_input("Delay between symbol calls (s)", min_value=0.0, max_value=5.0, value=0.2, step=0.05)

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
# MAIN LOGIC (preserves your original behavior)
# ======================================================
if run_scan:
    if not selected_symbols:
        st.warning("Please select at least one symbol.")
    elif len(selected_symbols) == 1:
        # SINGLE SYMBOL MODE
        sym = selected_symbols[0]
        close_price = get_close_price(sym)
        if close_price is None:
            st.error(f"{sym}: Close price not available from TV.")
        else:
            st.subheader(f"📌 {sym} — Close Price (TV): {close_price}")

            full_chain = build_full_chain_table_nt(sym, selected_expiry)
            if full_chain is None:
                st.error(f"{sym}: Option chain not available from NiftyTrader.")
            else:
                # Full chain with Greeks
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
                compact_df = build_compact_chain_table_nt(sym, selected_expiry)
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
        # MULTI-SYMBOL MODE
        all_results = []

        for sym in selected_symbols:
            # polite delay to avoid burst
            if per_symbol_delay:
                time.sleep(per_symbol_delay)

            close_price = get_close_price(sym)
            if close_price is None:
                st.write(f"Skipping {sym}: close price not available.")
                continue

            compact_df = build_compact_chain_table_nt(sym, selected_expiry)
            if compact_df is None or compact_df.empty:
                st.write(f"Skipping {sym}: option chain not available.")
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
                full_chain = build_full_chain_table_nt(sym, selected_expiry)
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
# End of app.py
