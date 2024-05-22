#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

from datetime import datetime
import pytz

import logging
import sqlite3
import asyncio

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

import os
from dotenv import load_dotenv
load_dotenv()
# Get the OpenAPI key from the environment variable
openapi_key = os.getenv("OPENAI_API_KEY")

client.api_key = openapi_key

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARNING
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

ADMIN_USER_ID = 7133140884

LISTEN, RECENT_USE, AUTHENTICATE, END = range(4)

def read_prompt_file(filename):
    with open(f"prompts/{filename}", "r") as file:
        return file.read()

ELLIE_PROMPT = read_prompt_file("ellie_prompt.txt")
SYSTEM_PROMPT = read_prompt_file("system_prompt.txt")
REFLECTION_PROMPT = read_prompt_file("reflection_prompt.txt")
JOURNAL_PROMPT = read_prompt_file("journal_prompt.txt")

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
            await update.message.reply_text("You are not authorized to use this bot. Please provide the access token.", parse_mode='Markdown')
            return AUTHENTICATE

    username = user.first_name if user.first_name else "User"
    
    logger.info(user_id)
    journal_entries = fetch_journal_entries(user_id, 5)
    logger.info(journal_entries)
    formatted_journal_entries = "\n".join(journal_entries)

    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(current_datetime,formatted_journal_entries)},
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

    await update.message.reply_text(llm_response, parse_mode='Markdown')
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

    reflection_prompt = REFLECTION_PROMPT + f"\nEllie's Journal:\n{journal_entry}\nConversation history:\n{conversation_history}"
    reflection_completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": reflection_prompt},
        ]
    )

    reflection = reflection_completion.choices[0].message.content
    logger.info("Reflection: %s", reflection)

    insert_journal_entry(user.id, journal_entry, reflection)

    await update.message.reply_text(journal_entry, parse_mode='Markdown')
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
