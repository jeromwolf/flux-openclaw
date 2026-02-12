"""Shim -> openclaw/auth.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.auth")
_sys.modules[__name__] = _mod
