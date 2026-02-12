"""Shim -> openclaw/rate_limiter.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.rate_limiter")
_sys.modules[__name__] = _mod
