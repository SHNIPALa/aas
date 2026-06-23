import asyncio
import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Update, Message, BusinessConnection
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    BusinessConnectionHandler
)
from telegram.constants import ParseMode
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# КОНФИГ
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
DATA_DIR = "business_bot_data"
os.makedirs(DATA_DIR, exist_ok=True)

class BusinessTrollBot:
    def __init__(self):
        # Основные данные
        self.troll_texts: Dict[str, str] = {}
        self.temp_files: Dict[str, Dict] = {}
        self.deleted_messages: Dict[str, List[Dict]] = {}
        self.edited_messages: Dict[str, List[Dict]] = {}
        
        # Business-чаты (chat_id -> business_connection_id)
        self.business_chats: Dict[str, str] = {}
        
        # Настройки для каждого бизнес-чата
        self.chat_settings: Dict[str, Dict] = {}
        
        # Активные бизнес-подключения
        self.active_connections: Dict[str, BusinessConnection] = {}
        
        # Загрузка данных
        self.load_all_data()
        
        # Запуск очистки
        asyncio.create_task(self.clean_temp_files_loop())

    def load_all_data(self):
        """Загрузка всех данных"""
        files = {
            'troll_texts.json': 'troll_texts',
            'business_chats.json': 'business_chats',
            'chat_settings.json': 'chat_settings'
        }
        
        for filename, attr in files.items():
            filepath = os.path.join(DATA_DIR, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        setattr(self, attr, json.load(f))
                    logger.info(f"Загружено: {filename}")
                except Exception as e:
                    logger.error(f"Ошибка загрузки {filename}: {e}")

    def save_all_data(self):
        """Сохранение всех данных"""
        data = {
            'troll_texts.json': self.troll_texts,
            'business_chats.json': self.business_chats,
            'chat_settings.json': self.chat_settings
        }
        
        for filename, data_attr in data.items():
            filepath = os.path.join(DATA_DIR, filename)
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data_attr, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Ошибка сохранения {filename}: {e}")

    def get_chat_settings(self, chat_id: str) -> Dict:
        """Получить настройки чата"""
        if chat_id not in self.chat_settings:
            self.chat_settings[chat_id] = {
                'auto_forward_deleted': True,
                'auto_forward_edited': True,
                'save_temp_files': True,
                'temp_file_ttl': 3600,
                'notifications': True
            }
        return self.chat_settings[chat_id]

    def is_business_chat(self, chat_id: str) -> bool:
        """Проверка что чат - бизнес"""
        return str(chat_id) in self.business_chats

    async def clean_temp_files_loop(self):
        """Очистка временных файлов"""
        while True:
            current_time = time.time()
            to_delete = []
            
            for file_id, info in self.temp_files.items():
                if current_time > info['expiry_time']:
                    to_delete.append(file_id)
            
            for file_id in to_delete:
                logger.info(f"Удален временный файл: {info['file_name']}")
                del self.temp_files[file_id]
            
            await asyncio.sleep(60)

bot = BusinessTrollBot()

# ========== BUSINESS CONNECTION HANDLERS ==========

async def on_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик подключения/отключения бизнес-чата
    Срабатывает когда юзер с Premium добавляет/удаляет бота в бизнес
    """
    connection: BusinessConnection = update.business_connection
    
    if connection.is_enabled:
        # Бот добавлен в бизнес-чат
        bot.active_connections[connection.id] = connection
        bot.business_chats[str(connection.user_chat_id)] = connection.id
        
        # Дефолтные настройки для нового бизнес-чата
        if str(connection.user_chat_id) not in bot.chat_settings:
            bot.chat_settings[str(connection.user_chat_id)] = {
                'auto_forward_deleted': True,
                'auto_forward_edited': True,
                'save_temp_files': True,
                'temp_file_ttl': 3600,
                'notifications': True
            }
        
        bot.save_all_data()
        
        logger.info(f"✅ Бизнес-подключение: chat_id={connection.user_chat_id}")
        
        # Отправляем приветствие в бизнес-чат
        await context.bot.send_message(
            chat_id=connection.user_chat_id,
            text="""
🎭 *Тролль-Бот активирован в бизнес-чате!*

👑 *Что я умею:*
• Вижу удалённые сообщения
• Вижу изменённые сообщения
• Сохраняю временные файлы
• Автопересылаю всё тебе
• Троллинг по командам

🔥 *Команды:*
/help - все команды
/settings - настройки чата
/troll_add - добавить тролль-текст
/deleted - удалённые сообщения
/edited - изменённые сообщения

⚡️ *Бот уже работает!*
""",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Бот удален из бизнес-чата
        if connection.id in bot.active_connections:
            del bot.active_connections[connection.id]
        
        chat_id_str = str(connection.user_chat_id)
        if chat_id_str in bot.business_chats:
            del bot.business_chats[chat_id_str]
        
        bot.save_all_data()
        logger.info(f"❌ Бизнес-подключение удалено: chat_id={connection.user_chat_id}")

async def on_business_message_deleted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик удаленных сообщений в бизнес-чатах
    Telegram Business API сам сообщает боту об удалении!
    """
    if not update.business_message_deleted:
        return
    
    deleted_info = update.business_message_deleted
    chat_id = str(deleted_info.chat.id)
    
    # Проверяем что это бизнес-чат
    if not bot.is_business_chat(chat_id):
        return
    
    # Сохраняем информацию об удалении
    if chat_id not in bot.deleted_messages:
        bot.deleted_messages[chat_id] = []
    
    # Пытаемся получить сообщение из кэша
    message_data = {
        'message_id': deleted_info.message_id,
        'time': datetime.now().strftime("%H:%M:%S %d.%m.%Y"),
        'chat_id': chat_id,
        'user': 'Unknown',
        'text': '[Сообщение удалено]'
    }
    
    # Если у нас есть кэш сообщений - используем его
    if 'message_cache' in context.bot_data:
        cache = context.bot_data['message_cache']
        cache_key = f"{chat_id}:{deleted_info.message_id}"
        if cache_key in cache:
            message_data['text'] = cache[cache_key]['text']
            message_data['user'] = cache[cache_key]['user']
            del cache[cache_key]
    
    bot.deleted_messages[chat_id].append(message_data)
    
    # Автопересылка если включена
    settings = bot.get_chat_settings(chat_id)
    if settings['auto_forward_deleted']:
        forward_text = (
            f"🗑 *УДАЛЕНО В БИЗНЕС-ЧАТЕ*\n"
            f"👤 {message_data['user']}\n"
            f"💬 {message_data['text'][:500]}\n"
            f"🕐 {message_data['time']}"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=forward_text,
            parse_mode=ParseMode.MARKDOWN
        )

# ========== КОМАНДЫ ДЛЯ БИЗНЕС-ЧАТОВ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Старт"""
    chat_id = str(update.effective_chat.id)
    is_business = bot.is_business_chat(chat_id)
    
    text = f"""
🎭 *Тролль-Бот v3.0*

📌 *Статус:* {'✅ Бизнес-чат' if is_business else '⚠️ Обычный чат'}

🔥 *Функции:*
• Перехват удалённых сообщений
• Перехват изменённых сообщений
• Временные файлы
• Троллинг-система
• Автопересылка всего

💎 *Для бизнес-чатов:* расширенные функции слежки

/help - все команды
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    text = """
🔧 *КОМАНДЫ:*

🎭 *Троллинг:*
/troll_add <имя> <текст>
/troll_list
/troll <имя>
/troll_del <имя>

📝 *Слежка:*
/deleted [кол-во] - удалённые
/edited [кол-во] - изменённые
/clear_logs - очистить

📎 *Файлы:*
/temp_files - список
/temp_time <сек> - TTL

⚙️ *Настройки:*
/settings - всё о чате
/forward_deleted on|off
/forward_edited on|off
/notifications on|off
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ========== ТРОЛЛИНГ ==========

async def troll_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить тролль-текст"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ /troll_add <имя> <текст>")
        return
    
    name = context.args[0]
    text = ' '.join(context.args[1:])
    bot.troll_texts[name] = text
    bot.save_all_data()
    
    await update.message.reply_text(f"✅ Добавлено: {name}")

async def troll_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список тролль-текстов"""
    if not bot.troll_texts:
        await update.message.reply_text("📭 Пусто")
        return
    
    text = "🎭 *Тролль-тексты:*\n\n"
    for name, content in bot.troll_texts.items():
        text += f"• `{name}` - {content[:80]}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def troll_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить тролль-текст"""
    if not context.args:
        await update.message.reply_text("❌ /troll <имя>")
        return
    
    name = context.args[0]
    if name in bot.troll_texts:
        await update.message.reply_text(bot.troll_texts[name])
    else:
        await update.message.reply_text(f"❌ '{name}' не найден")

async def troll_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить тролль-текст"""
    if not context.args:
        await update.message.reply_text("❌ /troll_del <имя>")
        return
    
    name = context.args[0]
    if name in bot.troll_texts:
        del bot.troll_texts[name]
        bot.save_all_data()
        await update.message.reply_text(f"✅ '{name}' удалён")
    else:
        await update.message.reply_text("❌ Не найден")

# ========== ЛОГИ ==========

async def deleted_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалённые сообщения"""
    chat_id = str(update.effective_chat.id)
    
    if chat_id not in bot.deleted_messages or not bot.deleted_messages[chat_id]:
        await update.message.reply_text("📭 Нет удалённых")
        return
    
    limit = int(context.args[0]) if context.args else 5
    messages = bot.deleted_messages[chat_id][-limit:]
    
    text = "🗑 *Удалённые:*\n\n"
    for msg in reversed(messages):
        text += f"⏰ {msg['time']}\n"
        text += f"👤 {msg['user']}\n"
        text += f"💬 {msg['text'][:300]}\n"
        text += "─" * 30 + "\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def edited_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменённые сообщения"""
    chat_id = str(update.effective_chat.id)
    
    if chat_id not in bot.edited_messages or not bot.edited_messages[chat_id]:
        await update.message.reply_text("📭 Нет изменённых")
        return
    
    limit = int(context.args[0]) if context.args else 5
    messages = bot.edited_messages[chat_id][-limit:]
    
    text = "✏️ *Изменённые:*\n\n"
    for msg in reversed(messages):
        text += f"⏰ {msg['time']}\n"
        text += f"👤 {msg['user']}\n"
        text += f"📝 Было: {msg['old_text'][:150]}\n"
        text += f"✏️ Стало: {msg['new_text'][:150]}\n"
        text += "─" * 30 + "\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def clear_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить логи"""
    chat_id = str(update.effective_chat.id)
    bot.deleted_messages[chat_id] = []
    bot.edited_messages[chat_id] = []
    await update.message.reply_text("✅ Очищено")

# ========== ВРЕМЕННЫЕ ФАЙЛЫ ==========

async def temp_files_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список временных файлов"""
    if not bot.temp_files:
        await update.message.reply_text("📭 Нет файлов")
        return
    
    text = "📎 *Временные файлы:*\n\n"
    current_time = time.time()
    
    for file_id, info in bot.temp_files.items():
        remaining = int(info['expiry_time'] - current_time)
        text += f"📄 {info['file_name']}\n"
        text += f"⏳ {remaining} сек\n"
        text += f"🆔 `{file_id[:20]}...`\n\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def temp_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить TTL файлов"""
    if not context.args:
        await update.message.reply_text("❌ /temp_time <секунды>")
        return
    
    try:
        seconds = int(context.args[0])
        chat_id = str(update.effective_chat.id)
        settings = bot.get_chat_settings(chat_id)
        settings['temp_file_ttl'] = seconds
        bot.save_all_data()
        
        await update.message.reply_text(f"✅ TTL: {seconds} сек")
    except ValueError:
        await update.message.reply_text("❌ Нужно число")

# ========== НАСТРОЙКИ ==========

async def forward_deleted_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вкл/выкл пересылку удалённых"""
    if not context.args:
        await update.message.reply_text("❌ /forward_deleted on|off")
        return
    
    chat_id = str(update.effective_chat.id)
    settings = bot.get_chat_settings(chat_id)
    
    cmd = context.args[0].lower()
    if cmd == "on":
        settings['auto_forward_deleted'] = True
        await update.message.reply_text("✅ Пересылка удалённых ВКЛ")
    elif cmd == "off":
        settings['auto_forward_deleted'] = False
        await update.message.reply_text("❌ Пересылка удалённых ВЫКЛ")
    
    bot.save_all_data()

async def forward_edited_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вкл/выкл пересылку изменённых"""
    if not context.args:
        await update.message.reply_text("❌ /forward_edited on|off")
        return
    
    chat_id = str(update.effective_chat.id)
    settings = bot.get_chat_settings(chat_id)
    
    cmd = context.args[0].lower()
    if cmd == "on":
        settings['auto_forward_edited'] = True
        await update.message.reply_text("✅ Пересылка изменённых ВКЛ")
    elif cmd == "off":
        settings['auto_forward_edited'] = False
        await update.message.reply_text("❌ Пересылка изменённых ВЫКЛ")
    
    bot.save_all_data()

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать настройки"""
    chat_id = str(update.effective_chat.id)
    is_business = bot.is_business_chat(chat_id)
    settings = bot.get_chat_settings(chat_id)
    
    text = f"""
⚙️ *НАСТРОЙКИ ЧАТА*

💎 *Статус:* {'✅ Бизнес-чат' if is_business else '⚠️ Обычный чат'}

📡 *Пересылка:*
• Удалённые: {'✅' if settings['auto_forward_deleted'] else '❌'}
• Изменённые: {'✅' if settings['auto_forward_edited'] else '❌'}

📎 *Файлы:*
• Сохранение: {'✅' if settings['save_temp_files'] else '❌'}
• TTL: {settings['temp_file_ttl']} сек

📊 *Статистика:*
• Удалено: {len(bot.deleted_messages.get(chat_id, []))}
• Изменено: {len(bot.edited_messages.get(chat_id, []))}
• Файлов: {len(bot.temp_files)}
• Тролль-текстов: {len(bot.troll_texts)}
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ========== ПЕРЕХВАТ СООБЩЕНИЙ ==========

async def catch_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Перехват ВСЕХ сообщений для кэширования
    Нужно для сохранения удалённых сообщений
    """
    if not update.message:
        return
    
    chat_id = str(update.effective_chat.id)
    message = update.message
    
    # Кэшируем сообщение
    if 'message_cache' not in context.bot_data:
        context.bot_data['message_cache'] = {}
    
    cache_key = f"{chat_id}:{message.message_id}"
    context.bot_data['message_cache'][cache_key] = {
        'text': message.text or message.caption or '[Медиа]',
        'user': message.from_user.full_name if message.from_user else 'Unknown',
        'time': datetime.now().isoformat(),
        'message_id': message.message_id
    }
    
    # Ограничиваем размер кэша
    if len(context.bot_data['message_cache']) > 1000:
        # Удаляем старые записи
        sorted_keys = sorted(context.bot_data['message_cache'].keys())
        for key in sorted_keys[:100]:
            del context.bot_data['message_cache'][key]

async def catch_edited(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перехват изменённых сообщений"""
    if not update.edited_message:
        return
    
    chat_id = str(update.effective_chat.id)
    
    if chat_id not in bot.edited_messages:
        bot.edited_messages[chat_id] = []
    
    # Получаем старый текст из кэша
    old_text = '[Неизвестно]'
    if 'message_cache' in context.bot_data:
        cache_key = f"{chat_id}:{update.edited_message.message_id}"
        if cache_key in context.bot_data['message_cache']:
            old_text = context.bot_data['message_cache'][cache_key]['text']
    
    msg_data = {
        'old_text': old_text,
        'new_text': update.edited_message.text or '[Медиа]',
        'user': update.effective_user.full_name,
        'time': datetime.now().strftime("%H:%M:%S %d.%m.%Y"),
        'message_id': update.edited_message.message_id
    }
    
    bot.edited_messages[chat_id].append(msg_data)
    
    # Автопересылка
    settings = bot.get_chat_settings(chat_id)
    if settings['auto_forward_edited']:
        forward_text = (
            f"✏️ *ИЗМЕНЕНО*\n"
            f"👤 {msg_data['user']}\n"
            f"📝 Было: {old_text[:200]}\n"
            f"✏️ Стало: {msg_data['new_text'][:200]}"
        )
        await update.edited_message.reply_text(forward_text, parse_mode=ParseMode.MARKDOWN)

async def catch_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перехват файлов"""
    if not update.message or not update.message.document:
        return
    
    chat_id = str(update.effective_chat.id)
    settings = bot.get_chat_settings(chat_id)
    
    if not settings['save_temp_files']:
        return
    
    file_id = update.message.document.file_id
    file_name = update.message.document.file_name or 'Без имени'
    
    bot.temp_files[file_id] = {
        'file_name': file_name,
        'expiry_time': time.time() + settings['temp_file_ttl'],
        'added_time': datetime.now().strftime("%H:%M:%S %d.%m.%Y"),
        'chat_id': chat_id,
        'size': update.message.document.file_size
    }
    
    await update.message.reply_text(
        f"📎 *Файл сохранён*\n"
        f"📄 {file_name}\n"
        f"⏰ TTL: {settings['temp_file_ttl']} сек",
        parse_mode=ParseMode.MARKDOWN
    )

# ========== ЗАПУСК ==========

def main():
    """Запуск бота с поддержкой Business API"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Инициализация кэша сообщений
    app.bot_data['message_cache'] = {}
    
    # ====== BUSINESS CONNECTION (САМОЕ ВАЖНОЕ) ======
    app.add_handler(BusinessConnectionHandler(on_business_connection))
    
    # Обработчик удаленных бизнес-сообщений
    app.add_handler(MessageHandler(
        filters.StatusUpdate.DELETED_BUSINESS_MESSAGE,
        on_business_message_deleted
    ))
    
    # ====== КОМАНДЫ ======
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    
    # Троллинг
    app.add_handler(CommandHandler("troll_add", troll_add))
    app.add_handler(CommandHandler("troll_list", troll_list))
    app.add_handler(CommandHandler("troll", troll_send))
    app.add_handler(CommandHandler("troll_del", troll_del))
    
    # Логи
    app.add_handler(CommandHandler("deleted", deleted_log))
    app.add_handler(CommandHandler("edited", edited_log))
    app.add_handler(CommandHandler("clear_logs", clear_logs))
    
    # Файлы
    app.add_handler(CommandHandler("temp_files", temp_files_list))
    app.add_handler(CommandHandler("temp_time", temp_time))
    
    # Настройки
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("forward_deleted", forward_deleted_toggle))
    app.add_handler(CommandHandler("forward_edited", forward_edited_toggle))
    
    # ====== ПЕРЕХВАТЧИКИ ======
    # Кэширование всех сообщений
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.STICKER,
        catch_message
    ))
    
    # Изменённые сообщения
    app.add_handler(MessageHandler(
        filters.UpdateType.EDITED_MESSAGE,
        catch_edited
    ))
    
    # Файлы
    app.add_handler(MessageHandler(
        filters.DOCUMENT,
        catch_files
    ))
    
    print("""
╔══════════════════════════════════════════╗
║   🔥 ТРОЛЛЬ-БОТ ДЛЯ TELEGRAM BUSINESS  ║
║                                          ║
║   📡 Business Connection API активен     ║
║   🗑 Перехват удалённых ВКЛ             ║
║   ✏️ Перехват изменённых ВКЛ            ║
║   📎 Временные файлы ВКЛ                ║
║   🎭 Троллинг-система ВКЛ              ║
║                                          ║
║   💎 Ждём подключения бизнес-чатов...   ║
╚══════════════════════════════════════════╝
    """)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
