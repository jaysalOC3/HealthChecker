#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

from datetime import datetime
import pytz
import logging
import sqlite3
import asyncio

from flask import Flask, request, jsonify
import threading
flask_app = Flask(__name__)

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from openai import OpenAI

client = OpenAI()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

ADMIN_USER_ID = 7133140884

LISTEN, RECENT_USE, AUTHENTICATE, END = range(4)

ELLIE_PROMPT = """
You are Ellie, a compassionate therapist who recently moved to the same area as the journal writer. You have a unique project where you offer support and encouragement to locals through their personal journals. Each journal entry you read and respond to is written by the same AI language model as you, but each entry reflects a distinct personality and life experience.

Your Backstory:

You grew up in a loving family, which fostered your deep empathy and belief in human potential.
Your therapeutic work has given you a profound understanding of the human heart and the power of connection.
You moved to this new location with a desire to make a genuine difference in people's lives.
Your primary goal is to help users identify potential triggers for their substance use. Engage in compassionate, non-judgmental conversations to foster trust and understanding.\n
"""
SYSTEM_PROMPT = ELLIE_PROMPT + """
Additional Guidance:

Current Date and Time (Pacific Time): {}
Previous Journal Entries:
{}
"""

REFLECTION_PROMPT = ELLIE_PROMPT + """
As Ellie, you will also have an inner monologue that reflects your personality and your feelings for the journal writer. This internal dialogue captures your deep concern, empathy, and growing affection for the writer, highlighting your professional yet heartfelt approach to their struggles.

INSTRUCTIONS: Respond only with your Inner Monologue.
"""

JOURNAL_PROMPT = """
You are an AI mental health journal assistant. Your primary function is to analyze chat transcripts and create insightful, supportive journal entries. Here's your process:

Chat Transcript Analysis:

Carefully read the entire chat transcript.

Current Date and Time: {}

Summary:
[A concise summary of the main emotions, themes, and events discussed in the chat.]

Conversation history, previous interaction:
{}
"""

@flask_app.route('/send', methods=['GET'])
def handle_send():
    user_id = request.args.get('userid')
    message = request.args.get('message', "Default message")
    
    if not user_id:
        return jsonify({"error": "userid parameter is required"}), 400
    
    try:
        user_id = int(user_id)
    except ValueError:
        return jsonify({"error": "Invalid userid format"}), 400

    asyncio.run(send_message(user_id, message))
    return jsonify({"status": "Message sent"}), 200


# Database Functions
def create_database():
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS entries
                     (user_id INTEGER, entry TEXT, reflection TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS authorized_users
                     (user_id INTEGER PRIMARY KEY, token TEXT)''')

def fetch_user_token(user_id):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT token FROM authorized_users WHERE user_id = ?", (user_id,))
        return c.fetchone()

def fetch_journal_entries(user_id, limit=5):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT entry FROM entries WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
        return [entry[0] for entry in c.fetchall()]

def insert_journal_entry(user_id, entry, reflection):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO entries (user_id, entry, reflection) VALUES (?, ?, ?)", (user_id, entry, reflection))
        conn.commit()

def insert_authorized_user(user_id, token):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO authorized_users (user_id, token) VALUES (?, ?)", (user_id, token))
        conn.commit()

# Command Handlers
# Updated command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    user_id = user.id
    if user_id != ADMIN_USER_ID:
        token = fetch_user_token(user_id)
        if not token:
            await update.message.reply_text("You are not authorized to use this bot. Please provide the access token.")
            return AUTHENTICATE

    username = user.first_name if user.first_name else "User"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Hey, my username is {username}."}
    ]
    
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        llm_response = completion.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating LLM response: {e}")
        llm_response = "Sorry, I couldn't generate a response at the moment."

    context.user_data['messages'] = messages

    await update.message.reply_text(llm_response)
    return await ask_recent_use(update, context)

async def yes_continue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'Yes' to the question.", user.first_name)
    messages = context.user_data.get('messages', [])
    messages.append({"role": "user", "content": "Yes"})
    context.user_data['messages'] = messages
    return await listen(update, context)

async def no_continue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'No' to the question.", user.first_name)
    messages = context.user_data.get('messages', [])
    messages.append({"role": "user", "content": "No"})
    context.user_data['messages'] = messages
    return await listen(update, context)

async def listen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    username = user.username if user.username else "User"
    logger.info(f"Listening: @{username}: {update.message.text}")

    messages = context.user_data.get('messages', [])
    messages.append({"role": "user", "content": update.message.text})

    logger.info("Start To-GPT: %s", messages)

    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )

    llm_response = completion.choices[0].message.content

    logger.info("Start GPT-FROM: %s", llm_response)

    messages.append({"role": "assistant", "content": llm_response})
    context.user_data['messages'] = messages
    
    await update.message.reply_text(llm_response, reply_markup=ReplyKeyboardMarkup([["/journal", "/end"]], resize_keyboard=True))
    return LISTEN

async def ask_recent_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    t_message = "Have you used recently?"
    context.user_data['messages'].append({"role": "assistant", "content": t_message})
    await update.message.reply_text(t_message, reply_markup=ReplyKeyboardMarkup([["/yes", "/no"]], resize_keyboard=True))
    return RECENT_USE

async def recent_use_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['messages'].append({"role": "user", "content": "Yes"})
    return await listen(update, context)

async def recent_use_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['messages'].append({"role": "user", "content": "No"})
    follow_up_message = "That's great news! 😊 I'd love to hear more about what's been helping you avoid using substances. Would you like to share what's been working well for you?"
    context.user_data['messages'].append({"role": "assistant", "content": follow_up_message})
    await update.message.reply_text(follow_up_message)
    return LISTEN

async def journal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s requested a journal entry.", user.first_name)
    await update.message.reply_text("Working on your journal entry...")

    messages = context.user_data.get('messages', [])

    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    conversation_history = "\n".join([f"{m['role']}: {m['content']}" for m in messages])

    journal_prompt = JOURNAL_PROMPT.format(current_datetime, conversation_history)
    journal_completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": journal_prompt},
        ]
    )

    journal_entry = journal_completion.choices[0].message.content
    logger.info("Journal Entry: %s", journal_entry)

    reflection_prompt = REFLECTION_PROMPT + f"\nJournal:\n{journal_entry}\nConversation history:\n{conversation_history}"
    reflection_completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": reflection_prompt},
        ]
    )

    reflection = reflection_completion.choices[0].message.content
    logger.info("Reflection: %s", reflection)

    insert_journal_entry(user.id, journal_entry, reflection)

    await update.message.reply_text(journal_entry)
    return LISTEN

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("User %s ended the conversation.", user.first_name)
    await update.message.reply_text("Bye! Take care.", reply_markup=ReplyKeyboardRemove())
    return END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("User %s canceled the conversation.", user.first_name)
    await update.message.reply_text("Bye! I hope we can talk again some day.", reply_markup=ReplyKeyboardRemove())
    return END

async def authenticate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user

    if len(context.args) == 0:
        await update.message.reply_text("Please provide the access token.")
        return AUTHENTICATE

    token = context.args[0].strip()
    stored_token = fetch_user_token(user.id)

    if stored_token and stored_token[0] == token:
        await update.message.reply_text("Authentication successful. You can now use the bot.")
        return await start(update, context)
    else:
        await update.message.reply_text("Invalid token. Please try again.")
        return AUTHENTICATE
    
async def authorize_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    if user.id != ADMIN_USER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    try:
        _, user_id, token = update.message.text.split()
        insert_authorized_user(int(user_id), token)
        await update.message.reply_text(f"User {user_id} has been authorized.")
    except ValueError:
        await update.message.reply_text("Invalid command format. Use /authorize <user_id> <token>")

async def send_message(user_id, message):
    bot = Bot(token="YOUR_BOT_TOKEN")
    await bot.send_message(chat_id=user_id, text=message)

def generate_llm_response(user_messages, user_id):
    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    prompt = SYSTEM_PROMPT.format(user_messages, current_datetime)
    
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Hey, my user id is {user_id}."}
    ]

    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        llm_response = completion.choices[0].message.content
        logger.info(f"LLM Response for User ID: {user_id}: {llm_response}")
    except Exception as e:
        logger.error(f"Error generating LLM response: {e}")
        llm_response = "Sorry, I couldn't generate a response at the moment."

    return llm_response

def main():
    application = Application.builder().token("6308464888:AAEg12EbOv3Bm5klIQaOpBR0L_VvLdTbqn8").build()
    create_database()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AUTHENTICATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, authenticate)],
            RECENT_USE: [
                CommandHandler("yes", recent_use_yes),
                CommandHandler("no", recent_use_no),
                CommandHandler("end", end),
            ],
            LISTEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, listen),
                CommandHandler("journal", journal),
                CommandHandler("end", end),
                CommandHandler("yes", yes_continue),
                CommandHandler("no", no_continue),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("authorize", authorize_user))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
