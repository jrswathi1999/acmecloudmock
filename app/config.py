"""Runtime settings. Values come from the server's environment, never from code."""
import os


def payments_api_url() -> str:
    return os.environ["PAYMENTS_API_URL"]


def admin_keys() -> list:
    raw = os.environ.get("ACME_ADMIN_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def version() -> str:
    return os.environ.get("ACME_VERSION", "dev")


def db_path() -> str:
    return os.environ.get("ACME_DB", os.path.join("data", "shop.db"))


def log_dir() -> str:
    return os.environ.get("ACME_LOG_DIR", "logs")
