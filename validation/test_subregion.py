"""Tests for the port-focused subregion bounds and R/L/C filtering.

Run with KiCad's Python, because ``gui`` imports wx:

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" test_subregion.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins"))

import gui  # noqa: E402


PORTS = [
    {"x": 137.2325, "y": -85.0000, "width": 0.6, "length": 5.6},
    {"x": 148.0850, "y": -85.4050, "width": 0.875, "length": 0.25},
]


def element(ref, start, stop):
    """Give the minimal lumped-element geometry used by the GUI filter."""
    return {"ref": ref, "start": start, "stop": stop}


def test_port_bounds_include_the_pml_margin():
    """The subregion must use the pad union plus twice the GUI margin."""
    bounds = gui._port_subregion_bounds(PORTS, 3.5)
    want = (127.4325, 155.2100, -92.8425, -77.7000)
    assert bounds is not None
    for actual, expected in zip(bounds, want):
        assert abs(actual - expected) < 1e-9, (bounds, want)
    text = gui._port_subregion_text(PORTS, 3.5)
    assert "Port bounds: X 134.43..148.21 mm" in text, text
    assert "X 127.43..155.21 mm" in text, text
    print("subregion bounds OK")


def test_pml_band_is_in_the_copper_bounds_but_not_in_the_part_box():
    """Copper goes to the port box + margin + PML; parts only to + margin."""
    margin, pml = 3.5, 10.0
    copper = gui._port_subregion_bounds(PORTS, margin, pml)
    parts = gui._port_part_bounds(PORTS, margin)
    assert abs((copper[1] - parts[1]) - pml) < 1e-9, (copper, parts)
    assert gui._port_subregion_bounds(PORTS, margin) ==         gui._port_subregion_bounds(PORTS, margin, margin)
    far = element("C5", [148.2 + margin + 4.0, -85.0, 1.6], [148.2 + margin + 4.5, -85.0, 1.6])
    # 4 mm beyond the part box: inside the PML band, so it is not modelled
    assert not gui._element_in_port_subregion(far, PORTS, margin)
    assert copper[1] > far["start"][0]
    print("part box excludes the PML band OK")


def test_filter_includes_local_part_and_excludes_r13():
    """A row outside the port region must not block export validation."""
    c6 = element("C6", [148.57, -87.60, 1.6], [149.53, -87.60, 1.6])
    r13 = element("R13", [180.00, -88.00, 1.6], [180.50, -88.00, 1.6])
    assert gui._element_in_port_subregion(c6, PORTS, 3.5)
    assert not gui._element_in_port_subregion(r13, PORTS, 3.5)
    print("subregion R/L/C filter OK")


if __name__ == "__main__":
    test_port_bounds_include_the_pml_margin()
    test_pml_band_is_in_the_copper_bounds_but_not_in_the_part_box()
    test_filter_includes_local_part_and_excludes_r13()
    print("PASS")