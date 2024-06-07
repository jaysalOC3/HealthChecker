import os
import logging
# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARNING
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

from datetime import datetime
import sqlite3

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

def generate_start_prompt(agent_prompt, topic):
    logger.warning(f'generate_start_prompt - called')
    logger.info(f'generate_start_prompt - agent_prompt len: {len(agent_prompt)}')
    logger.info(f'generate_start_prompt - topic len: {len(topic)}')
    llminput = FEEDBACK_PROMPT
    logger.info(f'generate_start_prompt- FEEDBACK_PROMPT - called')
    reflectioninput = fetch_reflection_entries(ADMIN_USER_ID)
    logger.info(f'generate_start_prompt - fetch_reflection_entries - called')
    llminput += "ORIGINAL SYSTEM PROMPT:\n" +  agent_prompt + "=== END ORIGINAL SYSTEM PROMPT ===\n\n"
    llminput += "Remember the journal topic: \n" + topic + "\n\n"
    llminput += "CONCIDER THE FEEDBACK FOR IMPROVEMENT:\n"
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

# Database Functions
def create_database():
    logger.warning(f'Checking Database.')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS entries
                     (user_id INTEGER, entry TEXT, reflection TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS authorized_users
                    (user_id INTEGER PRIMARY KEY, 
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                        token TEXT, 
                        bot_name TEXT, 
                        bot_sp TEXT,
                        topic TEXT
                    )''')

def create_user(user_id):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        default_bot_name = "Journal Bot"
        default_bot_sp = START_PROMPT
        c.execute("INSERT INTO authorized_users (user_id, bot_name, bot_sp) VALUES (?, ?, ?)", (user_id, default_bot_name, default_bot_sp))
        conn.commit()

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
        result = c.fetchone()
        return result[0] if result else None
    
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
        c.execute("SELECT bot_sp, topic FROM authorized_users WHERE user_id = ? LIMIT 1", (int(user_id),))
        result = c.fetchone()
        if result:
            return generate_start_prompt(result[0], result[1])
        else:
            return START_PROMPT

def update_bot_sp(user_id, sp, topic):
    logger.warning(f'Update Bot SYSTEM PROMPT:')
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute('''
        UPDATE authorized_users
        SET bot_sp = ?, timestamp = ?, topic = ?
        WHERE user_id = ?
        ''', (sp.replace("'",""), current_timestamp, topic, user_id))

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

def update_bot_topic(user_id, topic):
    logger.warning(f'Update Bot TOPIC / Purpose:')
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute('''
        UPDATE authorized_users
        SET topic = ?, timestamp = ?
        WHERE user_id = ?
        ''', (topic.replace("'",""), current_timestamp, user_id))

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
        entries = c.fetchall()
        if entries:
            logger.warning(f'Fetch Reflection Return:{len(entries)} Reflections Found')
            return [entry[0] for entry in entries]
        else:
            logger.warning(f'Fetch Reflection Entries: Return No Reflections')
            return ["No Reflections"]
    
def insert_journal_entry(user_id, entry, reflection):
    logger.warning(f'Writing Journal Entries:')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO entries (user_id, entry, reflection) VALUES (?, ?, ?)", (user_id, entry, reflection))
        conn.commit()

def insert_authorized_user(user_id, token, bot_name, bot_sp):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO authorized_users (user_id, token, bot_name, bot_sp) VALUES (?, ?, ?, ?)", (user_id, token, bot_name, bot_sp))
        conn.commit()

def is_authorized_user(user_id, token):
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM authorized_users WHERE user_id = ? AND token = ?", (user_id, token))
        result = c.fetchone()
        return result[0] > 0

def user_exists(user_id):
    logger.warning(f'Looking if User Exists: {user_id}')
    with sqlite3.connect('journal_entries.db') as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM authorized_users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        logger.warning(f'DONE - User Exists: {user_id}')
        return result[0] > 0
    

