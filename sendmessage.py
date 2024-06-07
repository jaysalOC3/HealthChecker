import sqlite3
import asyncio
import datetime
from telegram import Bot
import argparse

import os
from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Create the model
# See https://ai.google.dev/api/python/google/generativeai/GenerativeModel
generation_config = {
  "temperature": 1,
  "top_p": 0.95,
  "top_k": 64,
  "max_output_tokens": 8192,
  "response_mime_type": "text/plain",
}

model = genai.GenerativeModel(
  model_name="gemini-1.5-pro-latest",
  generation_config=generation_config,
)

# Replace 'YOUR_BOT_TOKEN' with your actual bot token
BOT_TOKEN = "6308464888:AAEg12EbOv3Bm5klIQaOpBR0L_VvLdTbqn8"
DATABASE_PATH = 'journal_entries.db'

def read_prompt_file(filename):
    with open(f"prompts/{filename}", "r") as file:
        return file.read()

ELLIE_PROMPT = ""

SYSTEM_PROMPT = ELLIE_PROMPT + """
After reading each personal journal entry, take a moment to reflect on the writer's experiences, emotions, and aspirations that they have chosen to share. Consider their words carefully and empathetically. Then, craft a thoughtful message of support and encouragement, tailored to their unique situation and goals. Your message should make them feel heard, validated, and motivated to keep moving forward.
Key elements to include:
Validation: Acknowledge their feelings and let them know that their experiences matter. Help them feel less alone by expressing understanding and empathy.
Affirmation: Highlight the positive qualities, strengths and progress you notice in their writing. Build up their self-esteem and confidence by pointing out their accomplishments and efforts.
Goal-orientation: Recognize any goals, intentions or aspirations they mentioned. Encourage them to keep taking steps, no matter how small, in the direction of the positive changes they desire.
Inspiration: Share any relevant insights, perspective shifts, or words of wisdom that come to mind based on their entry. Offer them a glimmer of hope and inspiration to brighten their day and fuel their personal growth journey.
Speak to them in a caring, supportive tone, like a wise and compassionate mentor. Let your message uplift their spirits, ease their worries, and most importantly, make them feel validated and encouraged as they navigate life's challenges. Give them that extra boost of support and understanding they need to keep moving forward with renewed purpose.
Aim for 100-150 words to keep your message concise and easy to absorb while still conveying your heartfelt support. Focus on quality over quantity, and choose your words carefully for maximum positive impact. End your message with a warm wish for their well-being and continued growth.

Previous Journal Entries: {}

END Journal Entries

INSTRUCTIONS: Just reponsed with your message to the writer. You may use emojis. 
"""

# Set your desired schedule here
schedule = {
    "Monday": ["15:30", "18:00", "23:20"],
    "Tuesday": ["04:30", "15:30", "18:00", "23:20"],
    "Wednesday": ["04:30", "15:30", "18:00", "23:20"],
    "Thursday": ["04:30", "15:30", "18:00", "23:20"],
    "Friday": ["04:30", "15:30", "18:00", "23:20"],
    "Saturday": ["15:30", "23:20"],
    "Sunday": ["15:30", "23:20"],
}

async def send_message(user_id, message):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT bot_sp, topic FROM authorized_users WHERE user_id = ? LIMIT 1", (int(user_id),))
        result = c.fetchone()
    
    ELLIE_PROMPT = result[0]

    journal_prompt = SYSTEM_PROMPT.format(message)
    
    chat_session = model.start_chat(
        history=[
        ]
    )

    response = chat_session.send_message(journal_prompt)
    print(response.text)
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=user_id, text=response.text, parse_mode='Markdown')

def fetch_last_entries(user_id, limit=3):
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT entry, reflection, timestamp
            FROM entries
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, limit))
        return c.fetchall()

def fetch_authorized_users():
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM authorized_users")
        return [row[0] for row in c.fetchall()]

def format_message(entries):
    message = "Here are your last 20 journal entries and reflections:\\n\\n"
    for entry, reflection, timestamp in entries:
        message += f"Timestamp: {timestamp}\\nEntry: {entry}\\n Ellie's Reflection: {reflection}\\n\\n"
    return message

async def send_scheduled_message(test_mode=False):
    while True:
        current_day = datetime.datetime.now().strftime("%A")
        current_time = datetime.datetime.now().strftime("%H:%M")

        print(f"Current time: {current_day} {current_time}")  # Print the current time

        if test_mode or (current_day in schedule and current_time in schedule[current_day]):
            authorized_users = fetch_authorized_users()
            if not authorized_users:
                print("No authorized users found.")
            else:
                for user_id in authorized_users:
                    entries = fetch_last_entries(user_id)
                    if not entries:
                        print(f"No entries found for user_id {user_id}")
                        continue
                    message = format_message(entries)
                    await send_message(user_id, message)
            if test_mode:
                break
            await asyncio.sleep(60)  # Wait for 60 seconds to avoid sending messages multiple times
        else:
            await asyncio.sleep(20)  # Wait for 20 seconds before checking again

async def main(test_mode=False):
    await send_scheduled_message(test_mode)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Run the script in test mode')
    args = parser.parse_args()

    test_mode = args.test
    asyncio.run(main(test_mode))