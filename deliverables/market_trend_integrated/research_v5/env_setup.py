import os
from pathlib import Path
from dotenv import load_dotenv
ENV_PATH = str(Path(__file__).resolve().parents[1] / ".env")
def load_env():
    load_dotenv(ENV_PATH, override=False)
