import yfinance as yf

# =========================
# GET CURRENT PRICES
# =========================
def get_prices(tickers):
    prices = {}

    for ticker in tickers:
        try:
            data = yf.download(ticker, period="5d")

            if not data.empty:
                price = data["Close"].dropna().iloc[-1]
                prices[ticker] = float(price)
            else:
                prices[ticker] = None

        except:
            prices[ticker] = None

    return prices


# =========================
# GET HISTORICAL DATA
# =========================
def get_historical_data(tickers):
    import yfinance as yf
    import pandas as pd

    try:
        data = yf.download(tickers, period="1y")["Close"]

        # If single ticker → convert to DataFrame
        if isinstance(data, pd.Series):
            data = data.to_frame()

        return data

    except:
        # Return empty DataFrame instead of None
        return pd.DataFrame()