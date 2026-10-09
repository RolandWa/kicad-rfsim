"""Every copper plane must sit exactly on a z mesh line.

openEMS treats a copper sheet that has no mesh line on it as NOT metal and
only prints "Unused primitive (type: LinPoly)". `_merge_close` used to
average the z lines of a thin dielectric (a 0.1 mm prepreg between F.Cu and
In1.Cu): the planes moved by a few micrometres or even by 30 um (B.Cu), and
ALL the copper of the run disappeared. The copper z values are anchors now.

Run with the solver python (it builds the model, it does not run it):
    C:\\openEMS\\venv\\Scripts\\python.exe test_copper_lines.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))

import runner  # noqa: E402


def model(z_cu, mesh="fine"):
    """A 16 mm track from a lumped port to a lumped port on a 4-layer board.
    `z_cu` are the z of F.Cu, In1.Cu, In2.Cu, B.Cu from the top."""
    names = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    cu = [{"name": n, "z": z, "thickness": 0.035} for n, z in zip(names, z_cu)]
    diel = [{"name": "dielectric %d" % (i + 1), "z_top": z_cu[i], "z_bottom": z_cu[i + 1],
             "epsilon": 4.4, "loss_tangent": 0.02} for i in range(3)]
    rect = lambda x0, y0, x1, y1: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    port = lambda n, x, d: {"number": n, "label": "P%d" % n, "x": x, "y": 5.0, "layer": "F.Cu",
                            "ref_layer": "B.Cu", "ref_layer2": None, "height": None,
                            "asymmetry": 0.0, "gap": None, "width": 0.4, "length": 0.4,
                            "direction": [d, 0], "track_width": 0.2, "type": "lumped",
                            "copper_run": 16.0}
    return {"version": 3, "stackup_source": "test", "copper_layers": cu, "dielectric_layers": diel,
            "board_rect": {"x0": 0.0, "x1": 20.0, "y0": 0.0, "y1": 10.0},
            "region": {"x0": -2.0, "x1": 22.0, "y0": -2.0, "y1": 12.0},
            "polygons": {"F.Cu": [rect(2.0, 4.9, 18.0, 5.1)], "B.Cu": [rect(-2.0, -2.0, 22.0, 12.0)]},
            "vias": [], "lumped_elements": [], "warnings": [],
            "ports": [port(1, 2.0, 1), port(2, 18.0, -1)],
            "settings": {"f_start": 1e8, "f_stop": 10e9, "z0": 50.0, "margin_mm": 2.0,
                         "mesh": mesh, "n_freq": 11, "max_timesteps": 1000,
                         "end_criteria": 1e-3, "excite": [1], "threads": 2}}


def check(z_cu, mesh):
    m = model(z_cu, mesh)
    eps = max(d["epsilon"] for d in m["dielectric_layers"])
    res = runner.C0 / m["settings"]["f_stop"] / np.sqrt(eps) * 1e3 / runner.RES_DIV[mesh]
    fdtd, _, _ = runner.build(m, 0, res, want_ff=False)
    zl = np.array(fdtd.GetCSX().GetGrid().GetLines("z"))
    for c in m["copper_layers"]:
        d = np.abs(zl - c["z"]).min()
        assert d < 1e-9, "%s (z=%g, %s): nearest z line is %.6f mm away" % (c["name"], c["z"], mesh, d)


if __name__ == "__main__":
    for z_cu in ((1.6, 1.0667, 0.5333, 0.0),       # equal layers (the dialog stackup)
                 (1.44, 1.34, 0.1, 0.0)):           # JLC-like: 0.1 mm prepreg on both sides
        for mesh in ("coarse", "medium", "fine"):
            check(z_cu, mesh)
    print("every copper plane is on a z mesh line OK")
    print("PASS")
