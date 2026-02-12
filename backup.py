"""Shim -> openclaw/backup.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.backup")
_sys.modules[__name__] = _mod
