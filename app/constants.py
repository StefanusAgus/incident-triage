"""Static application values; runtime settings live in config.py."""

APP_TITLE = "Incident Triage"

DEFAULT_LLM_MODEL = "gpt-4.1-mini"
DEFAULT_LLM_TIMEOUT_SECONDS = 30
MAX_LLM_TIMEOUT_SECONDS = 300
DEFAULT_DATABASE_URL = "sqlite:///./data/incidents.db"
DEFAULT_PORT = 8000
MIN_PORT = 1
MAX_PORT = 65535
MIN_MODEL_NAME_LENGTH = 1
MIN_LLM_TIMEOUT = 0
