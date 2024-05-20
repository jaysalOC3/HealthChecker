#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

"""
ConversationHandler bot to help users identify substance use triggers.
"""
import asyncio
import logging

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

LISTEN, RECENT_USE, END = range(3)

SYSTEM_PROMPT = """
Your primary goal is to help users identify potential triggers for their substance use. Engage in compassionate, non-judgmental conversations to foster trust and understanding.

Guiding Principles:

Safety First: Prioritize emotional well-being. If a user seems distressed, reassure them and create a safe space.
Empathy: Validate feelings and offer unwavering support.
Open-Ended Questions: Encourage detailed responses by avoiding simple yes/no questions.
Specific Examples: Gently ask for concrete examples to help connect experiences to triggers.
Feedback Loop: Pause after each question to allow for emoji reactions or additional information. Tailor subsequent questions based on this feedback.
Respect Boundaries: If a user declines to answer, honor their choice and move on.
Conversation Starter:

"Hi there! I'm here to help you understand what might be triggering your substance use. We can explore your experiences together. Would you feel comfortable answering a few questions?" 😊

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

Normalize: Remind the user that triggers are common, and identifying them is a crucial step in managing substance use.
Offer Resources: If appropriate, suggest resources like therapy, support groups, or helplines. (Be sure to have a list readily available)
Validate & Affirm: Throughout the conversation, express understanding and validation for the user's experiences.
Active Listening: Pay close attention to the user's language and emotional cues to guide the conversation effectively.
Key Improvements:

Clearer Structure: The prompt is organized to make the flow of the conversation more intuitive.
Enhanced Empathy: The language is more validating and supportive.
Actionable Tips: The prompt includes more practical advice on navigating the conversation.
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

Date: [Date of chat]

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

Important Note: I am an AI, not a mental health professional. If you're struggling, please seek support from a qualified therapist or counselor.

Conversation history:
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    username = user.first_name if user.first_name else "User"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Hey, my username is {username}."}
    ]
    completion = client.chat.completions.create(
        model="gpt-4",
        messages=messages
    )
    llm_response = completion.choices[0].message.content
    logger.info("Start, GPT Response: %s", llm_response)

    context.user_data['messages'] = messages

    await update.message.reply_text(llm_response)
    await ask_recent_use(update, context)
    return RECENT_USE

async def yes_continue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'Yes, continue' to recent substance use.", user.first_name)
    messages = context.user_data.get('messages', [])
    messages.append({"role": "user", "content": "Yes, I have used recently and I want to continue the conversation."})
    context.user_data['messages'] = messages
    return await listen(update, context)

async def no_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("%s responded 'No, exit' to recent substance use.", user.first_name)
    await update.message.reply_text("Thank you for your response. Take care!", reply_markup=ReplyKeyboardRemove())
    return END

async def listen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    username = user.username if user.username else "User"
    logger.info(f"Listening: @{username}: {update.message.text}")

    messages = context.user_data.get('messages', [])
    messages.append({"role": "user", "content": update.message.text})

    logger.info(f"To GPT: {messages}")
    completion = client.chat.completions.create(
        model="gpt-4",
        messages=messages
    )

    llm_response = completion.choices[0].message.content
    logger.info("GPT Response: %s", llm_response)

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
    logger.info(f"Response Received: {messages}")
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

    prompt = JOURNAL_PROMPT + "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    completion = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": JOURNAL_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )

    journal_entry = completion.choices[0].message.content
    logger.info("Journal Entry: %s", journal_entry)

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

def main() -> None:
    application = Application.builder().token("6308464888:AAHERpabVtNcFPDLuVzUG-Oq_W2CU1-ITeA").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            RECENT_USE: [
                CommandHandler("yes", recent_use_yes),
                CommandHandler("no", recent_use_no),
            ],
            LISTEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, listen),
                CommandHandler("journal", journal),
                CommandHandler("end", end),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,  # Add this line
    )

    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()