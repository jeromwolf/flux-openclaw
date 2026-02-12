"""Shim -> openclaw/cost_tracker.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.cost_tracker")
_sys.modules[__name__] = _mod
