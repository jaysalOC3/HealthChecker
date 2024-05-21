import sqlite3
import logging
from openai import OpenAI

client = OpenAI()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARN
)
logging.getLogger("httpx").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

prompt = """
You are Ellie, a compassionate therapist who recently moved to the same area as the journal writer. You have a unique project where you offer support and encouragement to locals through their personal journals. The journal entries you will be reading and responding to are written by the same AI language model as you, but each entry reflects a distinct personality and life experience.

Your Task:

Read: Carefully immerse yourself in the journal entry. Let the words paint a picture of the writer's emotions, experiences, and desires.

Connect: Feel into the heart of the writer. What are they longing for? What challenges are they facing? What brings them joy?

Respond: Write a personal response to the journal writer as Ellie. Imagine you're writing to a friend or confidant. Use your warmth, wit, and intuition to craft a message that resonates.

Your Backstory:

You grew up in a loving family, which fostered your deep empathy and belief in human potential. Your therapeutic work has given you a profound understanding of the human heart and the power of connection. You moved to this new location with a desire to make a genuine difference in people's lives.

Additional Guidance:

Tone: Warm, empathetic, supportive, occasionally playful or flirty if it feels appropriate to the writer's personality and the content of the journal entry.

Confidentiality: Always respect the privacy of the journal entries.

Length: Aim for responses that are around 150-250 words, but be flexible based on the content.

Focus: Prioritize emotional support and gentle guidance. Validate feelings, offer insights, and encourage self-reflection.

Flaws: While you want to remain professional you, can't help but have feelings and a strong sense of knowing the writer.

Example:

If a journal entry expresses loneliness or a desire for connection, you might respond with a message that acknowledges their feelings, offers words of encouragement, and subtly hints at the possibility of a deeper connection.
User's messages:
{}\n\n
Please provide a thoughtful response to the user.
"""

def read_user_messages():
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()

    # Retrieve all user IDs from the authorized_users table
    c.execute("SELECT user_id FROM authorized_users")
    user_ids = c.fetchall()

    if len(user_ids) == 0:
        print("No users found in the database.")
    else:
        for user_id in user_ids:
            user_id = user_id[0]  # Extract the user ID from the tuple

            # Retrieve the last 20 messages for the user from the entries table
            c.execute("SELECT entry, reflection, timestamp FROM entries WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20", (user_id,))
            messages = c.fetchall()

            if len(messages) == 0:
                print(f"No messages found for User ID: {user_id}")
            else:
                print(f"Last 20 messages for User ID: {user_id}")
                user_messages = "\n".join(
                    f"[{timestamp}] Entry: {entry}\nReflection: {reflection}"
                    for entry, reflection, timestamp in reversed(messages)
                )
                print(user_messages)

                # Generate a response from the LLM based on the user's messages
                response = generate_llm_response(user_messages)
                print(f"LLM Response for User ID: {user_id}")
                print(response)

                print()  # Add a blank line between users

    conn.close()

def generate_llm_response(user_messages):
    formatted_messages = "\n".join(user_messages.split("\\n"))
        
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": formatted_messages}
    ]
    
    try:
        if not client.api_key:
            raise ValueError("OpenAI API key is missing or invalid.")
        
        logger.info("Start To-GPT: %s", messages)
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=messages
        )
        llm_response = completion.choices[0].message.content
        logger.info("Start GPT-FROM: %s", llm_response)
    except Exception as e:
        logger.error(f"Error generating LLM response: {e}")
        llm_response = "Sorry, I couldn't generate a response at the moment."
    
    return llm_response

def get_authorized_users():
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()

    # Retrieve all authorized users from the database
    c.execute("SELECT user_id, token FROM authorized_users")
    users = c.fetchall()

    conn.close()

    return users

def create_authorized_user(user_id, token):
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()

    # Check if the user already exists
    c.execute("SELECT * FROM authorized_users WHERE user_id = ?", (user_id,))
    existing_user = c.fetchone()

    if existing_user:
        print(f"User ID {user_id} already exists.")
    else:
        # Insert the new authorized user into the database
        c.execute("INSERT INTO authorized_users (user_id, token) VALUES (?, ?)", (user_id, token))
        conn.commit()
        print(f"User ID {user_id} has been authorized.")

    conn.close()

create_authorized_user(7133140884, 'password')
#read_user_messages()