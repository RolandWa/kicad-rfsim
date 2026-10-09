"""Reference-layer pick and geometry warnings, with no solver run.

A plane with a notch (a void under an RF line) has a bounding box that
holds the pad. `_touches` says "copper"; `_coverage` must say 0.
Run with the python of KiCad 10 (it imports pcbnew through board_reader),
or the solver python for the runner part:
    python test_ref_coverage.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))

# A 20 x 20 plane with a notch 8 mm wide cut in from the left edge, y 8..12.
PLANE = [[(0, 0), (20, 0), (20, 8), (8, 8), (8, 12), (20, 12), (20, 20), (0, 20)]]
# Written the other way round: the notch opens to the LEFT.
PLANE = [[(0, 0), (20, 0), (20, 20), (0, 20), (0, 12), (12, 12), (12, 8), (0, 8)]]
PAD_IN_VOID = (2.0, 9.0, 3.0, 11.0)
PAD_ON_COPPER = (15.0, 9.0, 16.0, 11.0)


def part_board_reader():
    import board_reader as br
    assert br._touches(PLANE, PAD_IN_VOID), "bbox test is expected to be fooled"
    assert br._coverage(PLANE, PAD_IN_VOID) == 0.0, "pad in the void must be 0%"
    assert br._coverage(PLANE, PAD_ON_COPPER) == 1.0
    edge = (11.0, 9.0, 13.0, 11.0)          # half on the notch edge
    assert 0.3 < br._coverage(PLANE, edge) < 0.7
    print("coverage follows the real outline OK")


def part_runner():
    import runner
    model = {
        "polygons": {"In1.Cu": PLANE, "B.Cu": [[(0, 0), (20, 0), (20, 20), (0, 20)]],
                     "F.Cu": [[(1, 9), (4, 9), (4, 11), (1, 11)],
                              [(13, 9), (16, 9), (16, 11), (13, 11)]]},
        "copper_layers": [{"name": "F.Cu", "z": 1.6}, {"name": "In1.Cu", "z": 1.0},
                          {"name": "B.Cu", "z": 0.0}],
        "ports": [{"number": 1, "label": "P1", "x": 2.5, "y": 10.0, "length": 1.0,
                   "width": 1.0, "ref_layer": "In1.Cu", "type": "lumped"}],
        "lumped_elements": [
            {"ref": "R1", "type": "R", "value": 50.0, "ny": "x",
             "start": [4.0, 9.5, 1.6], "stop": [13.0, 10.5, 1.6]},      # both ends on pads
            {"ref": "R2", "type": "R", "value": 50.0, "ny": "x",
             "start": [4.0, 9.5, 1.6], "stop": [7.0, 10.5, 1.6]}],      # far end in air
    }
    w = runner._geometry_warnings(model)
    assert any("port 1" in x and "In1.Cu" in x for x in w), w
    assert not any("lumped R1" in x for x in w), w
    assert any("lumped R2" in x and "end 2" in x for x in w), w
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
