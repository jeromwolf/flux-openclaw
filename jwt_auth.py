"""Shim -> openclaw/jwt_auth.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.jwt_auth")
_sys.modules[__name__] = _mod
