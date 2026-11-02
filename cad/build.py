"""Animatronic eye (4in / 102mm hollow) with X/Y gimbal + upper/lower eyelids, SG90 servos.
Coordinates: origin = eye center, +Y = gaze forward, +Z = up, X = lateral. Units mm."""
import numpy as np, trimesh, os
from manifold3d import Manifold as M, CrossSection as CS, JoinType, OpType

SEG = 96
OUT = os.path.dirname(os.path.abspath(__file__)) + "/stl"
os.makedirs(OUT, exist_ok=True)

R_EYE, T_EYE = 51.0, 2.5          # 102mm OD eye; T_EYE = structural wall (rear, collar)
FRONT_WALL = 1.2                 # white of the eye: thin enough for the ring LEDs to glow through
IRIS_R = 20.0                    # iris radius (light window, lit by the centre LED)
IRIS_RECESS = 0.4                # iris sunk into the outside: window = FRONT_WALL - IRIS_RECESS = 0.8mm
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
    # iris recess (paint a pupil / iris pattern, or inlay). The iris is thinned only from the
    # outside: the inside stays one smooth sphere (eye_halves thins it to FRONT_WALL), so each
    # layer of the iris prints straight onto the white next to it. Thinning it from the inside
    # too left the iris rim starting in mid-air and printing stringy.
    e -= (sphere(R_EYE + 1) - sphere(R_EYE - IRIS_RECESS)) ^ cyl_y(IRIS_R, 0, 60)
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
    # thin the white of the eye (and the iris, under its recess) to FRONT_WALL so the LEDs glow
    # through it; the bayonet collar keeps its thickness
    front -= sphere(R_EYE - FRONT_WALL) ^ box(-60, 60, SEAM + COLLAR_H, 60, -60, 60)
    front += insert_shelves()
    return front, rear

def front_rim_support():
    """Breakaway ring for printing the front cap seam-down. The cap's flat mating rim
    (r ~47.5-50.2 at the seam) sits 3.3mm above the bed on the lip and would otherwise
    print in mid-air. Stops PRINT_GAP below the rim and clears the bayonet lugs (r 48.45)."""
    return ring_y(50.0, 48.75, LIP_Y0, SEAM - PRINT_GAP)

# ---------------- LED INSERT (WS2812 jewel: centre LED -> iris, 6 ring LEDs -> white of the eye) ----
JEWEL_HOLE_X = 9.2            # half of ~18.4mm hole spacing (measure yours!)
LED_FACE = 28.0               # Jewel LED-side PCB face (y). Deep enough that the funnel walls are 45 deg
P = LED_FACE + 1.75           # insert back plane: 1.6mm LED height + clearance
FUNNEL_WALL = 1.6             # horizontal wall: thick enough that ring-LED light doesn't leak into the iris
RIM_GAP = 0.05                # funnel rim to iris window, with the insert locked
# twist-lock: the insert's arm reaches the cap wall; its end pads sit on shelves inside the cap
LOCK_ANG = (90, 270)          # locked arm directions (deg, XZ plane, as LUG_ANG): top and bottom, under the lids
LOCK_TWIST = 32               # insert turns +32 deg (counter-clockwise seen from the open back) to lock
PAD_R0, PAD_HW = 33.0, 4.0    # arm end pad: inner radius, half width
SHELF_R = 34.5                # shelf inner edge

def frustum_y(r0, r1, y0, y1):
    return M.cylinder(y1 - y0, r0, r1, SEG).rotate([-90, 0, 0]).translate([0, y0, 0])

def led_insert():
    """Iris funnel. Carries the centre LED's light out to the iris window and keeps the six ring
    LEDs' light out of it, so they light the white of the eye instead. Prints back-face down
    without supports (45 deg walls). Push it into the front cap until the rim meets the iris
    and twist it to click onto the cap's shelves (insert_shelves). White PLA reflects the most
    light; if iris and white bleed into each other, paint the outside dark."""
    win_in = R_EYE - FRONT_WALL                # iris window inner surface
    r0, r1 = 3.8, IRIS_R - 0.8                 # funnel inner radius at the LED plane / at the window
    y1 = np.sqrt((win_in - RIM_GAP) ** 2 - r1 ** 2) + 1.5   # run past the window, then clip to it
    k = (r1 - r0) / (y1 - P)                   # radius growth per mm
    outer = frustum_y(r0 + FUNNEL_WALL, r1 + FUNNEL_WALL, P, y1)
    inner = frustum_y(r0 - k, r1 + k, P - 1, y1 + 1)       # same cone, extended 1mm each end
    funnel = (outer ^ sphere(win_in - RIM_GAP)) - inner
    # cross arm on the back plane, with screw bosses at the jewel's mounting holes. It runs out
    # to the cap wall, ending in the twist-lock pads.
    arm = box(-41, 41, P, P + 3.0, -1.5, 1.5)
    for s in (1, -1):
        pad = box(PAD_R0, 41, P, P + 2.5, -PAD_HW, PAD_HW)
        # 45 deg chamfers on the pad's lower edges, so it rides up over the detent bump
        for z in (-PAD_HW, PAD_HW):
            pad -= M.cube([20, 0.85, 0.85], True).rotate([45, 0, 0]).translate([37, P, z])
        arm += pad if s > 0 else pad.rotate([0, 180, 0])
    arm = arm ^ sphere(win_in - 0.5)
    for x in (-JEWEL_HOLE_X, JEWEL_HOLE_X):
        arm += cyl_y(2.0, P, P + 4.5, x=x)
    holes = M()
    for x in (-JEWEL_HOLE_X, JEWEL_HOLE_X):
        holes += cyl_y(0.8, P - 1, P + 4.3, x=x)
    # built with the arm along X; turn it to the locked direction (LOCK_ANG, +X -> +Z)
    return ((funnel + (arm - inner)) - holes).rotate([0, -90, 0])

def insert_shelves():
    """Twist-lock catches inside the front cap, one per LOCK_ANG. Turning the insert (+angle)
    its pad rides a lead-in ramp, clicks over a one-layer bump, seats, and meets an end stop.
    The 45 deg underside grows out of the wall, so the cap still prints seam-down unsupported."""
    def band(a1, a2, top):
        body = cyl_y(R_EYE, top - 16, top) - frustum_y(SHELF_R + 16, SHELF_R, top - 16, top)
        return body ^ wedge_y(a1, a2, top - 17, top + 1)
    s = M()
    for a in LOCK_ANG:
        s += band(a - 20, a - 14, P - 0.4)        # lead-in
        s += band(a - 14, a - 11, P - 0.2)
        s += band(a - 11, a - 7.5, P + 0.4)       # detent bump (arms flex ~0.35mm to pass)
        s += band(a - 7.5, a + 7.5, P)            # seat: pad bottom face
        s += band(a + 7.5, a + 12, P + 2.5)       # end stop
    return s ^ sphere(R_EYE - 0.6)

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

# ---------------- WINDOW MOUNT ----------------
# The frame's front is a plate that sits flush on the window glass, with a hole the eye looks
# out through. It rises above the eye to a pocket for one threaded suction cup (stud through
# the back of the pocket, brass nut behind). The whole frame is built from thin plates with
# lattice cut-outs (print it with 100% infill / solid walls: no hidden infill to print).
Y_GLASS = 60.0                # glass plane; lids reach y 56.5, so 3.5mm clearance
PLATE_T = 4.0                 # front plate thickness
VIEW_R = 40.0                 # hole the eye looks through (80mm; the eye can turn +-25 deg inside it)
CUP_POCKET_R = 35.0           # suction cup up to 2.68in (68mm) across, pressed flat
CUP_DEPTH = 14.0              # glass to the back of the cup's hub when pressed on the glass. MEASURE
                              # YOURS: too deep is fine (add cup_shims between hub and pocket floor)
CUP_Z = 97.0                  # suction cup centre height above the eye centre
CUP_WALL = 3.0
STUD_R = 2.4                  # 8-32 stud (4.17mm) clearance
ARCH_FLAT = 10.0              # half-width of the flat (bridged) top of holes in upright walls
RIB = 3.0                     # lattice rib width
LATTICE = 24.0                # lattice rib spacing
BASE_T = 4.0                  # base plate and rear (servo) wall thickness
REAR_Y = -127.0               # back face of the rear wall

# Cross-sections are used to find what touches a plate: Manifold.project() returns close to the
# convex hull for some shapes, which would mark whole plates as "keep solid".
def section_xz(m, y):
    """Cut through a solid at Y = y, as a CrossSection in (x, z)."""
    return m.rotate([-90, 0, 0]).slice(-y)      # (x, y, z) -> (x, z, -y)

def section_yz(m, x):
    """Cut through a solid at X = x, as a CrossSection in (y, z)."""
    return m.rotate([0, 0, -90]).rotate([-90, 0, 0]).slice(x)   # (x, y, z) -> (y, z, x)

def xz_slab(cs, y0, y1):
    """Extrude an (x, z) section along Y between y0 and y1."""
    return cs.extrude(y1 - y0).transform([[1, 0, 0, 0], [0, 0, -1, y1], [0, 1, 0, 0]])

def yz_slab(cs, x0, x1):
    return cs.extrude(x1 - x0).transform([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0]])

def lattice_holes(region, keep=None, border=5.0, angle=60.0, min_area=30.0):
    """Diamond cut-outs filling `region` (CrossSection), leaving RIB-wide ribs at +-angle, a
    `border` round the edge and solid wherever `keep` is (plus RIB). 60 deg ribs make every
    hole self-supporting when the plate prints standing up."""
    area = region.offset(-border, JoinType.Miter)
    if keep is not None:
        area = area - keep.offset(RIB, JoinType.Round)
    (x0, y0, x1, y1) = region.bounds()
    cx, cy, R = (x0 + x1) / 2, (y0 + y1) / 2, np.hypot(x1 - x0, y1 - y0)
    ribs = []
    for a in (angle, 180 - angle):
        n = np.radians(a + 90)
        for k in np.arange(-R, R, LATTICE):
            ribs.append(CS.square([2 * R, RIB], center=True).rotate(a)
                        .translate([cx + k * np.cos(n), cy + k * np.sin(n)]))
    holes = (area - CS.batch_boolean(ribs, OpType.Add))
    holes = holes.offset(-1.2, JoinType.Round).offset(1.2, JoinType.Round)   # round corners, drop slivers
    return CS.compose([p for p in holes.decompose() if p.area() >= min_area])

def circle(r, x=0.0, y=0.0):
    return CS.circle(r, SEG).translate([x, y])

def rect(x0, x1, y0, y1):
    return CS.square([x1 - x0, y1 - y0]).translate([x0, y0])

def arch(r, x=0.0, z=0.0):
    """Round hole for an upright wall: 45 deg shoulders up to a short flat top that bridges
    cleanly (a plain circle's top sags when printed standing up)."""
    a = r / np.sqrt(2)
    top = 2 * a - ARCH_FLAT
    return (circle(r) + CS([[(-a, a), (a, a), (ARCH_FLAT, top), (-ARCH_FLAT, top)]])).translate([x, z])

def front_outline():
    """Front plate in (x, z): full width at the bottom, narrowing up to the suction cup."""
    return (rect(-90, 90, -H - BASE_T, 40) + arch(CUP_POCKET_R + 4, 0, CUP_Z)).hull()

def cup_housing():
    """Pocket for the suction cup: open toward the glass, stud hole in its floor. Its underside is
    a 45 deg chin down to the front plate, so nothing starts in mid-air when printing."""
    y_floor = Y_GLASS - CUP_DEPTH
    back = y_floor - PLATE_T                      # back face of the pocket floor
    z_chin = CUP_Z - CUP_POCKET_R - CUP_WALL - (y_floor - back) - (Y_GLASS - PLATE_T - y_floor)
    outer = arch(CUP_POCKET_R + CUP_WALL, 0, CUP_Z) + rect(-CUP_POCKET_R - CUP_WALL, CUP_POCKET_R + CUP_WALL,
                                                           z_chin, CUP_Z)
    h = xz_slab(outer, back, Y_GLASS)
    # keep only what's above a 45 deg plane rising from the plate back toward the pocket floor
    yb = Y_GLASS - PLATE_T
    above = CS([[(yb, z_chin), (Y_GLASS + 1, z_chin - 50), (Y_GLASS + 1, 400), (yb - 300, 400),
                 (yb - 300, z_chin + 300)]])
    h ^= yz_slab(above, -100, 100)
    h -= xz_slab(arch(CUP_POCKET_R, 0, CUP_Z), y_floor, Y_GLASS + 1)
    return h - cyl_y(STUD_R, back - 1, y_floor + 1, z=CUP_Z)

def window_mount():
    """Front plate + cup housing + stiffening ribs + side gussets (before the lattice)."""
    view = xz_slab(arch(VIEW_R), Y_GLASS - 20, Y_GLASS + 1)
    pocket = xz_slab(arch(CUP_POCKET_R, 0, CUP_Z), Y_GLASS - CUP_DEPTH, Y_GLASS + 1)
    m = xz_slab(front_outline(), Y_GLASS - PLATE_T, Y_GLASS) + cup_housing()
    # bezel round the view hole stiffens its edge (lids stay inside r 26 at this depth)
    # (a 45 deg keel underneath, so its lowest point doesn't start in mid-air)
    keel = CS([[(-(VIEW_R + RIB), 0), (0, -(VIEW_R + RIB) * np.sqrt(2)), (VIEW_R + RIB, 0)]])
    m += xz_slab(arch(VIEW_R + RIB) + keel, Y_GLASS - 10, Y_GLASS - PLATE_T)
    # diagonal ribs behind the plate: carry the cup's pull down to the base corners
    for s in (1, -1):
        rib = (circle(RIB / 2, s * 30, CUP_Z - 20) + circle(RIB / 2, s * 86, -H + 2)).hull()
        m += xz_slab(rib, Y_GLASS - 14, Y_GLASS - PLATE_T)
    m -= view + pocket                               # ribs and bezel never cross the openings
    # side gussets: triangles tying the front plate to the base along both outer edges
    gusset = CS([[(Y_GLASS - PLATE_T, -H), (Y_GLASS - PLATE_T, 40), (-40, -H)]])
    for x0 in (86, -90):
        m += yz_slab(gusset, x0, x0 + 4)
    return m

def cup_shims():
    """Spacers between the cup hub and the pocket floor if your cup is shorter than CUP_DEPTH."""
    s = M()
    for i, t in enumerate((1.0, 2.0, 4.0)):
        s += (cyl_z(10, 0, t) - cyl_z(STUD_R, -1, t + 1)).translate([i * 24, 0, 0])
    return s

def frame():
    zb = -H
    f = box(-90, 90, REAR_Y, Y_GLASS - PLATE_T, zb - BASE_T, zb)    # base plate
    for x0, x1 in ((60.5, 65.5), (-65.5, -60.5)):                   # lid pivot uprights
        up = M.batch_hull([box(x0, x1, -30, 30, zb, zb + 1), box(x0, x1, -12, 12, -1, 0),
                           cyl_x(12, x0, x1)])
        f += up - cyl_x(TAP, x0 - 1, x1 + 1)
    f += box(-90, 90, REAR_Y, REAR_Y + BASE_T, zb, 35)              # rear wall
    # stalk pedestal: a channel (top plate + two side walls) with bosses for the stalk screws
    f += box(-7.5, 7.5, -123, -56, -14, -8)
    f += box(-7.5, -4.5, -123, -56, zb, -8) + box(4.5, 7.5, -123, -56, zb, -8)
    for yy in (-100, -75):
        f += cyl_z(4.5, zb, -8, y=yy) ^ box(-7.5, 7.5, -130, 0, zb - 1, 0)
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
    # base mounting holes (to stand it on a shelf instead)
    for x in (-80, 80):
        for y in (-115, 40):
            f -= cyl_z(2.2, zb - BASE_T - 1, zb + 1, x=x, y=y)
    f += window_mount()
    return lighten(f) + side_rails()

# Side rails: a low truss along each side, from the front gussets back into the rear wall. They tie
# the front (cup) half of the frame to the rear (servo) half, which otherwise meet only through
# the thin base plate behind the eye, and they're where the ESP32 board mounts: its holes are
# drilled through the two solid rails, so any board with hole rows RAIL_PITCH +- 7mm apart fits.
RAIL_W = 8.0                  # height of each solid rail
RAIL_PITCH = 20.0             # rail centre to rail centre
RAIL_Y0, RAIL_Y1 = REAR_Y + BASE_T - 0.01, -10.0   # rear wall to well inside the gusset

def side_rails():
    zb = -H
    z_top = zb + RAIL_PITCH + RAIL_W                   # 28mm above the base: below the eye and lids
    holes = lattice_holes(rect(RAIL_Y0, RAIL_Y1, zb + RAIL_W, z_top - RAIL_W), border=0)
    r = M()
    for x0 in (86, -90):
        r += box(x0, x0 + 4, RAIL_Y0, RAIL_Y1, zb, z_top) - yz_slab(holes, x0 - 0.01, x0 + 4.01)
    return r

def lighten(f):
    """Lattice cut-outs in the base, the rear (servo) wall, the front plate and the gussets.
    Each plate stays solid wherever something else joins it."""
    zb = -H
    keep = f.slice(zb + 0.5)                                       # everything standing on the base
    for x in (-80, 80):
        for y in (-115, 40):
            keep += circle(6, x, y)
    holes = lattice_holes(rect(-90, 90, REAR_Y, Y_GLASS - PLATE_T), keep)
    f -= holes.extrude(BASE_T + 2).translate([0, 0, zb - BASE_T - 1])
    # rear wall: servo cradles and the stalk pedestal join it
    keep = section_xz(f, REAR_Y + BASE_T + 0.5)
    f -= xz_slab(lattice_holes(rect(-90, 90, zb, 35), keep), REAR_Y - 1, REAR_Y + BASE_T + 0.01)
    # front plate: the view-hole bezel, ribs, cup housing and gussets join it
    keep = section_xz(f, Y_GLASS - PLATE_T - 0.5)
    region = front_outline() - arch(VIEW_R + RIB) - arch(CUP_POCKET_R + CUP_WALL, 0, CUP_Z)
    f -= xz_slab(lattice_holes(region, keep, border=4), Y_GLASS - PLATE_T - 0.01, Y_GLASS + 1)
    # side walls standing on the base: gussets, servo cradles, lid uprights, pedestal walls
    for x0, x1, y0, y1, z1 in YZ_WALLS:
        f = lighten_yz(f, x0, x1, y0, y1, zb + 0.01, z1)
    return f

# (x0, x1, y0, y1, top z) of each wall in the YZ plane that gets a lattice
YZ_WALLS = [(86, 90, -41, Y_GLASS - PLATE_T, 41), (-90, -86, -41, Y_GLASS - PLATE_T, 41),   # gussets
            (23, 27, -123, -71, -15), (45, 49, -123, -71, -15),                             # pan cradle
            (-21, -17, -123, -66, 32),                                                      # tilt cradle
            (65.5, 69.5, -123, -66, 12), (-73, -69, -123, -66, 12),                         # lid cradles
            (60.5, 65.5, -30, 30, 12), (-65.5, -60.5, -30, 30, 12),                         # lid uprights
            (4.5, 7.5, -123, -56, -14), (-7.5, -4.5, -123, -56, -14)]                       # pedestal walls

def lighten_yz(f, x0, x1, y0, y1, z0, z1):
    """Lattice through one wall in the YZ plane, kept solid wherever a neighbour touches it."""
    win = box(x0, x1, y0, y1, z0, z1)
    region = section_yz(f ^ win, (x0 + x1) / 2)
    keep = section_yz(f, x0 - 0.5) + section_yz(f, x1 + 0.5)
    holes = lattice_holes(region, keep, border=4)
    return f - yz_slab(holes, x0 - 0.01, x1 + 0.01) if not holes.is_empty() else f

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
        frame=fr, lid_upper=lu, lid_lower=ll, cup_shims=cup_shims())
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
                     ("yoke-stalk", yk, st), ("servos-frame", servos(), fr), ("insert-eye", li, eye)]:
        print(nm, "overlap vol %.1f" % (a ^ b).volume())
    # insert twist-lock: at the unlocked angle it must slide all the way in past the shelves
    li_free = li.rotate([0, LOCK_TWIST, 0])
    print("insert entry path overlap %.1f" % max((li_free.translate([0, -d, 0]) ^ front).volume()
                                                 for d in (0, 0.5, 1, 2, 4, 8, 16)))
    # eye rotated range check
    for ang in [(20, 0, 0), (-20, 0, 0), (0, 0, 20), (0, 0, -20), (15, 0, 15)]:
        er = eye.rotate(list(ang))
        print("eye", ang, "stalk %.1f" % (er ^ st).volume(), "lidsOpen %.1f" % (er ^ (lu_open + ll_open)).volume(),
              "frame %.1f" % (er ^ fr).volume())
