import logging
import asyncio
from typing import Optional, Tuple
from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException
from openai import OpenAI
import concurrent.futures  # For thread pool

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logger.info("Starting Bot and Web Server.")

# --- OpenAI Configuration ---
client = OpenAI()  # Initialize OpenAI client
system_message = {
    "role": "system",
    "content": "Your primary goal is to help the user identify potential triggers...",
}

# Chat history storage
chat_history = {}  

app = Flask(__name__)
port = int(os.environ.get("PORT", 8080))

# Use a thread pool executor
executor = concurrent.futures.ThreadPoolExecutor()

@app.route("/checkin", methods=["GET"])
def checkin():
    user_id = request.args.get("user_id")
    # Submit the coroutine to the executor
    executor.submit(asyncio.run, start_checkin_conversation(user_id, application.bot))
    return jsonify({"message": "Check-in conversation initiated"}), 200


async def start_checkin_conversation(user_id, bot):
    try:
        chat_history[user_id] = [system_message]
        await bot.send_message(
            chat_id=-4262702861, text="Hey, I wanted to check in on how you're feeling."
        )
    except Exception as e:
        logger.error(f"Error initiating check-in conversation: {e}")


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text

    # Initialize chat history if not present
    if user_id not in chat_history:
        chat_history[user_id] = [system_message]
        context.bot.send_message(
            chat_id=user_id, text="Hi there! Let's start our conversation."
        )  # Optionally, send a welcome message

    chat_history[user_id].append({"role": "user", "content": message_text})
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo", messages=chat_history[user_id]
    )
    response_message = completion.choices[0].message
    chat_history[user_id].append(response_message)

    context.bot.send_message(chat_id=user_id, text=response_message.content)

class MyHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        query = {}
        if '?' in path:
            path, query_string = path.split('?', 1)
            query = dict(param.split('=') for param in query_string.split('&'))
        
        with app.test_request_context(path=path, query_string=query):
            try:
                response = app.full_dispatch_request()
            except HTTPException as e:
                response = app.make_response(jsonify({'error': str(e)}), e.code)
        
        self.send_response(response.status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(response.get_data())

def main() -> None:
    httpd = ThreadingHTTPServer(("", port), MyHTTPRequestHandler)
    import threading
    httpd_thread = threading.Thread(target=httpd.serve_forever)
    httpd_thread.start()

    global application
    application = Application.builder().token('6308464888:AAFmfSayfq9uUoH4GmLx5sFX_Ebk1C8nhSc').build()
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_user_message)
    application.add_handler(message_handler)

    async def run_bot():
        async with application:
            await application.initialize()  
            await application.start()
            await asyncio.to_thread(httpd.serve_forever)
            await application.stop()
            await application.shutdown()

    # Create a dedicated loop for the bot
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)  

    try:
        bot_loop.run_until_complete(run_bot())
    finally:
        bot_loop.close()


if __name__ == "__main__":
    main()