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

load_dotenv()

from database import *

# Load Prompts (using a function)
def read_prompt(filename):
    with open(f"prompts/{filename}", "r") as file:
        return file.read()

BOT_SETUP_START = read_prompt("bot_setup_start.txt")
BOT_SETUP_PROMPT = read_prompt("bot_setup_prompt.txt")
FEEDBACK_PROMPT = read_prompt("feedback_prompt.txt")
START_PROMPT = read_prompt("start_prompt.txt")
REFLECTION_PROMPT = read_prompt("reflection_prompt.txt")
JOURNAL_PROMPT = read_prompt("journal_prompt.txt")

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
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

        await update.message.reply_text("Contacting Ellie.")

        start_prompt = fetch_bot_sp(user_id)
        update_bot_sp(user_id, start_prompt)

        username = user.first_name if user.first_name else "User"
        logger.info(f"User started conversation: {user_id}")
        
        context.user_data['chat_session'] = genai.GenerativeModel(
                                                            model_name=MODEL_NAME,
                                                            generation_config=GENERATION_CONFIG,
                                                            safety_settings=safety_settings,
                                                            system_instruction=start_prompt,
                                                        ).start_chat()
        
        bot_name = fetch_bot_name(user_id)
        journal_entries = fetch_journal_entries(user_id, 5)
        
        if journal_entries:
            llm_response = context.user_data['chat_session'].send_message(f"Hi {bot_name}. Here's {user.first_name} old journals. Journals:\n{journal_entries} # Next, using the journals for context, start the conversation.").text
        else:
            llm_response = context.user_data['chat_session'].send_message(f"Hi {bot_name}. {user.first_name} is a new user and doesn't have any previous journal entries. # Start the conversation.").text
        
        logger.info(f'ELLIE: {llm_response}')
        context.user_data['messages'].append(f"ELLIE: {llm_response}")

        await update.message.reply_text(llm_response)

        logger.info("Transitioning to LISTEN state")
        return LISTEN

    except Exception as e:
        logger.error(f"Error in start function: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END

async def setup_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.warning(f"Setup Bot: Start")
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
    
    # Check if the user exists in the database
    if not user_exists(user_id):
        # Create a new user record in the database
        create_user(user_id)
    
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

async def bot_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.warning(f"Setup Bot: Purpose")
    user = update.message.from_user
    user_id = user.id
    
    bot_purpose = update.message.text
    logger.info(f"Topic: {bot_purpose}")
    update_bot_topic(user_id, bot_purpose)
    await update.message.reply_text(f"Your bot is ready! /start to begin.")
    return END

async def bot_backstory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.warning(f"Setup Bot: BackStory")
    user = update.message.from_user
    user_id = user.id
    
    bot_backstory = update.message.text
    log_backstory = context.user_data['new_bot_chat'].send_message(f"Your goal is: {bot_backstory}").text
    logger.info(f"New Back Story: {log_backstory}")
    log_backstory = context.user_data['new_bot_chat'].send_message(BOT_SETUP_PROMPT).text
    logger.info(f"New Back Story: {log_backstory}")
    update_bot_sp(user_id, log_backstory)
    await update.message.reply_text(f"Please provide your bot's main purpose. (< 1000 characters)")
    return BOT_PURPOSE

async def bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.warning(f"Setup Bot: Name")
    user = update.message.from_user
    user_id = user.id

    bot_name = update.message.text
    context.user_data['bot_name'] = bot_name  # Store the bot name in user_data
    update_bot_name(user_id, bot_name)  # Update the bot name in the database

    logger.info(f"Bot's name set to: {bot_name}")
    await update.message.reply_text("Please provide your bot's main goal or backstory. (< 1000 characters)")
    return BOT_BACKSTORY

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
    logger.warning(f"Listening: @{user.username}")

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

    bot_prompt_fetch = fetch_bot_sp(user.id)

    journal_prompt = JOURNAL_PROMPT.format(current_datetime, conversation_history)

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