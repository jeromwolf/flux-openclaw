"""Shim -> openclaw/knowledge_base.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.knowledge_base")
_sys.modules[__name__] = _mod
