"""Shim -> openclaw/llm_provider.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.llm_provider")
_sys.modules[__name__] = _mod
