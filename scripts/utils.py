"""
apa_cis/utils.py
Shared utilities for the APA-CIS data pipeline.
DA RFO 02 — Climate Information Service, Cagayan Valley
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


# ── Project root detection ────────────────────────────────────────────────────
def get_project_root() -> Path:
    """Return the project root directory (where config/ lives)."""
    current = Path(__file__).resolve()
    for parent in [current, *current.parents]:
        if (parent / "config" / "settings.yaml").exists():
            return parent
    # Fallback: CWD
    return Path.cwd()


PROJECT_ROOT = get_project_root()


# ── Config loading ────────────────────────────────────────────────────────────
_config_cache: Optional[Dict] = None


def load_config() -> Dict:
    """Load and cache settings.yaml."""
    global _config_cache
    if _config_cache is None:
        config_path = PROJECT_ROOT / "config" / "settings.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def load_municipalities() -> List[Dict]:
    """Load municipalities.json."""
    mun_path = PROJECT_ROOT / "config" / "municipalities.json"
    with open(mun_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Logging ───────────────────────────────────────────────────────────────────
def setup_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure a named logger with both console and rotating file handlers.

    Args:
        name: Logger name (usually __name__ of calling module)
        log_file: Optional filename inside logs/. Defaults to <name>.log
    """
    cfg = load_config()
    log_dir = PROJECT_ROOT / cfg["paths"]["logs"]
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler
    fname = log_file or f"{name.split('.')[-1]}.log"
    fh = logging.FileHandler(log_dir / fname, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ── Date helpers ─────────────────────────────────────────────────────────────
def today_pht() -> date:
    """Return today's date in Philippine Standard Time (UTC+8)."""
    return (datetime.utcnow() + timedelta(hours=8)).date()


def date_range(start: Union[str, date], end: Union[str, date]) -> List[date]:
    """Return list of dates from start to end inclusive."""
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(end, str):
        end = date.fromisoformat(end)
    delta = (end - start).days
    return [start + timedelta(days=i) for i in range(delta + 1)]


def nasa_date_key(d: Union[str, date]) -> str:
    """Convert date to NASA POWER key format: YYYYMMDD."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%Y%m%d")


def iso_date(d: Union[str, date]) -> str:
    """Ensure ISO format YYYY-MM-DD."""
    if isinstance(d, date):
        return d.isoformat()
    return d


# ── File I/O ──────────────────────────────────────────────────────────────────
def save_json(data: Any, path: Union[str, Path], indent: int = 2) -> None:
    """Save data as JSON, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, default=str)


def load_json(path: Union[str, Path]) -> Any:
    """Load JSON file. Returns None if file does not exist."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(record: Dict, path: Union[str, Path]) -> None:
    """Append a single record to a JSONL (newline-delimited JSON) log file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def retry_get(
    url: str,
    params: Optional[Dict] = None,
    retries: int = 3,
    delay: float = 5.0,
    timeout: int = 45,
    logger: Optional[logging.Logger] = None,
) -> Optional[Any]:
    """
    GET request with exponential back-off retry.
    Returns response object on success, None on failure.
    """
    import requests

    log = logger or logging.getLogger("utils.http")
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            wait = delay * (2 ** (attempt - 1))
            log.warning(
                f"Attempt {attempt}/{retries} failed for {url}: {exc}. "
                f"Retrying in {wait:.0f}s..."
            )
            if attempt < retries:
                time.sleep(wait)
    log.error(f"All {retries} attempts failed for {url}")
    return None


# ── Data validation ───────────────────────────────────────────────────────────
FILL_VALUE = -999.0  # NASA POWER uses -999 for missing


def is_valid(value: Any, min_val: float = -200.0, max_val: float = 5000.0) -> bool:
    """Check if a numeric value is valid (not fill value, not NaN, in range)."""
    try:
        v = float(value)
        if v == FILL_VALUE or v != v:  # NaN check
            return False
        return min_val <= v <= max_val
    except (TypeError, ValueError):
        return False


def clean_value(
    value: Any,
    min_val: float = -200.0,
    max_val: float = 5000.0,
    default: Optional[float] = None,
) -> Optional[float]:
    """Return cleaned float or default if invalid."""
    if is_valid(value, min_val, max_val):
        return float(value)
    return default


def validate_rainfall(mm: Any) -> Optional[float]:
    return clean_value(mm, min_val=0.0, max_val=1500.0)


def validate_temperature(c: Any) -> Optional[float]:
    return clean_value(c, min_val=-10.0, max_val=55.0)


def validate_humidity(pct: Any) -> Optional[float]:
    return clean_value(pct, min_val=0.0, max_val=100.0)


def validate_wind(ms: Any) -> Optional[float]:
    return clean_value(ms, min_val=0.0, max_val=100.0)


# ── ETL logging ───────────────────────────────────────────────────────────────
def log_etl_event(
    source: str,
    run_date: str,
    records_fetched: int,
    records_valid: int,
    status: str,
    message: str = "",
    log_path: Optional[Path] = None,
) -> None:
    """Append an ETL run event to the metadata log (JSONL)."""
    if log_path is None:
        cfg = load_config()
        log_path = PROJECT_ROOT / cfg["paths"]["logs"] / "etl_runs.jsonl"
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "source": source,
        "run_date": run_date,
        "records_fetched": records_fetched,
        "records_valid": records_valid,
        "status": status,
        "message": message,
    }
    append_jsonl(record, log_path)


# ── Province helpers ──────────────────────────────────────────────────────────
def municipalities_by_province(province: str) -> List[Dict]:
    """Filter municipality list by province name."""
    return [m for m in load_municipalities() if m["province"] == province]


def get_municipality(psgc: str) -> Optional[Dict]:
    """Lookup a municipality by PSGC code."""
    for m in load_municipalities():
        if m["psgc"] == psgc:
            return m
    return None


PROVINCES = ["Batanes", "Cagayan", "Isabela", "Nueva Vizcaya", "Quirino"]
