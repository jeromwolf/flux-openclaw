"""Shim -> openclaw/onboarding.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.onboarding")
_sys.modules[__name__] = _mod
