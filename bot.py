import logging
import requests
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import yt_dlp
import os
import random
from yandex_music import Client
from urllib.parse import urlparse


yam_token = 'YANDEX_MUSIC_TOKEN'
client = Client(yam_token).init()
BOT_TOKEN = 'BOT_TOKEN'
logging.basicConfig(level=logging.INFO)


def init_db():
    with sqlite3.connect("history.db", check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                title TEXT,
                url TEXT,
                pinned INTEGER DEFAULT 0
            )
        ''')
        conn.commit()


init_db()


def add_to_history(user_id, media_type, title, url):
    with sqlite3.connect("history.db", check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO history (user_id, type, title, url) VALUES (?, ?, ?, ?)",
                  (user_id, media_type, title, url))
        conn.commit()

def get_history(user_id):
    with sqlite3.connect("history.db", check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute("SELECT id, title, url, type, pinned FROM history WHERE user_id=? ORDER BY pinned DESC, id DESC LIMIT 10",
                  (user_id,))
        return c.fetchall()

def pin_item(item_id):
    with sqlite3.connect("history.db", check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute("UPDATE history SET pinned=1 WHERE id=?", (item_id,))
        conn.commit()

async def start(update, context):
    #await update.message.reply_text("Привет! Отправь мне ссылку, и я пришлю тебе видео.")
    await update.message.reply_text("Вы подписались на бота! Новые сообщения скоро будут, оставайтесь на связи!")
    await update.message.reply_text("Чтобы отписаться, напишите в этот чат «/stop» или «/unsubscribe».")


async def video(update, context):
    message = update.message or update.callback_query.message
    url = " ".join(context.args).strip()
    #url = update.message.text.strip()
    if "tiktok.com" in url:
        try:
            api_url = f"https://tikwm.com/api/?url={url}"
            response = requests.get(api_url, timeout=15).json()

            if response.get("data") and response["data"].get("play"):
                await message.reply_text("Скачиваю видео")
                video_url = response["data"]["play"]
                title = response["data"]["title"][:20]
                await message.reply_video(video=video_url)
                add_to_history(update.effective_user.id, 'video', title, url)
            else:
                await message.reply_text("Не удалось получить видео. Попробуйте другую ссылку.")

        except Exception as e:
            logging.error(e)
            await message.reply_text("Произошла ошибка при обработке ссылки.")
    elif "youtube.com" in url or "youtu.be" in url:
        ydl_opts = {
            'format': 'mp4',
            'outtmpl': '%(title).10s.%(ext)s',
            'quiet': True
        }
        try:

            await message.reply_text("Скачиваю видео")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info["duration"] > 120:
                    await message.reply_text("Слишком длинное видео(2 минуты максимум)")
                    return
                info = ydl.extract_info(url, download=True)
                
                file_path = ydl.prepare_filename(info)
            await message.reply_video(video=open(file_path, 'rb'))
            add_to_history(update.effective_user.id, 'video', info['title'][:20], url)
            os.remove(file_path)
        except Exception as e:
            logging.error(e)
            await message.reply_text("Произошла ошибка при обработке ссылки.")


async def music(update, context):
    message = update.message or update.callback_query.message
    url = " ".join(context.args).strip()
    if 'music.yandex.ru' in url:
        try:
            await message.reply_text("Скачиваю трек")
            path = urlparse(url).path
            parts = url.split('/')
            track_id = parts[-1].split('?')
            track = client.tracks([track_id[0]])[0]
            best = track.get_download_info()[0]
            download_url = best.get_direct_link()
            r = requests.get(download_url, timeout=30)
            with open(f'{track.title}.mp3', 'wb') as f:
                f.write(r.content)
            track.download_cover(f'{track.title}.png')
            await message.reply_audio(audio=open(f'{track.title}.mp3', 'rb'),
                                             title=track.title, performer=', '.join(track.artists_name()),
                                             thumbnail=open(f'{track.title}.png', 'rb'))
            add_to_history(update.effective_user.id, 'music', track.title[:20], url)
            os.remove(f'{track.title}.mp3')
            os.remove(f'{track.title}.png')

        except Exception as e:
            logging.error(e)
            await message.reply_text("Произошла ошибка при обработке ссылки.")
    else:
        message.reply_text("Я умею скачивать только с Яндекс музыки!")


async def history(update, context):
    data = get_history(update.effective_user.id)

    if not data:
        await update.message.reply_text("История пуста.")
        return

    buttons = []
    for item_id, title, url, media_type, pinned in data:
        callback_data = f"resend|{title}"
        pin_data = f"pin|{item_id}"
        buttons.append([

            InlineKeyboardButton(text=title, callback_data=callback_data),
            InlineKeyboardButton(text="📌", callback_data=pin_data) if pinned else InlineKeyboardButton(text="Закрепить", callback_data=pin_data)
        ])

    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Ваша история:", reply_markup=markup)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.callback_query.message
    query = update.callback_query
    await query.answer()
    data = query.data


    if "resend|" in data:
        kal, title = data.split("|")
        with sqlite3.connect("history.db", check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute("SELECT url, type FROM history WHERE title=?",
                  (title,))
            a = c.fetchone()
            context.args = [a[0]]
            if a[1] == "video":
                await video(update, context)
            else:
                await music(update, context)
    else:
        kal, qid = data.split("|")
        with sqlite3.connect("history.db", check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute("UPDATE history SET pinned = (pinned + 1) % 2 WHERE id=?",
                      (qid,))
            conn.commit()
            c.execute("SELECT pinned, title FROM history WHERE id=?",
                      (qid,))
            a = c.fetchone()
            if a[0] == 0:
                await message.reply_text(f"Открепил {a[1]}")
            else:
                await message.reply_text(f"Закрепил {a[1]}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("video", video))
    app.add_handler(CommandHandler("music", music))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
