import os
import logging
from concurrent.futures import ThreadPoolExecutor

import anthropic
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from skills import feedback, qa, reminders

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

slack_app = App(token=os.environ["SLACK_BOT_TOKEN"])
claude    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
_pool     = ThreadPoolExecutor(max_workers=8)
scheduler = BackgroundScheduler(timezone="Asia/Dubai")

reminders.register(slack_app, scheduler)
qa.register(slack_app, _pool, claude, scheduler)
feedback.register(slack_app)

if __name__ == "__main__":
    logger.info("Starting UAEOPS Bot")
    scheduler.start()
    reminders.load_pending(scheduler)
    qa.start_background_sync(scheduler, _pool)
    logger.info("Bot ready. Connecting to Slack via Socket Mode...")
    SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"]).start()
