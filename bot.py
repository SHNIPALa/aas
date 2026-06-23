import asyncio
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)

# ========== КОНФИГУРАЦИЯ ==========
# Вставьте свои данные (уже предоставлены)
BOT_TOKEN = "8784364287:AAG2tCL1k6Sb3af4DIEVZtT3myAFcd7zT6o"
ADMIN_ID = 1816361127  # Ваш Telegram ID

# Папки и файлы
FILES_DIR = Path("downloads")
DB_PATH = Path("bot_data.db")
FILES_DIR.mkdir(exist_ok=True)

# Ограничения
MAX_HISTORY = 50
MAX_REPEAT = 10

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ (SQLite) ==========
import aiosqlite

class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db_sync()

    def _init_db_sync(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                text TEXT,
                date TEXT NOT NULL,
                is_edited BOOLEAN DEFAULT 0,
                edit_date TEXT,
                file_id TEXT,
                file_path TEXT,
                file_name TEXT,
                file_size INTEGER,
                mime_type TEXT,
                UNIQUE(chat_id, message_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trolls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pinned (
                chat_id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                pinned_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")

    async def save_message(self, chat_id: int, user_id: int, message):
        """Сохраняет сообщение (текст/файл) в БД и на диск."""
        file_id = file_path = file_name = file_size = mime_type = None
        # Определяем тип файла
        if message.document:
            file_id = message.document.file_id
            file_name = message.document.file_name
            file_size = message.document.file_size
            mime_type = message.document.mime_type
        elif message.photo:
            photo = message.photo[-1]
            file_id = photo.file_id
            file_name = f"photo_{photo.file_unique_id}.jpg"
            file_size = photo.file_size
            mime_type = "image/jpeg"
        elif message.video:
            file_id = message.video.file_id
            file_name = message.video.file_name or "video.mp4"
            file_size = message.video.file_size
            mime_type = message.video.mime_type
        elif message.audio:
            file_id = message.audio.file_id
            file_name = message.audio.file_name
            file_size = message.audio.file_size
            mime_type = message.audio.mime_type
        elif message.voice:
            file_id = message.voice.file_id
            file_name = f"voice_{message.voice.file_unique_id}.ogg"
            file_size = message.voice.file_size
            mime_type = "audio/ogg"
        elif message.video_note:
            file_id = message.video_note.file_id
            file_name = f"video_note_{message.video_note.file_unique_id}.mp4"
            file_size = message.video_note.file_size
            mime_type = "video/mp4"
        elif message.sticker:
            file_id = message.sticker.file_id
            file_name = f"sticker_{message.sticker.file_unique_id}.webp"
            file_size = message.sticker.file_size
            mime_type = "image/webp"

        # Скачиваем файл, если есть
        if file_id and message.chat:
            try:
                chat_dir = FILES_DIR / str(chat_id)
                chat_dir.mkdir(exist_ok=True)
                unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name or 'file'}"
                file_path = chat_dir / unique_name
                new_file = await message.get_file()
                await new_file.download_to_drive(file_path)
                file_path = str(file_path)
                logger.info(f"Сохранён файл: {file_path}")
            except Exception as e:
                logger.error(f"Ошибка скачивания: {e}")
                file_path = None

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO messages
                (chat_id, user_id, message_id, text, date, is_edited, edit_date,
                 file_id, file_path, file_name, file_size, mime_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id, user_id, message.message_id,
                    message.text or message.caption,
                    datetime.now().isoformat(),
                    0, None,
                    file_id, file_path, file_name, file_size, mime_type
                )
            )
            await db.commit()

    async def update_edited_message(self, chat_id: int, message):
        """Обновляет запись при редактировании."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE messages
                SET text = ?, is_edited = 1, edit_date = ?
                WHERE chat_id = ? AND message_id = ?
                """,
                (message.text or message.caption, datetime.now().isoformat(), chat_id, message.message_id)
            )
            await db.commit()

    # ---- Методы для работы с троллями ----
    async def add_troll(self, name: str, text: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO trolls (name, text, created_at) VALUES (?, ?, ?)",
                    (name, text, datetime.now().isoformat())
                )
                await db.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    async def remove_troll(self, name: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM trolls WHERE name = ?", (name,))
            await db.commit()
            return cur.rowcount > 0

    async def get_troll_list(self) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT name, text FROM trolls ORDER BY name")
            return await cur.fetchall()

    async def get_troll_text(self, name: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT text FROM trolls WHERE name = ?", (name,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def get_random_troll(self):
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT name, text FROM trolls ORDER BY RANDOM() LIMIT 1")
            return await cur.fetchone()

    # ---- Закреплённые сообщения ----
    async def set_pinned(self, chat_id: int, message_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO pinned (chat_id, message_id, pinned_at) VALUES (?, ?, ?)",
                (chat_id, message_id, datetime.now().isoformat())
            )
            await db.commit()

    async def get_pinned(self, chat_id: int) -> Optional[int]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT message_id FROM pinned WHERE chat_id = ?", (chat_id,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def clear_pinned(self, chat_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pinned WHERE chat_id = ?", (chat_id,))
            await db.commit()

    # ---- История и статистика ----
    async def get_history(self, chat_id: int, limit: int = 10) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT text, date, user_id, is_edited, edit_date, file_name
                FROM messages
                WHERE chat_id = ?
                ORDER BY date DESC
                LIMIT ?
                """,
                (chat_id, limit)
            )
            return await cur.fetchall()

    async def get_stats(self, chat_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            msg_count = (await db.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,))).fetchone()[0]
            file_count = (await db.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ? AND file_path IS NOT NULL", (chat_id,))).fetchone()[0]
            edited_count = (await db.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_edited = 1", (chat_id,))).fetchone()[0]
            troll_count = (await db.execute("SELECT COUNT(*) FROM trolls")).fetchone()[0]
            return {"messages": msg_count, "files": file_count, "edited": edited_count, "trolls": troll_count}

    async def clear_history(self, chat_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("SELECT file_path FROM messages WHERE chat_id = ? AND file_path IS NOT NULL", (chat_id,))
            paths = [row[0] for row in await cur.fetchall()]
            await db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            await db.commit()
        deleted = 0
        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)
                deleted += 1
            except Exception:
                pass
        chat_dir = FILES_DIR / str(chat_id)
        if chat_dir.exists():
            try:
                chat_dir.rmdir()
            except OSError:
                pass
        return deleted

    async def list_files(self, chat_id: int) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT file_name, file_path FROM messages WHERE chat_id = ? AND file_path IS NOT NULL ORDER BY date",
                (chat_id,)
            )
            return await cur.fetchall()

    async def get_file_info_by_index(self, chat_id: int, index: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT file_path, file_name, file_id, message_id
                FROM messages
                WHERE chat_id = ? AND file_path IS NOT NULL
                ORDER BY date
                """,
                (chat_id,)
            )
            rows = await cur.fetchall()
            if index < 1 or index > len(rows):
                return None
            row = rows[index - 1]
            return {"file_path": row[0], "file_name": row[1], "file_id": row[2], "message_id": row[3]}

db = Database(DB_PATH)


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def reply_and_remember(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
    """Отправляет сообщение и сохраняет его ID для /delete_last."""
    msg = await update.message.reply_text(*args, **kwargs)
    context.user_data["last_bot_message_id"] = msg.message_id
    return msg

async def send_doc_and_remember(update, context, document, filename=None, caption=""):
    msg = await update.message.reply_document(document=document, filename=filename, caption=caption)
    context.user_data["last_bot_message_id"] = msg.message_id
    return msg

# ========== ОБРАБОТЧИКИ КОМАНД ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Бот работает только в личных чатах.")
        return
    await reply_and_remember(
        update, context,
        "👋 Привет! Я бот-архиватор для личных чатов.\n"
        "Я сохраняю все сообщения и файлы, даже если вы их удалите.\n"
        "Отредактированные сообщения я перешлю в чат с пометкой.\n\n"
        "Команды:\n"
        "/help - подробная справка\n"
        "/history [N] - последние N сообщений\n"
        "/stats - статистика\n"
        "/list_files - список сохранённых файлов\n"
        "/get_file <номер> - скачать файл\n"
        "/add_troll <имя> <текст> - добавить тролль-фразу\n"
        "/remove_troll <имя> - удалить тролль\n"
        "/troll_list - список троллей\n"
        "/troll <имя> - отправить тролль-фразу\n"
        "/random_troll - случайный тролль\n"
        "/echo <текст> - повторить\n"
        "/repeat <число> <текст> - повторить N раз\n"
        "/pin (ответ на сообщение) - закрепить\n"
        "/pinned - показать закреплённое\n"
        "/unpin - открепить\n"
        "/delete_last - удалить последнее сообщение бота\n"
        "/clear_history - очистить историю (подтверждение)"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await reply_and_remember(
        update, context,
        "📚 **Подробная справка**\n\n"
        "Бот автоматически сохраняет каждое ваше сообщение (текст, фото, видео, аудио, голос, стикеры).\n"
        "Даже если вы удалите сообщение из чата, его копия останется в базе бота.\n"
        "При редактировании сообщения бот пришлёт обновлённую версию в чат.\n\n"
        "**Управление файлами:**\n"
        "/list_files – показать все сохранённые файлы с номерами\n"
        "/get_file <номер> – получить файл\n\n"
        "**Троллинг:**\n"
        "/add_troll имя текст – сохранить фразу\n"
        "/remove_troll имя – удалить\n"
        "/troll_list – все имена\n"
        "/troll имя – отправить фразу\n"
        "/random_troll – случайная\n\n"
        "**Закреп:**\n"
        "/pin (ответом) – закрепить сообщение\n"
        "/pinned – показать\n"
        "/unpin – снять\n\n"
        "**Другое:**\n"
        "/history [N] – показать последние N сообщений (макс. 50)\n"
        "/stats – статистика по чату\n"
        "/delete_last – удалить последнее сообщение бота\n"
        "/clear_history – очистить всю историю (с подтверждением)"
    )

# ----- История, статистика, файлы -----
async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    chat_id = update.effective_chat.id
    args = context.args
    limit = 10
    if args and args[0].isdigit():
        limit = min(int(args[0]), MAX_HISTORY)
    rows = await db.get_history(chat_id, limit)
    if not rows:
        await reply_and_remember(update, context, "История пуста.")
        return
    lines = []
    for text, date, user_id, is_edited, edit_date, file_name in rows:
        author = "Вы" if user_id != context.bot.id else "Бот"
        display = text[:200] + "..." if text and len(text) > 200 else text
        if not display and file_name:
            display = f"[Файл: {file_name}]"
        elif not display:
            display = "[Сообщение без текста]"
        if is_edited:
            display += " (ред.)"
        lines.append(f"{date[:16]} {author}: {display}")
    await reply_and_remember(update, context, "\n".join(lines))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    stats = await db.get_stats(update.effective_chat.id)
    await reply_and_remember(
        update, context,
        f"📊 **Статистика чата**\n"
        f"Сообщений: {stats['messages']}\n"
        f"Файлов: {stats['files']}\n"
        f"Отредактировано: {stats['edited']}\n"
        f"Троллей: {stats['trolls']}"
    )

async def list_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    files = await db.list_files(update.effective_chat.id)
    if not files:
        await reply_and_remember(update, context, "Файлов нет.")
        return
    lines = [f"{i}. {name or Path(path).name}" for i, (name, path) in enumerate(files, 1)]
    await reply_and_remember(update, context, "📂 **Файлы:**\n" + "\n".join(lines))

async def get_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    args = context.args
    if not args or not args[0].isdigit():
        await reply_and_remember(update, context, "Использование: /get_file <номер>")
        return
    index = int(args[0])
    info = await db.get_file_info_by_index(update.effective_chat.id, index)
    if not info:
        await reply_and_remember(update, context, f"Файл №{index} не найден.")
        return
    try:
        with open(info["file_path"], "rb") as f:
            await send_doc_and_remember(update, context, f, filename=info["file_name"], caption=f"Файл №{index}")
    except FileNotFoundError:
        await reply_and_remember(update, context, "Файл утерян на сервере.")

# ----- Троллинг -----
async def add_troll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    args = context.args
    if len(args) < 2:
        await reply_and_remember(update, context, "Использование: /add_troll <имя> <текст>")
        return
    name, text = args[0], " ".join(args[1:])
    if await db.add_troll(name, text):
        await reply_and_remember(update, context, f"✅ Тролль «{name}» добавлен.")
    else:
        await reply_and_remember(update, context, f"❌ Тролль «{name}» уже существует.")

async def remove_troll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not context.args:
        await reply_and_remember(update, context, "Использование: /remove_troll <имя>")
        return
    name = context.args[0]
    if await db.remove_troll(name):
        await reply_and_remember(update, context, f"✅ Тролль «{name}» удалён.")
    else:
        await reply_and_remember(update, context, f"❌ Тролль «{name}» не найден.")

async def troll_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    trolls = await db.get_troll_list()
    if not trolls:
        await reply_and_remember(update, context, "Список троллей пуст.")
        return
    lines = [f"• {name} — {text[:50]}..." if len(text)>50 else f"• {name} — {text}" for name, text in trolls]
    await reply_and_remember(update, context, "📋 **Тролли:**\n" + "\n".join(lines))

async def troll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not context.args:
        await reply_and_remember(update, context, "Использование: /troll <имя>")
        return
    name = context.args[0]
    text = await db.get_troll_text(name)
    if text is None:
        await reply_and_remember(update, context, f"❌ Тролль «{name}» не найден.")
    else:
        await reply_and_remember(update, context, text)

async def random_troll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    troll = await db.get_random_troll()
    if not troll:
        await reply_and_remember(update, context, "Нет троллей.")
    else:
        name, text = troll
        await reply_and_remember(update, context, f"🎲 **{name}:**\n{text}")

# ----- Прочие команды -----
async def echo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not context.args:
        await reply_and_remember(update, context, "Использование: /echo <текст>")
        return
    await reply_and_remember(update, context, " ".join(context.args))

async def repeat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    args = context.args
    if len(args) < 2 or not args[0].isdigit():
        await reply_and_remember(update, context, "Использование: /repeat <число> <текст>")
        return
    count = int(args[0])
    if count < 1 or count > MAX_REPEAT:
        await reply_and_remember(update, context, f"Число от 1 до {MAX_REPEAT}.")
        return
    text = " ".join(args[1:])
    for _ in range(count):
        await reply_and_remember(update, context, text)

async def delete_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    msg_id = context.user_data.get("last_bot_message_id")
    if not msg_id:
        await reply_and_remember(update, context, "Нет сохранённого сообщения бота.")
        return
    try:
        await context.bot.delete_message(update.effective_chat.id, msg_id)
        context.user_data["last_bot_message_id"] = None
    except Exception as e:
        await reply_and_remember(update, context, f"Не удалось удалить: {e}")

# ----- Закреп -----
async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    reply = update.message.reply_to_message
    if not reply:
        await reply_and_remember(update, context, "Ответьте на сообщение, чтобы закрепить.")
        return
    await db.set_pinned(update.effective_chat.id, reply.message_id)
    await reply_and_remember(update, context, "✅ Закреплено.")

async def pinned_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    msg_id = await db.get_pinned(update.effective_chat.id)
    if not msg_id:
        await reply_and_remember(update, context, "Нет закреплённого сообщения.")
        return
    try:
        await context.bot.copy_message(
            chat_id=update.effective_chat.id,
            from_chat_id=update.effective_chat.id,
            message_id=msg_id
        )
    except Exception as e:
        await reply_and_remember(update, context, f"Не удалось показать закреплённое: {e}")

async def unpin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await db.clear_pinned(update.effective_chat.id)
    await reply_and_remember(update, context, "✅ Закрепление снято.")

# ----- Очистка истории (с подтверждением) -----
async def clear_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    keyboard = [[
        InlineKeyboardButton("✅ Да, удалить всё", callback_data="clear_yes"),
        InlineKeyboardButton("❌ Отмена", callback_data="clear_no"),
    ]]
    await reply_and_remember(
        update, context,
        "⚠️ Удалить всю историю и файлы? Это необратимо!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    if query.data == "clear_yes":
        deleted = await db.clear_history(chat_id)
        await query.edit_message_text(f"✅ История очищена. Удалено файлов: {deleted}.")
    else:
        await query.edit_message_text("Очистка отменена.")

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========
async def save_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет все входящие сообщения (текст, медиа)."""
    if update.effective_chat.type != "private":
        return
    msg = update.effective_message
    if not msg:
        return
    await db.save_message(update.effective_chat.id, update.effective_user.id, msg)

async def handle_edited(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """При редактировании сообщения обновляем БД и пересылаем новую версию."""
    if update.effective_chat.type != "private":
        return
    edited = update.edited_message
    if not edited:
        return
    chat_id = edited.chat_id
    # Обновляем в БД
    await db.update_edited_message(chat_id, edited)
    # Пересылаем в чат с пометкой
    text = edited.text or edited.caption or "[Сообщение без текста]"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✏️ **Отредактировано:**\n{text}",
        reply_to_message_id=edited.message_id
    )

# ========== ЗАПУСК ==========
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("list_files", list_files_command))
    application.add_handler(CommandHandler("get_file", get_file_command))
    application.add_handler(CommandHandler("add_troll", add_troll_command))
    application.add_handler(CommandHandler("remove_troll", remove_troll_command))
    application.add_handler(CommandHandler("troll_list", troll_list_command))
    application.add_handler(CommandHandler("troll", troll_command))
    application.add_handler(CommandHandler("random_troll", random_troll_command))
    application.add_handler(CommandHandler("echo", echo_command))
    application.add_handler(CommandHandler("repeat", repeat_command))
    application.add_handler(CommandHandler("delete_last", delete_last_command))
    application.add_handler(CommandHandler("pin", pin_command))
    application.add_handler(CommandHandler("pinned", pinned_command))
    application.add_handler(CommandHandler("unpin", unpin_command))
    application.add_handler(CommandHandler("clear_history", clear_history_command))
    application.add_handler(CallbackQueryHandler(clear_callback, pattern="^clear_"))

    # Сохранение всех сообщений (кроме команд)
    application.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND,
        save_incoming
    ))
    # Редактирование
    application.add_handler(MessageHandler(
        filters.UpdateType.EDITED_MESSAGE,
        handle_edited
    ))

    logger.info("Бот запущен.")
    application.run_polling()

if __name__ == "__main__":
    main()
