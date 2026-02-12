"""Shim -> bots/discord_bot.py"""
import importlib as _importlib, sys as _sys
_mod = _importlib.import_module("bots.discord_bot")
_sys.modules[__name__] = _mod
if __name__ == "__main__":
    _mod.main()
