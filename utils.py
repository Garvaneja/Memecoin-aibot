import numpy as np
from discovery import fetch_new_pools
from signals import get_sentiment, get_dex_swap_velocity
from risk import check_rug_risk, check_liquidity,get_volume_threshold
from config import SENTIMENT_THRESHOLD, MIN_WALLET_SWAPS
import logging

logger = logging.getLogger(__name__)

async def find_hot_coins(state):
    hot_coins = []
    volume_threshold = await get_volume_threshold(state)
    for chain in ['solana', 'ethereum']:
        pools = await fetch_new_pools(chain)
        logger.info(f"Found {len(pools)} new {chain} pools")
        for token in pools:
            try:
                async with state.lock:
                    state.total_requests += 1
                symbol = f"{token}/USDT"
                ticker = await state.kucoin.fetch_ticker(symbol)
                ohlcv = await state.kucoin.fetch_ohlcv(symbol, '1h', limit=24)
                avg_volume = np.mean([candle[5] for candle in ohlcv])
                if ticker['baseVolume'] > volume_threshold * avg_volume and await check_liquidity(symbol, state):
                    sentiment = await get_sentiment(token, state)
                    dex_swaps = await get_dex_swap_velocity(token, chain, state)
                    if sentiment > SENTIMENT_THRESHOLD and dex_swaps and await check_rug_risk(token, chain, state):
                        hot_coins.append((symbol, ticker['last'], chain))
                        await state.send_telegram_alert(f"Hot coin detected: {symbol} ({chain})")
                    else:
                        await state.send_telegram_alert(f"Rejected {symbol}: Sentiment {sentiment:.2f}, Swaps {dex_swaps}, Rug risk {not await check_rug_risk(token, chain, state)}")
            except Exception as e:
                async with state.lock:
                    state.error_count += 1
                logger.error(f"Error checking {token}: {e}", exc_info=True)
                await state.send_telegram_alert(f"Error checking {token}: {e}")
    return hot_coins