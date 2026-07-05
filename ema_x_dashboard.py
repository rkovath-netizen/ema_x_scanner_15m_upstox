import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="FnO Scanner Dashboard", layout="wide")
st.title("📈 Upstox FnO 15-Minute Strategy Scanner")

@st.cache_data(ttl=60)
def load_data():
    if os.path.exists('master_ledger.csv'):
        return pd.read_csv('master_ledger.csv')
    return pd.DataFrame()

df = load_data()

if df.empty:
    st.info("No trades have been logged yet. The scanner is waiting for conditions to be met.")
else:
    # Top Level Metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Trades Taken", len(df))
    col2.metric("Active Buy Signals", len(df[df['Strategy Name'] == 'b_ema_cross_15mt']))
    col3.metric("Active Sell Signals", len(df[df['Strategy Name'] == 's_ema_cross_15mt']))
    
    # Display the Ledger
    st.subheader("Master Ledger")
    st.dataframe(df, use_container_width=True)
    
    # Optional filtering
    sector_filter = st.selectbox("Filter by Category", ['All'] + list(df['Category'].unique()))
    if sector_filter != 'All':
        st.dataframe(df[df['Category'] == sector_filter])