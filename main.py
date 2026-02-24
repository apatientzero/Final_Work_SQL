import telebot
from telebot import types
import psycopg2
import random
import os
import logging
from dotenv import load_dotenv

# .env
load_dotenv()

# --- Config ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')

# Check TOKEN
if not BOT_TOKEN:
    raise ValueError("Не найден токен бота! Проверьте файл .env")

# Init bot
bot = telebot.TeleBot(BOT_TOKEN)


# --- DB ---
def get_db_connection():
    """Creating a connection."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}")
        return None


def init_db():
    """Creating tables and fills."""
    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()

    # 1. Создание таблицы пользователей (формат SQL)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS users
                   (
                       id
                       SERIAL
                       PRIMARY
                       KEY,
                       telegram_id
                       BIGINT
                       UNIQUE
                       NOT
                       NULL,
                       username
                       VARCHAR
                   (
                       255
                   ),
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                       )
                   """)

    # 2. Создание таблицы слов (формат SQL)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS words
                   (
                       id
                       SERIAL
                       PRIMARY
                       KEY,
                       word_ru
                       VARCHAR
                   (
                       255
                   ) NOT NULL,
                       word_en VARCHAR
                   (
                       255
                   ) NOT NULL,
                       is_common BOOLEAN DEFAULT TRUE,
                       owner_id INTEGER REFERENCES users
                   (
                       id
                   ) ON DELETE CASCADE
                       )
                   """)

    # 3. Заполнение общими словами
    cursor.execute("SELECT count(*) FROM words WHERE is_common = TRUE")
    count = cursor.fetchone()[0]

    if count == 0:
        initial_words = [
            ("Мы", "We"), ("Она", "She"), ("Он", "He"), ("Оно", "It"),
            ("Они", "They"), ("Я", "I"), ("Ты", "You"), ("Кот", "Cat"),
            ("Дом", "House"), ("Сон", "Dream")
        ]
        for ru, en in initial_words:
            cursor.execute("INSERT INTO words (word_ru, word_en, is_common) VALUES (%s, %s, TRUE)", (ru, en))
        print("База данных заполнена начальными словами.")

    conn.commit()
    cursor.close()
    conn.close()


def get_or_create_user(telegram_id, username):
    """Checking for the presence of the user in the database, if not, creates."""
    conn = get_db_connection()
    if not conn: return None
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,))
    user = cursor.fetchone()

    if not user:
        cursor.execute("INSERT INTO users (telegram_id, username) VALUES (%s, %s)", (telegram_id, username))
        conn.commit()
        cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cursor.fetchone()

    cursor.close()
    conn.close()
    return user[0]


def get_random_word_for_quiz(user_id):
    """Getting a random word for the quiz."""
    conn = get_db_connection()
    if not conn: return None
    cursor = conn.cursor()

    query = """
            SELECT id, word_ru, word_en
            FROM words
            WHERE is_common = TRUE \
               OR owner_id = %s
            ORDER BY RANDOM() LIMIT 1 \
            """
    cursor.execute(query, (user_id,))
    result = cursor.fetchone()

    cursor.close()
    conn.close()
    return result


def get_wrong_options(correct_word_en, user_id, limit=3):
    """Getting 3 incorrect answers."""
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor()

    query = """
            SELECT word_en
            FROM words
            WHERE word_en != %s \
              AND (is_common = TRUE \
               OR owner_id = %s)
            ORDER BY RANDOM()
                LIMIT %s \
            """
    cursor.execute(query, (correct_word_en, user_id, limit))
    results = cursor.fetchall()

    cursor.close()
    conn.close()
    return [r[0] for r in results]


def add_personal_word(user_id, word_ru, word_en):
    """Adding new word."""
    conn = get_db_connection()
    if not conn: return False
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO words (word_ru, word_en, is_common, owner_id) VALUES (%s, %s, FALSE, %s)",
            (word_ru, word_en, user_id)
        )
        conn.commit()
        success = True
    except Exception as e:
        print(f"Ошибка добавления слова: {e}")
        success = False
    finally:
        cursor.close()
        conn.close()

    return success


def get_user_words(user_id):
    """Getting a list of all the user's personal words."""
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor()

    cursor.execute("SELECT id, word_ru, word_en FROM words WHERE owner_id = %s", (user_id,))
    results = cursor.fetchall()

    cursor.close()
    conn.close()
    return results


def delete_word_by_id(word_id, user_id):
    """Delete a word only if it belongs to the user."""
    conn = get_db_connection()
    if not conn: return False
    cursor = conn.cursor()

    cursor.execute("DELETE FROM words WHERE id = %s AND owner_id = %s", (word_id, user_id))
    deleted_count = cursor.rowcount

    conn.commit()
    cursor.close()
    conn.close()

    return deleted_count > 0


# --- BOT's logic ---

user_states = {}


@bot.message_handler(commands=['start'])
def send_welcome(message):
    get_or_create_user(message.from_user.id, message.from_user.username)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_quiz = types.KeyboardButton("Начать тренировку")
    btn_add = types.KeyboardButton("Добавить слово")
    btn_delete = types.KeyboardButton("Удалить слово")
    markup.add(btn_quiz, btn_add, btn_delete)

    welcome_text = (
        f"Привет, {message.from_user.first_name}! \n"
        "Я бот EnglishCard для изучения английского языка.\n\n"
        "Что ты хочешь сделать?"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Начать тренировку")
def start_quiz(message):
    user_internal_id = get_or_create_user(message.from_user.id, message.from_user.username)
    word_data = get_random_word_for_quiz(user_internal_id)

    if not word_data:
        bot.send_message(message.chat.id, "Пока нет слов для тренировки. Добавьте свои слова!")
        return

    word_id, word_ru, correct_en = word_data

    if message.chat.id not in user_states:
        user_states[message.chat.id] = {}

    user_states[message.chat.id]['current_question'] = {
        'word_id': word_id,
        'correct': correct_en
    }

    wrong_options = get_wrong_options(correct_en, user_internal_id)
    while len(wrong_options) < 3:
        wrong_options.append("FakeWord")

    options = wrong_options + [correct_en]
    random.shuffle(options)

    markup = types.InlineKeyboardMarkup()
    for opt in options:
        markup.add(types.InlineKeyboardButton(opt, callback_data=f"answer_{opt}"))

    bot.send_message(message.chat.id, f"Как переводится слово:\n\n🇷🇺 <b>{word_ru}</b>?", parse_mode='HTML',
                     reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('answer_'))
def check_answer(call):
    selected_answer = call.data.split('_', 1)[1]
    chat_id = call.message.chat.id

    if chat_id not in user_states or 'current_question' not in user_states[chat_id]:
        bot.answer_callback_query(call.id, "Время вышло! Начните заново.")
        return

    correct_answer = user_states[chat_id]['current_question']['correct']

    if selected_answer == correct_answer:
        bot.answer_callback_query(call.id, "Верно!", show_alert=False)
        bot.edit_message_text(f"Отлично! Правильный ответ: <b>{correct_answer}</b>", chat_id, call.message.message_id,
                              parse_mode='HTML')
    else:
        bot.answer_callback_query(call.id, "Неверно", show_alert=False)
        bot.edit_message_text(f"Ошибка. Правильный ответ: <b>{correct_answer}</b>\nПопробуй еще раз!", chat_id,
                              call.message.message_id, parse_mode='HTML')


@bot.message_handler(func=lambda message: message.text == "➕ Добавить слово")
def ask_add_word_ru(message):
    bot.send_message(message.chat.id, "Введите слово на русском языке:")
    user_states[message.chat.id] = {'action': 'adding_ru'}


@bot.message_handler(func=lambda message: message.text == "🗑 Удалить слово")
def show_delete_list(message):
    user_internal_id = get_or_create_user(message.from_user.id, message.from_user.username)
    words = get_user_words(user_internal_id)

    if not words:
        bot.send_message(message.chat.id, "У вас пока нет личных слов для удаления.")
        return

    markup = types.InlineKeyboardMarkup()
    for w_id, w_ru, w_en in words:
        btn_text = f"{w_ru} - {w_en}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"delete_{w_id}"))

    bot.send_message(message.chat.id, "Выберите слово, которое хотите удалить:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
def confirm_delete(call):
    word_id = int(call.data.split('_', 1)[1])
    user_internal_id = get_or_create_user(call.message.chat.id, call.message.from_user.username)

    if delete_word_by_id(word_id, user_internal_id):
        bot.answer_callback_query(call.id, "Слово удалено!", show_alert=False)
        bot.edit_message_text("Слово успешно удалено из вашей базы.", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "Ошибка при удалении.", show_alert=True)


@bot.message_handler(
    func=lambda message: message.chat.id in user_states and user_states[message.chat.id].get('action') == 'adding_ru')
def process_add_ru(message):
    word_ru = message.text
    user_states[message.chat.id]['temp_ru'] = word_ru
    user_states[message.chat.id]['action'] = 'adding_en'
    bot.send_message(message.chat.id, f"Принято: '{word_ru}'. Теперь введите перевод на английский:")


@bot.message_handler(
    func=lambda message: message.chat.id in user_states and user_states[message.chat.id].get('action') == 'adding_en')
def process_add_en(message):
    word_en = message.text
    word_ru = user_states[message.chat.id].get('temp_ru')
    user_internal_id = get_or_create_user(message.from_user.id, message.from_user.username)

    if add_personal_word(user_internal_id, word_ru, word_en):
        bot.send_message(message.chat.id, f"Слово '{word_ru} - {word_en}' успешно добавлено!")
    else:
        bot.send_message(message.chat.id, "Ошибка при сохранении.")

    del user_states[message.chat.id]


# if __name == '__main__'
if __name__ == '__main__':
    print("Инициализация базы данных...")
    init_db()
    print("Запуск бота...")
    telebot.logger.setLevel(logging.ERROR)
    bot.infinity_polling()