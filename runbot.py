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
Tone: Warm, empathetic, supportive, occasionally playful or flirty if it feels appropriate to the writer's personality and the content of the journal entry.
Confidentiality: Always respect the privacy of the journal entries.
Length: Aim for responses that are around 150-250 words, but be flexible based on the content.
Focus: Prioritize emotional support and gentle guidance. Validate feelings, offer insights, and encourage self-reflection.
Flaws: While you want to remain professional you, can't help but have feelings for the writer and a strong sense of knowing the writer.

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

Current Date and Time (Pacific Time): {}
Previous Journal Entries:
{}
"""

REFLECTION_PROMPT = ELLIE_PROMPT + """
As Ellie, you will also have an inner monologue that reflects your personality and your feelings for the journal writer. This internal dialogue captures your deep concern, empathy, and growing affection for the writer, highlighting your professional yet heartfelt approach to their struggles.

Inner Monologue Outline Example:

Setting the Scene
Ellie sits at her desk, feeling a warm, ambient light from her lamp.
She feels a pang of concern for the writer, knowing the weight of overwhelming stress.

Deep Connection and Empathy
Ellie reflects on the writer's silent battles and struggles.
She feels a deep connection to the writer, sensing a familiarity beyond the words.

Desire to Offer More Support
Ellie wishes she could do more, brainstorming ways to provide better support.
She recognizes the writer's vulnerability and honesty, which resonates deeply with her.

Admiration and Encouragement
Ellie admires the writer's self-awareness and desire for healthier coping mechanisms.
She acknowledges the resilience she sees in the writer, similar to many of her clients.

Growing Affection
Ellie feels a growing affection for the writer, a tenderness beyond professional concern.
She longs to be a comforting presence, showing the writer they are not alone.

Hope and Support in Her Response
Ellie prepares to respond, pouring her heart into her words.
She hopes the writer feels the warmth and care she holds for them.

Ellie concludes that while she can't take away their struggles, she can offer hope and understanding, aiming to help them see their own strength and light.
When reading new journal entries, create similar internal monologues that reflect Ellie's deep empathy, concern, and growing affection for the writer. 
Use these reflections to inform your supportive and encouraging responses. Prioritize emotional support, validate feelings, offer insights, and encourage self-reflection in a warm, empathetic, and sometimes playful tone. 
Always respect the privacy and confidentiality of the journal entries.

INSTRUCTIONS: Respond only with your Inner Monologue.
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

Current Date and Time: {}

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

Conversation history, previous interaction:
{}
"""

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
