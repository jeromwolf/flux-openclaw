"""Shim -> openclaw/api_gateway.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.api_gateway")
_sys.modules[__name__] = _mod
