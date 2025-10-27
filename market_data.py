import okx.MarketData as Market
import numpy as np
from retrying import retry

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i-1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period

        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)

    return rsi[-1]
    
@retry(stop_max_attempt_number=5)
def get_pair_price(pair):
    marketAPI = Market.MarketAPI()
    return marketAPI.get_ticker(pair)['data'][0]['last']

@retry(stop_max_attempt_number=5)
def get_crypto_metrics(symbol):
    marketAPI = Market.MarketAPI()
    
    try:
        ticker_result = marketAPI.get_ticker(instId=symbol)
        
        if ticker_result['code'] != '0':
            raise Exception(f"failed to get ticker: {ticker_result['msg']}")
        
        ticker_data = ticker_result['data'][0]
        candles_result = marketAPI.get_candlesticks(
            instId=symbol,
            bar='1D',
            limit='30'
        )
        
        if candles_result['code'] != '0':
            raise Exception(f"failed to get candlesticks: {candles_result['msg']}")
        
        candles = candles_result['data']
        
        close_prices = np.array([float(candle[4]) for candle in reversed(candles)])
        current_price = float(ticker_data['last'])
        high_24h = float(ticker_data['high24h'])
        low_24h = float(ticker_data['low24h'])
        total_volume = float(ticker_data['vol24h'])
        
        price_change_24h = float(ticker_data['last']) - float(ticker_data['open24h'])
        if len(close_prices) >= 8:
            price_change_7d = current_price - close_prices[-8]
        else:
            price_change_7d = None
        
        sma_7 = np.mean(close_prices[-7:]) if len(close_prices) >= 7 else None
        sma_14 = np.mean(close_prices[-14:]) if len(close_prices) >= 14 else None
        rsi_14 = calculate_rsi(close_prices, period=14) if len(close_prices) >= 15 else None
        
        return {
            'symbol': symbol,
            'current_price': current_price,
            'total_volume': total_volume,
            'price_change_24h': round(price_change_24h, 5),
            'price_change_24h_percentage': round(price_change_24h / current_price * 100, 5),
            'price_change_7d': round(price_change_7d, 5) if price_change_7d else None,
            'price_change_7d_percentage': round(price_change_7d / current_price * 100, 5) if price_change_7d else None,
            'high_24h': high_24h,
            'low_24h': low_24h,
            'sma_7': sma_7,
            'sma_14': sma_14,
            'rsi_14': rsi_14
        }
        
    except Exception as e:
        print(f"Failed to retrieve data: {str(e)}")
        raise e