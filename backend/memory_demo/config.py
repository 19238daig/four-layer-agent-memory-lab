import os
import json
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
DATA_DIR = Path(os.getenv('MEMORY_DATA_DIR', str(ROOT / 'data')))
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
MODEL = os.getenv('OPENAI_MODEL', 'deepseek-v4.1-flash')
MODEL_EXTRA_BODY = json.loads(os.getenv('OPENAI_EXTRA_BODY', '{}'))
BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').replace('https\\:', 'https:')
API_URL = os.getenv('MEMORY_API_URL', 'http://127.0.0.1:8010')
