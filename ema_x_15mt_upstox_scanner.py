import os
import smtplib
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
from email.mime.text import MIMEText

# --- CONFIGURATION FROM GITHUB SECRETS ---
UPSTOX_TOKEN = os.getenv("UPSTOX_TOKEN")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS")
RISK_PER_TRADE = 5000  # Adjust based on your max loss tolerance

def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = GMAIL_USER
    msg['To'] = GMAIL_USER  # Sending to yourself
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASS)
            smtp.send_message(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")

def get_historical_data(instrument_key, interval, days_back=10):
    """Fetch historical candles from Upstox API V3."""
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    url = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {UPSTOX_TOKEN}'
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json().get('data', {}).get('candles', [])
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
        df = df.iloc[::-1].reset_index(drop=True)  # Reverse to chronological order
        return df
    return pd.DataFrame()

def process_stock(symbol, category, instrument_key):
    # Fetch Multi-Timeframe Data
    df_day = get_historical_data(instrument_key, 'day', 30)
    df_1hr = get_historical_data(instrument_key, '1hour', 15)
    df_15m = get_historical_data(instrument_key, '15minute', 5)
    
    if df_day.empty or df_1hr.empty or df_15m.empty:
        return None
        
    # Calculate Daily Indicators
    df_day['EMA_5'] = ta.ema(df_day['close'], length=5)
    df_day['EMA_13_H'] = ta.ema(df_day['high'], length=13)
    df_day['EMA_13_L'] = ta.ema(df_day['low'], length=13)
    
    # Calculate 1 Hour Indicators
    df_1hr['EMA_5'] = ta.ema(df_1hr['close'], length=5)
    df_1hr['EMA_13_H'] = ta.ema(df_1hr['high'], length=13)
    df_1hr['EMA_13_L'] = ta.ema(df_1hr['low'], length=13)
    
    # Calculate 15 Min Indicators
    df_15m['EMA_5'] = ta.ema(df_15m['close'], length=5)
    df_15m['EMA_13_H'] = ta.ema(df_15m['high'], length=13)
    df_15m['EMA_13_L'] = ta.ema(df_15m['low'], length=13)
    df_15m['OBV'] = ta.obv(df_15m['close'], df_15m['volume'])
    df_15m['OBV_EMA_20'] = ta.ema(df_15m['OBV'], length=20)
    df_15m.ta.atr(length=14, append=True) 
    atr_col = [col for col in df_15m.columns if 'ATR' in col][0]

    # Get latest completed states
    day_latest = df_day.iloc[-1]
    hr_latest = df_1hr.iloc[-1]
    
    prev_15 = df_15m.iloc[-2]  # t-1 (previous candle)
    prev2_15 = df_15m.iloc[-3] # t-2 (candle before previous)
    curr_15 = df_15m.iloc[-1]  # t (current open candle)

    signal = None
    strategy_name = ""
    
    # --- BUY CONDITIONS ---
    if (day_latest['EMA_5'] > day_latest['EMA_13_H'] and 
        hr_latest['EMA_5'] > hr_latest['EMA_13_H'] and 
        prev_15['EMA_5'] > prev_15['EMA_13_H'] and 
        prev2_15['EMA_5'] < prev2_15['EMA_13_H'] and 
        prev_15['OBV'] > prev_15['OBV_EMA_20']):
        
        signal = 'BUY'
        strategy_name = 'b_ema_cross_15mt'
        entry_price = curr_15['open']
        sl_points = prev_15[atr_col] * 3
        
    # --- SELL CONDITIONS ---
    elif (day_latest['EMA_5'] < day_latest['EMA_13_L'] and 
          hr_latest['EMA_5'] < hr_latest['EMA_13_L'] and 
          prev_15['EMA_5'] < prev_15['EMA_13_L'] and 
          prev2_15['EMA_5'] > prev2_15['EMA_13_L'] and 
          prev_15['OBV'] < prev_15['OBV_EMA_20']):
        
        signal = 'SELL'
        strategy_name = 's_ema_cross_15mt'
        entry_price = curr_15['open']
        sl_points = prev_15[atr_col] * 3

    if signal:
        qty = int(RISK_PER_TRADE / sl_points) if sl_points > 0 else 0
        target = entry_price * 1.05 if signal == 'BUY' else entry_price * 0.95
        
        return {
            'Date': datetime.now().strftime('%Y-%m-%d'),
            'Symbol': symbol,
            'Strategy Name': strategy_name,
            'Category': category,
            'Timeframe': '15mt',
            'Trigger Time': prev_15['timestamp'],
            'Entry Time': curr_15['timestamp'],
            'Entry Price': entry_price,
            'Qty': qty,
            'Target': target,
            'TSL (3xATR)': sl_points,
            'Status': 'OPEN'
        }
    return None

def main():
    stocks_df = pd.read_csv('fno_with_sectors.csv')
    ledger_file = 'master_ledger_emax15hrd.csv'
    
    # Initialize ledger if it doesn't exist
    if not os.path.exists(ledger_file):
        pd.DataFrame(columns=['Date', 'Symbol', 'Strategy Name', 'Category', 'Timeframe', 
                              'Trigger Time', 'Entry Time', 'Entry Price', 'Qty', 
                              'Target', 'TSL (3xATR)', 'Status']).to_csv(ledger_file, index=False)
                              
    ledger = pd.read_csv(ledger_file)
    new_trades = []

    for index, row in stocks_df.iterrows():
        # Requires exact Upstox Instrument Key format in your CSV, e.g., NSE_EQ|INE123...
        trade = process_stock(row['Symbol'], row['Sector'], row['Instrument_Key'])
        if trade:
            new_trades.append(trade)
            
    if new_trades:
        new_df = pd.DataFrame(new_trades)
        updated_ledger = pd.concat([ledger, new_df], ignore_index=True)
        updated_ledger.to_csv(ledger_file, index=False)
        
        # Send Email Alert
        email_body = f"New trades executed:\n\n{new_df.to_string()}"
        send_email("Upstox Scanner Alert", email_body)

if __name__ == "__main__":
    main()
