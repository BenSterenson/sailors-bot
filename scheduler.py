import os
from apscheduler.schedulers.blocking import BlockingScheduler
from sailors_bot.bot import run_bot

scheduler = BlockingScheduler()

INTERVAL_MINUTES = os.getenv("INTERVAL_MINUTES", 0)
INTERVAL_HOURS = os.getenv("INTERVAL_HOURS", 3)


@scheduler.scheduled_job('interval', hours=INTERVAL_HOURS, minutes=INTERVAL_MINUTES)
def scheduled_job():
    run_bot()


scheduler.start()
