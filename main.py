import asyncio
from discovery import fetch_new_pools
from signals import get_sentiment, get_dex_swap_velocity
from risk import check_rug_risk, check_liquidity, get_volume_threshold
from execution import snipe_entry, manage_trade, withdraw_profits, check_capital_loss, emergency_stop, check_btc_crash,check_api_health, send_telegram_alert
from config import SENTIMENT_THRESHOLD
from backtest import run_backtest
import logging
import time
import numpy as np
import ccxt
from config import KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import httpx
import ccxt.async_support as ccxt
from config import POSITION_SIZE_USD, MAX_SLIPPAGE, RETRY_LIMIT, COOLDOWN_SECONDS, WITHDRAW_THRESHOLD, CAPITAL_LOSS_LIMIT, PAPER_TRADING
from config import API_ERROR_THRESHOLD, API_CHECK_WINDOW
# Initialize Kucoin client
kucoin = ccxt.kucoin({
    'apiKey': KUCOIN_API_KEY,
    'secret': KUCOIN_SECRET,
    'password': KUCOIN_PASSPHRASE,
    'enableRateLimit': True
})

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

async def main():
    last_backtest = 0
    while True:
        try:
            if not await check_api_health() or await check_btc_crash() or await check_capital_loss():
                break
            if time.time() - last_backtest > 86400:
                await run_backtest()
                last_backtest = time.time()
            hot_coins = await find_hot_coins()
            for symbol, price, chain in hot_coins:
                entry_price, market_type = await snipe_entry(symbol, price, chain)
                if entry_price:
                    await manage_trade(symbol, entry_price, market_type)
            await withdraw_profits()
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"CRASH: {e}")
            await send_telegram_alert(f"CRASH: {e}")
            await emergency_stop()
            await asyncio.sleep(60)

async def find_hot_coins():
    from config import SENTIMENT_THRESHOLD, MIN_WALLET_SWAPS
    hot_coins = []
    volume_threshold = await get_volume_threshold()
    for chain in ['solana', 'ethereum']:
        pools = await fetch_new_pools(chain)
        logger.info(f"Found {len(pools)} new {chain} pools")
        for token in pools:
            try:
                symbol = f"{token}/USDT"
                ticker = await kucoin.fetch_ticker(symbol)
                ohlcv = await kucoin.fetch_ohlcv(symbol, '1h', limit=24)
                avg_volume = np.mean([candle[5] for candle in ohlcv])
                if ticker['baseVolume'] > volume_threshold * avg_volume and await check_liquidity(symbol):
                    sentiment = await get_sentiment(token)
                    dex_swaps = await get_dex_swap_velocity(token, chain)
                    if sentiment > SENTIMENT_THRESHOLD and dex_swaps and await check_rug_risk(token, chain):
                        hot_coins.append((symbol, ticker['last'], chain))
                        await send_telegram_alert(f"Hot coin detected: {symbol} ({chain})")
                    else:
                        await send_telegram_alert(f"Rejected {symbol}: Sentiment {sentiment:.2f}, Swaps {dex_swaps}, Rug risk {not await check_rug_risk(token, chain)}")
            except Exception as e:
                error_count += 1
                logger.error(f"Error checking {token}: {e}")
                await send_telegram_alert(f"Error checking {token}: {e}")
    return hot_coins

if __name__ == "__main__":
    asyncio.run(main())