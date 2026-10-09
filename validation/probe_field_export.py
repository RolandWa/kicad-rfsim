"""The field export buttons of the result window, run the way KiCad runs the plugin.

KiCad imports the plugin as a PACKAGE, and its folder is not on sys.path. A plain
`from rfsim_viewer import ...` inside gui.py then raised ModuleNotFoundError: the button
"Save Field Animation" did nothing and gave no message. This script imports gui as a member
of a package (a stand-in package whose path is the plugin folder, which is not put on
sys.path), presses the buttons with the file dialog and the message box replaced, and prints
one line for each result. test_four_layer.py runs it and reads the lines.

    python probe_field_export.py <plugin folder> <run folder> <output folder>

Run it with the python of KiCad (wx, pcbnew).
"""
import importlib
import os
import shutil
import sys
import tempfile
import traceback
import types

plug, run, out = (os.path.abspath(a) for a in sys.argv[1:4])
os.makedirs(out, exist_ok=True)
pkg = types.ModuleType("rfsim_pkg")
pkg.__path__ = [plug]
sys.modules["rfsim_pkg"] = pkg
assert plug not in sys.path, "the plugin folder must NOT be on sys.path for this test"

import wx  # noqa: E402

app = wx.App(False)
gui = importlib.import_module("rfsim_pkg.gui")
messages = []
wx.MessageBox = lambda msg, *a, **k: messages.append(str(msg)) or 0
target = {"path": None}


class FakeDialog:
    def __init__(self, *a, **k):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def GetPath(self):
        return target["path"]

    def GetPaths(self):
        return [target["path"]]

    def Destroy(self):
        pass


wx.FileDialog = FakeDialog
work = tempfile.mkdtemp(prefix="field_probe_")
for name in ("results.s2p", "model.json", "lines.json"):
    if os.path.isfile(os.path.join(run, name)):
        shutil.copy(os.path.join(run, name), work)
for d in os.listdir(run):
    if d.startswith("exc") and os.path.isdir(os.path.join(run, d)):
        shutil.copytree(os.path.join(run, d), os.path.join(work, d), ignore=shutil.ignore_patterns("port_*", "et", "ht"))
frame = gui.ResultsFrame(None, os.path.join(work, "results.s2p"))
views = list(frame.choice.GetStrings())


def press(kind, what):
    idx = next(i for i, v in enumerate(views) if v.startswith(kind + "-Field"))
    frame.choice.SetSelection(idx)
    frame._plot()
    del messages[:]
    try:
        if what == "animation":
            target["path"] = os.path.join(out, "%s_animation.gif" % kind)
            if os.path.exists(target["path"]):
                os.remove(target["path"])
            frame._save_field_animation(None)
            ok = os.path.isfile(target["path"]) and os.path.getsize(target["path"]) > 2000
        else:
            frame._export_field_paraview(None)
            ok = any(f.endswith(".xdmf") for _, _, fs in os.walk(work) for f in fs)
        err = [m for m in messages if m.lower().startswith("could not") or "cannot be loaded" in m]
        print("%s %s: %s%s" % (kind, what, "OK" if ok and not err else "FAILED", " " + err[0][:140] if err else ""))
    except Exception:
        print("%s %s: RAISED (the user sees nothing): %s" % (kind, what, traceback.format_exc().strip().splitlines()[-1]))


for kind in ("E", "H"):
    press(kind, "animation")
press("E", "paraview")
shutil.rmtree(work, ignore_errors=True)
