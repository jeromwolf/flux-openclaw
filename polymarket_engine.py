"""Shim -> trading/polymarket_engine.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("trading.polymarket_engine")
_sys.modules[__name__] = _mod
