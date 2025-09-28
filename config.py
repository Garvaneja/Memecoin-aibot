from dotenv import load_dotenv
import os

load_dotenv()
# Config
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY') or 'missing_key'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or 'missing_token'
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID') or 'missing_chat_id'
KUCOIN_API_KEY = os.getenv('KUCOIN_API_KEY') or 'missing_key'
KUCOIN_SECRET = os.getenv('KUCOIN_SECRET') or 'missing_secret'
KUCOIN_PASSPHRASE = os.getenv('KUCOIN_PASSPHRASE') or 'missing_passphrase'
KRAKEN_WITHDRAW_ADDRESS = os.getenv('KRAKEN_WITHDRAW_ADDRESS') or 'missing_address'
SENTIMENT_THRESHOLD = 0.85
TARGET_GAIN = 0.50
TRAILING_STOP = 0.10
HARD_STOP_LOSS = -0.30
POSITION_SIZE_USD = 10  # $10 for test, $50 for full
MAX_SLIPPAGE = 0.03
RETRY_LIMIT = 3
COOLDOWN_SECONDS = 300  # 5 minutes
VOLATILITY_THRESHOLD = 0.05  # BTC price range for micro-cooldown
WITHDRAW_THRESHOLD = 2000
CAPITAL_LOSS_LIMIT = 282  # 50% of $564 USD
PAPER_TRADING = True
MIN_WALLET_SWAPS = 50
API_ERROR_THRESHOLD = 0.05
API_CHECK_WINDOW = 120