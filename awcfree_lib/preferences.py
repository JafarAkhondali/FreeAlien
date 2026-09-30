"""Shared installer/UI preferences. Missing or malformed settings use safe defaults."""
import json
import os
from pathlib import Path


def load_preferences():
    path = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'awcfree/preferences.json'
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
