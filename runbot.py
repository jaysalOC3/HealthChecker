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
from httpx import ReadError

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
MODEL_NAME = "gemini-1.5-flash-latest"
GENERATION_CONFIG = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,  
}

safety_settings = [
  {
    "category": "HARM_CATEGORY_SEXUAL",
    "threshold": "BLOCK_NONE",
  },
]

# Constants
ADMIN_USER_ID = 7133140884
AUTHENTICATE, RECENT_USE, LISTEN, END = range(4)
BOT_NAME, BOT_BACKSTORY, BOT_PROMPT = range(3)

# Load Prompts (using a function)
def read_prompt(filename):
    with open(f"prompts/{filename}", "r") as file:
        return file.read()


ELLIE_PROMPT = read_prompt("ellie_prompt.txt")
START_PROMPT_0 = read_prompt("START_PROMPT_0.txt")
BOT_SETUP_START = read_prompt("bot_setup_start.txt")
BOT_SETUP_PROMPT = read_prompt("bot_setup_prompt.txt")
FEEDBACK_PROMPT = read_prompt("feedback_prompt.txt")
START_PROMPT = read_prompt("start_prompt.txt")
REFLECTION_PROMPT = read_prompt("reflection_prompt.txt")
JOURNAL_PROMPT = read_prompt("journal_prompt.txt")

# Database Functions
def create_database():
    logger.warning(f'Creating new database!')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS entries
                     (user_id INTEGER, entry TEXT, reflection TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS authorized_users
                    (user_id INTEGER PRIMARY KEY, 
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                        token TEXT, 
                        bot_name TEXT, 
                        bot_sp TEXT
                    )''')

def fetch_user_token(user_id):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT token FROM authorized_users WHERE user_id = ?", (user_id,))
        return c.fetchone()
    
def fetch_bot_name(user_id):
    logger.warning(f'Fetch Bot Name:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT bot_name FROM authorized_users WHERE user_id = ?", (user_id,))
        return c.fetchone()
    
def update_bot_name(user_id, name):
    logger.warning(f'Update Bot Name:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute(f'''INSERT OR REPLACE INTO authorized_users (user_id, bot_name)
                     VALUES ({user_id}, '{name}');''')
    
def fetch_bot_sp(user_id):
    logger.warning(f'Fetch Bot SYSTEM PROMPT:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT bot_sp FROM authorized_users WHERE user_id = ? LIMIT 1", (int(user_id),))
        return generate_start_prompt(c.fetchone()[0])
    return "ERROR: Unable to get bot SYSTEM PROMPT."

def update_bot_sp(user_id, backstory):
    logger.warning(f'Update Bot SYSTEM PROMPT:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute(f'''INSERT OR REPLACE INTO authorized_users (user_id, bot_sp)
                     VALUES ({user_id}, '{backstory.replace("'","")}');''')
    return "ERROR: Unable to get bot SYSTEM PROMPT."

def update_bot_sp(user_id, sp):
    logger.warning(f'Update Bot SYSTEM PROMPT:')
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute('''
        UPDATE authorized_users
        SET bot_sp = ?, timestamp = ?
        WHERE user_id = ?
        ''', (sp.replace("'",""), current_timestamp, user_id))

def fetch_journal_entries(user_id, limit=1):
    logger.warning(f'Fetch Journal Entries:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT entry FROM entries WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
        return [entry[0] for entry in c.fetchall()]

def fetch_reflection_entries(user_id, limit=1):
    logger.warning(f'Fetch Reflection Entries:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT reflection FROM entries WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?", (user_id, limit))
        return [entry[0] for entry in c.fetchall()]
    
def insert_journal_entry(user_id, entry, reflection):
    logger.warning(f'Writing Journal Entries:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO entries (user_id, entry, reflection) VALUES (?, ?, ?)", (user_id, entry, reflection))
        conn.commit()

def insert_authorized_user(user_id, token):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO authorized_users (user_id, token) VALUES (?, ?)", (user_id, token))
        conn.commit()

def generate_start_prompt(agent_prompt):
    llminput = FEEDBACK_PROMPT
    reflectioninput = fetch_reflection_entries(ADMIN_USER_ID)
    llminput += "ORIGINAL SYSTEM PROMPT:\n" +  agent_prompt + "=== END ORIGINAL SYSTEM PROMPT ===\n\n"
    llminput += "FEEDBACK FOR IMPROVEMENT:\n"
    for item in reflectioninput:
        llminput += f"\n{item}\n"
    llminput += "=== END FEEDBACK ===\n"
    
    logger.info(f"INPUT: {llminput}")
    new_system_prompt = genai.GenerativeModel(
                                            model_name=MODEL_NAME ,
                                            generation_config=GENERATION_CONFIG,
                                            safety_settings=safety_settings,
                                            system_instruction=llminput,
                                ).start_chat().send_message("\n").text
    return new_system_prompt

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

    start_prompt = fetch_bot_sp(user_id)
    update_bot_sp(user_id, start_prompt)

    username = user.first_name if user.first_name else "User"
    logger.info(f"User started conversation: {user_id}")
    await update.message.reply_text("Contacting Ellie.")
    
    context.user_data['chat_session'] = genai.GenerativeModel(
                                                        model_name=MODEL_NAME ,
                                                        generation_config=GENERATION_CONFIG,
                                                        safety_settings=safety_settings,
                                                        system_instruction=start_prompt,
                                                        ).start_chat()
    llm_response = context.user_data['chat_session'].send_message(f"Hi {fetch_bot_name(user_id)}. Here's {user.first_name} old journals before we work on this new one. {fetch_journal_entries(user_id, 5)}. Ask a relevant question.").text
    logger.info(f'ELLIE: {llm_response}')
    context.user_data['messages'].append(f"ELLIE: {llm_response}")

    await update.message.reply_text(llm_response)

    return LISTEN

async def setup_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Welcome: Experience journaling like never before. Dive into meaningful conversations with your own AI bot, designed to help you understand yourself better.  Save your interactive journal with /journal, and let your bot surprise you with thoughtful messages.")
    llminput = BOT_SETUP_START
    context.user_data['new_bot_chat'] = genai.GenerativeModel(
                                            model_name=MODEL_NAME ,
                                            generation_config=GENERATION_CONFIG,
                                            safety_settings=safety_settings,
                                            system_instruction=llminput,
                                ).start_chat()
    await update.message.reply_text("Let's start by naming your bot.")
    logger.info("End Setup Bot > Bot Name")
    return BOT_NAME

async def bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    user_id = user.id

    bot_name = update.message.text
    bot_prompt = context.user_data['new_bot_chat'].send_message(f"Your name is: {bot_name}").text
    update_bot_name(user_id, bot_name)
    logger.info(f"Bot's name set to: {bot_name}: {bot_prompt}")
    await update.message.reply_text("Please provide your bot's main goal. (< 1000 characters)")
    return BOT_BACKSTORY

async def bot_backstory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    user_id = user.id
    
    bot_backstory = update.message.text
    log_backstory = context.user_data['new_bot_chat'].send_message(f"Your goal is: {bot_backstory}").text
    logger.info(f"New Back Story: {log_backstory}")
    log_backstory = context.user_data['new_bot_chat'].send_message(BOT_SETUP_PROMPT).text
    logger.info(f"New Back Story: {log_backstory}")
    update_bot_sp(user_id, log_backstory)
    await update.message.reply_text(f"Your bot is ready! Here's the system prompt:\n\n{log_backstory}")
    return END

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
    username = user.first_name if user.first_name else "User"
    user_message = update.message.text  # Get user message directly
    logger.info(f"Listening: @{user.username}: {user_message}")

    try:
        user_message = update.message.text
        context.user_data['messages'].append(f"{username}: {user_message}")
        
        # Get the LLM response (extract text only)
        llm_response = context.user_data['chat_session'].send_message(user_message).text
        
        context.user_data['messages'].append(f"ELLIE: {llm_response}")

    except Exception as e:
        logger.error(f"Error generating LLM response: {e}")
        return LISTEN  # Stay in the LISTEN state for error recovery

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
    logger.warning("---- Starting journal entry ----")
    await update.message.reply_text("Working on your journal entry...")

    messages = context.user_data.get('messages', [])

    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    conversation_history = "\n".join([
        f"{m}" if hasattr(m, 'text') else f"{m}"  # Handle strings and message objects
        for m in messages
    ])
    logger.info("---------Conversation History: %s", conversation_history)

    journal_prompt = ELLIE_PROMPT + JOURNAL_PROMPT.format(current_datetime, conversation_history)

    # Send the journal_prompt to Google AI and store in journal_entry
    journal_entry = genai.generate_text(
        prompt=journal_prompt, 
        **GENERATION_CONFIG, 
        safety_settings=safety_settings,
        ).result
    logger.info("---------Journal: %s", journal_entry)
    
    await update.message.reply_text("Working on my thoughts...")

    reflection_prompt = REFLECTION_PROMPT + f"\n\n### START Chat Transcripts:\n{conversation_history}### END Chat Transcripts:"

    # Send the reflection_prompt to Google AI and store in reflection
    reflection = genai.generate_text(
        prompt=reflection_prompt, 
        **GENERATION_CONFIG, 
        safety_settings=safety_settings,
        ).result
    logger.info("---------Reflection: %s", reflection)

    insert_journal_entry(user.id, journal_entry, reflection)

    await update.message.reply_text(journal_entry)

    # Send the user back to the start of the conversation flow
    return END

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
    
    # Check if messages are empty
    if not messages:
        await update.message.reply_text("No conversation history yet.")
        return LISTEN

    conversation_history = []
    current_chunk = ""
    MAX_CHUNK_SIZE = 500

    for message in messages:
        message_text = message.text if hasattr(message, 'text') else str(message)
        if message_text.strip():  # Ensure message_text is not just whitespace
            if len(current_chunk) + len(message_text) + 1 > MAX_CHUNK_SIZE:
                conversation_history.append(current_chunk)
                current_chunk = ""
            current_chunk += message_text + "\n"  

    if current_chunk:
        conversation_history.append(current_chunk)

    # Send the conversation history in multiple chunks
    for chunk in conversation_history:
        if chunk.strip(): # Ensure chunk is not just whitespace
            await update.message.reply_text(chunk, parse_mode='Markdown')
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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        raise context.error
    except ReadError as e:
        # Handle network error
        logger.error("Network error occurred: %s", str(e))
        # You can send a message to the user or perform any other necessary action
        if update:
            await update.message.reply_text("Sorry, a network error occurred. Please try again later.")
    except Exception as e:
        # Handle other exceptions
        logger.error("An error occurred: %s", str(e))
        # You can send a message to the user or perform any other necessary action
        if update:
            await update.message.reply_text("Sorry, an error occurred. Please try again later.")

def main():
    application = Application.builder().token("6308464888:AAEg12EbOv3Bm5klIQaOpBR0L_VvLdTbqn8").build()
    create_database()

    setup_bot_handler = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_bot)],
        states={
            AUTHENTICATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, authenticate)],
            BOT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_name)],
            BOT_BACKSTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot_backstory)],
            END: [MessageHandler(filters.TEXT & ~filters.COMMAND, start)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    allow_reentry=True,
    )

    application.add_handler(setup_bot_handler)

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
            # END state to explicitly handle the end of the conversation
            END: [MessageHandler(filters.TEXT & ~filters.COMMAND, start)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("authorize", authorize_user))
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    #bot_setup()
    #generate_start_prompt()
    main()