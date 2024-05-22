import sqlite3
import asyncio
import datetime
from telegram import Bot
from openai import OpenAI
import argparse

client = OpenAI()
# Replace 'YOUR_BOT_TOKEN' with your actual bot token
BOT_TOKEN = "6308464888:AAEg12EbOv3Bm5klIQaOpBR0L_VvLdTbqn8"
DATABASE_PATH = 'journal_entries.db'

def read_prompt_file(filename):
    with open(f"prompts/{filename}", "r") as file:
        return file.read()

ELLIE_PROMPT = read_prompt_file("ellie_prompt.txt")

SYSTEM_PROMPT = ELLIE_PROMPT + """
Task Instructions: Read the last journal entries and inner monologues Ellie wrote in the past. 
Craft a simple message to the writer, unsolicited, offering support and a touch of flirtation, while maintaining the spirit of support and encouragement derived from the journal context.
Please reply with only the text message to the journal writer.

Previous Journal Entries: {}
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
    message_completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": journal_prompt},
        ]
    )
    print(message_completion.choices[0].message.content)
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=user_id, text=message_completion.choices[0].message.content)

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