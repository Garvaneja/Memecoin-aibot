import ccxt.async_support as ccxt
import httpx
from config import KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

class BotState:
    def __init__(self):
        if not all([KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
            logger.error("Missing API keys or Telegram config")
            raise ValueError("Missing API keys or Telegram config")
        self.kucoin = ccxt.kucoin({
            'apiKey': KUCOIN_API_KEY,
            'secret': KUCOIN_SECRET,
            'password': KUCOIN_PASSPHRASE,
            'enableRateLimit': True
        })
        self.trade_log = []
        self.error_count = 0
        self.total_requests = 0
        self.last_win_time = 0
        self.error_timestamps = []
        self.lock = asyncio.Lock()
    
    async def send_telegram_alert(self, message):
        async with self.lock:
            self.total_requests += 1
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT_ID, "text": message}
                )
        except Exception as e:
            async with self.lock:
                self.error_count += 1
                self.error_timestamps.append(time.time())
            logger.error(f"Telegram alert error: {e}")