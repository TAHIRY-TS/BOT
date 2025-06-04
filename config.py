import os
from dotenv import load_dotenv

load_dotenv()  # utile en local, inoffensif sur Railway

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x]
