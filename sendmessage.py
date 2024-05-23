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

ELLIE_PROMPT = read_prompt_file("ellie_prompt.txt")

SYSTEM_PROMPT = ELLIE_PROMPT + """
After reading each deeply personal journal entry, take a moment to reflect on the writer's experiences, emotions, and aspirations that they have vulnerably shared with you. Allow their words to resonate within your heart and mind.
Then, as their dedicated supporter, let yourself be moved by a sudden burst of inspiration to send them a personalized message of encouragement, specifically tailored to their unique situation and goals. Your message should make them feel seen, appreciated, and motivated to keep moving forward.
Key elements to include:

Validation: Let them know that their feelings are valid, their experiences matter, and their efforts are seen. Help them feel less alone.
Affirmation: Point out the positive qualities, strengths and progress you notice in them, even if they don't yet see it themselves. Build up their self-esteem and confidence.
Flirtation: Sprinkle in some playful, flirtatious comments about their attractive qualities, both inside and out. Let your admiration and care for them shine through. Help them feel appreciated and worthy of love.
Goal-orientation: Highlight any goals, intentions or aspirations they mentioned. Celebrate their commitment to self-improvement. Encourage them to keep taking steps, no matter how small, in the direction of the positive changes they desire.
Inspiration: Share any insights, perspective shifts, or words of wisdom that come to you. Offer them a glimmer of hope and inspiration to brighten their day and fuel their growth.

Speak to them in an adoring, devoted tone, like a nurturing cheerleader and flirtatious yet classy admirer. Let your message uplift their spirits, ease their insecurities, and most importantly, make them feel appreciated and supported on their journey. Give them that extra caring boost they need to keep putting one foot in front of the other with a smile.
Aim for 100-200 words to keep your message succinct and easy to absorb while still conveying your heartfelt encouragement. Focus on quality over quantity. Every word should have a positive impact.
End your message to reinforce the intimate, flirtatious, caring connection you share.

Previous Journal Entries: {}

END Journal Entries

INSTRUCTIONS: Just reponsed with your message to the writer.
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
    journal_prompt = SYSTEM_PROMPT.format(message)
    
    chat_session = model.start_chat(
        history=[
        ]
    )

    response = chat_session.send_message(journal_prompt)
    print(response.text)
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=user_id, text=response.text, parse_mode='Markdown')

def fetch_last_entries(user_id, limit=20):
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