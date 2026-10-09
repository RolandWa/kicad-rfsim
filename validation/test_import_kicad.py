"""Check that the plugin modules import in the Python of an installed KiCad.

The package `__init__` registers the action plugin and asserts outside of
KiCad, so the modules are imported one by one under a stand-in package. Run
it with the python of each KiCad version, on the repository:

    "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe"  test_import_kicad.py
    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" test_import_kicad.py

A GUI session is still needed to test the dialog and the result viewer.
"""
import importlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
MODULES = ("solverenv", "board_reader", "gui", "rfsim", "rfsim_viewer",
           "rfsim_compare")


def main(plugins=PLUGINS):
    pkg = types.ModuleType("rfsim_pkg")
    pkg.__path__ = [plugins]
    sys.modules["rfsim_pkg"] = pkg
    sys.path.insert(0, plugins)
    import pcbnew
    for name in MODULES:
        importlib.import_module("rfsim_pkg." + name)
    print("KiCad %s: %d modules import OK" % (pcbnew.GetBuildVersion(), len(MODULES)))
    print("PASS")


if __name__ == "__main__":
    main(*sys.argv[1:2])
