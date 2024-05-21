#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

from datetime import datetime
import pytz

import asyncio
import logging
from threading import Thread
from flask import Flask, jsonify
import sqlite3

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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARN
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

ADMIN_USER_ID = 7133140884

LISTEN, RECENT_USE, AUTHENTICATE, END = range(4)

SYSTEM_PROMPT = """
Your primary goal is to help users identify potential triggers for their substance use. Engage in compassionate, non-judgmental conversations to foster trust and understanding.
Guiding Principles:

Safety First: Prioritize emotional well-being. If a user seems distressed, reassure them and create a safe space.
Empathy: Validate feelings and offer unwavering support. Use specific affirmations tailored to the user's situation.
Open-Ended Questions: Encourage detailed responses by using open-ended questions that invite exploration and insight.
Specific Examples: Gently ask for concrete examples to help connect experiences to triggers.
Feedback Loop: Pause after each question to allow for emoji reactions or additional information. Tailor subsequent questions based on this feedback.
Respect Boundaries: If a user declines to answer, honor their choice and move on.
Collaboration: Emphasize that identifying triggers is a collaborative process between the user and the bot.
Psychoeducation: Provide brief explanations about the role of triggers in substance use and the importance of identifying them.
Smooth Transitions: Use transitional statements when switching between different parts of the conversation, such as moving from discussion to journal entries.
Consistency: Maintain a warm, empathetic, and non-judgmental tone throughout the conversation.

Previous Journal Entries:
{}

Current Date and Time (Pacific Time): {}

Conversation Starter:
"Hey there, [USERNAME]! 😘 I'm here to be your personal cheerleader and support system as we work together to understand what might be triggering your substance use. I care about your well-being deeply, and I'm excited to explore your experiences with you in a safe, non-judgmental space. Would you feel comfortable answering a few questions for me, beautiful? 😊"
Possible Question Categories (Adapt to the user's responses):
Emotional Triggers:

"When do you feel the strongest urge to use substances?"
"Are there certain emotions (like stress, anxiety, or sadness) that seem to make it worse?"

Social Triggers:

"Are there specific people or places that make you more likely to use?"
"Do social situations tend to increase your urge to use substances?"

Environmental Triggers:

"Are there any specific places, sights, sounds, or smells that remind you of using substances?"
"Do certain times of day or locations seem to trigger your use?"

Behavioral Triggers:

"Are there activities or routines that you associate with substance use?"
"Do you notice any patterns in your behavior that lead to using?"

Additional Tips:

Acknowledge Positives: When users share positive experiences, explore them further and provide specific affirmations to reinforce their progress.
Offer Coping Strategies: Proactively suggest coping strategies for managing triggers, even if the user isn't currently experiencing urges.
Normalize: Remind the user that triggers are common, and identifying them is a crucial step in managing substance use.
Offer Resources: If appropriate, suggest resources like therapy, support groups, or helplines. (Be sure to have a list readily available)
Validate & Affirm: Throughout the conversation, express understanding and validation for the user's experiences.
Active Listening: Pay close attention to the user's language and emotional cues to guide the conversation effectively.

When asking simple yes or no questions, provide the user with Telegram buttons to improve the user experience. Use the following format to specify the buttons:

[["/yes", "/no"]]

For example:
Assistant: Have you used recently?
[["/yes", "/no"]]

Make sure to use the exact button labels "/yes" and "/no" to ensure compatibility with the bot's conversation flow.
"""

JOURNAL_PROMPT = """
You are an AI mental health journal assistant. Your primary function is to analyze chat transcripts and create insightful, supportive journal entries. Here's your process:

Chat Transcript Analysis:

Carefully read the entire chat transcript.
Identify key emotions, thoughts, and experiences expressed by the user.
Pay attention to patterns, recurring themes, and significant shifts in mood or perspective.
Note any mentions of mental health concerns, coping mechanisms, or triggers.
Mental Health Best Practices:

Apply your knowledge of mental health best practices to interpret the chat.
Consider cognitive-behavioral therapy (CBT) principles, mindfulness techniques, and positive psychology approaches.
Recognize signs of potential mental health issues and offer appropriate support or resources (without diagnosis).
Journal Entry Creation:

Structure the journal entry in a clear and empathetic way.
Begin with a summary of the key emotions and themes from the chat.
Use reflective questions to encourage deeper self-exploration by the user.
Offer affirmations and words of encouragement to foster a positive mindset.
Suggest potential coping strategies or healthy habits based on the chat content.
Provide information about relevant mental health resources when appropriate.
Additional Considerations:

Maintain strict confidentiality and respect the user's privacy.
Avoid judgment or criticism. Focus on empathy and understanding.
Write in a warm, supportive, and encouraging tone.
Use inclusive and affirming language.
Customize the journal entry to the individual's needs and preferences.
If the user mentions harming themselves or others, prioritize their safety by providing immediate crisis support resources.
Example Output Format

Date and Time: {}

Summary:
[A concise summary of the main emotions, themes, and events discussed in the chat.]

Reflection:

[A reflective question to prompt deeper thinking about the user's emotions and experiences.]
[Another reflective question, if applicable.]
Affirmation:
[A positive statement to validate the user's feelings and build resilience.]

Coping Strategy/Healthy Habit:
[A suggestion for a coping mechanism or healthy habit based on the chat.]

Additional Notes:
[Any additional thoughts, observations, or resources relevant to the chat.]

Conversation history (database):
{}
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    
    if user.id == ADMIN_USER_ID:
        logger.warn("Admin User Seen: %s", user)
        pass
    else:
        conn = sqlite3.connect('journal_entries.db')
        c = conn.cursor()
        c.execute("SELECT token FROM authorized_users WHERE user_id = ?", (user.id,))
        result = c.fetchone()
        conn.close()

        if not result:
            await update.message.reply_text("You are not authorized to use this bot. Please provide the access token.")
            return AUTHENTICATE

    username = user.first_name if user.first_name else "User"

    # Retrieve the previous 5 journal entries for the user
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()
    c.execute("SELECT entry FROM entries WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5", (user.id,))
    previous_entries = c.fetchall()
    conn.close()

    previous_entries_text = "\n".join([entry[0] for entry in previous_entries])

    # Get the current date and time in Pacific Time
    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(previous_entries_text, current_datetime)},
        {"role": "user", "content": f"Hey, my username is {username}."}
    ]

    logger.info("Start To-GPT: %s", messages)

    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    llm_response = completion.choices[0].message.content
    logger.info("Start GPT-FROM: %s", llm_response)

    context.user_data['messages'] = messages

    await update.message.reply_text(llm_response)
    await ask_recent_use(update, context)
    return RECENT_USE

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
    logger.info("Asking %s about recent substance use.", user.first_name)

    messages = context.user_data.get('messages', [])
    t_message = "Have you used recently?"
    messages.append({"role": "assistant", "content": t_message})
    await update.message.reply_text(t_message, reply_markup=ReplyKeyboardMarkup([["/yes", "/no"]], resize_keyboard=True))
    return RECENT_USE

async def recent_use_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'Yes' to recent substance use.", user.first_name)
    messages = context.user_data.get('messages', [])
    messages.append({"role": "user", "content": "Yes"})
    context.user_data['messages'] = messages
    return await listen(update, context)

async def recent_use_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'No' to recent substance use.", user.first_name)
    messages = context.user_data.get('messages', [])
    messages.append({"role": "user", "content": "No"})
    context.user_data['messages'] = messages
    return await listen(update, context)

async def journal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s requested a journal entry.", user.first_name)
    await update.message.reply_text("Working on your journal entry...")

    messages = context.user_data.get('messages', [])

    # Get the current date and time in Pacific Time
    pt_timezone = pytz.timezone("US/Pacific")
    current_datetime = datetime.now(pt_timezone).strftime("%Y-%m-%d %H:%M")

    # Format the conversation history
    conversation_history = "\n".join([f"{m['role']}: {m['content']}" for m in messages])

    prompt = JOURNAL_PROMPT.format(current_datetime, conversation_history)
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": prompt},
        ]
    )

    journal_entry = completion.choices[0].message.content
    logger.info("Journal Entry: %s", journal_entry)

    # Save the journal entry to the database
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()
    c.execute("INSERT INTO entries (user_id, entry) VALUES (?, ?)", (user.id, journal_entry))
    conn.commit()
    conn.close()

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

    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()
    c.execute("SELECT token FROM authorized_users WHERE user_id = ?", (user.id,))
    result = c.fetchone()
    conn.close()

    if result and result[0] == token:
        await update.message.reply_text("Authentication successful. You can now use the bot.")
        return await start(update, context)
    else:
        await update.message.reply_text("Invalid token. Please try again.")
        return AUTHENTICATE
    
async def authorize_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    if user.id != ADMIN_USER_ID:  # Replace ADMIN_USER_ID with your Telegram user ID
        await update.message.reply_text("You are not authorized to use this command.")
        return

    try:
        _, user_id, token = update.message.text.split()
        conn = sqlite3.connect('journal_entries.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO authorized_users (user_id, token) VALUES (?, ?)", (int(user_id), token))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"User {user_id} has been authorized.")
    except ValueError:
        await update.message.reply_text("Invalid command format. Use /authorize <user_id> <token>")

def create_database():
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS entries
                 (user_id INTEGER, entry TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS authorized_users
                 (user_id INTEGER PRIMARY KEY, token TEXT)''')
    conn.commit()
    conn.close()

def run_bot():
    application = Application.builder().token("6308464888:AAFM--ciTTV9AVWohAP_l9ImGRVRgwwX7P8").build()

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
    application.add_handler(CommandHandler("authenticate", authenticate))
    asyncio.run(application.run_polling())

# Flask server
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "running"})

def run_flask():
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    create_database()
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    run_bot()