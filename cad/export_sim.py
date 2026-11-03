"""Export the assembled parts for the tracker's 3D simulator (tracker/eyetracker/static/model/).

Unlike stl/ (print orientation), every part here is in assembly coordinates - origin = eye
centre, +Y = gaze, +Z = up - so the simulator can move them as the servos do:
  pan   yoke + eye + LED insert turn about Z
  tilt  eye + LED insert turn about X (on the yoke pins)
  lids  turn about X; as modelled they are closed, open = +-LID_OPEN
Run from cad/:  python export_sim.py   (re-run after changing build.py)"""
import json, os
import build as b

b.SEG = 48   # coarser than the print files: the browser only needs the shape
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tracker", "eyetracker", "static", "model")
os.makedirs(OUT, exist_ok=True)

b.SEG = 80               # the eye itself stays round, so the iris edge is smooth
front, rear = b.eye_halves()
b.SEG = 48
parts = dict(frame=b.frame(), stalk=b.stalk(), yoke=b.yoke(), eye_front=front, eye_rear=rear,
             led_insert=b.led_insert(), lid_upper=b.lid(True), lid_lower=b.lid(False), servos=b.servos())
for name, m in parts.items():
    mesh = m.to_mesh()
    b.trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts).export(f"{OUT}/{name}.stl")
    print(name, os.path.getsize(f"{OUT}/{name}.stl") // 1024, "KB")
# dimensions the simulator needs to colour the iris and swing the lids
with open(f"{OUT}/model.json", "w") as f:
    json.dump({"r_eye": b.R_EYE, "iris_r": b.IRIS_R, "led_face": b.LED_FACE, "lid_open": b.LID_OPEN, "y_glass": b.Y_GLASS,
               "parts": list(parts)}, f, indent=1)
