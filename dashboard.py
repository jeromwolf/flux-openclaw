"""Shim -> openclaw/dashboard_server.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.dashboard_server")
_sys.modules[__name__] = _mod
if __name__ == "__main__":
    _mod.run_dashboard()
