"""Shim -> openclaw/plugin_sdk.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.plugin_sdk")
_sys.modules[__name__] = _mod
if __name__ == "__main__":
    _mod.main()
