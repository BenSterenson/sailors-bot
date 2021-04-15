from typing import Dict
from datetime import date
from datetime import timedelta
from collections import defaultdict
import logging
import os

import requests
import psycopg2
import psycopg2.errors

from requests import PreparedRequest, Response
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, PrefixHandler

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MY_VISIT_BASE_URL = os.getenv("MY_VISIT_BASE_URL")
MY_VISIT_MAX_RESULTS = os.getenv("MY_VISIT_MAX_RESULTS", 31)
MY_VISIT_ACCESS_TOKEN = os.getenv("MY_VISIT_ACCESS_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))

SERVICE_IDS = {
    6142: "סניף תל-אביב בחינה ממוחשבת",
    6140: "סניף חיפה בחינה ממוחשבת",
    6143: "סניף חיפה בחינה בכתב",
    6148: "סניף תל-אביב בחינה בכתב",
    6141: "סניף טבריה בחינה ממוחשבת",
}

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
updater = Updater(TELEGRAM_TOKEN, use_context=True)


def get_access_token():
    return MY_VISIT_ACCESS_TOKEN


def send_request(prepared_request: PreparedRequest) -> Response:
    session = requests.Session()
    return session.send(request=prepared_request)


def prepare_request(access_token: str, service_id: int) -> PreparedRequest:
    request = requests.Request("GET", MY_VISIT_BASE_URL)

    request.headers["Authorization"] = f"JWT {access_token}"
    request.params["maxResults"] = MY_VISIT_MAX_RESULTS
    request.params["startDate"] = str(date.today() + timedelta(days=1))
    request.params["serviceId"] = service_id

    return request.prepare()


def get_myvisit_dates():
    available_dates = defaultdict(list)
    for service_id in SERVICE_IDS:
        try:
            response = send_request(prepare_request(get_access_token(), service_id))
            data = response.json()
            logger.info(f"dates: {data}")
            if data.get("Results"):
                for available_date in data.get("Results", []):
                    available_dates[service_id].append(available_date.get("calendarDate"))

        except Exception as e:
            logger.error(f"failed getting dates {e}")

    return available_dates


def get_all_users():
    registered_users = []
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("select chat_id, first_name, last_name, registered_services from sailors")
            registered_users = cursor.fetchall()
    except Exception as e:
        updater.bot.send_message(ADMIN_CHAT_ID, f"failed getting all users - see logs")
        logger.error(f"failed getting dates {e}")

    return registered_users


def format_msg(personal_dates: Dict) -> str:
    personal_msg = "מצאתי תאריכים חדשים ל"
    for name, dates in personal_dates.items():
        personal_msg += f"{name} : {dates}"
    return personal_msg


def notify_registered_users(updater: Updater, available_dates: defaultdict):
    if not available_dates:
        return

    registered_users = get_all_users()

    for chat_id, first_name, last_name, registered_services in registered_users:
        personal_dates = {}
        registered_services = [] if registered_services is None else registered_services
        for service in registered_services:
            if service in available_dates:
                name = SERVICE_IDS.get(service)
                personal_dates[name] = available_dates[service]

        if personal_dates:
            personal_msg = format_msg(personal_dates)

            logger.info(f"sending notification to {first_name}, {last_name} chat_id: {chat_id} dates {personal_dates}")
            updater.bot.send_message(chat_id, f"היי {first_name}, {personal_msg} הרשמה ב myvisit.com")


def update_user_status(chat_id: int, registered_services):
    if not registered_services:
        registered_services = {}

    with conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE sailors SET registered_services='{registered_services}' WHERE chat_id={chat_id}")


def get_registered_services(chat_id: int):
    registered_services = set()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT registered_services from sailors WHERE chat_id={chat_id}")
            [(services,)] = cursor.fetchall()
            registered_services = set(services)
    except Exception as e:
        logger.error(f"failed getting registered_services for {chat_id} - {e}")

    return set(registered_services)


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
    services = context_to_services(" ".join(context.args))
    registered_services = get_registered_services(chat_id)
    services_to_keep = registered_services.union(services)
    registered_services_text = ", ".join(SERVICE_IDS.get(service_id) for service_id in services_to_keep)
    success_msg = f"נרשמת בהצלחה לקבלת התראות על מועדי מבחן ב{registered_services_text}. נעדכן אותך ברגע שנזהה תאריך פנוי ב myvisit.com "

    first_name = update.message.chat.first_name or ""
    last_name = update.message.chat.last_name or ""
    success = False
    try:
        with conn:
            cur = conn.cursor()
            command = f"INSERT INTO sailors(chat_id, first_name, last_name, is_registered, registered_services) VALUES({chat_id}, '{first_name}', '{last_name}', TRUE, '{services_to_keep}')"
            cur.execute(command)

        success = True
        update.message.reply_text(success_msg)

    except psycopg2.errors.lookup("23505"):
        update_user_status(chat_id=chat_id, registered_services=services_to_keep)
        success = True
        update.message.reply_text(success_msg)

    except Exception as e:
        logger.error(f"failed inserting user {chat_id} {first_name} {last_name} error - {e}")

    updater.bot.send_message(
        ADMIN_CHAT_ID, f"Registration request {chat_id} {first_name} {last_name} success: {success}"
    )


def context_to_services(context):
    services = set()
    if "ממוחשב" in context:
        if "תא" in context or "תל אביב" in context or "תל-אביב" in context or "תל אביב" in context:
            services.add(6142)
        if "חיפה" in context:
            services.add(6140)
        if "טבריה" in context:
            services.add(6141)

    elif "כתב" in context:
        if "תא" in context:
            services.add(6148)
        if "חיפה" in context:
            services.add(6143)
    elif "כללי" in context:
        services = set(SERVICE_IDS.keys())

    return services


def unregister(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    services_to_remove = context_to_services(" ".join(context.args))
    registered_services = get_registered_services(chat_id)
    services_to_keep = registered_services - services_to_remove
    success = False
    try:
        update_user_status(chat_id=chat_id, registered_services=services_to_keep)
        success = True
        removed_services_text = ", ".join(SERVICE_IDS.get(service_id) for service_id in services_to_remove)
        update.message.reply_text(f"אוקי, אנחנו נפסיק לשלוח לך התראות על מועדי בחינה ב{removed_services_text}")
    except Exception as e:
        logger.error(f"failed to Removed Registration {chat_id} error - {e}")

    updater.bot.send_message(ADMIN_CHAT_ID, f"remove request {chat_id} success: {success}")


def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        """הפקודות הבאות זמינות:

רישום [עיר - (תל אביב, חיפה, טבריה)] [סוג מבחן - (ממוחשב, בכתב)]


הסר [עיר - (תל אביב, חיפה, טבריה)] [סוג מבחן - (ממוחשב, בכתב)]

דוגמאות:

רישום תל אביב ממוחשב
רישום תל אביב חיפה ממוחשב
רישום טבריה ממוחשב
רישום תל אביב חיפה בכתב
רישום כללי


הסר תל אביב ממוחשב
הסר תל אביב חיפה ממוחשב
הסר תל אביב חיפה בכתב
הסר כללי
"""
    )


def echo(update: Update, context: CallbackContext) -> None:
    """Echo the user message."""
    update.message.reply_text(update.message.text)


def main():
    available_dates = get_myvisit_dates()

    dispatcher = updater.dispatcher

    dispatcher.add_handler(PrefixHandler("", "רישום", register))
    dispatcher.add_handler(PrefixHandler("", "הסר", unregister))
    dispatcher.add_handler(CommandHandler("get_raw_response", get_raw_response))
    dispatcher.add_handler(CommandHandler("help", help_command))

    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, help_command))

    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=WEBHOOK_URL + TELEGRAM_TOKEN,
    )

    notify_registered_users(updater, available_dates)

    updater.idle()


if __name__ == "__main__":
    main()
