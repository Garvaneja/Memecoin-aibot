from twython import Twython
import aiohttp
import numpy as np
import httpx
from config import TWITTER_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RETRY_LIMIT, COOLDOWN_SECONDS, MIN_WALLET_SWAPS
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import logging
import time
import asyncio

nltk.download('vader_lexicon', quiet=True)
sid = SentimentIntensityAnalyzer()
twitter = Twython(TWITTER_API_KEY)
logger = logging.getLogger(__name__)

async def get_dex_swap_velocity(token, chain='solana', state=None):
    async with state.lock:
        state.total_requests += 1
    try:
        url = f"https://api.raydium.io/v2/swaps?token={token}" if chain == 'solana' else f"https://api.uniswap.org/v3/swaps?token={token}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                swaps = await resp.json()
                swaps = swaps['swaps']
        unique_wallets = len(set(swap['wallet'] for swap in swaps if swap['timestamp'] > time.time() - 60))
        logger.info(f"{chain} swap velocity for {token}: {unique_wallets} wallets")
        return unique_wallets >= MIN_WALLET_SWAPS
    except Exception as e:
        async with state.lock:
            state.error_count += 1
            state.error_timestamps.append(time.time())
        logger.error(f"DEX swap error: {e}")
        await state.send_telegram_alert(f"DEX swap error for {token}: {e}")
        return False

async def get_sentiment(symbol, state=None):
    async with state.lock:
        if time.time() - state.last_win_time < COOLDOWN_SECONDS:
            logger.info("Cooldown active, skipping sentiment")
            return 0
    sentiment = 0
    for _ in range(RETRY_LIMIT):
        try:
            tweets = twitter.search(q=f"${symbol}", count=5)
            if len(tweets['statuses']) >= 5:
                scores = [sid.polarity_scores(tweet['text'])['compound'] for tweet in tweets['statuses']]
                sentiment += np.mean(scores) * 0.7 if scores else 0
                logger.info(f"Twitter sentiment for {symbol}: {sentiment:.2f}")
                break
            else:
                await state.send_telegram_alert(f"False positive? Low tweets for {symbol}: {len(tweets['statuses'])}")
                await asyncio.sleep(60)  # Twitter rate limit
        except Exception as e:
            async with state.lock:
                state.error_count += 1
                state.error_timestamps.append(time.time())
            logger.error(f"Twitter error: {e}. Retrying...")
            await asyncio.sleep(2 ** _)
    for _ in range(RETRY_LIMIT):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                    params={"offset": -1}
                )
                updates = response.json().get('result', [])
                messages = [msg['message']['text'] for msg in updates if 'message' in msg and f"${symbol}" in msg['message']['text'].lower()]
                if messages:
                    scores = [sid.polarity_scores(msg)['compound'] for msg in messages]
                    sentiment += np.mean(scores) * 0.3 if scores else 0
                    logger.info(f"Telegram sentiment for {symbol}: {sentiment:.2f}")
                    break
                else:
                    await state.send_telegram_alert(f"False positive? No Telegram hype for {symbol}")
        except Exception as e:
            async with state.lock:
                state.error_count += 1
                state.error_timestamps.append(time.time())
            logger.error(f"Telegram error: {e}. Retrying...")
            await asyncio.sleep(2 ** _)
    return sentiment