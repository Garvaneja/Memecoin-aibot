import aiohttp
from config import RETRY_LIMIT
import logging
import asyncio
import time

logger = logging.getLogger(__name__)

async def fetch_new_pools(chain='solana'):
    url = 'wss://api.raydium.io/v2/main/pairs' if chain == 'solana' else 'wss://api.uniswap.org/v1/pools'
    for _ in range(RETRY_LIMIT):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=30) as ws:
                    msg = await ws.receive_json()
                    pools = [pool for pool in msg if pool['created_at'] > time.time() - 5]
                    return [pool['baseMint' if chain == 'solana' else 'token0'] for pool in pools]
        except Exception as e:
            logger.error(f"{chain} WebSocket error: {e}. Retrying...")
            await asyncio.sleep(2 ** _)
    return []