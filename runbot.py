#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

import logging
import sqlite3
import asyncio
from datetime import datetime

import pytz
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import os
from dotenv import load_dotenv

import google.generativeai as genai

load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Model Configuration (using global variables)
MODEL_NAME = "gemini-1.5-pro-latest"
GENERATION_CONFIG = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,  
}

# Constants
ADMIN_USER_ID = 7133140884
LISTEN, RECENT_USE, AUTHENTICATE, END = range(4)

# Load Prompts (using a function)
def read_prompt(filename):
    with open(f"prompts/{filename}", "r") as file:
        return file.read()


ELLIE_PROMPT = read_prompt("ellie_prompt.txt")
SYSTEM_PROMPT = read_prompt("system_prompt.txt")
REFLECTION_PROMPT = read_prompt("reflection_prompt.txt")
JOURNAL_PROMPT = read_prompt("journal_prompt.txt")

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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    user_id = user.id

    # Initialize 'messages' list here
    context.user_data['messages'] = []

    # Authentication Check
    if user_id != ADMIN_USER_ID:
        token = fetch_user_token(user_id)
        if not token:
            await update.message.reply_text(
                "You are not authorized. Provide the access token."
            )
            return AUTHENTICATE

    username = user.first_name if user.first_name else "User"
    logger.info(f"User started conversation: {user_id}")

    # Fetch and Format Journal Entries
    journal_entries = fetch_journal_entries(user_id, 5)
    formatted_journal_entries = "\n".join(journal_entries)

    # Get Current Time
    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    # Prepare System Prompt
    system_prompt = ELLIE_PROMPT + SYSTEM_PROMPT.format(
        current_datetime, formatted_journal_entries
    )

    logger.info(f"SYSTEM_PROMPT: {system_prompt}")

    # Add SYSTEM_PROMPT to User Messages Context
    context.user_data['messages'].append(system_prompt)

    # Start Chat Session
    context.user_data['chat_session'] = genai.GenerativeModel(
        model_name=MODEL_NAME, generation_config=GENERATION_CONFIG
    ).start_chat()
    context.user_data['chat_session'].send_message(system_prompt)

    user_prompt = f"New Message from: {username}. Hi."
    context.user_data['messages'].append(user_prompt)
    context.user_data['chat_session'].send_message(user_prompt)
    
    llm_response = context.user_data['chat_session'].last
    logger.info(f'llm_response: {llm_response.text}')    
    context.user_data['messages'].append(llm_response.text) 

    await update.message.reply_text(llm_response.text)
    return await ask_recent_use(update, context)


async def yes_continue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'Yes' to the question.", user.first_name)
    messages = context.user_data.get('messages', [])
    messages.append("Yes")
    context.user_data['messages'] = messages
    return await listen(update, context)

async def no_continue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'No' to the question.", user.first_name)
    messages = context.user_data.get('messages', [])
    messages.append("No")
    context.user_data['messages'] = messages
    return await listen(update, context)

async def listen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    username = user.username if user.username else "User"
    user_message = update.message.text  # Get user message directly
    logger.info(f"Listening: @{user.username}: {user_message}")

    try:
        uuser_message = update.message.text
        context.user_data['messages'].append(user_message)

        # Get the LLM response (extract text only)
        llm_response = context.user_data['chat_session'].send_message(user_message).text
        #logger.info("LLM Response: %s", llm_response)
        context.user_data['messages'].append(llm_response)

    except Exception as e:
        logger.error(f"Error generating LLM response: {e}")
        return LISTEN  # Stay in the LISTEN state for error recovery

    context.user_data['messages'].append(llm_response) # Add LLM response to messages list

    await update.message.reply_text(
        llm_response, reply_markup=ReplyKeyboardMarkup([["/journal", "/end"]], resize_keyboard=True)
    )

    logger.info(f"-------------------------Chat Session:")
    for msg in context.user_data['messages']:
        logger.info(msg)

    return LISTEN

async def ask_recent_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    t_message = "Have you used recently?"
    context.user_data['messages'].append(t_message)
    context.user_data['chat_session'].send_message(t_message)
    await update.message.reply_text(t_message, reply_markup=ReplyKeyboardMarkup([["/yes", "/no"]], resize_keyboard=True))
    return RECENT_USE

async def recent_use_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['messages'].append("Yes")
    context.user_data['chat_session'].send_message("Yes")
    return await listen(update, context)

async def recent_use_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['messages'].append("No")
    follow_up_message = "That's great news! 😊 I'd love to hear more about what's been helping you avoid using substances. Would you like to share what's been working well for you?"
    context.user_data['messages'].append(follow_up_message)
    context.user_data['chat_session'].send_message(follow_up_message)
    await update.message.reply_text(follow_up_message)
    return LISTEN

async def journal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s requested a journal entry.", user.first_name)
    await update.message.reply_text("Working on your journal entry...")

    messages = context.user_data.get('messages', [])

    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    conversation_history = "\n".join([
        f"{m.text}" if hasattr(m, 'text') else f"{m}"  # Handle strings and message objects
        for m in messages
    ])

    journal_prompt = ELLIE_PROMPT + JOURNAL_PROMPT.format(current_datetime, conversation_history)

    # Send the journal_prompt to Google AI and store in journal_entry
    journal_entry = genai.generate_text(prompt=journal_prompt, **GENERATION_CONFIG).result
    print(journal_entry)
    
    await update.message.reply_text("Working on my thoughts...")

    reflection_prompt = ELLIE_PROMPT + REFLECTION_PROMPT + f"\n\n### START Chat Transcripts:\n{conversation_history}### END Chat Transcripts:"

    # Send the reflection_prompt to Google AI and store in reflection
    reflection = genai.generate_text(prompt=reflection_prompt, **GENERATION_CONFIG).result
    logger.info("---------Reflection: %s", reflection)

    insert_journal_entry(user.id, journal_entry, reflection)

    await update.message.reply_text(journal_entry)
    return LISTEN

async def get_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    user_id = user.id

    # Authentication Check
    if user_id != ADMIN_USER_ID:
        token = fetch_user_token(user_id)
        if not token:
            await update.message.reply_text(
                "You are not authorized. Provide the access token."
            )
            return AUTHENTICATE
        
    messages = context.user_data.get('messages', [])

    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    conversation_history = "\n".join([
        f"{m.text}" if hasattr(m, 'text') else f"{m}"  # Handle strings and message objects
        for m in messages
    ])
    
    await update.message.reply_text(conversation_history[:200], parse_mode='Markdown')
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
    application.add_handler(CommandHandler("get_context", get_context))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()