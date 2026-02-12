"""Shim -> openclaw/cors.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.cors")
_sys.modules[__name__] = _mod
