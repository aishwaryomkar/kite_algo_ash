"""
Thin wrapper around Kite Connect's historical data and quote endpoints.
Kite rate-limits at 3 requests/second - the sleep() after each historical
call keeps every module that uses this class safely under that limit
without needing to think about it everywhere else.
"""
import time
import datetime as dt
import pandas as pd


class DataFetcher:
    def __init__(self, kite):
        self.kite = kite
        self._instrument_cache = None

    def instruments(self, exchange="NSE"):
        if self._instrument_cache is None:
            self._instrument_cache = pd.DataFrame(self.kite.instruments(exchange))
        return self._instrument_cache

    def token_for_symbol(self, symbol, exchange="NSE"):
        df = self.instruments(exchange)
        row = df[(df["tradingsymbol"] == symbol) & (df["segment"] == "NSE")]
        if row.empty:
            raise ValueError(f"Instrument token not found for {symbol}")
        return int(row.iloc[0]["instrument_token"])

    def historical(self, symbol, days=400, interval="day", exchange="NSE"):
        token = self.token_for_symbol(symbol, exchange)
        to_date = dt.date.today()
        from_date = to_date - dt.timedelta(days=days)
        data = self.kite.historical_data(token, from_date, to_date, interval)
        df = pd.DataFrame(data)
        time.sleep(0.34)  # stay under 3 req/sec
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        return df

    def ltp(self, symbols, exchange="NSE"):
        if not symbols:
            return {}
        keys = [f"{exchange}:{s}" for s in symbols]
        quotes = self.kite.ltp(keys)
        return {k.split(":")[1]: v["last_price"] for k, v in quotes.items()}
