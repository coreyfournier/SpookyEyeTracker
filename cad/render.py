"""Render the CAD parts to PNGs for the docs (docs/images/cad-*.png).

    .venv\\Scripts\\python cad\\render.py

Builds the parts with build.py, places them as assembled (plus a window pane and a suction
cup for context), and renders them with three.js in headless Edge via Playwright. Needs
network access for three.js (jsDelivr) and `pip install playwright pillow`.
"""
import functools
import http.server
import json
import os
import sys
import tempfile
import threading

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build as b  # noqa: E402

OUT = os.path.join(HERE, "..", "docs", "images")
W, H = 1600, 1000

# name -> (colour, opacity, roughness, metalness)
STYLE = {
    "frame": ("#3b3f45", 1, 0.75, 0.0),
    "eye_front": ("#f3efe4", 1, 0.55, 0.0),
    "eye_rear": ("#e6e1d3", 1, 0.6, 0.0),
    "led_insert": ("#ffffff", 1, 0.6, 0.0),
    "yoke": ("#8b9198", 1, 0.6, 0.0),
    "stalk": ("#8b9198", 1, 0.6, 0.0),
    "lid_upper": ("#6b2420", 1, 0.5, 0.0),
    "lid_lower": ("#6b2420", 1, 0.5, 0.0),
    "servos": ("#2f5fd0", 1, 0.45, 0.0),
    "cup": ("#d8e3ea", 0.85, 0.3, 0.0),
    "nut": ("#c9a13b", 1, 0.35, 0.8),
    "glass": ("#a8d8ff", 0.16, 0.05, 0.0),
}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#f4f4f1}</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script></head><body>
<script type="module">
import * as THREE from 'three';
import {STLLoader} from 'three/addons/loaders/STLLoader.js';
import {toCreasedNormals} from 'three/addons/utils/BufferGeometryUtils.js';
const W = %d, H = %d;
const renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
renderer.setSize(W, H); renderer.setPixelRatio(1);
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color('#f4f4f1');
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8577, 1.6));
const key = new THREE.DirectionalLight(0xffffff, 2.2); scene.add(key);
const fill = new THREE.DirectionalLight(0xdfe8ff, 0.8); scene.add(fill);
const root = new THREE.Group(); root.rotation.x = -Math.PI / 2;   // CAD is Z-up, three.js is Y-up
scene.add(root);
const camera = new THREE.PerspectiveCamera(30, W / H, 1, 5000);
const meshes = {};
const toThree = p => new THREE.Vector3(p[0], p[2], -p[1]);

window.load = async (parts) => {
  const loader = new STLLoader();
  for (const p of parts) {
    let g = await loader.loadAsync(p.url);
    g = toCreasedNormals(g, Math.PI / 7);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({color: p.color, roughness: p.rough,
      metalness: p.metal, transparent: p.opacity < 1, opacity: p.opacity, depthWrite: p.opacity >= 0.5,
      side: THREE.DoubleSide}));
    m.renderOrder = p.opacity < 1 ? 1 : 0;
    root.add(m); meshes[p.name] = m;
  }
  return Object.keys(meshes);
};
// Camera from a direction (CAD coords), fitted to the visible parts; returns once rendered.
window.view = ({show, dir, target, fov = 30, margin = 1.08}) => {
  for (const [n, m] of Object.entries(meshes)) m.visible = show.includes(n);
  root.updateMatrixWorld(true);   // so the box is measured after the Z-up -> Y-up rotation
  const box = new THREE.Box3();
  for (const n of show) if (meshes[n] && n !== 'glass') box.expandByObject(meshes[n]);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const c = target ? toThree(target) : sphere.center;
  const d = toThree(dir).normalize();
  camera.fov = fov; camera.updateProjectionMatrix();
  const dist = sphere.radius * margin / Math.sin(THREE.MathUtils.degToRad(fov / 2) * Math.min(1, W / H));
  camera.position.copy(c).addScaledVector(d, dist);
  camera.lookAt(c);
  key.position.copy(camera.position).add(new THREE.Vector3(-dist * 0.6, dist * 0.9, 0));
  fill.position.copy(c).addScaledVector(d, -dist).add(new THREE.Vector3(0, dist * 0.3, 0));
  renderer.render(scene, camera);
  return true;
};
window.ready = true;
</script></body></html>"""


def export(m, path):
    mesh = m.to_mesh()
    trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts).export(path)


def cup_model():
    """A suction cup pressed on the glass, sitting in the frame's pocket, plus its nut."""
    yg, floor = b.Y_GLASS, b.Y_GLASS - b.CUP_DEPTH
    z = b.CUP_Z
    rim = b.cyl_y(31.75, yg - 2, yg, z=z)
    dome = b.M.cylinder(floor - 0 - (yg - 2) and (yg - 2 - floor), 9.0, 30.0, 96).rotate([-90, 0, 0]) \
        .translate([0, floor, z])
    hub = b.cyl_y(9.0, floor, floor + 3, z=z)
    stud = b.cyl_y(2.08, floor - b.PLATE_T - 6, floor, z=z)
    nut = (b.M.cylinder(3.2, 5.0, 5.0, 6).rotate([-90, 0, 0]).translate([0, floor - b.PLATE_T - 3.2, z])
           - b.cyl_y(2.08, floor - 20, floor, z=z))
    return rim + dome + hub + stud, nut


def assembled_parts(tmp):
    front, rear = b.eye_halves()
    lu, ll = b.lid(True), b.lid(False)
    cup, nut = cup_model()
    parts = {
        "frame": b.frame(), "eye_front": front, "eye_rear": rear, "led_insert": b.led_insert(),
        "yoke": b.yoke(), "stalk": b.stalk(), "servos": b.servos(),
        "lid_upper": lu.rotate([b.LID_OPEN * 0.6, 0, 0]), "lid_lower": ll.rotate([-b.LID_OPEN * 0.6, 0, 0]),
        "cup": cup, "nut": nut,
        "glass": b.box(-170, 170, b.Y_GLASS, b.Y_GLASS + 6, -130, 200),
    }
    out = []
    for name, m in parts.items():
        export(m, os.path.join(tmp, f"{name}.stl"))
        c, op, r, mt = STYLE[name]
        out.append({"name": name, "url": f"{name}.stl", "color": c, "opacity": op, "rough": r, "metal": mt})
    return out


PRINTED = [("frame", "frame.stl"), ("eye_front", "eye_front.stl"),
           ("eye_rear", "eye_rear.stl"), ("lid_upper", "lid_upper.stl"), ("lid_lower", "lid_lower.stl"),
           ("led_insert", "led_insert.stl"), ("stalk", "stalk.stl"), ("yoke", "yoke.stl"),
           ("cup_shims", "cup_shims.stl")]


def printed_parts(tmp):
    """The print-ready STLs as they sit on the bed."""
    out = []
    for name, _ in PRINTED:
        t = trimesh.load(os.path.join(HERE, "stl", f"{name}.stl"))
        t.export(os.path.join(tmp, f"print_{name}.stl"))
        c, op, r, mt = STYLE.get(name, ("#d06a2a", 1, 0.6, 0.0))
        out.append({"name": f"print_{name}", "url": f"print_{name}.stl", "color": c, "opacity": op,
                    "rough": r, "metal": mt})
    return out


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(directory):
    handler = functools.partial(QuietHandler, directory=directory)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def trim(path, pad=40):
    """Crop a render to its contents (anything that isn't background) plus a margin."""
    img = Image.open(path).convert("RGB")
    bg = Image.new("RGB", img.size, img.getpixel((0, 0)))
    from PIL import ImageChops
    box = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(img.height, box[3] + pad))
        img.crop(box).save(path)


def label_grid(tiles, cols, path):
    font = ImageFont.truetype("segoeui.ttf", 30) if os.name == "nt" else ImageFont.load_default()
    tw, th = tiles[0][0].size
    rows = (len(tiles) + cols - 1) // cols
    grid = Image.new("RGB", (cols * tw, rows * (th + 50)), "#f4f4f1")
    draw = ImageDraw.Draw(grid)
    for i, (img, text) in enumerate(tiles):
        x, y = (i % cols) * tw, (i // cols) * (th + 50)
        grid.paste(img, (x, y))
        draw.text((x + tw // 2, y + th + 8), text, fill="#333", font=font, anchor="ma")
    grid.save(path)


def main():
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        parts = assembled_parts(tmp) + printed_parts(tmp)
        with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
            f.write(PAGE % (W, H))
        srv = serve(tmp)
        assembly = ["frame", "eye_front", "eye_rear", "led_insert", "yoke", "stalk", "servos",
                    "lid_upper", "lid_lower", "cup", "nut"]
        views = {
            # from inside the house, behind and above: servos, lattice, eye in its gimbal
            "cad-inside.png": dict(show=assembly, dir=[-0.75, -1.0, 0.65]),
            # from the street, through the window
            "cad-street.png": dict(show=assembly + ["glass"], dir=[0.45, 1.0, 0.18], margin=1.0),
            # the frame on its own: window plate, cup pocket, lattice
            "cad-frame.png": dict(show=["frame"], dir=[0.9, -1.0, 0.7]),
            # side view: how it sits on the glass and hangs from the cup
            "cad-side.png": dict(show=assembly + ["glass"], dir=[1.0, 0.0, 0.08], margin=1.0),
        }
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--use-angle=swiftshader",
                                                                "--enable-unsafe-swiftshader"])
            page = browser.new_page(viewport={"width": W, "height": H})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
            page.wait_for_function("window.ready === true", timeout=60000)
            page.evaluate("parts => window.load(parts)", parts)
            for name, v in views.items():
                page.evaluate("v => window.view(v)", v)
                page.locator("canvas").screenshot(path=os.path.join(OUT, name))
                trim(os.path.join(OUT, name))
                print("wrote", name)
            tiles = []
            for name, text in PRINTED:
                page.evaluate("v => window.view(v)", dict(show=[f"print_{name}"], dir=[0.8, -1.0, 0.9], margin=1.05))
                shot = os.path.join(tmp, f"tile_{name}.png")
                page.locator("canvas").screenshot(path=shot)
                img = Image.open(shot).convert("RGB")
                tiles.append((img.crop(((W - H) // 2, 0, (W + H) // 2, H)).resize((420, 420), Image.LANCZOS), text))
            label_grid(tiles, 3, os.path.join(OUT, "cad-parts.png"))
            print("wrote cad-parts.png")
            if errors:
                print("page errors:", json.dumps(errors))
            browser.close()
        srv.shutdown()


if __name__ == "__main__":
    main()
