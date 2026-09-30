"""Headless GUI tests; never open a desktop window during automated runs."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
