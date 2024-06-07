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

from database import *
import handler as h

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARNING
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
BOT_NAME, BOT_BACKSTORY, BOT_PURPOSE, BOT_PROMPT = range(4)

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

def main():
    create_database()

    application = Application.builder().token("6308464888:AAEg12EbOv3Bm5klIQaOpBR0L_VvLdTbqn8").build()
    
    setup_bot_handler = ConversationHandler(
        entry_points=[CommandHandler("setup", h.setup_bot)],
        states={
            AUTHENTICATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.authenticate)],
            BOT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.bot_name)],
            BOT_BACKSTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.bot_backstory)],
            BOT_PURPOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.bot_purpose)],
            END: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start)],
        },
        fallbacks=[CommandHandler("cancel", h.cancel)],
        allow_reentry=True,
    )

    application.add_handler(setup_bot_handler)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", h.start)],
        states={
            AUTHENTICATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.authenticate)],
            RECENT_USE: [
                CommandHandler("yes", h.recent_use_yes),
                CommandHandler("no", h.recent_use_no),
                CommandHandler("end", h.end),
            ],
            LISTEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.listen),
                CommandHandler("journal", h.journal),
                CommandHandler("end", h.end),
                CommandHandler("yes", h.yes_continue),
                CommandHandler("no", h.no_continue),
            ],
            # END state to explicitly handle the end of the conversation
            END: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.start)],
        },
        fallbacks=[CommandHandler("cancel", h.cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    
    application.add_error_handler(h.error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    #bot_setup()
    #generate_start_prompt()
    main()