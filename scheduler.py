"""Shim -> openclaw/scheduler.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("openclaw.scheduler")
_sys.modules[__name__] = _mod
if __name__ == "__main__":
    _mod.cli_main()
