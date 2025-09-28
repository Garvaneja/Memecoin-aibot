import ccxt.async_support as ccxt
import pandas as pd
from config import KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE, POSITION_SIZE_USD, MAX_SLIPPAGE, RETRY_LIMIT, COOLDOWN_SECONDS, WITHDRAW_THRESHOLD, CAPITAL_LOSS_LIMIT, PAPER_TRADING
import logging
import asyncio
import time
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, API_ERROR_THRESHOLD, API_CHECK_WINDOW
import telegram
from config import SENTIMENT_THRESHOLD, TARGET_GAIN, TRAILING_STOP, HARD_STOP_LOSS
from risk import check_liquidity
from signals import get_sentiment

kucoin = ccxt.kucoin({
    'apiKey': KUCOIN_API_KEY,
    'secret': KUCOIN_SECRET,
    'password': KUCOIN_PASSPHRASE,
    'enableRateLimit': True
})
telegram_bot = telegram.Bot(TELEGRAM_BOT_TOKEN)
logger = logging.getLogger(__name__)
trade_log = []
error_count = 0
total_requests = 0
last_win_time = 0

async def send_telegram_alert(message):
    global error_count, total_requests
    try:
        total_requests += 1
        await telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except Exception as e:
        error_count += 1
        logger.error(f"Telegram alert error: {e}")

async def withdraw_profits():
    global error_count, total_requests
    try:
        total_requests += 1
        balance = await kucoin.fetch_balance()
        usdt_balance = balance['USDT']['free']
        if usdt_balance >= WITHDRAW_THRESHOLD:
            withdraw_amount = usdt_balance * 0.75
            await kucoin.withdraw('USDT', withdraw_amount, 'your_kraken_usdt_address', {'network': 'SOL'})
            await send_telegram_alert(f"WITHDRAW: Sent {withdraw_amount:.2f} USDT to Kraken")
    except Exception as e:
        error_count += 1
        logger.error(f"Withdraw error: {e}")
        await send_telegram_alert(f"Withdraw error: {e}")

async def check_capital_loss():
    global error_count, total_requests
    try:
        total_requests += 1
        balance = await kucoin.fetch_balance()
        usdt_balance = balance['USDT']['free']
        if usdt_balance < CAPITAL_LOSS_LIMIT:
            await send_telegram_alert(f"Capital loss limit hit: {usdt_balance:.2f} USDT. Stopping bot.")
            await emergency_stop()
            return True
        return False
    except Exception as e:
        error_count += 1
        logger.error(f"Capital check error: {e}")
        return False

async def check_api_health():
    global error_count, total_requests
    error_rate = error_count / total_requests if total_requests > 0 else 0
    if error_rate > API_ERROR_THRESHOLD:
        await send_telegram_alert(f"API error rate high ({error_rate:.2%}). Pausing bot for 5 min.")
        await asyncio.sleep(300)
        error_count = 0
        total_requests = 0
        return False
    return True

def calculate_kelly_position(balance):
    if not trade_log:
        return min(POSITION_SIZE_USD, balance * 0.05)
    df = pd.DataFrame(trade_log)
    win_rate = len(df[df['profit'] > 0]) / len(df)
    avg_win = df[df['profit'] > 0]['profit'].mean() if len(df[df['profit'] > 0]) > 0 else 1
    avg_loss = abs(df[df['profit'] < 0]['profit'].mean()) if len(df[df['profit'] < 0]) > 0 else 1
    kelly_fraction = (win_rate * (avg_win / avg_loss) - (1 - win_rate)) / (avg_win / avg_loss)
    kelly_fraction = max(0, min(kelly_fraction, 0.15))
    return balance * kelly_fraction

async def snipe_entry(symbol, price, chain):
    global last_win_time, error_count, total_requests, trade_log
    if time.time() - last_win_time < COOLDOWN_SECONDS:
        logger.info("Cooldown active, skipping entry")
        return None, None
    for _ in range(RETRY_LIMIT):
        try:
            total_requests += 1
            balance = await kucoin.fetch_balance()
            usdt_balance = balance['USDT']['free']
            position_size_usd = calculate_kelly_position(usdt_balance)
            if usdt_balance < position_size_usd:
                await send_telegram_alert(f"Insufficient funds: {usdt_balance:.2f} USDT")
                return None, None
            current_price = (await kucoin.fetch_ticker(symbol))['last']
            if abs(current_price - price) / price > MAX_SLIPPAGE:
                await send_telegram_alert(f"Slippage too high for {symbol}: {current_price:.2f} vs {price:.2f}")
                return None, None
            position_size = (position_size_usd * 2) / current_price if await check_liquidity(symbol) else position_size_usd / current_price
            market_type = 'futures' if await check_liquidity(symbol) else 'spot'
            if PAPER_TRADING:
                await send_telegram_alert(f"[PAPER] Would snipe {symbol} at {current_price:.2f} ({market_type}, {position_size:.2f} units, ${position_size_usd:.2f})")
                return current_price, market_type
            await kucoin.create_market_buy_order(symbol, position_size, {'leverage': 2} if market_type == 'futures' else {})
            await send_telegram_alert(f"SNIPED {symbol} at {current_price:.2f} on KuCoin ({market_type}, ${position_size_usd:.2f})")
            trade_log.append({'symbol': symbol, 'entry_price': current_price, 'market_type': market_type, 'position_size_usd': position_size_usd, 'timestamp': time.time()})
            return current_price, market_type
        except Exception as e:
            error_count += 1
            logger.error(f"Entry failed: {e}. Retrying...")
            await send_telegram_alert(f"Entry failed for {symbol}: {e}")
            await asyncio.sleep(2 ** _)
    return None, None

async def manage_trade(symbol, entry_price, market_type):
    global last_win_time, error_count, total_requests, trade_log
    start_time = time.time()
    highest_price = entry_price
    position_size_usd = trade_log[-1]['position_size_usd'] if trade_log else POSITION_SIZE_USD
    position_size = (position_size_usd * (2 if market_type == 'futures' else 1)) / entry_price
    sold_half = False
    while True:
        try:
            total_requests += 1
            current_price = (await kucoin.fetch_ticker(symbol))['last']
            profit_pct = (current_price - entry_price) / entry_price
            highest_price = max(highest_price, current_price)
            trailing_stop_price = highest_price * (1 - TRAILING_STOP)
            
            await send_telegram_alert(f"Monitoring {symbol}: Price={current_price:.2f}, Profit={profit_pct*100:.2f}%")
            
            if profit_pct >= 1.0 and not sold_half:
                if PAPER_TRADING:
                    await send_telegram_alert(f"[PAPER] Would sell 50% of {symbol} at {current_price:.2f} (+{profit_pct*100:.2f}%)")
                else:
                    await kucoin.create_market_sell_order(symbol, position_size / 2, {'leverage': 2} if market_type == 'futures' else {})
                    await send_telegram_alert(f"PARTIAL EXIT: Sold 50% of {symbol} at {current_price:.2f} (+{profit_pct*100:.2f}%)")
                sold_half = True
                position_size /= 2
            
            if profit_pct >= TARGET_GAIN or current_price <= trailing_stop_price or profit_pct <= HARD_STOP_LOSS:
                if PAPER_TRADING:
                    await send_telegram_alert(f"[PAPER] Would exit {symbol} at {current_price:.2f} (+{profit_pct*100:.2f}%)")
                else:
                    await kucoin.create_market_sell_order(symbol, position_size, {'leverage': 2} if market_type == 'futures' else {})
                    await send_telegram_alert(f"EXIT: Sold {symbol} at {current_price:.2f} (+{profit_pct*100:.2f}%)")
                profit = profit_pct * position_size_usd * (2 if market_type == 'futures' else 1)
                trade_log.append({'symbol': symbol, 'profit': profit, 'timestamp': time.time()})
                if profit_pct >= 1.0:
                    last_win_time = time.time()
                    await withdraw_profits()
                break
            elif time.time() - start_time > 300:
                if PAPER_TRADING:
                    await send_telegram_alert(f"[PAPER] Would timeout {symbol} at {current_price:.2f}")
                else:
                    await kucoin.create_market_sell_order(symbol, position_size, {'leverage': 2} if market_type == 'futures' else {})
                    await send_telegram_alert(f"TIMEOUT: Sold {symbol} at {current_price:.2f}")
                profit = profit_pct * position_size_usd * (2 if market_type == 'futures' else 1)
                trade_log.append({'symbol': symbol, 'profit': profit, 'timestamp': time.time()})
                break
            await asyncio.sleep(0.1)
        except Exception as e:
            error_count += 1
            logger.error(f"Trade error: {e}")
            await send_telegram_alert(f"Trade error for {symbol}: {e}")
            await asyncio.sleep(1)

async def emergency_stop():
    global error_count, total_requests
    try:
        total_requests += 1
        positions = await kucoin.fetch_open_orders()
        for pos in positions:
            if PAPER_TRADING:
                await send_telegram_alert(f"[PAPER] Would close {pos['symbol']} ({pos['amount']} units)")
            else:
                await kucoin.create_market_sell_order(pos['symbol'], pos['amount'], {'leverage': 2} if pos['type'] == 'futures' else {})
                await send_telegram_alert(f"Closed {pos['symbol']} ({pos['amount']} units)")
        await send_telegram_alert("EMERGENCY STOP: Closed all positions on KuCoin")
    except Exception as e:
        error_count += 1
        logger.error(f"Emergency stop failed: {e}")
        await send_telegram_alert(f"Emergency stop failed: {e}")

async def check_btc_crash():
    global error_count, total_requests
    try:
        total_requests += 1
        ohlcv = await kucoin.fetch_ohlcv('BTC/USDT', '1h', limit=2)
        price_change = (ohlcv[-1][4] - ohlcv[-2][4]) / ohlcv[-2][4]
        if price_change <= -0.05:
            await send_telegram_alert("BTC crashed >5%! Stop trading and check manually.")
            await emergency_stop()
            return True
        return False
    except Exception as e:
        error_count += 1
        logger.error(f"BTC check error: {e}")
        return False
