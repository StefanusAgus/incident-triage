"""Static application values; runtime settings live in config.py."""

from enum import StrEnum

APP_TITLE = "Incident Triage"

DEFAULT_LLM_MODEL = "gpt-4.1-mini"
DEFAULT_LLM_TIMEOUT_SECONDS = 30
MAX_LLM_TIMEOUT_SECONDS = 300
DEFAULT_LLM_MAX_RETRIES = 2
MAX_LLM_MAX_RETRIES = 5
DEFAULT_DATABASE_URL = "sqlite:///./data/incidents.db"
DEFAULT_DATA_PATH = "data/incidents.json"
DEFAULT_PORT = 8000
MIN_PORT = 1
MAX_PORT = 65535
MIN_MODEL_NAME_LENGTH = 1
MIN_LLM_TIMEOUT = 0

DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 50
MAX_SEARCH_QUERY_LENGTH = 500
MAX_FILTER_VALUE_LENGTH = 100
MAX_FILTER_TAGS = 10
SEARCH_TITLE_WEIGHT = 5.0
SEARCH_SNIPPET_TOKENS = 32
MAX_SNIPPET_LENGTH = 240
ASSIST_CANDIDATE_LIMIT = 10
ASSIST_MAX_OUTPUT_TOKENS = 1200
MAX_ASSIST_QUESTION_LENGTH = 1000
CORRELATION_ID_HEADER = "X-Correlation-ID"
MAX_CORRELATION_ID_LENGTH = 128
MAX_TRACE_EVENTS_PER_ID = 100

# Keep technical/causal words such as "not", "out", and "after" searchable.
SEARCH_STOPWORDS = frozenset({
    "a", "an", "are", "did", "do", "does", "how", "is", "the", "was", "were",
    "what", "when", "where", "which", "who", "why",
})


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
