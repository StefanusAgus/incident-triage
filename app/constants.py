"""Static application values; runtime settings live in config.py."""

from enum import StrEnum

APP_TITLE = "Incident Triage"

DEFAULT_LLM_MODEL = "gpt-4.1-mini"
DEFAULT_LLM_TIMEOUT_SECONDS = 30
MAX_LLM_TIMEOUT_SECONDS = 300
DEFAULT_DATABASE_URL = "sqlite:///./data/incidents.db"
DEFAULT_DATA_PATH = "data/incidents.json"
DEFAULT_PORT = 8000
MIN_PORT = 1
MAX_PORT = 65535
MIN_MODEL_NAME_LENGTH = 1
MIN_LLM_TIMEOUT = 0


class Environment(StrEnum):
    DEV = "dev"
    QA = "qa"
    STAGE = "stage"
    PROD = "prod"


class Severity(StrEnum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"
