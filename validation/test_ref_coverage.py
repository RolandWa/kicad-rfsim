"""Reference-layer pick and geometry warnings, with no solver run.

A plane with a notch (a void under an RF line) has a bounding box that
holds the pad. `_touches` says "copper"; `_coverage` must say 0. The
layer choice, the pour-edge case and the runner warnings are tested here.

Run with the python of KiCad (board_reader imports pcbnew) for the first
part, and with the solver python for the runner part. Each part is skipped
when its import is not available:
    python test_ref_coverage.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))

# A 20 x 20 plane with a notch cut in from the LEFT edge, y 8..12, x 0..12.
PLANE = [[(0, 0), (20, 0), (20, 20), (0, 20), (0, 12), (12, 12), (12, 8), (0, 8)]]
PAD_IN_VOID = (2.0, 9.0, 3.0, 11.0)
PAD_ON_COPPER = (15.0, 9.0, 16.0, 11.0)
NAMES = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def part_board_reader():
    import board_reader as br
    assert br._touches(PLANE, PAD_IN_VOID), "bbox test is expected to be fooled"
    assert br._coverage(PLANE, PAD_IN_VOID) == 0.0, "pad in the void must be 0%"
    assert br._coverage(PLANE, PAD_ON_COPPER) == 1.0
    edge = (11.0, 9.0, 13.0, 11.0)          # half on the notch edge
    assert 0.3 < br._coverage(PLANE, edge) < 0.7
    # a pad right at the edge of a pour: no sample on copper, but not a void
    at_edge = (11.7, 9.0, 11.95, 11.0)       # in the notch, 0.05 mm from copper at x=12
    assert br._coverage(PLANE, at_edge) == 0.0
    assert br._near_copper(PLANE, at_edge), "a pad at a pour edge is near copper"
    assert not br._near_copper(PLANE, PAD_IN_VOID), "a pad deep in a void is not"
    print("coverage follows the real outline OK")

    ch = br._choose_ref
    # void under the line on both inner layers -> B.Cu, nearer layers are reported
    ref, sk = ch(NAMES, 0, {"In1.Cu": 0.0, "In2.Cu": 0.0, "B.Cu": 0.6})
    assert ref == "B.Cu" and [n for n, _ in sk] == ["In1.Cu", "In2.Cu"], (ref, sk)
    # solid plane below -> the adjacent layer, nothing skipped
    ref, sk = ch(NAMES, 0, {"In1.Cu": 1.0, "In2.Cu": 1.0, "B.Cu": 1.0})
    assert ref == "In1.Cu" and not sk
    # antenna feed at the edge of its pour: 30% on the ADJACENT layer is enough
    ref, sk = ch(NAMES, 0, {"In1.Cu": 0.3, "In2.Cu": 1.0, "B.Cu": 1.0})
    assert ref == "In1.Cu" and not sk, (ref, sk)
    # ... but 30% on a FARTHER layer is not
    ref, _ = ch(NAMES, 0, {"In1.Cu": 0.0, "In2.Cu": 0.3, "B.Cu": 0.9})
    assert ref == "B.Cu"
    # inner-layer pad, both neighbours equal: toward B.Cu
    ref, _ = ch(NAMES, 1, {"F.Cu": 1.0, "In2.Cu": 1.0, "B.Cu": 1.0})
    assert ref == "In2.Cu"
    # nothing qualifies: the layer with the MOST copper, not just the one below
    ref, sk = ch(NAMES, 0, {"In1.Cu": 0.1, "In2.Cu": 0.2, "B.Cu": 0.0})
    assert ref == "In2.Cu", (ref, sk)
    # nothing at all: nearest, toward B.Cu (the old behaviour)
    ref, _ = ch(NAMES, 1, {"F.Cu": 0.0, "In2.Cu": 0.0, "B.Cu": 0.0})
    assert ref == "In2.Cu"
    print("reference layer choice OK")


def part_runner():
    import runner
    model = {
        "polygons": {"In1.Cu": PLANE, "B.Cu": [[(0, 0), (20, 0), (20, 20), (0, 20)]],
                     "F.Cu": [[(1, 9), (4, 9), (4, 11), (1, 11)],
                              [(13, 9), (16, 9), (16, 11), (13, 11)]]},
        "copper_layers": [{"name": "F.Cu", "z": 1.6}, {"name": "In1.Cu", "z": 1.0},
                          {"name": "B.Cu", "z": 0.0}],
        "region": {"x0": 0.0, "x1": 20.0, "y0": 0.0, "y1": 20.0},
        "ports": [{"number": 1, "label": "P1", "x": 2.5, "y": 10.0, "length": 1.0,
                   "width": 1.0, "ref_layer": "In1.Cu", "type": "lumped"}],
        "lumped_elements": [
            {"ref": "R1", "type": "R", "value": 50.0, "ny": "x",
             "start": [4.0, 9.5, 1.6], "stop": [13.0, 10.5, 1.6]},      # both ends on pads
            {"ref": "R2", "type": "R", "value": 50.0, "ny": "x",
             "start": [4.0, 9.5, 1.6], "stop": [7.0, 10.5, 1.6]},       # far end in air
            {"ref": "R3", "type": "R", "value": 50.0, "ny": "x",
             "start": [16.0, 9.5, 1.6], "stop": [20.5, 10.5, 1.6]},     # far end cut by the domain
            {"ref": "R4", "type": "R", "value": 2e5, "ny": "x",         # open: not in the grid
             "start": [4.0, 9.5, 1.6], "stop": [7.0, 10.5, 1.6]}],
        "settings": {"f_start": 1e8, "f_stop": 1e9, "z0": 50.0},
    }
    w = runner._geometry_warnings(model)
    assert any("port 1" in x and "In1.Cu" in x for x in w), w
    assert not any("lumped R1" in x for x in w), w
    assert any("lumped R2" in x and "end 2" in x for x in w), w
    assert not any("lumped R3" in x for x in w), ("end outside the region is not a fault", w)
    assert not any("lumped R4" in x for x in w), ("an open part is not in the grid", w)
    model["ports"][0]["ref_layer"] = "B.Cu"
    assert not any("port 1" in x for x in runner._geometry_warnings(model))
    print("runner geometry warnings OK")


if __name__ == "__main__":
    for part in (part_board_reader, part_runner):
        try:
            part()
        except ImportError as exc:
            print("skipped %s: %s" % (part.__name__, exc))
    print("PASS")
