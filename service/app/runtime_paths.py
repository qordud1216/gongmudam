"""Mutable state may live outside the installed code; desktop paths stay compatible."""
import os
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def state_root():
    value = os.environ.get('GONGMUDAM_DATA_ROOT')
    if not value:
        return SERVICE_ROOT
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError('GONGMUDAM_DATA_ROOT must be an absolute path.')
    return path.resolve()


def no_llm():
    return os.environ.get('GONGMUDAM_NO_LLM') == '1'


def cloud_mode():
    return os.environ.get('GONGMUDAM_CLOUD') == '1'
