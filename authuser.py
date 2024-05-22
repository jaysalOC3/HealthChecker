import sqlite3
import logging
import argparse

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARN
)
logging.getLogger("httpx").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_USER_ID = 7133140884
ADMIN_TOKEN = "123456"

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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Authorize a user and generate LLM responses.')
    parser.add_argument('username', type=str, help='Username of the user', nargs='?')
    parser.add_argument('--token', type=str, help='Token for the user')

    args = parser.parse_args()

    if args.username is None:
        # No arguments provided, add the admin user by default
        create_authorized_user(ADMIN_USER_ID, ADMIN_TOKEN)
        print("Admin user has been set. Please provide the username and token for other users.")
    else:
        user_id = args.username
        token = args.token
        create_authorized_user(user_id, token)