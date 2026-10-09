"""Standalone RFsim result viewer and field-export utility.

Examples:
    python rfsim_viewer.py results.s1p
    python rfsim_viewer.py --save-animation rfsim_results --field E
    python rfsim_viewer.py --export-paraview rfsim_results --field E --open-paraview

The ParaView export writes an XDMF descriptor and an HDF5 dataset containing
real and imaginary vector components of the selected openEMS field dump.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import h5py
import numpy as np


def load_field(h5_path):
    """Read an openEMS FD dump as x/y mm and complex F[y, x, component]."""
    with h5py.File(h5_path, "r") as handle:
        mesh = handle["Mesh"]
        x, y = np.asarray(mesh["x"], float), np.asarray(mesh["y"], float)
        fd = handle["FieldData"]["FD"]
        frequency = float(fd.attrs["frequency"][0])
        if "f0" in fd:
            field = np.asarray(fd["f0"])
        else:
            field = np.asarray(fd["f0_real"]) + 1j * np.asarray(fd["f0_imag"])
    if float(x.max() - x.min()) < 1.0:
        x, y = x * 1e3, y * 1e3
    field = np.squeeze(field)
    if field.shape[0] == 3:
        field = np.moveaxis(field, 0, -1)
    if field.shape[:2] == (len(x), len(y)):
        field = np.swapaxes(field, 0, 1)
    return x, y, field, frequency


def _field_port(h5_path):
    """Read the excited port number from an excN field path."""
    match = re.search(r"exc(\d+)", os.path.normpath(h5_path))
    return int(match.group(1)) if match else None


def find_field(result_dir, field_kind, port=None):
    """Find the selected E or H field dump below a result folder."""
    name = field_kind.upper() + "f.h5"
    if port:
        path = os.path.join(result_dir, "exc%d" % int(port), name)
        if os.path.isfile(path):
            return path
        raise FileNotFoundError("No %s field dump found for port %d below %s"
                                % (field_kind.upper(), int(port), result_dir))
    matches = glob.glob(os.path.join(result_dir, "exc*", name))
    if not matches:
        raise FileNotFoundError("No %s field dump found below %s" % (field_kind.upper(), result_dir))
    return max(matches, key=os.path.getmtime)


def _load_model(result_dir):
    try:
        with open(os.path.join(result_dir, "model.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _dump_z(model, port):
    if not model or not port:
        return None
    try:
        z_of = {c["name"]: c["z"] for c in model["copper_layers"]}
        p = next(q for q in model["ports"] if q["number"] == port)
        return 0.5 * (z_of[p["layer"]] + z_of[p["ref_layer"]])
    except Exception:
        return None


def _field_stem(field_kind, frequency, port=None):
    tag = "_port%d" % int(port) if port else ""
    return "%s_field%s_%.3gGHz" % (field_kind.upper(), tag, frequency / 1e9)


def save_animation(result_dir, field_kind, output_path=None, frames=24, port=None):
    """Save a phase animation of the magnitude of one complex field dump."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter

    h5_path = find_field(result_dir, field_kind, port)
    port = port or _field_port(h5_path)
    x, y, field, frequency = load_field(h5_path)
    model = _load_model(result_dir)
    plane_z = _dump_z(model, port)
    unit = "V/m" if field_kind.upper() == "E" else "A/m"
    output_path = output_path or os.path.join(
        result_dir, _field_stem(field_kind, frequency, port) + ".gif")

    def magnitude(index):
        return np.linalg.norm(np.real(field * np.exp(2j * np.pi * index / frames)), axis=-1)

    vmax = max(float(magnitude(index).max()) for index in range(frames)) or 1.0
    figure = plt.figure(layout="constrained")
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 3.2])
    info_axis = figure.add_subplot(grid[0])
    info_axis.axis("off")
    axis = figure.add_subplot(grid[1])
    image = axis.pcolormesh(x, y, magnitude(0), cmap="jet", vmin=0.0, vmax=vmax,
                            shading="gouraud")
    figure.colorbar(image, ax=axis, label=unit)
    axis.set(xlabel="x (mm)", ylabel="y (mm)", aspect="equal")
    port_line = "Port: %d\n" % int(port) if port else ""
    plane_line = "Plane: z=%.2f mm\n(substrate mid-plane)" % plane_z if plane_z is not None else "Plane: unknown"
    head = "Frequency: %.2f GHz\n%s" % (frequency / 1e9, port_line)
    tail = "\nMaximum: %.4g %s\n%s" % (vmax, unit, plane_line)
    info = info_axis.text(0.0, 0.5, head + "Phase: 0 deg" + tail,
                          fontsize=9, va="center", ha="left", linespacing=1.8)

    def update(index):
        image.set_array(magnitude(index).ravel())
        phase = round(360.0 * index / frames)
        axis.set_title("%s field, %.3g GHz, phase %d deg" % (
            field_kind.upper(), frequency / 1e9, phase))
        info.set_text(head + "Phase: %d deg" % phase + tail)
        return image, info

    animation = FuncAnimation(figure, update, frames=frames, interval=75, blit=False)
    animation.save(output_path, writer=PillowWriter(fps=12))
    plt.close(figure)
    return output_path


def export_paraview(result_dir, field_kind, output_dir=None, port=None):
    """Export one openEMS field dump as HDF5 plus an XDMF descriptor for ParaView."""
    h5_path = find_field(result_dir, field_kind, port)
    port = port or _field_port(h5_path)
    x, y, field, frequency = load_field(h5_path)
    output_dir = output_dir or result_dir
    os.makedirs(output_dir, exist_ok=True)
    stem = _field_stem(field_kind, frequency, port)
    h5_out = os.path.join(output_dir, stem + ".h5")
    xdmf_out = os.path.join(output_dir, stem + ".xdmf")
    dataset = "/Fields/%s" % field_kind.upper()
    ny, nx, components = field.shape
    # ParaView's XDMF reader wants a vector as a flat (points, 3) table, the points in the
    # order of the mesh (x fastest). A (ny, nx, 3) table is refused with "selection + offset
    # not within extent" and the mesh then shows no data.
    flat = field.reshape(ny * nx, components)
    with h5py.File(h5_out, "w") as handle:
        handle.create_dataset("/Mesh/x_mm", data=x)
        handle.create_dataset("/Mesh/y_mm", data=y)
        handle.create_dataset(dataset + "_real", data=flat.real.astype("f8"))
        handle.create_dataset(dataset + "_imag", data=flat.imag.astype("f8"))
        handle.create_dataset(dataset + "_abs", data=np.sqrt((np.abs(flat) ** 2).sum(axis=1)).astype("f8"))
        for name in ("_real", "_imag", "_abs"):
            handle[dataset + name].attrs["frequency_hz"] = frequency
            if port:
                handle[dataset + name].attrs["port"] = int(port)
    h5_name = os.path.basename(h5_out)
    kind = field_kind.upper()
    xdmf = """<?xml version="1.0" ?>
<Xdmf Version="3.0">
  <Domain>
    <Grid Name="RFsim %(k)s Field" GridType="Uniform">
      <Topology TopologyType="2DRectMesh" Dimensions="%(ny)d %(nx)d"/>
      <Geometry GeometryType="VXVY">
        <DataItem Dimensions="%(nx)d" NumberType="Float" Precision="8" Format="HDF">%(h5)s:/Mesh/x_mm</DataItem>
        <DataItem Dimensions="%(ny)d" NumberType="Float" Precision="8" Format="HDF">%(h5)s:/Mesh/y_mm</DataItem>
      </Geometry>
      <Attribute Name="%(k)s_abs" AttributeType="Scalar" Center="Node">
        <DataItem Dimensions="%(n)d" NumberType="Float" Precision="8" Format="HDF">%(h5)s:%(ds)s_abs</DataItem>
      </Attribute>
      <Attribute Name="%(k)s_real" AttributeType="Vector" Center="Node">
        <DataItem Dimensions="%(n)d %(c)d" NumberType="Float" Precision="8" Format="HDF">%(h5)s:%(ds)s_real</DataItem>
      </Attribute>
      <Attribute Name="%(k)s_imag" AttributeType="Vector" Center="Node">
        <DataItem Dimensions="%(n)d %(c)d" NumberType="Float" Precision="8" Format="HDF">%(h5)s:%(ds)s_imag</DataItem>
      </Attribute>
    </Grid>
  </Domain>
</Xdmf>
""" % dict(k=kind, ny=ny, nx=nx, n=ny * nx, c=components, h5=h5_name, ds=dataset)
    with open(xdmf_out, "w", encoding="utf-8") as handle:
        handle.write(xdmf)
    vtr_out = os.path.splitext(xdmf_out)[0] + ".vtr"
    write_vtr(vtr_out, x, y, flat, kind, z=_dump_z(_load_model(result_dir), port))
    try:                      # the layers, ports and parts are an extra; the field export must not fail on them
        export_geometry_paraview(result_dir, output_dir, port, vtr_out, kind + "_abs")
    except Exception as exc:
        print("Geometry export for ParaView failed: %s" % exc)
    return xdmf_out


def write_vtr(path, x, y, flat, kind, z=None):
    """Write the field as a VTK XML RectilinearGrid, which ParaView opens without a reader choice.

    ParaView reads the XDMF file well with its "Xdmf3 Reader" but not with the older "XDMF
    Reader", and it asks which of the two to use. `flat` is (points, 3) complex, x fastest.
    """
    def ascii_array(name, values, comps=1, number_type="Float32"):
        text = " ".join("%.6g" % v for v in np.asarray(values).ravel())
        return ('<DataArray type="%s" Name="%s" NumberOfComponents="%d" format="ascii">%s</DataArray>'
                % (number_type, name, comps, text))

    nx, ny = len(x), len(y)
    arrays = [ascii_array(kind + "_abs", np.sqrt((np.abs(flat) ** 2).sum(axis=1))),
              ascii_array(kind + "_real", flat.real, 3), ascii_array(kind + "_imag", flat.imag, 3)]
    extent = "0 %d 0 %d 0 0" % (nx - 1, ny - 1)   # one layer; z is the height of the field plane
    with open(path, "w", encoding="ascii") as handle:
        handle.write('<?xml version="1.0"?>\n'
                     '<VTKFile type="RectilinearGrid" version="1.0" byte_order="LittleEndian">\n'
                     '<RectilinearGrid WholeExtent="%s"><Piece Extent="%s">\n' % (extent, extent))
        handle.write('<PointData Scalars="%s_abs" Vectors="%s_real">\n%s\n</PointData>\n'
                     % (kind, kind, "\n".join(arrays)))
        handle.write("<CellData></CellData>\n<Coordinates>\n%s\n%s\n%s\n</Coordinates>\n"
                     % (ascii_array("x_mm", x, 1, "Float64"), ascii_array("y_mm", y, 1, "Float64"),
                        ascii_array("z_mm", [0.0 if z is None else z], 1, "Float64")))
        handle.write("</Piece></RectilinearGrid></VTKFile>\n")


def _write_vtp(path, points, verts=(), lines=(), polys=(), cell_ints=None):
    """Write a VTK XML PolyData file (ascii). Cells are listed as verts, lines, polys.

    `cell_ints` is {name: [one integer for each cell, in the same order]}.
    """
    def conn(cells):
        flat, offsets, total = [], [], 0
        for c in cells:
            flat += [int(i) for i in c]
            total += len(c)
            offsets.append(total)
        return " ".join(map(str, flat)), " ".join(map(str, offsets))

    def block(tag, cells):
        flat, offsets = conn(cells)
        return ('<%s><DataArray type="Int64" Name="connectivity" format="ascii">%s</DataArray>'
                '<DataArray type="Int64" Name="offsets" format="ascii">%s</DataArray></%s>'
                % (tag, flat, offsets, tag))

    pts = np.asarray(points, float).reshape(-1, 3)
    data = "".join('<DataArray type="Int32" Name="%s" format="ascii">%s</DataArray>'
                   % (name, " ".join(str(int(v)) for v in values))
                   for name, values in (cell_ints or {}).items())
    with open(path, "w", encoding="ascii") as handle:
        handle.write('<?xml version="1.0"?>\n'
                     '<VTKFile type="PolyData" version="1.0" byte_order="LittleEndian" header_type="UInt64">\n'
                     '<PolyData><Piece NumberOfPoints="%d" NumberOfVerts="%d" NumberOfLines="%d" '
                     'NumberOfStrips="0" NumberOfPolys="%d">\n' % (len(pts), len(verts), len(lines), len(polys)))
        handle.write("<PointData></PointData>\n<CellData>%s</CellData>\n" % data)
        handle.write('<Points><DataArray type="Float32" NumberOfComponents="3" format="ascii">%s'
                     "</DataArray></Points>\n" % " ".join("%.6g" % v for v in pts.ravel()))
        handle.write(block("Verts", verts) + "\n" + block("Lines", lines) + "\n"
                     + block("Strips", []) + "\n" + block("Polys", polys) + "\n")
        handle.write("</Piece></PolyData></VTKFile>\n")


def _trapezoids(ring):
    """Split a polygon into trapezoids with vertical sides (even-odd rule).

    The copper polygons of a plane are one ring that is cut and joined again around each hole
    by zero-width slits. An ear-cutting triangulation (VTK's) fails on such a ring and draws
    wrong wedges; a slab decomposition does not care about slits. Returns quads of 4 (x, y).
    """
    pts = [(float(a), float(b)) for a, b in ring]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    edges = [(p, q) if p[0] <= q[0] else (q, p) for p, q in edges if p[0] != q[0]]
    xs = sorted({p[0] for p in pts})
    quads = []
    for xa, xb in zip(xs, xs[1:]):
        crossing = []
        for p, q in edges:
            if p[0] <= xa and q[0] >= xb:
                slope = (q[1] - p[1]) / (q[0] - p[0])
                crossing.append((p[1] + slope * (xa - p[0]), p[1] + slope * (xb - p[0])))
        crossing.sort(key=lambda c: c[0] + c[1])
        for lo, hi in zip(crossing[0::2], crossing[1::2]):
            if hi[0] - lo[0] > 1e-9 or hi[1] - lo[1] > 1e-9:
                quads.append([(xa, lo[0]), (xb, lo[1]), (xb, hi[1]), (xa, hi[0])])
    return quads


def _si(value, unit):
    """Text for a component value: 100 -> '100 ohm', 4.7e-9 -> '4.7 nH'."""
    for factor, prefix in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "u"),
                           (1e-9, "n"), (1e-12, "p"), (1e-15, "f")):
        if abs(value) >= factor:
            return "%g %s%s" % (value / factor, prefix, unit)
    return "%g %s" % (value, unit)


# The scene that ParaView runs (File > Open ParaView started with --script, or Tools > Python
# Shell > Run Script). It reads scene.json, which names the files and the labels.
_SCENE_SCRIPT = '''"""RFsim scene for ParaView: layers, ports, parts and the field. Written by rfsim_viewer.py."""
import json
import os
from paraview.simple import *

# the folder of the data is written into the script: ParaView does not find a script by a relative name
here = "HERE_DIR"
if not os.path.isdir(here):
    here = os.getcwd()
with open(os.path.join(here, "STEM_scene.json"), encoding="utf-8") as fh:
    cfg = json.load(fh)
view = GetActiveViewOrCreate("RenderView")
view.OrientationAxesVisibility = 1
view.Background = [0.32, 0.34, 0.43]
view.UseColorPaletteForBackground = 0


def show_poly(name, color, opacity=1.0, line_width=None, points=False):
    reader = XMLPolyDataReader(registrationName=name, FileName=[os.path.join(here, name)])
    display = Show(reader, view)
    display.ColorArrayName = ["POINTS", ""]
    display.DiffuseColor = color
    display.AmbientColor = color
    display.Opacity = opacity
    if line_width:
        display.LineWidth = line_width
    if points:
        display.SetRepresentationType("Points")
        display.PointSize = 12
        display.RenderPointsAsSpheres = 1
    return display


for item in cfg["copper"]:
    show_poly(item["file"], item["color"], 1.0)
if cfg.get("dielectric"):
    show_poly(cfg["dielectric"], [0.35, 0.6, 0.35], 0.18)
if cfg.get("vias"):
    show_poly(cfg["vias"], [0.9, 0.8, 0.2], 1.0, line_width=2)
if cfg.get("ports"):
    show_poly(cfg["ports"], [1.0, 0.9, 0.1], 1.0, line_width=3)
    show_poly(cfg["ports"], [1.0, 0.9, 0.1], 1.0, points=True)
if cfg.get("parts"):
    show_poly(cfg["parts"], [0.1, 0.9, 0.9], 1.0, line_width=6)

for label in cfg["labels"]:
    text = a3DText(registrationName=label["text"], Text=label["text"])
    moved = Transform(Input=text)
    moved.Transform.Scale = [label["size"]] * 3
    moved.Transform.Translate = [label["x"], label["y"], label["z"]]
    display = Show(moved, view)
    display.ColorArrayName = ["POINTS", ""]
    display.DiffuseColor = label["color"]
    display.AmbientColor = label["color"]

if cfg.get("field"):
    field = XMLRectilinearGridReader(registrationName=cfg["field"], FileName=[os.path.join(here, cfg["field"])])
    display = Show(field, view)
    ColorBy(display, ("POINTS", cfg["field_array"]))
    display.RescaleTransferFunctionToDataRange(True, False)
    display.SetScalarBarVisibility(view, True)
    display.Opacity = 0.85

x0, x1, y0, y1 = cfg["bounds"]
view.CameraFocalPoint = [0.5 * (x0 + x1), 0.5 * (y0 + y1), cfg["z_mid"]]
view.CameraPosition = [0.5 * (x0 + x1), 0.5 * (y0 + y1) - 0.01, cfg["z_mid"] + 1.4 * max(x1 - x0, y1 - y0)]
view.CameraViewUp = [0, 1, 0]
Render(view)
'''


def export_geometry_paraview(result_dir, output_dir=None, port=None, field_vtr=None, field_array=None):
    """Write the layer geometry, the ports and the parts of a run for ParaView.

    Files (in `output_dir`, which is the result folder by default): geometry_copper_<layer>.vtp
    (one for each copper layer, the polygons at the height of the layer), geometry_dielectric.vtp
    (boxes), geometry_vias.vtp, geometry_ports.vtp (a point and a line to the reference layer for
    each port), geometry_parts.vtp (a line between the pads of each R/L/C part), and
    `<stem>_scene.py` + `<stem>_scene.json`, a script that loads all of this together with the
    field, with a text label for each port ("Port 1: ...") and each part ("R2 100 ohm 0402").
    Returns the path of the scene script, or None when the run has no model.json.
    """
    model = _load_model(result_dir)
    if not model:
        return None
    output_dir = output_dir or result_dir
    os.makedirs(output_dir, exist_ok=True)
    z_of = {c["name"]: c["z"] for c in model["copper_layers"]}
    palette = [[0.85, 0.25, 0.2], [0.25, 0.7, 0.3], [0.3, 0.45, 0.9], [0.95, 0.6, 0.15]]
    cfg = {"copper": [], "labels": [], "field": None}

    for index, (layer, polygons) in enumerate(model["polygons"].items()):
        points, polys = [], []
        for ring in polygons:
            if len(ring) < 3:
                continue
            for quad in _trapezoids(ring):
                first = len(points)
                points += [(px, py, z_of.get(layer, 0.0)) for px, py in quad]
                polys.append(range(first, first + 4))
        if not polys:
            continue
        name = "geometry_copper_%s.vtp" % layer.replace(".", "_")
        _write_vtp(os.path.join(output_dir, name), points, polys=polys)
        cfg["copper"].append({"file": name, "color": palette[index % len(palette)]})

    rect = model.get("board_rect") or model["region"]
    boxes, cell_layer = [], []
    points = []
    for k, layer in enumerate(model["dielectric_layers"]):
        z0, z1 = layer["z_bottom"], layer["z_top"]
        c = len(points)
        points += [(x, y, z) for z in (z0, z1) for x, y in ((rect["x0"], rect["y0"]), (rect["x1"], rect["y0"]),
                                                             (rect["x1"], rect["y1"]), (rect["x0"], rect["y1"]))]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        boxes += [[c + i for i in f] for f in faces]
        cell_layer += [k] * 6
    if boxes:
        _write_vtp(os.path.join(output_dir, "geometry_dielectric.vtp"), points, polys=boxes,
                   cell_ints={"dielectric": cell_layer})
        cfg["dielectric"] = "geometry_dielectric.vtp"

    vias = model.get("vias") or []
    if vias:
        points = []
        for v in vias:
            points += [(v["x"], v["y"], v["z0"]), (v["x"], v["y"], v["z1"])]
        _write_vtp(os.path.join(output_dir, "geometry_vias.vtp"), points,
                   lines=[(2 * i, 2 * i + 1) for i in range(len(vias))])
        cfg["vias"] = "geometry_vias.vtp"

    z_top = max(z_of.values())
    ports = model.get("ports") or []
    if ports:
        points, lines = [], []
        for k, p in enumerate(ports):
            z_sig = z_of.get(p["layer"], z_top)
            z_ref = z_of.get(p.get("ref_layer"), z_sig)
            points += [(p["x"], p["y"], z_sig), (p["x"], p["y"], z_ref)]
            name = (p.get("label") or "").split(" (")[0]      # "J1 Pad 1 (Net-(J1-In))" -> "J1 Pad 1"
            cfg["labels"].append({"text": "Port %d: %s" % (p["number"], name),
                                  "x": p["x"] + 0.4, "y": p["y"] + (1.2 if k % 2 == 0 else -1.8),
                                  "z": z_top + 0.35, "size": 0.5, "color": [1.0, 0.95, 0.2]})
        _write_vtp(os.path.join(output_dir, "geometry_ports.vtp"), points,
                   verts=[(2 * i,) for i in range(len(ports))],
                   lines=[(2 * i, 2 * i + 1) for i in range(len(ports))],
                   cell_ints={"port": [p["number"] for p in ports] * 2})
        cfg["ports"] = "geometry_ports.vtp"

    parts = model.get("lumped_elements") or []
    if parts:
        points, lines = [], []
        for k, e in enumerate(parts):
            a, b = e.get("pads") or [e["start"][:2], e["stop"][:2]]
            z = z_of.get(e.get("layer"), z_top)
            points += [(a[0], a[1], z), (b[0], b[1], z)]
            unit = {"R": "ohm", "L": "H", "C": "F"}.get(e.get("type"), "")
            value = _si(e["value"], unit) if e.get("value") is not None else str(e.get("type", ""))
            package = e.get("package") or ""
            text = "%s %s" % (e["ref"], value) + (" %s" % package if package and " " not in package else "")
            cfg["labels"].append({"text": text, "x": 0.5 * (a[0] + b[0]) + 0.3,
                                  "y": 0.5 * (a[1] + b[1]) + (0.9 if k % 2 == 0 else -1.2),
                                  "z": z_top + 0.35, "size": 0.35, "color": [0.7, 1.0, 1.0]})
        _write_vtp(os.path.join(output_dir, "geometry_parts.vtp"), points,
                   lines=[(2 * i, 2 * i + 1) for i in range(len(parts))])
        cfg["parts"] = "geometry_parts.vtp"

    if field_vtr:
        cfg["field"] = os.path.basename(field_vtr)
        cfg["field_array"] = field_array or "E_abs"
    cfg["bounds"] = [rect["x0"], rect["x1"], rect["y0"], rect["y1"]]
    cfg["z_mid"] = 0.5 * z_top
    stem = os.path.splitext(os.path.basename(field_vtr))[0] if field_vtr else "geometry"
    with open(os.path.join(output_dir, stem + "_scene.json"), "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=1)
    script = os.path.join(output_dir, stem + "_scene.py")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(_SCENE_SCRIPT.replace("STEM", stem)
                     .replace("HERE_DIR", os.path.abspath(output_dir).replace(os.sep, "/")))
    return script


PARAVIEW_EXE = r"C:\Program Files\ParaView 6.1.1\bin\paraview.exe"


def launch_paraview(scene=None, data_file=None):
    """Start ParaView with the scene script (or, without one, with a data file).

    ParaView reads the value of --script as a list that it splits at commas, and it does not
    find a script that is given by a relative name. A folder like "Company, Inc" breaks both.
    The script is given with its full path; when that path has a comma the script is copied to
    the temp folder first (it holds the data folder itself, so it works from there). A data file
    is opened from its own folder with the bare name.
    """
    if scene and os.path.isfile(scene):
        path = os.path.abspath(scene)
        if "," in path:
            path = os.path.join(tempfile.gettempdir(), "rfsim_" + os.path.basename(path))
            shutil.copyfile(scene, path)
        return subprocess.Popen([PARAVIEW_EXE, "--script=" + path])
    return subprocess.Popen([PARAVIEW_EXE, os.path.basename(data_file)],
                            cwd=os.path.dirname(os.path.abspath(data_file)))


def main():
    parser = argparse.ArgumentParser(description="Export RFsim fields for animation or ParaView")
    parser.add_argument("--save-animation", metavar="RESULT_DIR")
    parser.add_argument("--export-paraview", metavar="RESULT_DIR")
    parser.add_argument("--field", choices=("E", "H"), default="E")
    parser.add_argument("--port", type=int, help="Excited port number to export")
    parser.add_argument("--output", help="Output GIF path or ParaView output directory")
    parser.add_argument("--open-paraview", action="store_true")
    args = parser.parse_args()
    if bool(args.save_animation) == bool(args.export_paraview):
        parser.error("choose exactly one of --save-animation or --export-paraview")
    if args.save_animation:
        path = save_animation(args.save_animation, args.field, args.output,
                              port=args.port)
        print("Saved animation: %s" % path)
        return
    path = export_paraview(args.export_paraview, args.field, args.output,
                           port=args.port)
    print("ParaView XDMF: %s" % path)
    if args.open_paraview:
        # ParaView splits a path at commas: start it in the folder with the bare file name
        vtr = os.path.splitext(path)[0] + ".vtr"
        launch_paraview(os.path.splitext(path)[0] + "_scene.py", vtr)


if __name__ == "__main__":
    main()
