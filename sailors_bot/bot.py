from typing import List
from datetime import date
import logging
import os

import requests
import psycopg2
import psycopg2.errors

from requests import PreparedRequest, Response
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext


logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MY_VISIT_BASE_URL = os.getenv("MY_VISIT_BASE_URL")
MY_VISIT_MAX_RESULTS = os.getenv("MY_VISIT_MAX_RESULTS", 31)
MY_VISIT_ACCESS_TOKEN = os.getenv("MY_VISIT_ACCESS_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")


conn = psycopg2.connect(DATABASE_URL, sslmode="require")
updater = Updater(TELEGRAM_TOKEN, use_context=True)


def get_access_token():
    return MY_VISIT_ACCESS_TOKEN


def send_request(prepared_request: PreparedRequest) -> Response:
    session = requests.Session()
    return session.send(request=prepared_request)


def prepare_request(access_token: str) -> PreparedRequest:
    request = requests.Request("GET", MY_VISIT_BASE_URL)

    request.headers["Authorization"] = f"JWT {access_token}"
    request.params["maxResults"] = MY_VISIT_MAX_RESULTS
    request.params["startDate"] = str(date.today())
    request.params["serviceId"] = 6142

    return request.prepare()


def get_myvisit_dates():
    available_dates = []
    try:
        response = send_request(prepare_request(get_access_token()))
        data = response.json()
        logger.info(f"dates: {data}")
        if data.get("Results"):
            for available_date in data.get("Results", []):
                available_dates.append(available_date.get("calendarDate"))

    except Exception as e:
        logger.error(f"failed getting dates {e}")

    return available_dates


def notify_registered_users(updater: Updater, available_dates: List):
    if available_dates:
        with conn:
            cursor = conn.cursor()
            cursor.execute("select chat_id, first_name, last_name from sailors where is_registered = TRUE")

            registered_users = cursor.fetchall()

            for chat_id, first_name, last_name in registered_users:
                logger.info(f"sending notification to {first_name}, {last_name} chat_id: {chat_id}")
                updater.bot.send_message(chat_id, f"New dates available {available_dates}")


def update_user_status(chat_id: int, status: bool):
    with conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE sailors SET is_registered={status} WHERE chat_id={chat_id}")


def get_raw_response(update: Update, context: CallbackContext):
    try:
        response = send_request(prepare_request(get_access_token()))
        update.message.reply_text(f"Raw response: {response.content}")

        data = response.json()
        update.message.reply_text(f"Json Raw response: {data}")

    except Exception as e:
        update.message.reply_text(f"failed getting dates {e}")
        logger.error(f"failed getting dates {e}")


def register(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    first_name = update.message.chat.first_name or ""
    last_name = update.message.chat.last_name or ""
    success = False
    try:
        with conn:
            cur = conn.cursor()
            command = f"INSERT INTO sailors(chat_id, first_name, last_name, is_registered) VALUES({chat_id}, '{first_name}', '{last_name}', TRUE)"
            cur.execute(command)

        success = True
        update.message.reply_text(
            "Hi! Registered successfully - we will notify you once myvisit.com is available for registration"
        )

    except psycopg2.errors.lookup("23505"):
        update_user_status(chat_id=chat_id, status=True)
        success = True
        update.message.reply_text(
            "Hi! Registered successfully - we will notify you once myvisit.com is available for registration"
        )

    except Exception as e:
        logger.error(f"failed inserting user {chat_id} {first_name} {last_name} error - {e}")

    updater.bot.send_message(
        ADMIN_CHAT_ID, f"Registration request {chat_id} {first_name} {last_name} success: {success}"
    )


def unregister(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    success = False
    try:
        update_user_status(chat_id=chat_id, status=False)
        success = True
        update.message.reply_text("Hi! Removed Registration successfully - Hope you passed the exam :)")
    except Exception as e:
        logger.error(f"failed to Removed Registration {chat_id} error - {e}")

    updater.bot.send_message(
        ADMIN_CHAT_ID, f"remove request {chat_id} success: {success}"
    )


def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Use /register to get notified once myvisit is available for registration\nUse /unregister to stop receiving notification"
    )


def echo(update: Update, context: CallbackContext) -> None:
    """Echo the user message."""
    update.message.reply_text(update.message.text)


def main():
    available_dates = get_myvisit_dates()

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("register", register))
    dispatcher.add_handler(CommandHandler("get_raw_response", get_raw_response))
    dispatcher.add_handler(CommandHandler("unregister", unregister))
    dispatcher.add_handler(CommandHandler("help", help_command))

    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, help_command))

    updater.start_polling()

    notify_registered_users(updater, available_dates)

    updater.idle()


if __name__ == "__main__":
    main()
