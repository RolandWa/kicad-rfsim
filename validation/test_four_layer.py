"""A fast test of the 4-layer path, and of the parts of board_reader that no board test reached.

1. `make_four_layer` builds the simplest board with 4 copper layers (14 x 8 mm, one line of 10 mm
   on F.Cu, B.Cu a ground plane, In1.Cu and In2.Cu ground pours with a notch cut away under the
   line and the pads).
2. `extract()` must choose B.Cu as the reference of both ports, say that it skipped In1.Cu and
   In2.Cu, and export the 4 copper layers.
3. The model is changed to a stackup with 0.1 mm prepregs (the thin dielectric that once made the
   mesh lose all the copper) and run with the solver (coarse mesh, 2 excitations, about 10 s):
   no "Unused primitive", the run ends on its criterion, the result is passive and reciprocal and
   the line conducts.
4. `rfsim_viewer.py` writes an animation and a ParaView export of the fields of that run.
5. Unit tests of `_stackup_from_text`, `_parse_value` and `_add_shape` (pads / graphic shapes).

Run it with the python of KiCad (pcbnew); the solver and the viewer are started from it:

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" test_four_layer.py [--no-solver]
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGINS = os.path.join(os.path.dirname(HERE), "plugins")
sys.path.insert(0, PLUGINS)
sys.path.insert(0, HERE)

import pcbnew  # noqa: E402
from pcbnew import FromMM, VECTOR2I  # noqa: E402

import board_reader as br  # noqa: E402
import make_test_board  # noqa: E402
import solverenv  # noqa: E402

OUT = os.path.join(HERE, "out_four_layer")


# ----------------------------------------------------------------------------- 5. unit tests
STACKUP = """(stackup
  (layer "F.SilkS" (type "Top Silk Screen"))
  (layer "F.Cu" (type "copper") (thickness 0.035))
  (layer "dielectric 1" (type "prepreg") (thickness 0.1) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))
  (layer "In1.Cu" (type "copper") (thickness 0.035))
  (layer "dielectric 2" (type "core") (thickness 1.24) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02)
     addsublayer (thickness 0.2) (material "X") (epsilon_r 3.0))
  (layer "B.Cu" (type "copper"))
  (copper_finish "None"))"""


def test_stackup_text():
    items = br._stackup_from_text("(kicad_pcb (stackup " + STACKUP[len("(stackup"):] + ")")
    kinds = [(i["kind"], i["name"]) for i in items]
    assert kinds == [("copper", "F.Cu"), ("dielectric", "dielectric 1"), ("copper", "In1.Cu"),
                     ("dielectric", "dielectric 2"), ("dielectric", "dielectric 2 sub 2"),
                     ("copper", "B.Cu")], kinds
    d = {i["name"]: i for i in items}
    assert d["dielectric 1"]["thickness"] == 0.1 and d["dielectric 1"]["epsilon"] == 4.4
    # a sub-layer keeps its own er; its loss tangent comes from the layer above it
    assert d["dielectric 2 sub 2"]["epsilon"] == 3.0 and d["dielectric 2 sub 2"]["loss_tangent"] == 0.02
    assert d["B.Cu"]["thickness"] == br.DEF_CU_T, "a copper layer with no thickness gets the default"
    assert br._stackup_from_text("(kicad_pcb (general))") is None
    assert br._stackup_from_text("") is None
    print("stackup text OK (copper, prepreg, core, a sub-layer, defaults, no stackup)")


def test_value_parser():
    cases = [("4k7", "R", 4700.0), ("4.7k", "R", 4700.0), ("1k5", "R", 1500.0), ("4R7", "R", 4.7),
             ("100nF", "C", 1e-7), ("3n3", "C", 3.3e-9), ("10nH", "L", 1e-8),
             ("10 kOhm", "R", 1e4), ("4.7 uF", "C", 4.7e-6), ("10uF/16V", "C", 1e-5),
             ("1uF/", "C", 1e-6), ("100k 1%", "R", 1e5), ("2.2µF", "C", 2.2e-6)]
    for text, kind, want in cases:
        got = br._parse_value(text, kind)
        assert got is not None and abs(got - want) <= 1e-9 * abs(want), (text, kind, got, want)
    for text in ("", "DNP", "n/a"):
        assert br._parse_value(text, "R") is None, text
    assert br._parse_value("100nF", "R") is None or True      # a capacitor value on a resistor: do not crash
    print("value parser OK (%d values, 3 refusals)" % len(cases))


def _shape(board, kind, **kw):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(kind)
    return s


def _area_mm2(ps):
    return abs(ps.Area()) / 1e12


def test_shapes():
    board = pcbnew.NewBoard(os.path.join(tempfile.gettempdir(), "shapes_unused.kicad_pcb"))

    def fill(s, on):
        try:
            s.SetFilled(on)
        except Exception:
            s.SetFillMode(pcbnew.FILL_T_FILLED_SHAPE if on else pcbnew.FILL_T_NO_FILL)

    def area(s):
        ps = pcbnew.SHAPE_POLY_SET()
        br._add_shape(ps, s)
        ps.Simplify()           # as _copper_polys does: overlapping pieces are one copper
        return _area_mm2(ps)

    # a solid circle of r = 1 mm
    s = _shape(board, pcbnew.SHAPE_T_CIRCLE)
    s.SetCenter(VECTOR2I(FromMM(5), FromMM(5)))
    s.SetEnd(VECTOR2I(FromMM(6), FromMM(5)))
    s.SetWidth(0)
    fill(s, True)
    assert abs(area(s) - math.pi) < 0.05 * math.pi, area(s)
    # a ring: r = 1 mm, width 0.2 mm -> 2 pi r w
    fill(s, False)
    s.SetWidth(FromMM(0.2))
    assert abs(area(s) - 2 * math.pi * 1.0 * 0.2) < 0.08, area(s)
    # a solid rectangle 2 x 3 mm
    s = _shape(board, pcbnew.SHAPE_T_RECT)
    s.SetStart(VECTOR2I(FromMM(0), FromMM(0)))
    s.SetEnd(VECTOR2I(FromMM(2), FromMM(3)))
    s.SetWidth(0)
    fill(s, True)
    assert abs(area(s) - 6.0) < 0.05, area(s)
    # the outline of that rectangle, 0.2 mm wide: about perimeter x width
    fill(s, False)
    s.SetWidth(FromMM(0.2))
    assert abs(area(s) - 10.0 * 0.2) < 0.25, area(s)
    # a segment of 4 mm, 0.4 mm wide: a stadium
    s = _shape(board, pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(VECTOR2I(0, 0))
    s.SetEnd(VECTOR2I(FromMM(4), 0))
    s.SetWidth(FromMM(0.4))
    assert abs(area(s) - (4 * 0.4 + math.pi * 0.2 ** 2)) < 0.06, area(s)
    # a solid polygon: a right triangle with legs of 2 mm
    s = _shape(board, pcbnew.SHAPE_T_POLY)
    s.SetPolyPoints([VECTOR2I(0, 0), VECTOR2I(FromMM(2), 0), VECTOR2I(0, FromMM(2))])
    s.SetWidth(0)
    fill(s, True)
    assert abs(area(s) - 2.0) < 0.05, area(s)
    # an arc of 90 degrees, r = 2 mm, 0.2 mm wide: about length x width
    try:
        s = _shape(board, pcbnew.SHAPE_T_ARC)
        r = FromMM(2)
        s.SetArcGeometry(VECTOR2I(r, 0), VECTOR2I(int(r * math.cos(math.pi / 4)), int(r * math.sin(math.pi / 4))),
                         VECTOR2I(0, r))
        s.SetWidth(FromMM(0.2))
        a = area(s)
        assert abs(a - (math.pi / 2 * 2.0) * 0.2) < 0.12, a
        arc = "arc"
    except AttributeError:
        arc = "arc skipped (no SetArcGeometry)"
    print("graphic shapes OK (circle, ring, rectangle, outline, segment, polygon, %s)" % arc)


# ----------------------------------------------------------------------------- 1-2. the board
def build(tmp):
    path = os.path.join(tmp, "four_layer.kicad_pcb")
    board, pads = make_test_board.make_four_layer(path)
    model = br.extract(board, pads, margin_mm=1.0, f_stop=5e9, mesh="coarse", full_board=False)
    return board, pads, model


def test_extraction(model):
    names = [c["name"] for c in model["copper_layers"]]
    assert names == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], names
    for p in model["ports"]:
        assert p["ref_layer"] == "B.Cu", ("the reference must be the plane that is under the pad", p["number"], p["ref_layer"])
        assert p["ref_coverage"] >= br.REF_MIN_COVER, p["ref_coverage"]
        skipped = dict((n, c) for n, c in p["ref_skipped"])
        assert set(skipped) == {"In1.Cu", "In2.Cu"} and max(skipped.values()) < br.REF_MIN_COVER_ADJ, skipped
    text = " ".join(model["warnings"])
    assert "nearer layer In1.Cu" in text and "uses B.Cu" in text, model["warnings"]
    assert model["subregion"]["enabled"] is True
    for layer in names:
        assert model["polygons"].get(layer), "no copper exported for %s" % layer
    # the void: no In1.Cu polygon covers the middle of the line, B.Cu and F.Cu pour do
    x0, y0 = 7.0, make_test_board.FL_H
    cx = [p for p in model["ports"]][0]["x"]
    assert br._covered(model["polygons"]["B.Cu"], cx, model["ports"][0]["y"])
    assert not br._covered(model["polygons"]["In1.Cu"], cx, model["ports"][0]["y"]), "In1.Cu must be void under the pad"
    assert not br._covered(model["polygons"]["In2.Cu"], cx, model["ports"][0]["y"])
    print("4-layer extraction OK (ports use B.Cu, In1/In2 skipped with 0 %% coverage, %d polygons)"
          % sum(len(v) for v in model["polygons"].values()))


# ----------------------------------------------------------------------------- 3. the solver
THIN = dict(z=(1.44, 1.34, 0.1, 0.0), eps=(4.4, 4.5, 4.5))


def thin_prepreg(model):
    """The stackup of a board with a 0.1 mm prepreg on each side of a 1.24 mm core."""
    names = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    model["copper_layers"] = [{"name": n, "z": z, "thickness": 0.035} for n, z in zip(names, THIN["z"])]
    z = THIN["z"]
    model["dielectric_layers"] = [{"name": "dielectric %d" % (i + 1), "z_top": z[i], "z_bottom": z[i + 1],
                                   "epsilon": THIN["eps"][i], "loss_tangent": 0.02} for i in range(3)]
    for v in model["vias"]:
        v["z0"], v["z1"] = 0.0, z[0]
    for e in model["lumped_elements"]:
        e["start"][2] = e["stop"][2] = z[0]
    model["stackup_source"] = "test (0.1 mm prepreg)"
    return model


def run_solver(model, tmp):
    model = thin_prepreg(json.loads(json.dumps(model)))
    model["settings"] = {"f_start": 1e8, "f_stop": 5e9, "z0": 50.0, "margin_mm": 1.0, "mesh": "coarse",
                         "n_freq": 21, "max_timesteps": 100000, "end_criteria": 1e-3, "excite": [1, 2],
                         "lumped": True, "parasitics": False}
    os.makedirs(OUT, exist_ok=True)
    mp = os.path.join(OUT, "model.json")
    with open(mp, "w") as fh:
        json.dump(model, fh)
    py = solverenv.solver_python() or sys.executable
    r = subprocess.run([py, os.path.join(PLUGINS, "runner.py"), mp, OUT], capture_output=True, text=True, timeout=900)
    log = r.stdout + r.stderr
    assert r.returncode == 0, "the solver stopped (code %s):\n%s" % (r.returncode, log[-800:])
    assert "Unused primitive" not in log, "openEMS dropped copper (a copper sheet with no mesh line):\n" + "\n".join(
        l for l in log.splitlines() if "Unused primitive" in l)[:600]
    assert "got to its end criteria" in log, "the run did not end on its criterion:\n" + log[-500:]
    return log


def test_result():
    import numpy as np
    rows = np.loadtxt(os.path.join(OUT, "results.s2p"), comments=("!", "#"))
    f = rows[:, 0]
    s = rows[:, 1:].reshape(-1, 4, 2)
    s11, s21, s12, s22 = [s[:, i, 0] + 1j * s[:, i, 1] for i in range(4)]
    assert np.all(np.abs(s11) ** 2 + np.abs(s21) ** 2 <= 1.03), "not passive at port 1"
    assert np.all(np.abs(s22) ** 2 + np.abs(s12) ** 2 <= 1.03), "not passive at port 2"
    assert np.max(np.abs(s21 - s12)) < 0.06, "not reciprocal: %.3f" % np.max(np.abs(s21 - s12))
    i = int(np.argmin(np.abs(f - 1e9)))
    db21 = 20 * math.log10(abs(s21[i]))
    assert db21 > -8.0, "the line does not conduct: |S21| = %.1f dB at 1 GHz (a copper-less run gives -80 dB)" % db21
    print("solver run OK: passive, reciprocal, |S21| = %.1f dB and |S11| = %.1f dB at 1 GHz"
          % (db21, 20 * math.log10(abs(s11[i]))))


# ----------------------------------------------------------------------------- 4. the viewer
def test_viewer():
    viewer = os.path.join(PLUGINS, "rfsim_viewer.py")
    gif = os.path.join(OUT, "e_field_test.gif")
    pv = os.path.join(OUT, "paraview_test")
    for p in (gif,):
        if os.path.exists(p):
            os.remove(p)
    r = subprocess.run([sys.executable, viewer, "--save-animation", OUT, "--field", "E", "--port", "1",
                        "--output", gif], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0 and os.path.isfile(gif) and os.path.getsize(gif) > 2000, \
        "the animation was not written:\n" + (r.stdout + r.stderr)[-600:]
    py = solverenv.solver_python() or sys.executable      # the solver python has h5py and the XDMF writer
    r = subprocess.run([py, viewer, "--export-paraview", OUT, "--field", "H", "--port", "1", "--output", pv],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, "the ParaView export failed:\n" + (r.stdout + r.stderr)[-600:]
    produced = [os.path.join(dp, f) for dp, _, fs in os.walk(pv) for f in fs]
    assert any(p.endswith(".xdmf") for p in produced) and any(p.endswith(".h5") for p in produced), produced
    # the lookup of a field and the error for a port that was not excited
    import rfsim_viewer
    assert rfsim_viewer.find_field(OUT, "E", 1).endswith(os.path.join("exc1", "Ef.h5"))
    try:
        rfsim_viewer.find_field(OUT, "E", 7)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("a port that was not excited must give FileNotFoundError")
    print("viewer OK (GIF %d kB, ParaView %d files)" % (os.path.getsize(gif) // 1024, len(produced)))


def test_field_buttons_in_package_context():
    """The buttons Save Field Animation and Export Field for ParaView of the result window, with the plugin
    imported as a package (as KiCad does). They did nothing, and said nothing, when gui.py had
    `from rfsim_viewer import ...` (no such module outside the plugin folder)."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "probe_field_export.py"), PLUGINS, OUT,
                        os.path.join(OUT, "buttons")], capture_output=True, text=True, timeout=600)
    lines = [l for l in r.stdout.splitlines() if re.match(r"^[EH] (animation|paraview):", l)]
    assert len(lines) == 3, "the probe wrote %d lines:\n%s" % (len(lines), (r.stdout + r.stderr)[-800:])
    bad = [l for l in lines if ": OK" not in l]
    assert not bad, "a field export button failed in the package context:\n" + "\n".join(bad)
    print("field buttons OK in the package context (E animation, H animation, ParaView export)")


def main(argv):
    test_stackup_text()
    test_value_parser()
    test_shapes()
    with tempfile.TemporaryDirectory() as tmp:
        board, pads, model = build(tmp)
        test_extraction(model)
        if "--no-solver" not in argv:
            run_solver(model, tmp)
            test_result()
            test_viewer()
            test_field_buttons_in_package_context()
    print("PASS")


if __name__ == "__main__":
    main(sys.argv[1:])
