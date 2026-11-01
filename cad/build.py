"""Animatronic eye (4in / 102mm hollow) with X/Y gimbal + upper/lower eyelids, SG90 servos.
Coordinates: origin = eye center, +Y = gaze forward, +Z = up, X = lateral. Units mm."""
import numpy as np, trimesh, os
from manifold3d import Manifold as M, CrossSection as CS

SEG = 96
OUT = os.path.dirname(os.path.abspath(__file__)) + "/stl"
os.makedirs(OUT, exist_ok=True)

R_EYE, T_EYE = 51.0, 2.5          # 102mm OD eye
R_LO, R_LI = 56.5, 54.0          # eyelid shell
PIN = 1.65                       # M3 / 3mm pin clearance radius
TAP = 1.4                        # M3 self-tap radius
ROD = 1.1                        # pushrod / ball-link hole radius
LID_OPEN = 45.0                  # lid travel (deg)
H = 70.0                         # eye center height above base top

def box(x0, x1, y0, y1, z0, z1):
    return M.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])
def cyl_z(r, z0, z1, x=0, y=0):
    return M.cylinder(z1 - z0, r, r, SEG).translate([x, y, z0])
def cyl_x(r, x0, x1, y=0, z=0):
    return M.cylinder(x1 - x0, r, r, SEG).rotate([0, 90, 0]).translate([x0, y, z])
def cyl_y(r, y0, y1, x=0, z=0):
    return M.cylinder(y1 - y0, r, r, SEG).rotate([-90, 0, 0]).translate([x, y0, z])
def sphere(r):
    return M.sphere(r, SEG * 2)
def shell(ro, ri):
    return sphere(ro) - sphere(ri)
def wedge_x(a1, a2, x0, x1, r=120):
    """Sector about the X axis; angle phi measured from +Y toward +Z (deg)."""
    angs = np.radians(np.linspace(a1, a2, 48))
    pts = [(0.0, 0.0)] + [(r * np.cos(a), r * np.sin(a)) for a in angs]
    ex = CS([pts]).extrude(x1 - x0)                       # (u,v,w)
    T = [[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0]]        # u->Y, v->Z, w->X
    return ex.transform(T)

# ---------------- EYE ----------------
SEAM = 9.0                    # front cap / rear body split plane (y)
def boss(sign):
    # boss lives entirely in the rear section (flat-topped below the seam lip)
    b = (cyl_x(7, 40, 50) if sign > 0 else cyl_x(7, -50, -40)) ^ box(-60, 60, -10, SEAM - 3.6, -10, 10)
    # 3mm dowel pin: press-fit (r1.5) through the shell side, free-running in the yoke
    h = cyl_x(1.5, 38, 53) if sign > 0 else cyl_x(1.5, -53, -38)
    return b, h

def rear_boss_supports():
    """Snap-off blocks for printing the rear seam-down: each pivot boss's flat face sits
    3.6mm above the bed with only air under its inner part (the lip socket is bored out).
    Stops PRINT_GAP below the boss and clears the socket bore wall (r 47.65)."""
    s = M()
    for sign in (1, -1):
        x0, x1 = (40.3, 47.0) if sign > 0 else (-47.0, -40.3)
        s += box(x0, x1, SEAM - 3.6 + PRINT_GAP, SEAM, -4.2, 4.2)
    return s

def eye_full():
    e = shell(R_EYE, R_EYE - T_EYE)
    bosses, holes = M(), M()
    for s in (1, -1):
        b, h = boss(s); bosses += b; holes += h
    e = (e + (bosses ^ sphere(R_EYE - 0.3))) - holes
    # iris + pupil recesses (paint or inlay)
    e -= (sphere(R_EYE + 1) - sphere(R_EYE - 0.8)) ^ cyl_y(20, 0, 60)
    # ---- glowing iris: thin the iris to a 0.8mm light window ----
    e -= sphere(R_EYE - 1.6) ^ cyl_y(20, 0, 60)          # 50.2 outer -> 49.4 inner
    # LED hardware now lives on the separate led_insert() part
    # rear opening for the support stalk
    e -= cyl_y(30, -60, -20)
    # yaw (pan) tab: plate in XY plane, hole along Z
    yt = (box(32, 40, -50, -30, -2.5, 2.5) - sphere(R_EYE - T_EYE)) - cyl_z(ROD, -5, 5, x=36, y=-45)
    # pitch (tilt) tab: plate in YZ plane, hole along X
    pt = (box(-34.5, -29.5, -50, -30, 16, 24) - sphere(R_EYE - T_EYE)) - cyl_x(ROD, -40, -25, y=-46, z=20)
    e += yt + pt
    return e

def wedge_y(a1, a2, y0, y1, r=60):
    """Sector about the Y axis; angle measured in the XZ plane from +X toward +Z (deg)."""
    angs = np.radians(np.linspace(a1, a2, max(8, int(abs(a2 - a1)))))
    pts = ([(0.0, 0.0)] + [(r * np.cos(a), -r * np.sin(a)) for a in angs])[::-1]
    return CS([pts]).extrude(y1 - y0).rotate([-90, 0, 0]).translate([0, y0, 0])

def ring_y(ro, ri, y0, y1):
    return cyl_y(ro, y0, y1) - cyl_y(ri, y0 - 1, y1 + 1)

# twist-lock parameters
LUG_ANG = (30, 150, 270)      # lug positions (deg, XZ plane)
TWIST = 15                    # front cap turns +15 deg to lock
BORE = 47.65                  # rear-half socket bore radius
LIP_O, LIP_I = BORE - 0.2, BORE - 1.85
LIP_Y0 = SEAM - 3.3           # lip depth into the rear half
COLLAR_H = 4.0                # height of the ring bonding the lip to the front cap wall
PRINT_GAP = 0.2               # air gap between a breakaway support and the part (one 0.2mm layer)

def eye_halves():
    e = eye_full()
    front = e ^ box(-60, 60, SEAM, 60, -60, 60)
    rear = e ^ box(-60, 60, -60, SEAM, -60, 60)
    # rear: cylindrical socket bore for the lip
    rear -= cyl_y(BORE, LIP_Y0 - 0.2, SEAM + 1)
    # rear: L-shaped bayonet slots (axial entry + circumferential run + click detent)
    for a in LUG_ANG:
        entry = ring_y(48.65, BORE - 1, LIP_Y0 + 0.4, SEAM + 1) ^ wedge_y(a - 6, a + 6, LIP_Y0, SEAM + 2)
        run = ring_y(48.65, BORE - 1, LIP_Y0 + 0.4, LIP_Y0 + 2.2) ^ wedge_y(a - 6, a + TWIST + 6, LIP_Y0, SEAM)
        detent = ring_y(48.7, 48.3, LIP_Y0, SEAM) ^ wedge_y(a + 8.5, a + 10, LIP_Y0 - 1, SEAM + 1)
        rear -= (entry + run) - detent
    # front: lip with three lugs, shown in the LOCKED position (rotated +TWIST)
    lip = ring_y(LIP_O, LIP_I, LIP_Y0, SEAM + 0.5)
    for a in LUG_ANG:
        lip += ring_y(48.45, LIP_I + 0.5, LIP_Y0 + 0.6, LIP_Y0 + 1.8) ^ wedge_y(a + TWIST - 5, a + TWIST + 5, LIP_Y0, SEAM)
    front += lip ^ sphere(R_EYE - 0.5)
    # collar: fuses the lip into the cap wall. Without it the lip (r <= LIP_O) sits ~0.2mm
    # inside the cap's inner surface, so the two never touch and the cap rim prints in mid-air.
    # Lives entirely above the seam, so the rear socket/bayonet are unaffected.
    front += ring_y(R_EYE, LIP_I, SEAM, SEAM + COLLAR_H) ^ sphere(R_EYE - 0.5)
    return front, rear

def front_rim_support():
    """Breakaway ring for printing the front cap seam-down. The cap's flat mating rim
    (r ~47.5-50.2 at the seam) sits 3.3mm above the bed on the lip and would otherwise
    print in mid-air. Stops PRINT_GAP below the rim and clears the bayonet lugs (r 48.45)."""
    return ring_y(50.0, 48.75, LIP_Y0, SEAM - PRINT_GAP)

# ---------------- LED INSERT (WS2812 Jewel x7 + pupil cone) ----------------
JEWEL_HOLE_X = 9.2            # half of ~18.4mm hole spacing (measure yours!)
LED_FACE = 36.0               # Jewel LED-side PCB face (y)
P = LED_FACE + 1.75           # insert back plane: 1.6mm LED height + clearance (M2 nut spacer)

def led_insert():
    """Prints back-face down, no supports. Glue tube rim to the cap's inner wall."""
    # light baffle tube: confines glow to the iris
    tube = (cyl_y(22, P, 52) - cyl_y(20.5, P - 1, 53)) ^ sphere(R_EYE - T_EYE - 0.15)
    # pupil cone around centre LED: inner r 3.8 at LED -> 6.0 at the window
    h = 52 - P
    r_in0, r_in1 = 3.8, 3.8 + (6.0 - 3.8) * h / (49.25 - P)
    cone_o = M.cylinder(h, r_in0 + 0.9, r_in1 + 0.9, SEG).rotate([-90, 0, 0]).translate([0, P, 0])
    cone_i = M.cylinder(h + 2, r_in0, r_in1 + 0.2, SEG).rotate([-90, 0, 0]).translate([0, P - 1, 0])
    cone = (cone_o ^ sphere(R_EYE - 1.6 - 0.15)) - cone_i
    # cross arm (thin, sits above LED tops) + M2 screw posts at the Jewel holes
    arm = box(-21, 21, P, P + 2.0, -1.5, 1.5)
    posts = M()
    for x in (-JEWEL_HOLE_X, JEWEL_HOLE_X):
        posts += cyl_y(2.0, P, P + 5, x=x)
    holes = M()
    for x in (-JEWEL_HOLE_X, JEWEL_HOLE_X):
        holes += cyl_y(0.8, P - 1, P + 4.5, x=x)
    ins = tube + cone + ((arm + posts) - cyl_y(r_in0 + 0.5, P - 1, 60) - cone_i - (sphere(80) - sphere(R_EYE - T_EYE - 0.15)))
    return ins - holes

# ---------------- YOKE (inside eye) ----------------
def yoke():
    # arms are as tall as the hub (+-4.8) so the part prints flat; with +-4 arms they hung
    # 0.8mm above the bed. The hub already keeps this 0.2mm clearance to the stalk plates.
    y = box(-39.6, 39.6, -4, 4, -4.8, 4.8) + cyl_z(7, -4.8, 4.8)
    y -= cyl_z(PIN, -10, 10)
    y -= cyl_x(PIN, 26, 41) + cyl_x(PIN, -41, -26)
    return y

# ---------------- STALK (bolts to frame pedestal) ----------------
def stalk():
    plate = cyl_z(7.5, 0, 3) + box(-7.5, 7.5, -40, 0, 0, 3)
    s = plate.translate([0, 0, 5]) + plate.translate([0, 0, -8])
    s += box(-7.5, 7.5, -110, -38, -8, 8)
    s -= cyl_z(PIN, -10, 10)
    for yy in (-100, -75):
        s -= cyl_z(PIN, -10, 10, y=yy)
    return s

# ---------------- EYELIDS ----------------
def lid(upper=True):
    a1, a2 = (1, 70)
    xin, xout = (53, 56) if upper else (56.5, 59.5)
    L = M()
    for s in (1, -1):
        body = shell(R_LO, R_LI) ^ wedge_x(a1, a2, -47, 47)
        bridge = (cyl_x(33, 44, xout) - cyl_x(29, 40, xout + 1)) ^ wedge_x(a1, a2, 40, xout + 1)
        plate = (wedge_x(a1, a2, xin, xout, r=33) + cyl_x(7, xin, xout))
        part = bridge + plate
        if s < 0:
            part = part.mirror([1, 0, 0])
        L += part if s > 0 else part
        if s > 0:
            L += body
    L -= cyl_x(1.7, -70, 70)
    # lever arm on one side only (upper: +X side, lower: -X side)
    lev = (box(xin, xout, -28, 0, -4, 4) + cyl_x(5, xin, xout, y=-28)) - cyl_x(ROD, xin - 1, xout + 1, y=-28)
    lev = lev.rotate([-20, 0, 0])   # arm points to phi=160 when closed
    L += lev
    if not upper:
        L = L.mirror([0, 0, 1]).mirror([1, 0, 0])
    return L

# ---------------- SERVO CRADLES / FRAME ----------------
SV_L, SV_W, EAR = 22.8, 12.4, 13.9   # SG90 body + ear hole offset

def cradle_plate_z(cx, cy, z_top, x0, x1, y0, y1):
    """Horizontal plate, servo shaft +Z, body long axis along Y."""
    p = box(x0, x1, y0, y1, z_top - 4, z_top)
    p -= box(cx - SV_W / 2, cx + SV_W / 2, cy - SV_L / 2 - 0.3, cy + SV_L / 2 + 0.3, z_top - 10, z_top + 1)
    for d in (-EAR, EAR):
        p -= cyl_z(0.9, z_top - 10, z_top + 1, x=cx, y=cy + d)
    return p

def cradle_plate_x(face, thk_dir, cy, cz, y0, y1, z0, z1):
    """Vertical plate normal to X. face = x where servo ears rest; thk_dir=+1 plate extends +x."""
    xa, xb = (face, face + 4) if thk_dir > 0 else (face - 4, face)
    p = box(xa, xb, y0, y1, z0, z1)
    p -= box(xa - 1, xb + 1, cy - SV_L / 2 - 0.3, cy + SV_L / 2 + 0.3, cz - SV_W / 2, cz + SV_W / 2)
    for d in (-EAR, EAR):
        p -= cyl_x(0.9, xa - 1, xb + 1, y=cy + d, z=cz)
    return p

def frame():
    zb = -H
    f = box(-90, 90, -128, 62, zb - 5, zb)                         # base plate
    for x0, x1 in ((60.5, 65.5), (-65.5, -60.5)):                   # lid pivot uprights
        up = M.batch_hull([box(x0, x1, -30, 30, zb, zb + 1), box(x0, x1, -12, 12, -1, 0),
                           cyl_x(12, x0, x1)])
        f += up - cyl_x(TAP, x0 - 1, x1 + 1)
    f += box(-90, 90, -128, -123, zb, 35)                           # rear wall
    f += box(-7.5, 7.5, -123, -56, zb, -8)                          # stalk pedestal
    for yy in (-100, -75):
        f -= cyl_z(TAP, -30, -7, y=yy)
    # pan servo (shaft +Z at x=36,y=-85, horn plane z=0)
    f += cradle_plate_z(36, -90.5, -11, 23, 49, -123, -71)
    f += box(23, 27, -123, -71, zb, -15) + box(45, 49, -123, -71, zb, -15)
    # tilt servo (shaft -X, horn plane x=-32 at y=-85,z=20); ears rest on face x=-21
    f += cradle_plate_x(-21, +1, -90.5, 20, -123, -66, zb, 32)
    # upper-lid servo (horn plane x=54.5, y=-80, z=0); ears on face x=65.5
    f += cradle_plate_x(65.5, +1, -85.5, 0, -123, -66, zb, 12)
    # lower-lid servo (horn plane x=-58); ears on face x=-69
    f += cradle_plate_x(-69, -1, -85.5, 0, -123, -66, zb, 12)
    # base mounting holes
    for x in (-80, 80):
        for y in (-115, 50):
            f -= cyl_z(2.2, zb - 6, zb + 1, x=x, y=y)
    return f

# ---------------- dummy servos for preview ----------------
def sg90():
    s = box(-SV_W / 2, SV_W / 2, -SV_L / 2, SV_L / 2, -15.9, 6.8)        # body (ears at z=0..2.5)
    s += box(-SV_W / 2, SV_W / 2, -16.1, 16.1, 0, 2.5)
    s += cyl_z(2.4, 6.8, 11, y=SV_L / 2 - 5.9)                          # shaft
    s += box(-3, 3, SV_L / 2 - 5.9 - 16, SV_L / 2 - 5.9 + 3, 10, 11.5)  # horn
    return s  # shaft at y=+5.5, horn top ~11 above ears

def servos():
    s = M()
    # pan: ears rest z=-11, shaft at y=-85
    s += sg90().rotate([0, 0, 180]).translate([36, -90.5, -11]).rotate([0, 0, 0])
    # tilt: shaft along -X; map servo +Z -> -X
    s += sg90().rotate([0, 0, 180]).rotate([0, -90, 0]).translate([-21, -90.5, 20])
    s += sg90().rotate([0, 0, 180]).rotate([0, -90, 0]).translate([65.5, -85.5, 0])
    s += sg90().rotate([0, 0, 180]).rotate([0, 90, 0]).translate([-69, -85.5, 0])
    return s

def save(m, name):
    mesh = m.to_mesh()
    t = trimesh.Trimesh(mesh.vert_properties[:, :3], mesh.tri_verts)
    t.export(f"{OUT}/{name}.stl")
    return t

if __name__ == "__main__":
    front, rear = eye_halves()
    yk, st, fr = yoke(), stalk(), frame()
    lu, ll = lid(True), lid(False)
    li = led_insert()
    # assembly (lids shown open)
    lu_open, ll_open = lu.rotate([LID_OPEN, 0, 0]), ll.rotate([-LID_OPEN, 0, 0])
    parts = dict(led_insert=li, eye_front=front, eye_rear=rear, yoke=yk, stalk=st, frame=fr,
                 lid_upper=lu, lid_lower=ll)
    # print orientations
    printable = dict(
        eye_front=(front + front_rim_support()).rotate([90, 0, 0]),   # split face down, snap-off rim support
        eye_front_nosupport=front.rotate([90, 0, 0]),                 # for slicer-generated supports
        eye_rear=(rear + rear_boss_supports()).rotate([-90, 0, 0]),   # snap-off boss supports
        eye_rear_nosupport=rear.rotate([-90, 0, 0]),
        yoke=yk, stalk=st.rotate([0, 90, 0]), led_insert=li.rotate([90, 0, 0]),
        frame=fr, lid_upper=lu, lid_lower=ll)
    for k, v in printable.items():
        bb = v.bounding_box()
        v = v.translate([-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, -bb[2]])
        save(v, k)
        print(k, "ok", v.status(), "vol %.0f" % v.volume())
    asm = front + rear + li + yk + st + fr + lu_open + ll_open
    asm = asm.translate([0, 0, H + 5])
    save(asm, "ASSEMBLY_preview")
    save((asm + servos().translate([0, 0, H + 5])), "ASSEMBLY_with_servos")
    # interference checks (lids open & closed vs eye/frame)
    eye = front + rear
    for nm, a, b in [("eye-frame", eye, fr), ("eye-lidU_open", eye, lu_open), ("eye-lidL_open", eye, ll_open),
                     ("eye-lidU_closed", eye, lu), ("lidU-lidL_closed", lu, ll), ("lidU-lidL_open", lu_open, ll_open),
                     ("lids-frame", lu_open + ll_open, fr), ("lidsC-frame", lu + ll, fr), ("eye-stalk", eye, st),
                     ("yoke-stalk", yk, st), ("servos-frame", servos(), fr)]:
        print(nm, "overlap vol %.1f" % (a ^ b).volume())
    # eye rotated range check
    for ang in [(20, 0, 0), (-20, 0, 0), (0, 0, 20), (0, 0, -20), (15, 0, 15)]:
        er = eye.rotate(list(ang))
        print("eye", ang, "stalk %.1f" % (er ^ st).volume(), "lidsOpen %.1f" % (er ^ (lu_open + ll_open)).volume(),
              "frame %.1f" % (er ^ fr).volume())
