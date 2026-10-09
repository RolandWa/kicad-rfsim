"""View Exported Geometry: the model of the preview is the model of the run.

The preview used its own copy of the code that makes the model. With the preset "KiCad's
Stackup" the dialog gives er / tand / h / cu_t = None, and the copy passed them to `extract()`
as a dict of None: the preview stopped with a message about a float and a NoneType.
`rfsim._build_model` is the single code of the run and of the preview now.

The test makes the settings with the real dialog, then (1) builds the model for the board
stackup (None), for a custom substrate and for a subregion, (2) checks that the run and the
preview get the same model, (3) writes the geometry XML with the solver (`runner.py --geometry`).

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" test_preview_geometry.py
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, HERE)

import wx  # noqa: E402

app = wx.App(False)
pkg = types.ModuleType("rfsim_pkg")          # as KiCad imports the plugin: a package, folder not on sys.path
pkg.__path__ = [PLUGINS]
sys.modules["rfsim_pkg"] = pkg
gui = importlib.import_module("rfsim_pkg.gui")
rfsim = importlib.import_module("rfsim_pkg.rfsim")
board_reader = importlib.import_module("rfsim_pkg.board_reader")
solverenv = importlib.import_module("rfsim_pkg.solverenv")
import make_test_board  # noqa: E402


def settings_of(board, pads, outdir):
    pre = board_reader.extract(board, pads, 1.0)
    d = gui.SettingsDialog(None, pre["ports"], outdir, pre.get("lumped_elements", []), preview=pre,
                           packages=board_reader.package_presets(), esr=board_reader.esr_presets())
    s = d.get_settings()
    d.Destroy()
    s["outdir"] = outdir
    return s


def main():
    with tempfile.TemporaryDirectory() as tmp:
        board, pads = make_test_board.make_four_layer(os.path.join(tmp, "b.kicad_pcb"))
        out = os.path.join(tmp, "out")
        base = settings_of(board, pads, out)

        # 1. the three kinds of settings
        results = {}
        for name, change in (
                ("board stackup (None)", dict(er=None, tand=None, h=None, cu_t=None)),
                ("custom substrate", dict(er=3.5, tand=0.004, h=0.8, cu_t=0.035)),
                ("subregion", dict(port_focused_subregion=True)),
                ("ultrafine mesh", dict(mesh="ultrafine"))):
            s = dict(base, **change)
            model, outdir, sep, ordered = rfsim._build_model(board, pads, s)
            assert model["settings"]["f_stop"] == s["f_stop"] and model["settings"]["mesh"] == s["mesh"]
            assert len(model["ports"]) == len(pads) == len(ordered)
            assert "er" not in model["settings"] and "port_types" not in model["settings"], "dialog keys must be consumed"
            results[name] = model
        assert results["board stackup (None)"]["stackup_source"] in ("default", "file", "memory"), results["board stackup (None)"]["stackup_source"]
        assert results["custom substrate"]["dielectric_layers"][0]["epsilon"] == 3.5
        assert results["subregion"]["subregion"]["enabled"] is True
        print("the model is built for the board stackup, a custom substrate, a subregion and the ultrafine mesh OK")

        # 2. the run and the preview make the same model
        a = rfsim._build_model(board, pads, dict(base, er=None, tand=None, h=None, cu_t=None))[0]
        b = rfsim._build_model(board, pads, dict(base, er=None, tand=None, h=None, cu_t=None), live=False)[0]
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

        # 3. the geometry XML, as _preview_geometry writes it (the viewer is not started)
        model = results["board stackup (None)"]
        os.makedirs(out, exist_ok=True)
        mp, xml = os.path.join(out, "geometry_preview_model.json"), os.path.join(out, "geometry_preview.xml")
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump(model, fh)
        py = solverenv.solver_python() or sys.executable
        r = subprocess.run([py, os.path.join(PLUGINS, "runner.py"), "--geometry", mp, xml],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0 and os.path.isfile(xml) and os.path.getsize(xml) > 2000, \
            "the geometry export failed:\n" + (r.stdout + r.stderr)[-800:]
        print("geometry XML written by runner.py --geometry (%d kB) OK" % (os.path.getsize(xml) // 1024))
    print("PASS")


if __name__ == "__main__":
    main()
