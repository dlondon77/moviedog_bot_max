# test_maxgram.py
from maxgram import Bot
from maxgram.keyboards import InlineKeyboard

TOKEN = "YOUR_MAX_TOKEN"  # твой токен

bot = Bot(TOKEN)

# Создаём клавиатуру
main_keyboard = InlineKeyboard([
    [{"text": "🎲 Случайный фильм", "callback": "random"}],
    [{"text": "🔍 Поиск", "callback": "search"}],
    [{"text": "🎉 Премьеры", "callback": "premiers"}],
    [{"text": "🐾 Мнение о фильме", "callback": "opinion"}],
])

@bot.command("start")
def start_command(context):
    context.reply(
        "🐾 Привет! Я КиноИщейка!\n\nВыбери действие:",
        keyboard=main_keyboard
    )

@bot.on("message_callback")
def handle_callback(context):
    payload = context.payload
    
    if payload == "random":
        context.reply_callback("🎲 Ищу случайный фильм...", is_current=True)
        # Здесь будет логика поиска фильма
        context.reply("🎬 Показан случайный фильм (заглушка)")
    
    elif payload == "search":
        context.reply_callback("🔍 Введи название фильма:", is_current=True)
        # Переключаем режим ожидания текста
    
    elif payload == "premiers":
        context.reply_callback("🎉 Ищу премьеры...", is_current=True)
        context.reply("🎬 Список премьер (заглушка)")
    
    elif payload == "opinion":
        context.reply_callback("🐾 Введи ID или название фильма:", is_current=True)
    
    else:
        context.reply_callback(f"Неизвестная команда: {payload}", is_current=True)

@bot.on("message")
def handle_message(context):
    text = context.text
    context.reply(f"Ты написал: {text}\n\nИспользуй /start для меню")

if __name__ == "__main__":
    print("🚀 Бот запущен на maxgram")
    bot.run()
