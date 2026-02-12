"""Shim -> trading/survival_sim.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("trading.survival_sim")
_sys.modules[__name__] = _mod
if __name__ == "__main__":
    _mod.main()
