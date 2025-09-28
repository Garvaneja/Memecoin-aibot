import aiohttp
from config import POSITION_SIZE_USD, RETRY_LIMIT
import logging
import time
import state
import asyncio

logger = logging.getLogger(__name__)

async def check_rug_risk(token, chain='solana', state=None):
    async with state.lock:
        state.total_requests += 1
    try:
        url = f"https://api.solscan.io/token/holders?token={token}" if chain == 'solana' else f"https://api.etherscan.io/api?module=contract&action=getsourcecode&address={token}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
        if chain == 'solana':
            dev_holdings = sum([h['amount'] for h in data['data'] if 'dev' in h['owner'].lower()])
            return dev_holdings < 0.10 * data['total_supply']
        else:
            return 'verified' in data['result'][0]['SourceCode'].lower()
    except Exception as e:
        async with state.lock:
            state.error_count += 1
            state.error_timestamps.append(time.time())
        logger.error(f"{chain} rug check error: {e}. Assuming risky.")
        await state.send_telegram_alert(f"Rug check failed for {token}: {e}")
        return False

async def check_liquidity(symbol, state):
    try:
        async with state.lock:
            state.total_requests += 1
        order_book = await state.kucoin.fetch_order_book(symbol)
        bid_volume = sum([bid[1] for bid in order_book['bids'][:5]])
        ask_volume = sum([ask[1] for ask in order_book['asks'][:5]])
        return bid_volume + ask_volume > POSITION_SIZE_USD * 20
    except Exception as e:
        async with state.lock:
            state.error_count += 1
            state.error_timestamps.append(time.time())
        logger.error(f"Liquidity check error: {e}")
        return False

async def get_volume_threshold():
    try:
        btc_ticker = await state.kucoin.fetch_ticker('BTC/USDT')
        ohlcv = await state.kucoin.fetch_ohlcv('BTC/USDT', '1h', limit=24)
        price_range = max([candle[2] for candle in ohlcv]) - min([candle[3] for candle in ohlcv])
        volatility = price_range / btc_ticker['last']
        return 50 if volatility > 0.05 else 200
    except Exception as e:
        logger.error(f"Volatility error: {e}. Using default 100x")
        return 100