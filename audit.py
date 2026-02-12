"""Shim -> openclaw/audit.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.audit")
_sys.modules[__name__] = _mod
