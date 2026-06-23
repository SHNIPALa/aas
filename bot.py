import asyncio, os, random, time
from datetime import datetime
import aiofiles, aiosqlite
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

# ТВОИ ДАННЫЕ
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
BOT_TOKEN = "8784364287:AAG2tCL1k6Sb3af4DIEVZtT3myAFcd7zT6o"
ADMIN_ID = 1816361127

TEMP_DIR = "temp_storage"
MEMES_DIR = "memes"
DB_PATH = "ryzen_data.db"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(MEMES_DIR, exist_ok=True)

app = Client("ryzenbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER, chat_id INTEGER,
            user_id INTEGER, username TEXT, text TEXT, media_type TEXT,
            file_path TEXT, timestamp REAL)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS edited (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, message_id INTEGER,
            old_text TEXT, new_text TEXT, timestamp REAL)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS stalker (
            user_id INTEGER PRIMARY KEY, username TEXT, first_seen REAL,
            last_seen REAL, times INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS troll_commands (
            command TEXT PRIMARY KEY, text TEXT, added_by INTEGER, timestamp REAL)''')
        await db.commit()

def split_text_parts(text: str, min_parts=2, max_parts=3):
    if not text: return [""]
    length = len(text)
    target_len = max(1, length // random.randint(min_parts, max_parts))
    parts = []; start = 0
    while start < length:
        end = min(start + target_len, length)
        if end < length:
            while end > start and text[end] != ' ': end -= 1
            if end == start: end = start + target_len
        parts.append(text[start:end].strip())
        start = end
        while start < length and text[start] == ' ': start += 1
    while len(parts) > max_parts:
        parts[-2] += ' ' + parts[-1]; parts.pop()
    return parts if parts else [text]

# 1. Сохранение всех входящих (только ЛС!)
@app.on_message(filters.private & ~filters.bot)
async def save_message(client, message: Message):
    print(f"[LOG] Сообщение от {message.from_user.first_name}: {message.text}")  # <-- проверка
    text = message.text or message.caption or ""
    media_type = None; file_path = None
    if message.media:
        media_type = str(message.media).split('.')[-1]
        fname = f"{int(time.time())}_{message.from_user.id}.{media_type}"
        file_path = os.path.join(TEMP_DIR, fname)
        await message.download(file_name=file_path)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (message_id, chat_id, user_id, username, text, media_type, file_path, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (message.id, message.chat.id, message.from_user.id,
             message.from_user.username, text, media_type, file_path, time.time()))
        await db.commit()

# 2. Удалённые – мгновенно
@app.on_deleted_messages()
async def on_delete(client, messages):
    for msg in messages:
        if not msg.chat or msg.chat.type != "private": continue
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id, username, text, media_type, file_path FROM messages "
                "WHERE chat_id=? AND message_id=? ORDER BY timestamp DESC LIMIT 1",
                (msg.chat.id, msg.id))
            row = await cur.fetchone()
        if not row: continue
        user_id, username, text, media_type, file_path = row
        if user_id == (await app.get_me()).id: continue
        who = username or f"ID{user_id}"
        if text:
            await app.send_message(msg.chat.id, f"🗑️ Удалено у {who}:\n{text[:4000]}")
        elif file_path and os.path.exists(file_path):
            try:
                await app.send_document(msg.chat.id, file_path, caption=f"🗑️ Удалённый файл от {who}")
            except:
                await app.send_message(msg.chat.id, f"🗑️ Удалён медиафайл от {who} (не удалось переслать)")

# 3. Изменённые – мгновенно
@app.on_edited_message(filters.private & ~filters.bot)
async def on_edit(client, message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT text FROM messages WHERE chat_id=? AND message_id=?", (message.chat.id, message.id))
        old_row = await cur.fetchone()
        old_text = old_row[0] if old_row else "неизвестно"
        await db.execute("UPDATE messages SET text=? WHERE chat_id=? AND message_id=?", (message.text or "", message.chat.id, message.id))
        await db.execute("INSERT INTO edited (chat_id, message_id, old_text, new_text, timestamp) VALUES (?,?,?,?,?)",
                         (message.chat.id, message.id, old_text, message.text or "", time.time()))
        await db.commit()
    who = message.from_user.first_name
    await message.reply(f"✏️ Изменено ({who}):\n❌ {old_text[:500]}\n✅ {message.text[:500]}")

# 4. Кастомные тролль-команды
@app.on_message(filters.command("addtroll"))
async def add_troll(client, message: Message):
    if len(message.command) < 2: return await message.reply("Формат: `/addtroll команда | текст`")
    full = message.text.split(maxsplit=1)[1]
    if '|' not in full: return await message.reply("Используй `|`. Пример: `/addtroll прикол | Ты смешной`")
    cmd, text = full.split('|', 1)
    cmd = cmd.strip().lower(); text = text.strip()
    if not cmd or not text: return await message.reply("Команда и текст не могут быть пустыми")
    if not cmd.startswith('/'): cmd = '/' + cmd
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO troll_commands (command, text, added_by, timestamp) VALUES (?,?,?,?)",
                         (cmd, text, message.from_user.id, time.time()))
        await db.commit()
    await message.reply(f"✅ Команда {cmd} сохранена. Печатается частями.")

@app.on_message(filters.private & filters.command & ~filters.regex(
    r"^/(addtroll|start|troll|spam|stalk|stalkers|fake|purge|files|meme|deleted|dump|status|help)$"))
async def run_custom_troll(client, message: Message):
    cmd = message.command[0]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT text FROM troll_commands WHERE command=?", (cmd,))
        row = await cur.fetchone()
    if not row: return
    parts = split_text_parts(row[0])
    for i, part in enumerate(parts):
        try:
            await message.reply(part)
            if i < len(parts) - 1: await asyncio.sleep(1.0)
        except FloodWait as e: await asyncio.sleep(e.value)

# 5. Обычный троллинг
TROLL_PHRASES = [
    "О, {name}, ты снова здесь! Думал спрятаться? 🤡",
    "Боже, {name}, от твоих сообщений у меня процессор плавится 🔥",
    "{name}, твоя мамка знает, что ты такой скуф? 💀",
    "Твой IQ явно ниже комнатной температуры 🥶",
    "Даже нейросетке стыдно за твой запрос",
    "Иди обновись до заводских настроек, железяка"
]
@app.on_message(filters.command("troll"))
async def troll(client, message):
    name = message.from_user.first_name
    await message.reply(random.choice(TROLL_PHRASES).format(name=name))

@app.on_message(filters.command("spam"))
async def spam(client, message):
    try:
        count = int(message.command[1])
        text = " ".join(message.command[2:]) if len(message.command) > 2 else "СПАМ!"
        for i in range(min(count, 100)):
            await message.reply(f"{text} [{i+1}/{count}]")
            await asyncio.sleep(0.5)
    except: await message.reply("Формат: /spam <число> <текст>")

# 6. Слежка
@app.on_message(filters.command("stalk"))
async def stalk(client, message):
    if not message.reply_to_message: return await message.reply("Ответь на сообщение юзера")
    u = message.reply_to_message.from_user
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO stalker (user_id, username, first_seen, last_seen, times) VALUES (?,?,?,?,COALESCE((SELECT times FROM stalker WHERE user_id=?),0)+1)",
            (u.id, u.username, time.time(), time.time(), u.id))
        await db.commit()
    await message.reply(f"👁️ Слежу за {u.first_name}")

@app.on_message(filters.command("stalkers"))
async def stalkers_list(client, message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username, last_seen, times FROM stalker")
        rows = await cur.fetchall()
    if rows:
        txt = "👥 Жертвы слежки:\n" + "\n".join(f"• {r[0]} — {r[2]} раз(а), последний {datetime.fromtimestamp(r[1]).strftime('%H:%M')}" for r in rows)
    else: txt = "Слежки нет."
    await message.reply(txt)

# 7. Фейки и purge
@app.on_message(filters.command("fake"))
async def fake(client, message):
    if not message.reply_to_message: return await message.reply("Ответь на сообщение для цитирования")
    target = message.reply_to_message
    fake_text = " ".join(message.command[1:]) if len(message.command) > 1 else "Привет, я лох"
    await client.send_message(message.chat.id, fake_text, reply_to_message_id=target.id)
    await message.delete()

@app.on_message(filters.command("purge"))
async def purge(client, message):
    if message.from_user.id != ADMIN_ID: return
    count = int(message.command[1]) if len(message.command) > 1 else 100
    async for msg in client.get_chat_history(message.chat.id, limit=count):
        if msg.from_user and msg.from_user.is_self:
            await msg.delete()
            await asyncio.sleep(0.5)
    await message.reply(f"🗑️ Удалено до {count} моих сообщений")

# 8. Файлы и мемы
@app.on_message(filters.command("files"))
async def files_list(client, message):
    files = os.listdir(TEMP_DIR)
    if files: await message.reply("📂 Файлы:\n" + "\n".join(f"• {f}" for f in files))
    else: await message.reply("Нет файлов.")

@app.on_message(filters.command("meme"))
async def meme(client, message):
    memes = os.listdir(MEMES_DIR)
    if not memes: return await message.reply("Папка memes пуста.")
    await message.reply_photo(os.path.join(MEMES_DIR, random.choice(memes)))

# 9. Дамп чата
@app.on_message(filters.command("dump"))
async def dump_chat(client, message):
    dump_path = f"dump_{message.chat.id}_{int(time.time())}.txt"
    async with aiofiles.open(dump_path, "w", encoding="utf-8") as f:
        async for msg in client.get_chat_history(message.chat.id, limit=1000):
            line = f"[{msg.date}] {msg.from_user.first_name if msg.from_user else '?'}: {msg.text or msg.caption or '<media>'}\n"
            await f.write(line)
    await message.reply_document(dump_path)
    os.remove(dump_path)

# 10. История удалённых
@app.on_message(filters.command("deleted"))
async def show_deleted(client, message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username, text, media_type, timestamp FROM messages WHERE chat_id=? ORDER BY timestamp DESC LIMIT 10", (message.chat.id,))
        rows = await cur.fetchall()
    if rows:
        txt = "📜 Последние сообщения (включая удалённые):\n"
        for r in rows:
            content = r[1][:100] if r[2] == "text" else f"[{r[2]}]"
            txt += f"• {r[0]}: {content} ({datetime.fromtimestamp(r[3]).strftime('%H:%M')})\n"
        await message.reply(txt)
    else: await message.reply("Нет записей.")

# 11. Статус и помощь
@app.on_message(filters.command("status"))
async def status(client, message):
    async with aiosqlite.connect(DB_PATH) as db:
        c1 = await db.execute("SELECT COUNT(*) FROM messages"); msg_cnt = (await c1.fetchone())[0]
        c2 = await db.execute("SELECT COUNT(*) FROM edited"); edit_cnt = (await c2.fetchone())[0]
        c3 = await db.execute("SELECT COUNT(*) FROM troll_commands"); troll_cnt = (await c3.fetchone())[0]
    files = len(os.listdir(TEMP_DIR)); memes = len(os.listdir(MEMES_DIR))
    await message.reply(f"🤖 **RyzenBot**\n📨 Сохранено: {msg_cnt}\n✏️ Правок: {edit_cnt}\n📁 Файлов: {files}\n🖼️ Мемов: {memes}\n🃏 Тролль-команд: {troll_cnt}")

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply("""**♨️ RyzenBot**
Удалённые/изменённые приходят мгновенно!
/addtroll /команда | текст – добавить тролль-команду (печатает по частям)
/troll – случайный троллинг
/spam N текст – спам
/stalk – слежка (ответ на сообщение)
/stalkers – список отслеживаемых
/fake текст – фейк с цитированием
/purge N – удалить свои сообщения
/files – временные файлы
/meme – случайный мем
/deleted – история сообщений
/dump – выгрузить чат
/status – состояние""")

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply("♨️ RyzenBot активирован. Все удалённые/изменённые сообщения будут показаны. /help")

async def main():
    await init_db()
    await app.start()
    print("🤖 RyzenBot запущен и слушает ЛС...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    app.run(main())
