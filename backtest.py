import pandas as pd
from config import POSITION_SIZE_USD, TARGET_GAIN, TRAILING_STOP, HARD_STOP_LOSS, SENTIMENT_THRESHOLD
import logging
import time
import asyncio
from signals import get_sentiment, get_dex_swap_velocity
from risk import check_rug_risk, check_liquidity
from discovery import fetch_new_pools
from utils import find_hot_coins

logger = logging.getLogger(__name__)

async def run_backtest(state):
    backtest_log = []
    start_time = time.time() - 86400
    hot_coins = await find_hot_coins(state)
    for symbol, price, chain in hot_coins:
        try:
            entry_price = price
            market_type = 'futures' if await check_liquidity(symbol, state) else 'spot'
            position_size = POSITION_SIZE_USD * (2 if market_type == 'futures' else 1) / entry_price
            ohlcv = await state.kucoin.fetch_ohlcv(symbol, '1m', limit=60)
            highest_price = entry_price
            for candle in ohlcv:
                if candle[0] < start_time:
                    continue
                current_price = candle[4]
                profit_pct = (current_price - entry_price) / entry_price
                highest_price = max(highest_price, current_price)
                trailing_stop_price = highest_price * (1 - TRAILING_STOP)
                if profit_pct >= TARGET_GAIN or current_price <= trailing_stop_price or profit_pct <= HARD_STOP_LOSS:
                    profit = profit_pct * POSITION_SIZE_USD * (2 if market_type == 'futures' else 1)
                    backtest_log.append({'symbol': symbol, 'profit': profit, 'timestamp': candle[0]})
                    break
        except Exception as e:
            logger.error(f"Backtest error for {symbol}: {e}")
    if backtest_log:
        df = pd.DataFrame(backtest_log)
        win_rate = len(df[df['profit'] > 0]) / len(df)
        avg_profit = df['profit'].mean()
        await state.send_telegram_alert(f"Backtest: Win rate {win_rate:.2%}, Avg profit ${avg_profit:.2f}")
        missed_pumps = len([log for log in backtest_log if log['profit'] > 0.5])
        if missed_pumps > 3:
            global SENTIMENT_THRESHOLD
            SENTIMENT_THRESHOLD = max(0.80, SENTIMENT_THRESHOLD - 0.05)
            await state.send_telegram_alert(f"Tuned sentiment threshold to {SENTIMENT_THRESHOLD:.2f}")