import ccxt
import telebot
import threading
import time
import os
import pandas as pd
import ta
import requests
from flask import Flask, request
from dotenv import load_dotenv

# ==== Завантаження змінних середовища ====
load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NEWSAPI_URL = "https://newsapi.org/v2/everything"

exchange = ccxt.kucoin({'options': {'defaultType': 'spot'}})
bot = telebot.TeleBot(bot_token, threaded=False)

# Очистка і оновлення команд
bot.set_my_commands([])
bot.set_my_commands([
    telebot.types.BotCommand("status", "Перевірити статус бота")
])

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот працює!"

@app.route(f"/{bot_token}", methods=["POST"])
def webhook():
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK", 200

def load_symbols_from_file(filename="symbols.txt"):
    with open(filename, "r") as f:
        return [line.strip() for line in f if line.strip()]

symbols = load_symbols_from_file()

def check_news_for_symbol(symbol):
    if not NEWSAPI_KEY:
        print("⚠️ NEWSAPI_KEY не встановлено")
        return []

    params = {
        "q": symbol.replace("/", ""),
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "apiKey": NEWSAPI_KEY
    }

    try:
        response = requests.get(NEWSAPI_URL, params=params, timeout=10)
        response.raise_for_status()
        articles = response.json().get("articles", [])

        keywords = ['crash', 'dump', 'pump', 'hack', 'regulation', 'ban', 'lawsuit', 'scam', 'partnership']
        found_keywords = set()

        for article in articles:
            title = article.get("title", "").lower()
            description = article.get("description", "").lower()
            for kw in keywords:
                if kw in title or kw in description:
                    found_keywords.add(kw)

        return list(found_keywords)

    except Exception as e:
        print(f"❌ Помилка при отриманні новин для {symbol}: {e}")
        return []

@bot.message_handler(commands=['status'])
def status(message):
    bot.send_message(message.chat.id, "✅ Бот активний та працює без помилок.")

def get_signal(symbol):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=200)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        avg_volume = df['volume'].iloc[-10:].mean()
        if avg_volume < 10000:
            return None, None, None, None, None

        df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
        df['ema200'] = ta.trend.ema_indicator(df['close'], window=200)
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()

        last = df.iloc[-1]
        change = (last['close'] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100

        if change >= 2.0 and last['ema50'] > last['ema200'] and last['rsi'] > 50 and last['macd'] > last['macd_signal']:
            tp = round(last['close'] * 1.05, 6)
            sl = round(last['close'] * 0.98, 6)
            msg = f"📈 LONG Signal\n📊 {symbol}\n📅 Вхід: ${last['close']:.6f}\n🌟 TP: ${tp}\n📛 SL: ${sl}"
            return "LONG", msg, last['close'], tp, sl

        elif change <= -5.0 and last['ema50'] < last['ema200'] and last['rsi'] < 50 and last['macd'] < last['macd_signal']:
            tp = round(last['close'] * 0.95, 6)
            sl = round(last['close'] * 1.02, 6)
            msg = f"📉 SHORT Signal\n📊 {symbol}\n📅 Вхід: ${last['close']:.6f}\n🌟 TP: ${tp}\n📛 SL: ${sl}"
            return "SHORT", msg, last['close'], tp, sl

        return None, None, None, None, None

    except Exception as e:
        print(f"❌ Помилка при аналізі {symbol}: {e}")
        return None, None, None, None, None

def generate_strategy_with_data(symbol, direction):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
        df['ema200'] = ta.trend.ema_indicator(df['close'], window=200)
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        bb = ta.volatility.BollingerBands(df['close'])
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()

        last = df.iloc[-1]

        prompt = (
            f"Аналіз {symbol} для сигналу {direction}.\n"
            f"Ціна: {last['close']:.6f}, EMA50: {last['ema50']:.6f}, EMA200: {last['ema200']:.6f}\n"
            f"RSI: {last['rsi']:.2f}, MACD: {last['macd']:.6f}, MACD Signal: {last['macd_signal']:.6f}\n"
            f"BB Верхня: {last['bb_upper']:.6f}, Нижня: {last['bb_lower']:.6f}, ATR: {last['atr']:.6f}\n"
            f"Volume: {last['volume']:.2f}.\n"
            "На основі цих даних сформуй коротку торгову стратегію (до 3 речень)."
        )

        headers = {
            "Authorization": f"Bearer {openrouter_api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": "mistralai/mistral-7b-instruct:free",
            "messages": [{"role": "user", "content": prompt}]
        }

        res = requests.post("https://openrouter.ai/api/v1/chat/completions", json=data, headers=headers)
        res.raise_for_status()
        return res.json()['choices'][0]['message']['content']

    except Exception as e:
        print(f"❌ Помилка при генерації стратегії: {e}")
        return "⚠️ Не вдалося отримати стратегію від ШІ."

def send_signals_loop():
    while True:
        print(f"🔎 Перевірка сигналів для {len(symbols)} монет...")
        for symbol in symbols:
            direction, signal_msg, entry, tp, sl = get_signal(symbol)
            if signal_msg:
                news_keywords = check_news_for_symbol(symbol)
                warning = f"\n\n⚠️ Попередження: знайдено новини з ключовими словами: {', '.join(news_keywords)}" if news_keywords else ""
                strategy = generate_strategy_with_data(symbol, direction)
                full_msg = f"{signal_msg}{warning}\n\n📊 Стратегія ШІ:\n{strategy}"
                try:
                    bot.send_message(chat_id, full_msg)
                except Exception as e:
                    print(f"❌ Помилка при надсиланні повідомлення: {e}")
        print("⏳ Очікування 15 хвилин...\n")
        time.sleep(15 * 60)

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    external_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if not external_hostname:
        print("❌ Помилка: не знайдено RENDER_EXTERNAL_HOSTNAME")
        exit(1)

    webhook_url = f"https://{external_hostname}/{bot_token}"
    bot.remove_webhook()
    success = bot.set_webhook(url=webhook_url)
    print("🔗 Webhook встановлено:", success)

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    signals_thread = threading.Thread(target=send_signals_loop, daemon=True)
    signals_thread.start()
