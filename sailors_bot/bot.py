from datetime import date
import logging
import os

import requests
from requests import PreparedRequest, Response
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext


logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MY_VISIT_BASE_URL = os.getenv("MY_VISIT_BASE_URL")
MY_VISIT_MAX_RESULTS = os.getenv("MY_VISIT_MAX_RESULTS", 31)
MY_VISIT_ACCESS_TOKEN = os.getenv("MY_VISIT_ACCESS_TOKEN")

registered_users = {}


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
        if data.get("Results"):
            for available_date in data.get("Results", []):
                available_dates.append(available_date.get("calendarDate"))

    except Exception as e:
        logger.error(f"failed getting dates {e}")

    return available_dates


def register(update: Update, context: CallbackContext) -> None:
    registered_users.update({update.message.chat_id: {"first_name": update.message.chat.first_name,
                                                      "last_name": update.message.chat.last_name}})

    update.message.reply_text(
        "Hi! Registered successfully - we will notify you once myvisit.com is available for registration"
    )


def unregister(update: Update, context: CallbackContext) -> None:
    registered_users.pop(update.message.chat_id)
    update.message.reply_text(
        "Hi! Removed Registration successfully - Hope you passed the exam :)"
    )


def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Use /register to get notified once myvisit is available for registration")
    update.message.reply_text("Use /unregister to stop receiving notification")


def echo(update: Update, context: CallbackContext) -> None:
    """Echo the user message."""
    update.message.reply_text(update.message.text)


def main():
    available_dates = get_myvisit_dates()
    updater = Updater(TELEGRAM_TOKEN, use_context=True)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("register", register))
    dispatcher.add_handler(CommandHandler("unregister", unregister))
    dispatcher.add_handler(CommandHandler("help", help_command))

    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))

    updater.start_polling()

    if available_dates:
        for chat_id, user in registered_users.items():
            logger.info(f"sending notification to {user.get('first_name')}, {user.get('last_name')} chat_id: {chat_id}")
            updater.bot.send_message(chat_id, f"New dates available {available_dates}")

    updater.idle()


if __name__ == "__main__":
    main()
