"""A zoo of test bodies whose extra parts are not a tail: wings, a dorsal fin, a shoulder
cannon, two tails, a trunk, a cape, tentacles, an asymmetric horn pair, a quadruped.

The pipeline must not be tuned to the one model it was first tried on ("the tail is for this
model - what if it has wings in another one?"). These bodies are built like the director's AI
meshes (Tripo): simple primitives fused by a voxel remesh into ONE closed surface (optionally
with a few loose or buried extra shells), Z up, facing -Y, feet on the ground, about 1-2 m
tall, T-pose where there are arms.

Every generator returns (object, info):
  info["appendages"][name] = {
      "kind":      wing / fin / cannon / pauldron / tail / trunk / cape / tentacle / horn / ear
      "side":      "l" (+X), "r" (-X) or "c" (on the centre line)
      "symmetry":  one of SYMMETRY (pair, pair_posed, pair_asym, one-sided, centre)
      "twin":      the name of its mirror partner (pairs only)
      "root", "tip":  where it leaves the body (design: the middle of the root for a long one,
                   whose ends are "root_line") and its far end, world space
      "root_shape", "root_size":  designed root cross-section ("round", "oval", "slot",
                   "line", "arc") and its (long, short) extent in metres
      "ring":      the root ring MEASURED on the fused mesh from the ground truth (centre,
                   radius, major, minor, aspect, verts) - None for a loose shell
      "contacts":  places where it touches the body or another part AWAY from its root
      "thin", "thickness":  a sheet / thin tube (designed), typical thickness in metres
      "rig":       what a rig would hang on it: chain, wing, cloth, rigid
      "path":      a centre polyline from root to tip (bodies.arc works on it)
      "mirror_on_surface", "mirror_on_twin":  share of its vertices whose mirror image
                   (x -> -x) lies on the rest of the surface / on its twin }
  info["limbs"]: the same for arms and legs (covered by a humanoid skeleton).
  info["joints_hint"]: where a humanoid skeleton's main joints belong (pelvis, neck, head,
  hands, shoulders, hips, knees, ankles); empty for a quadruped.
  info["labels"]: owner names; the per-vertex ground truth (index into labels: which group of
  primitives each surface vertex came from) is info["truth"] and the int point attribute
  TRUTH_ATTR on the mesh, so it follows the mesh through copies and cuts.

Every generator takes voxel (remesh size), scale (overall size) and shells (extra shells:
buried inside the trunk / loose beside the body, alternating) plus its own shape parameters,
so tests can sweep them. Thin features never go under 2.2 voxels (they would break apart):
info["clamped"] lists any that were thickened for the chosen voxel.

A new body takes a few lines: k = _start(...); a base (_humanoid / _quadruped); primitives on
an owner named after the part (k.ball, k.tube, k.path, k.plate for a flat outline, k.sheet for
a curved one); k.appendage(...) to say what it is; return k.build(shells, params); add it to ZOO.
"""

from __future__ import annotations

import math

import bpy
import numpy as np

TRUTH_ATTR = "zoo_truth"
SYMMETRY = {
    "pair": "a mirrored twin of the same shape and pose",
    "pair_posed": "a twin of the same shape in another pose (most of it still mirrors onto the twin)",
    "pair_asym": "a twin at the mirrored root but of another shape or size (broken horn, other tail)",
    "one-sided": "no twin: mirroring would copy or delete it",
    "centre": "on the mirror plane, its own mirror image",
}


# ----------------------------------------------------------------------------- small helpers

def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _resample(pts, m: int) -> np.ndarray:
    """m points evenly spaced along a polyline."""
    P = np.asarray(pts, float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, s[-1], m)
    return np.stack([np.interp(t, s, P[:, i]) for i in range(3)], axis=1)


def _arc_params(pts) -> np.ndarray:
    P = np.asarray(pts, float)
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return s / max(s[-1], 1e-12)


def _lerp_ctrl(ctrl, t) -> np.ndarray:
    """Values given at evenly spaced control points (0..1), linearly interpolated at t."""
    C = np.asarray(ctrl, float)
    u = np.linspace(0.0, 1.0, len(C))
    if C.ndim == 1:
        return np.interp(t, u, C)
    return np.stack([np.interp(t, u, C[:, i]) for i in range(C.shape[1])], axis=1)


def coords(me) -> np.ndarray:
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype(np.float64)


def edges(me) -> np.ndarray:
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    return ev.reshape(-1, 2).astype(np.int64)


def _components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Connected component label per vertex (union-find over the given edges)."""
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, j in zip(a.tolist(), b.tolist()):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    return np.array([find(i) for i in range(n)])


def shells(me) -> int:
    """Number of separate pieces (connected surfaces) of the mesh."""
    ev = edges(me)
    lab = _components(len(me.vertices), ev[:, 0], ev[:, 1])
    return len(np.unique(lab))


def open_edges(me) -> tuple:
    """(boundary edges, edges with more than two faces): (0, 0) for a closed surface."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    b = sum(1 for e in bm.edges if e.is_boundary)
    nm = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    bm.free()
    return b, nm


def truth(me) -> np.ndarray | None:
    """The ground-truth owner index per vertex (see info["labels"]), or None."""
    a = me.attributes.get(TRUTH_ATTR)
    if a is None or a.domain != "POINT":
        return None
    v = np.empty(len(me.vertices), np.int32)
    a.data.foreach_get("value", v)
    return v


def part_mask(me, info: dict, name: str) -> np.ndarray:
    """Vertices whose ground truth is the named part (appendage, limb, "body", shell)."""
    lab = truth(me)
    if lab is None:
        lab = info["truth"]
    return lab == info["labels"].index(name)


def info_json(info: dict) -> dict:
    """The info without numpy arrays (for json.dump)."""
    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if not (k == "truth" and isinstance(v, np.ndarray))}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        if isinstance(x, np.ndarray):
            return clean(x.tolist())
        if isinstance(x, (np.floating,)):
            return float(x)
        if isinstance(x, (np.integer,)):
            return int(x)
        if isinstance(x, (np.bool_,)):
            return bool(x)
        return x
    return clean(info)


# ----------------------------------------------------------------------------- the kit

class Kit:
    """Primitives collected per owner ("body", "arm_l", "wing_l"...), fused at the end by a
    voxel remesh. Coordinates are design units (metres at scale 1)."""

    def __init__(self, name: str, kind: str, voxel: float, scale: float = 1.0):
        self.name, self.kind = name, kind
        self.voxel, self.scale = float(voxel), float(scale)
        self.tmin = 2.2 * self.voxel / self.scale        # thinnest feature that survives the remesh
        self.geo: dict = {}                              # owner -> ([verts], [faces])
        self.app: dict = {}                              # appendage name -> design info
        self.limbs: dict = {}
        self.clamped: list = []
        self.core = (0.0, 0.0, 1.2)                      # deep inside the trunk (buried shells)
        self.beside = (0.32, -0.04, 0.85)                # empty space next to the body (loose shells)
        self.joints: dict = {}                           # where a humanoid skeleton's joints belong
        self.notes = ""

    # -- primitives
    def _add(self, owner: str, V, F) -> None:
        gv, gf = self.geo.setdefault(owner, ([], []))
        off = len(gv)
        gv.extend(tuple(map(float, v)) for v in V)
        gf.extend([off + int(i) for i in f] for f in F)

    def _add_bm(self, owner: str, bm) -> None:
        self._add(owner, [v.co[:] for v in bm.verts], [[v.index for v in f.verts] for f in bm.faces])

    def _thin(self, t, what: str):
        t = np.asarray(t, float)
        if (t < self.tmin).any():
            self.clamped.append(what)
        return np.maximum(t, self.tmin)

    def ball(self, owner, c, r, s=(1, 1, 1), rot=None, seg: int = 24) -> None:
        """An ellipsoid: centre c, radius r times the axis scales s, optional rotation (3x3)."""
        import bmesh
        from mathutils import Matrix
        bm = bmesh.new()
        sx, sy, sz = (r * s[0], r * s[1], r * s[2])
        sx, sy, sz = (max(x, self.tmin / 2) for x in (sx, sy, sz))
        m = Matrix.Translation(c)
        if rot is not None:
            m = m @ Matrix(np.asarray(rot, float).tolist()).to_4x4()
        m = m @ Matrix.Diagonal((sx, sy, sz, 1))
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(8, seg * 2 // 3), radius=1.0, matrix=m)
        self._add_bm(owner, bm)
        bm.free()

    def tube(self, owner, a, b, r1, r2=None, seg: int = 16) -> None:
        """A capped cone from a (radius r1) to b (radius r2)."""
        import bmesh
        from mathutils import Matrix, Vector
        a, b = Vector(a), Vector(b)
        d = b - a
        if d.length < 1e-9:
            return
        r2 = r1 if r2 is None else r2
        r1, r2 = max(r1, self.tmin / 2), max(r2, self.tmin / 2)     # (a tapering tip: silently)
        bm = bmesh.new()
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r1, radius2=r2, depth=d.length, matrix=m)
        self._add_bm(owner, bm)
        bm.free()

    def path(self, owner, pts, radii, seg: int = 16, end_ball: bool = True) -> None:
        """Tubes along a polyline with a ball at every joint (a smooth bent tube)."""
        pts = [tuple(map(float, p)) for p in pts]
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            self.tube(owner, a, b, radii[i], radii[i + 1], seg)
            if i + 2 < len(pts) or end_ball:
                self.ball(owner, b, max(radii[i + 1], self.tmin / 2), seg=seg)

    def plate(self, owner, outline, thick, origin, u, v) -> None:
        """A flat solid: a 2D outline (in the plane origin + x*u + y*v) given a thickness
        (one value, or one per outline point: a tapered wedge)."""
        o, u, v = np.asarray(origin, float), _unit(u), _unit(v)
        nrm = _unit(np.cross(u, v))
        Q = np.asarray(outline, float)
        n = len(Q)
        t = np.broadcast_to(self._thin(thick, f"{owner} plate"), (n,))
        P = o + Q[:, :1] * u + Q[:, 1:2] * v
        top = P + nrm * (t[:, None] / 2)
        bot = P - nrm * (t[:, None] / 2)
        V = np.concatenate([top, bot])
        F = [list(range(n)), list(range(2 * n - 1, n - 1, -1))]
        F += [[i, n + i, n + (i + 1) % n, (i + 1) % n] for i in range(n)]
        self._add(owner, V, F)

    def sheet(self, owner, P, t) -> None:
        """A curved solid sheet: grid points P (m, c, 3) on its middle surface, thickness t (m, c)."""
        P = np.asarray(P, float)
        m, c = P.shape[:2]
        t = self._thin(np.broadcast_to(np.asarray(t, float), (m, c)), f"{owner} sheet")
        di = np.gradient(P, axis=0)
        dk = np.gradient(P, axis=1)
        N = np.cross(di, dk)
        N /= np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-12)
        top = (P + N * (t[..., None] / 2)).reshape(-1, 3)
        bot = (P - N * (t[..., None] / 2)).reshape(-1, 3)
        V = np.concatenate([top, bot])
        o = m * c

        def T(i, k):
            return i * c + k
        F = []
        for i in range(m - 1):
            for k in range(c - 1):
                F.append([T(i, k), T(i, k + 1), T(i + 1, k + 1), T(i + 1, k)])
                F.append([o + T(i, k), o + T(i + 1, k), o + T(i + 1, k + 1), o + T(i, k + 1)])
        for i in range(m - 1):
            F.append([T(i, 0), T(i + 1, 0), o + T(i + 1, 0), o + T(i, 0)])
            F.append([T(i + 1, c - 1), T(i, c - 1), o + T(i, c - 1), o + T(i + 1, c - 1)])
        for k in range(c - 1):
            F.append([T(0, k + 1), T(0, k), o + T(0, k), o + T(0, k + 1)])
            F.append([T(m - 1, k), T(m - 1, k + 1), o + T(m - 1, k + 1), o + T(m - 1, k)])
        self._add(owner, V, F)

    # -- what the parts are
    def appendage(self, name, kind, side, symmetry, root, tip, root_shape, root_size, thin, thickness,
                  rig, path=None, twin=None, **extra) -> None:
        assert symmetry in SYMMETRY, symmetry
        self.app[name] = {"kind": kind, "side": side, "symmetry": symmetry, "twin": twin,
                          "root": root, "tip": tip, "root_shape": root_shape, "root_size": root_size,
                          "thin": bool(thin), "thickness": float(thickness), "rig": rig,
                          "path": [tuple(map(float, p)) for p in (path if path is not None else (root, tip))],
                          **extra}

    def limb(self, name, kind, side, root, tip, path=None) -> None:
        self.limbs[name] = {"kind": kind, "side": side, "symmetry": "pair", "twin": name[:-1] + {"l": "r", "r": "l"}[name[-1]],
                            "root": root, "tip": tip,
                            "path": [tuple(map(float, p)) for p in (path if path is not None else (root, tip))]}

    # -- fuse
    def build(self, shells: int = 0, params: dict | None = None):
        """Voxel-remesh everything into one closed surface, put it on the ground, label every
        vertex with the owner it came from, measure the roots. Returns (object, info)."""
        s = self.scale
        owners = list(self.geo)
        allV, allF = [], []
        for o in owners:
            V, F = self.geo[o]
            off = len(allV)
            allV += V
            allF += [[i + off for i in f] for f in F]
        V = np.asarray(allV) * s
        src = bpy.data.meshes.new(self.name + "_src")
        src.from_pydata(V.tolist(), [], allF)
        src.update()
        ob = bpy.data.objects.new(self.name, src)
        bpy.context.scene.collection.objects.link(ob)
        mod = ob.modifiers.new("zoo_voxel", "REMESH")
        mod.mode, mod.voxel_size = "VOXEL", self.voxel
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        ob.modifiers.remove(mod)
        ob.data = me
        bpy.data.meshes.remove(src)
        me.name = self.name
        co = coords(me)
        dz = -float(co[:, 2].min())
        co[:, 2] += dz
        me.vertices.foreach_set("co", co.astype(np.float32).ravel())
        me.update()

        def W(p):                                   # design point -> world (scaled, on the ground)
            p = np.asarray(p, float) * s
            return (float(p[0]), float(p[1]), float(p[2] + dz))

        # ground truth: the owner whose primitives' surface is nearest
        from mathutils.bvhtree import BVHTree
        dist = np.full((len(owners), len(co)), np.inf)
        pad = 3 * self.voxel
        for j, o in enumerate(owners):
            Vo = np.asarray(self.geo[o][0]) * s + [0, 0, dz]
            tree = BVHTree.FromPolygons(Vo.tolist(), self.geo[o][1])
            lo, hi = Vo.min(axis=0) - pad, Vo.max(axis=0) + pad
            sel = np.nonzero(np.all((co >= lo) & (co <= hi), axis=1))[0]
            fn = tree.find_nearest
            dj = dist[j]
            for i in sel.tolist():
                h = fn(co[i])
                if h[0] is not None:
                    dj[i] = h[3]
        lab = np.argmin(dist, axis=0).astype(np.int32)
        labels = list(owners)

        # extra shells, like AI meshes have: buried inside the trunk / loose beside the body
        shell_info = []
        if shells:
            import bmesh
            from mathutils import Matrix
            bm = bmesh.new()
            bm.from_mesh(me)
            n0 = len(bm.verts)
            for i in range(shells):
                buried = i % 2 == 0
                k = i // 2
                if buried:
                    c = np.asarray(self.core, float) + [0.0, 0.0, 0.05 * k]
                    r = 0.035
                else:
                    c = np.asarray(self.beside, float) + [0.0, 0.0, 0.08 * k]
                    r = 0.02
                before = len(bm.verts)
                bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r * s,
                                           matrix=Matrix.Translation(W(c)))
                name = f"shell_{'buried' if buried else 'loose'}_{k + 1}"
                labels.append(name)
                shell_info.append({"name": name, "buried": buried, "centre": W(c), "radius": r * s,
                                   "verts": len(bm.verts) - before})
            bm.to_mesh(me)
            bm.free()
            me.update()
            extra = []
            for j, sh in enumerate(shell_info):
                extra += [len(owners) + j] * sh["verts"]
            lab = np.concatenate([lab, np.asarray(extra, np.int32)])
            assert len(lab) == len(me.vertices) and n0 + sum(x["verts"] for x in shell_info) == len(lab)
        a = me.attributes.new(TRUTH_ATTR, "INT", "POINT")
        a.data.foreach_set("value", lab)

        co = coords(me)
        ev = edges(me)
        app = {}
        for name, d in self.app.items():
            e = dict(d)
            e["root"], e["tip"] = W(d["root"]), W(d["tip"])
            e["path"] = [W(p) for p in d["path"]]
            e["root_size"] = tuple(float(x) * s for x in d["root_size"])
            e["thickness"] = d["thickness"] * s
            for key in ("contact_design", "root_line"):
                if key in e:
                    e[key] = [W(p) for p in e[key]]
            app[name] = e
        limbs = {}
        for name, d in self.limbs.items():
            e = dict(d)
            e["root"], e["tip"] = W(d["root"]), W(d["tip"])
            e["path"] = [W(p) for p in d["path"]]
            limbs[name] = e
        extras = set(app)
        from mathutils.kdtree import KDTree
        kd = KDTree(len(co))
        for i, p in enumerate(co):
            kd.insert(p, i)
        kd.balance()
        for name, e in list(app.items()) + list(limbs.items()):
            k = labels.index(name)
            e["verts"] = int((lab == k).sum())
            e["ring"], e["contacts"], e["root_on"] = _rings(co, ev, lab, labels, k, np.asarray(e["root"]), extras)
            e["mirror_on_surface"], e["mirror_on_twin"] = _mirror_share(kd, co, lab, labels, k, e, self.voxel)
        H = float(co[:, 2].max() - co[:, 2].min())
        info = {"name": self.name, "kind": self.kind, "height": H, "voxel": self.voxel, "scale": s,
                "front": "-Y", "up": "+Z", "verts": len(co), "faces": len(me.polygons),
                "labels": labels, "truth": lab, "appendages": app, "limbs": limbs, "shells": shell_info,
                "joints_hint": {j: W(p) for j, p in self.joints.items()},
                "clamped": sorted(set(self.clamped)), "params": dict(params or {}), "notes": self.notes}
        ob["zoo_body"] = self.name
        return ob, info


def _rings(co, ev, lab, labels, k, root_design, extras) -> tuple:
    """The root ring (where the part meets what it grows from, nearest its designed root) and
    the other contacts (touching the body or another part away from the root)."""
    inA = lab == k
    cross = inA[ev[:, 0]] != inA[ev[:, 1]]
    if not cross.any():
        return None, [], []
    a_side = np.where(inA[ev[cross, 0]], ev[cross, 0], ev[cross, 1])
    b_side = np.where(inA[ev[cross, 0]], ev[cross, 1], ev[cross, 0])
    band = np.zeros(len(co), bool)
    band[a_side] = True
    band[b_side] = True
    e_in = band[ev[:, 0]] & band[ev[:, 1]]
    sub = np.nonzero(band)[0]
    remap = np.full(len(co), -1)
    remap[sub] = np.arange(len(sub))
    comp = _components(len(sub), remap[ev[e_in, 0]], remap[ev[e_in, 1]])
    groups = []
    for cid in np.unique(comp[remap[a_side]]):
        m = comp[remap[a_side]] == cid
        av = np.unique(a_side[m])
        others = lab[b_side[m]]
        vals, cnt = np.unique(others, return_counts=True)
        with_ = [labels[int(x)] for x in vals[np.argsort(-cnt)]]
        groups.append((av, with_))
    # the root: the group nearest the designed root among those touching the body or a limb
    def is_body(names):
        return any(n not in extras for n in names)
    cands = [g for g in groups if is_body(g[1])] or groups
    root = min(cands, key=lambda g: float(np.min(np.linalg.norm(co[g[0]] - root_design, axis=1))))
    rc = co[root[0]]
    centre = rc.mean(axis=0)
    if len(rc) >= 3:
        _u, sv, vt = np.linalg.svd(rc - centre, full_matrices=False)
        proj = (rc - centre) @ vt[:2].T
        major = float(proj[:, 0].max() - proj[:, 0].min()) / 2
        minor = float(proj[:, 1].max() - proj[:, 1].min()) / 2
    else:
        major = minor = 0.0
    radius = float(np.median(np.linalg.norm(rc - centre, axis=1))) if len(rc) else 0.0
    aspect = minor / major if major > 1e-9 else 1.0
    shape = "round" if aspect >= 0.55 else "oval" if aspect >= 0.25 else "slot"
    ring = {"centre": tuple(map(float, centre)), "radius": radius, "major": major, "minor": minor,
            "aspect": float(aspect), "shape": shape, "verts": int(len(rc))}
    contacts = []
    for av, with_ in groups:
        if av is root[0]:
            continue
        contacts.append({"with": with_, "centre": tuple(map(float, co[av].mean(axis=0))), "verts": int(len(av))})
    contacts.sort(key=lambda c: -c["verts"])
    return ring, contacts, root[1]


def _mirror_share(kd, co, lab, labels, k, e, voxel) -> tuple:
    """Share of the part's vertices whose mirror image (x -> -x) lies on the surface: on any
    other owner (or on itself for a centre part), and on its twin."""
    idx = np.nonzero(lab == k)[0]
    if len(idx) == 0:
        return 0.0, None
    idx = idx[:: max(1, len(idx) // 3000)]
    tol = max(3.0 * voxel, 0.5 * float(e.get("thickness", 0.0) or 0.0))
    twin = labels.index(e["twin"]) if e.get("twin") in labels else None
    on_s = on_t = 0
    centre = e.get("symmetry") == "centre"
    for i in idx.tolist():
        p = co[i]
        q = (-p[0], p[1], p[2])
        hits = kd.find_range(q, tol)
        ls = {int(lab[h[1]]) for h in hits}
        if (ls - ({k} if not centre else set())) or (centre and k in ls):
            on_s += 1
        if twin is not None and twin in ls:
            on_t += 1
    n = len(idx)
    return on_s / n, (on_t / n if twin is not None else None)


# ----------------------------------------------------------------------------- bases

def _start(name, kind, voxel, scale, reset):
    if reset:
        bpy.ops.wm.read_homefile(use_empty=True)
    return Kit(name, kind, voxel, scale)


HEAD = (0.10, 0.11, 0.12)


def _humanoid(k: Kit, head=HEAD, head_c=(0.0, -0.01, 1.69), legs: bool = True) -> None:
    """A plain T-pose humanoid (1.8 m): trunk + head in "body", arms and legs as limbs."""
    B = "body"
    k.ball(B, (0, 0, 0.97), 1.0, (0.165, 0.12, 0.1125))           # pelvis
    k.ball(B, (0, 0, 1.22), 1.0, (0.19, 0.125, 0.29))             # torso
    k.tube(B, (-0.15, 0, 1.41), (0.15, 0, 1.41), 0.075)           # shoulders
    for x in (1, -1):
        k.ball(B, (0.15 * x, 0, 1.41), 0.07)
    k.tube(B, (0, 0, 1.44), (0, 0, 1.60), 0.05)                   # neck
    k.ball(B, head_c, 1.0, head)
    for x, s in ((1, "l"), (-1, "r")):
        arm = [(0.14 * x, 0, 1.41), (0.46 * x, 0, 1.41), (0.71 * x, 0, 1.41)]
        k.path(f"arm_{s}", arm, [0.055, 0.044, 0.035])
        k.ball(f"arm_{s}", (0.775 * x, -0.005, 1.41), 1.0, (0.065, 0.03, 0.045))
        k.limb(f"arm_{s}", "arm", s, (0.16 * x, 0, 1.41), (0.84 * x, -0.005, 1.41), arm + [(0.84 * x, -0.005, 1.41)])
        if legs:
            leg = [(0.095 * x, 0, 1.0), (0.10 * x, 0, 0.52), (0.10 * x, 0.01, 0.09)]
            k.path(f"leg_{s}", leg, [0.08, 0.06, 0.042])
            k.ball(f"leg_{s}", (0.10 * x, -0.05, 0.045), 1.0, (0.05, 0.12, 0.045))
            k.limb(f"leg_{s}", "leg", s, (0.095 * x, 0, 0.92), (0.10 * x, -0.17, 0.0),
                   leg + [(0.10 * x, -0.17, 0.02)])
    k.core = (0.0, 0.0, 1.2)
    k.beside = (0.32, -0.04, 0.85)
    k.joints = {"pelvis": (0, 0, 0.97), "neck": (0, 0, 1.47), "head": (0, head_c[1], head_c[2] - 0.9 * head[2]),
                "head_top": (0, head_c[1], head_c[2] + head[2]), "hand_l": (0.84, -0.005, 1.41),
                "hand_r": (-0.84, -0.005, 1.41), "shoulder_l": (0.16, 0, 1.41), "shoulder_r": (-0.16, 0, 1.41)}
    if legs:
        k.joints.update({"hip_l": (0.095, 0, 0.95), "hip_r": (-0.095, 0, 0.95), "knee_l": (0.10, 0, 0.52),
                         "knee_r": (-0.10, 0, 0.52), "ankle_l": (0.10, 0.01, 0.09), "ankle_r": (-0.10, 0.01, 0.09)})
    else:
        del k.joints["pelvis"]                       # no legs: where a pelvis goes is a rig choice


def _torso_back(z: float, x: float = 0.0) -> float:
    """y of the humanoid's back surface (torso ellipsoid) at height z, side offset x."""
    q = 1.0 - (x / 0.19) ** 2 - ((z - 1.22) / 0.29) ** 2
    return 0.125 * math.sqrt(max(q, 0.0))


# ----------------------------------------------------------------------------- wings

def _bat_wing(k: Kit, x: int, s: str, thick: float, span: float, fingers: int, scallop: float,
              bones: bool, symmetry: str, twin):
    """A membrane wing from the upper back: a flat plate a few voxels thick, a long slot-shaped
    root, finger bones fanning from the wrist, a scalloped trailing edge."""
    name = f"wing_{s}"
    R = np.array([0.07 * x, _torso_back(1.28, 0.07), 1.28])
    u = _unit((1.0 * x, 0.75, 0.15))
    v = _unit(np.array([0.0, 0.0, 1.0]) - u[2] * u)
    hr, bury = 0.12, 0.06
    W2 = np.array([0.30, 0.30]) * span
    angs = np.radians(np.linspace(15, -70, fingers))
    lens = np.linspace(0.62, 0.42, fingers) * span
    tips = [W2 + L * np.array([math.cos(a), math.sin(a)]) for a, L in zip(angs, lens)]
    cen = np.mean([W2] + tips + [np.array([0.0, -hr])], axis=0)

    def scal(P, Q, n=8):
        P, Q = np.asarray(P), np.asarray(Q)
        mid = (P + Q) / 2
        d = Q - P
        nrm = np.array([-d[1], d[0]])
        nrm = nrm / max(np.linalg.norm(nrm), 1e-12)
        if nrm @ (cen - mid) < 0:
            nrm = -nrm
        C = mid + nrm * scallop * np.linalg.norm(d)
        t = np.linspace(0, 1, n + 2)[1:-1, None]
        return list((1 - t) ** 2 * P + 2 * (1 - t) * t * C + t ** 2 * Q)
    out = [np.array([-bury, hr]), np.array([0.0, hr]), W2, tips[0]]
    for a, b in zip(tips, tips[1:]):
        out += scal(a, b) + [b]
    out += scal(tips[-1], np.array([0.03, -hr])) + [np.array([0.03, -hr]), np.array([-bury, -hr])]
    k.plate(name, out, thick, R, u, v)

    def to3(q):
        return R + q[0] * u + q[1] * v
    if bones:
        br = 0.8 * max(thick, k.tmin)
        k.tube(name, to3(np.array([-bury, 0.0])), to3(W2), br * 1.3, br * 1.1)
        k.ball(name, to3(W2), br * 1.3)
        for t in tips:
            k.tube(name, to3(W2), to3(t), br, br * 0.5)
    far = max(tips, key=lambda t: np.linalg.norm(t))
    k.appendage(name, "wing", s, symmetry, R, to3(far), "slot", (2 * hr, thick), True, thick, "wing",
                path=[R, to3(W2), to3(far)], twin=twin, fingers=fingers)


def bat_wings(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, thick: float = 0.024,
              span: float = 1.0, fingers: int = 3, scallop: float = 0.22, bones: bool = True,
              sides: str = "lr", reset: bool = True):
    """1. A humanoid with a mirrored PAIR of thin membrane wings from the upper back (flat
    plates a few voxels thick, long slot-shaped root, scalloped edge). sides="l" or "r" makes
    it one-sided."""
    k = _start("bat_wings" if sides == "lr" else f"bat_wing_{sides}", "humanoid", voxel, scale, reset)
    _humanoid(k)
    pair = sides == "lr"
    for x, s in ((1, "l"), (-1, "r")):
        if s in sides:
            _bat_wing(k, x, s, thick, span, fingers, scallop, bones, "pair" if pair else "one-sided",
                      f"wing_{'r' if s == 'l' else 'l'}" if pair else None)
    k.notes = "Thin membrane pair: wings, not ears or tails; rooted on the back as a slot; mirror OK."
    return k.build(shells, dict(thick=thick, span=span, fingers=fingers, scallop=scallop, bones=bones, sides=sides))


def _bird_wing(k: Kit, x: int, s: str, t_root: float, t_tip: float, span: float, fold: float,
               feathers: int, symmetry: str, twin, rest: bool = True):
    """A thick feathered wing: a tapered wedge (thick leading edge, thin trailing edge) going
    out to the wrist, then folded down along the back; its lower trailing edge rests against
    the back of the thigh (a contact AWAY from the root)."""
    name = f"wing_{s}"
    X = np.array([x, 1, 1], float)
    sp = span
    # inner wing (arm): root on the upper back -> wrist, chord pointing down
    inner = np.array([(0.03, 0.07, 1.36), (0.12, 0.15, 1.42), (0.12 + 0.14 * sp, 0.15 + 0.11 * sp, 1.50),
                      (0.12 + 0.26 * sp, 0.15 + 0.17 * sp, 1.49)]) * X
    wrist = inner[-1]
    # outer wing (hand + primaries), folded: wrist -> down along the back to the tip
    lo = 1.49 - (1.49 - 0.84) * fold
    outer = np.array([wrist + np.array([0.02 * x, 0.0, 0.03]),
                      (wrist[0] + 0.01 * x, wrist[1], 1.49 - (1.49 - lo) * 0.3),
                      (wrist[0] - 0.05 * x, wrist[1] - 0.04, 1.49 - (1.49 - lo) * 0.68),
                      (wrist[0] - 0.13 * x, wrist[1] - 0.12, lo)])
    m = 28
    L = _resample(inner, m)
    t = _arc_params(L)
    chord = _lerp_ctrl([(0, 0.02, -0.15), (0, 0.03, -0.17), (0, 0.04, -0.17), (0, 0.04, -0.15)], t)
    tl = _lerp_ctrl([t_root, 0.85 * t_root, 0.7 * t_root, 0.6 * t_root], t)
    c = 7
    kk = np.linspace(0, 1, c)
    serr = 1.0 + 0.18 * ((np.arange(m) * feathers / m) % 1.0) * (t > 0.25)
    P = L[:, None, :] + chord[:, None, :] * (kk[None, :, None] * serr[:, None, None])
    T = tl[:, None] * (1.0 - 0.5 * kk[None, :])           # trailing edge half the leading edge
    k.sheet(name, P, T)
    m2 = 40
    L2 = _resample(outer, m2)
    t2 = _arc_params(L2)
    if rest:          # the inner (trailing) edge comes in to rest on the back of the thigh
        ctrl = [(-0.16 * x, -0.02, 0), (-0.17 * x, -0.06, 0), (-0.18 * x, -0.10, 0), (-0.15 * x, -0.14, 0)]
    else:             # folded, but held clear of the body
        ctrl = [(-0.16 * x, -0.02, 0), (-0.15 * x, -0.04, 0), (-0.13 * x, -0.04, 0), (-0.10 * x, -0.03, 0)]
    chord2 = _lerp_ctrl(ctrl, t2)
    tl2 = _lerp_ctrl([0.6 * t_root, 0.5 * t_root, 0.4 * t_root, t_tip], t2)
    serr2 = 1.0 + 0.3 * ((np.arange(m2) * feathers / m2) % 1.0)
    P2 = L2[:, None, :] + chord2[:, None, :] * (kk[None, :, None] * serr2[:, None, None])
    T2 = tl2[:, None] * (1.0 - 0.5 * kk[None, :])
    k.sheet(name, P2, T2)
    k.ball(name, wrist, 0.45 * t_root)
    R = np.array([0.08 * x, _torso_back(1.36, 0.08) + 0.01, 1.38])
    tip = L2[-1] + chord2[-1] * 0.5
    contact = [L2[-1] + chord2[-1] * serr2[-1]] if rest else []
    k.appendage(name, "wing", s, symmetry, R, tip, "oval", (0.16, t_root), False, t_root, "wing",
                path=[R, wrist, L2[m2 // 2], tip], twin=twin, contact_design=contact, feathers=feathers)


def bird_wings(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, t_root: float = 0.07,
               t_tip: float = 0.036, span: float = 1.0, fold: float = 1.0, feathers: int = 6,
               sides: str = "lr", rest: bool = True, reset: bool = True):
    """2. A creature with a mirrored pair of thick feathered wings (tapered wedge plates) folded
    partly against the body: the folded tip rests against the back of the thigh (contact with
    the body away from the root). rest=False holds the folded wing clear of the body; fold
    (0..1) is how far down the folded part hangs."""
    k = _start("bird_wings" if sides == "lr" else f"bird_wing_{sides}", "humanoid", voxel, scale, reset)
    _humanoid(k)
    pair = sides == "lr"
    for x, s in ((1, "l"), (-1, "r")):
        if s in sides:
            _bird_wing(k, x, s, t_root, t_tip, span, fold, feathers, "pair" if pair else "one-sided",
                       f"wing_{'r' if s == 'l' else 'l'}" if pair else None, rest)
    k.notes = ("Thick wedge wings folded down the back; the tip touches the thigh: a contact that is "
               "not a root. Each wing is one part from the back root to the tip.")
    return k.build(shells, dict(t_root=t_root, t_tip=t_tip, span=span, fold=fold, feathers=feathers, sides=sides,
                                rest=rest))


def one_wing(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, style: str = "bird", side: str = "l",
             reset: bool = True, **kw):
    """3. The winged creature with ONE wing only (the other is missing): the asymmetric case.
    style "bird" (thick folded wedge) or "bat" (thin membrane)."""
    gen = bird_wings if style == "bird" else bat_wings
    ob, info = gen(voxel=voxel, scale=scale, shells=shells, sides=side, reset=reset, **kw)
    info["name"] = ob.name = f"one_wing_{style}_{side}"
    info["params"].update(style=style)
    info["notes"] = "One wing, no twin: mirroring must neither copy it to the other side nor delete it."
    return ob, info


# ----------------------------------------------------------------------------- centre line

def _fin_outline(back, outward, height, spikes: int, bury: float):
    """2D outline of a crest standing on a curve: back (n,2) points, outward (n,2) normals."""
    n = len(back)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t) ** 0.6
    tri = 1.0 - np.abs(((t * spikes) % 1.0) * 2.0 - 1.0)      # 0 at the valleys, 1 at the spikes
    h = height * env * (0.45 + 0.55 * tri) if spikes else height * env
    root = back - bury * outward
    top = back + (h[:, None] + 0.004) * outward
    return np.concatenate([root, top[::-1]]), n


def dorsal_fin(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, height: float = 0.16,
               thick_root: float = 0.04, thick_edge: float = 0.018, spikes: int = 6, base: str = "humanoid",
               reset: bool = True):
    """4. A creature with a fin / crest along the back ON the centre line: symmetric, its root
    is a long line on the mirror plane. base "humanoid" (crest down the back) or "quadruped"
    (crest along the top of the back)."""
    k = _start(f"dorsal_fin_{base}" if base != "humanoid" else "dorsal_fin", base, voxel, scale, reset)
    if base == "quadruped":
        _quadruped(k, tail=True, ears=True)
        ys = np.linspace(-0.30, 0.30, 60)
        zs = 0.75 + 0.18 * np.sqrt(np.maximum(1 - (ys / 0.45) ** 2, 0))
        back = np.stack([ys, zs], axis=1)
        g = np.stack([ys / 0.45 ** 2, (zs - 0.75) / 0.18 ** 2], axis=1)
    else:
        _humanoid(k)
        zs = np.linspace(1.00, 1.48, 60)
        ys = np.array([_torso_back(z) for z in zs])
        back = np.stack([ys, zs], axis=1)
        g = np.stack([ys / 0.125 ** 2, (zs - 1.22) / 0.29 ** 2], axis=1)
    outward = g / np.linalg.norm(g, axis=1, keepdims=True)
    outline, n = _fin_outline(back, outward, height, spikes, 0.035)
    thick = np.concatenate([np.full(n, thick_root), np.full(n, thick_edge)])
    k.plate("fin", outline, thick, (0, 0, 0), (0, 1, 0), (0, 0, 1))
    mid = n // 2
    root = (0.0, *back[mid])
    tip = (0.0, *(back[mid] + height * outward[mid]))
    L = float(np.sum(np.linalg.norm(np.diff(back, axis=0), axis=1)))
    k.appendage("fin", "fin", "c", "centre", root, tip, "line", (L, thick_root), True, thick_edge, "rigid",
                path=[(0.0, *p) for p in back[::10]] + [(0.0, *back[-1])], spikes=spikes,
                root_line=[(0.0, *back[0]), (0.0, *back[-1])])
    k.notes = "A centre-line crest: its own mirror image. Root is a long line ON the mirror plane."
    return k.build(shells, dict(height=height, thick_root=thick_root, thick_edge=thick_edge, spikes=spikes, base=base))


# ----------------------------------------------------------------------------- one-sided, thick

def shoulder_cannon(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, kind: str = "cannon",
                    side: str = "l", barrel_r: float = 0.05, reset: bool = True):
    """5. A humanoid with a thick one-sided object fused on one shoulder: an arm cannon (housing
    + barrel pointing forward + drum behind) or a pauldron (a dome over the shoulder).
    One-sided but NOT thin."""
    k = _start(f"shoulder_{kind}", "humanoid", voxel, scale, reset)
    _humanoid(k)
    x = 1 if side == "l" else -1
    name = f"{kind}_{side}"
    if kind == "cannon":
        k.ball(name, (0.20 * x, 0.03, 1.50), 1.0, (0.09, 0.10, 0.07))                     # housing
        k.tube(name, (0.22 * x, 0.02, 1.545), (0.22 * x, -0.38, 1.545), barrel_r)        # barrel
        k.tube(name, (0.22 * x, -0.33, 1.545), (0.22 * x, -0.41, 1.545), barrel_r * 1.3)  # muzzle
        k.tube(name, (0.17 * x, 0.14, 1.50), (0.27 * x, 0.14, 1.50), 0.06)               # drum
        root, tip = (0.18 * x, 0.02, 1.45), (0.22 * x, -0.41, 1.545)
        path = [root, (0.22 * x, 0.0, 1.545), tip]
        size, th = (0.18, 0.12), 2 * barrel_r
    else:
        rot = np.array([[math.cos(0.35 * x), 0, math.sin(0.35 * x)], [0, 1, 0],
                        [-math.sin(0.35 * x), 0, math.cos(0.35 * x)]])
        k.ball(name, (0.19 * x, 0.0, 1.47), 1.0, (0.12, 0.12, 0.07), rot=rot)              # dome
        k.ball(name, (0.21 * x, 0.0, 1.535), 1.0, (0.05, 0.09, 0.035), rot=rot)            # ridge
        root, tip = (0.17 * x, 0.0, 1.47), (0.30 * x, 0.0, 1.43)
        path = [root, tip]
        size, th = (0.24, 0.24), 0.07
    k.appendage(name, kind, side, "one-sided", root, tip, "oval", size, False, th, "rigid", path=path)
    k.notes = "Thick and one-sided: it must stay with (or be cut from) the body, never mirrored."
    return k.build(shells, dict(kind=kind, side=side, barrel_r=barrel_r))


# ----------------------------------------------------------------------------- chains

def two_tails(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, r: float = 0.03,
              turns: float = 1.25, reset: bool = True):
    """6. A biped with two tails from the rump: one hanging out to +X, one curled (a helix
    spiral) on the -X side. Roots mirror each other, the shapes do not."""
    k = _start("two_tails", "humanoid", voxel, scale, reset)
    _humanoid(k)
    a = [(0.04, 0.06, 0.98), (0.05, 0.16, 0.93), (0.10, 0.30, 0.80), (0.17, 0.42, 0.60), (0.22, 0.50, 0.38),
         (0.25, 0.54, 0.22)]
    k.path("tail_l", a, [r * f for f in (1.05, 1.0, 0.88, 0.75, 0.6, 0.42)])
    C = np.array([-0.15, 0.42, 1.06])
    n = 40
    ph = np.linspace(math.pi, math.pi + turns * 2 * math.pi, n)
    rho = np.linspace(0.15, 0.05, n)
    drift = np.linspace(0.0, -0.06 * turns, n)
    spiral = [C + (drift[i], rho[i] * math.cos(ph[i]), rho[i] * math.sin(ph[i])) for i in range(n)]
    b = [(-0.04, 0.06, 0.98), (-0.06, 0.16, 0.98)] + [tuple(p) for p in spiral]
    rb = list(np.linspace(1.05, 0.45, len(b)) * r)
    k.path("tail_r", b, rb, seg=12)
    k.appendage("tail_l", "tail", "l", "pair_asym", _rump(0.05), a[-1], "round", (2 * r, 2 * r), True, 2 * r,
                "chain", path=a, twin="tail_r")
    k.appendage("tail_r", "tail", "r", "pair_asym", _rump(-0.05), b[-1], "round", (2 * r, 2 * r), True, 2 * r,
                "chain", path=b, twin="tail_l", curled=True)
    k.notes = "Two tails, roots side by side: two parts, each its own chain; their roots must not merge."
    return k.build(shells, dict(r=r, turns=turns))


def _rump(x: float) -> tuple:
    return (x, 0.12 * math.sqrt(max(1 - (x / 0.165) ** 2 - ((0.98 - 0.97) / 0.1125) ** 2, 0)), 0.98)


def trunk(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, length: float = 1.0, ears: bool = True,
          reset: bool = True):
    """7. An animal head (elephant-like, on a humanoid) with a long trunk from the front of the
    face, hanging down in front of the chest, tip curling forward; big flat ears."""
    k = _start("trunk", "humanoid", voxel, scale, reset)
    hc = (0.0, -0.01, 1.70)
    _humanoid(k, head=(0.12, 0.13, 0.13), head_c=hc)
    pts = [(0, -0.08, 1.67), (0, -0.15, 1.64), (0, -0.21, 1.56), (0, -0.23, 1.44), (0, -0.22, 1.32),
           (0, -0.21, 1.22), (0, -0.24, 1.14), (0, -0.29, 1.12)]
    P = np.array(pts)
    P[1:] = P[1] + (P[1:] - P[1]) * length
    radii = [0.05, 0.047, 0.042, 0.036, 0.031, 0.026, 0.021, 0.016]
    k.path("trunk", P, radii)
    k.appendage("trunk", "trunk", "c", "centre", (0, -0.135, 1.655), tuple(P[-1]), "round", (0.094, 0.094), True,
                0.06, "chain", path=[(0, -0.135, 1.655)] + [tuple(p) for p in P[2:]])
    if ears:
        for x, s in ((1, "l"), (-1, "r")):
            a = -0.5 * x
            rot = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
            k.ball(f"ear_{s}", (0.155 * x, 0.03, 1.70), 1.0, (0.012, 0.10, 0.12), rot=rot)
            k.appendage(f"ear_{s}", "ear", s, "pair", (0.11 * x, -0.03, 1.70), (0.21 * x, 0.12, 1.70), "slot",
                        (0.2, 0.024), True, 0.024, "chain", twin=f"ear_{'r' if s == 'l' else 'l'}")
    k.notes = "A trunk on the face front pointing down: a chain on the centre line, not a snout."
    return k.build(shells, dict(length=length, ears=ears))


def cape(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, thick: float = 0.024, gap: float = 0.03,
         touch_rump: bool = True, touch_leg: str = "l", length: float = 1.0, reset: bool = True):
    """8. A humanoid with a thin cape sheet hanging from the shoulders: fused along the
    shoulders (a long arc root), hanging `gap` behind the back (never less than the remesh keeps
    open), touching the rump and (touch_leg "l"/"r"/"") the back of one calf."""
    k = _start("cape", "humanoid", voxel, scale, reset)
    _humanoid(k)
    t = max(thick, k.tmin)
    g = max(gap, 2.5 * voxel / scale)
    m, c = 56, 37
    z_top, z_bot = 1.47, 1.47 - 1.17 * length
    zs = np.linspace(z_top, z_bot, m)
    th = np.radians(np.linspace(-80, 80, c))
    P = np.zeros((m, c, 3))
    into = 0.012                                    # how far a touching cape dents into the body
    for i, z in enumerate(zs):
        f = (z_top - z) / (z_top - z_bot)                      # 0 at the shoulders, 1 at the hem
        w = 0.17 + 0.12 * min(1.0, f * 1.6)
        hang = 0.125 + g + t / 2 + 0.03 * f                    # behind the deepest point of the back
        hug = min(0.10 + 0.4 * (1.47 - min(z, 1.47)), hang)    # over the shoulders: on the upper back
        q = min(1.0, max(0.0, (1.36 - z) / 0.10))
        yc = -0.02 * (1 - q)
        d = hug * (1 - q) + hang * q
        if touch_rump:                                         # the middle comes in onto the rump
            target = 0.118 - into + t / 2
            d -= max(0.0, yc + d - target) * math.exp(-((z - 0.95) / 0.08) ** 2)
        ripple = 0.012 * np.sin(5 * th) * f
        x = w * np.sin(th)
        y = yc + d * np.cos(th) + ripple
        if touch_leg in ("l", "r"):                            # a fold falls onto one calf
            sx = 0.10 if touch_leg == "l" else -0.10
            ts = math.asin(max(-1.0, min(1.0, sx / w)))
            at = yc + d * math.cos(ts) + 0.012 * math.sin(5 * ts) * f
            pull = max(0.0, at - (0.058 - into + t / 2))
            y = y - pull * np.exp(-((x - sx) / 0.06) ** 2) * math.exp(-((z - 0.42) / 0.10) ** 2)
        P[i, :, 0], P[i, :, 1], P[i, :, 2] = x, y, z
    k.sheet("cape", P, thick)
    contacts = []
    if touch_rump:
        contacts.append((0.0, 0.11, 0.95))
    if touch_leg in ("l", "r"):
        contacts.append((0.10 if touch_leg == "l" else -0.10, 0.06, 0.42))
    k.appendage("cape", "cape", "c", "centre", (0.0, 0.065, 1.36), tuple(P[-1, c // 2]), "arc", (0.45, thick), True,
                thick, "cloth", path=[tuple(P[i, c // 2]) for i in range(0, m, 8)] + [tuple(P[-1, c // 2])],
                contact_design=contacts, root_line=[tuple(P[0, 0]), tuple(P[0, c // 2]), tuple(P[0, -1])])
    k.notes = ("A thin sheet close to the back and legs, touching them: cloth, not a tail. Its root is an arc over "
               "the shoulders; the rump and calf contacts are not roots. Mostly its own mirror image (one calf fold).")
    return k.build(shells, dict(thick=thick, gap=gap, touch_rump=touch_rump, touch_leg=touch_leg, length=length))


def tentacles(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, n: int = 6, touch: bool = True,
              r: float = 0.055, reset: bool = True):
    """9. A body with n (4-6) tentacles from the lower body instead of legs, radiating out and
    down to the ground, tips curling; two neighbours on the +X side bend together and touch."""
    k = _start("tentacles", "creature", voxel, scale, reset)
    _humanoid(k, legs=False)
    k.ball("body", (0, 0, 0.86), 1.0, (0.21, 0.19, 0.18))           # mantle
    angs = [-180 + 360 * (j + 0.5) / n for j in range(n)]
    pos = sorted([a for a in angs if 0 < a < 180])
    pair = pos[:2] if touch and len(pos) >= 2 else []
    if pair:
        # bend the two towards each other until they overlap by a quarter of their girth half-way down
        gap = 2.0 * math.degrees(math.asin(min(1.0, 1.5 * 0.8 * r / (2 * 0.34))))
        bend_by = max(0.0, (pair[1] - pair[0] - gap) / 2)

    def d(ang):
        t = math.radians(ang)
        return np.array([math.sin(t), -math.cos(t), 0.0])
    for j, a in enumerate(angs):
        bend = (bend_by if a == pair[0] else -bend_by) if a in pair else 0.0
        curl = -25.0 * (1 if a > 1e-6 else -1 if a < -1e-6 else 0)       # tips curl towards the front
        z = np.array([0, 0, 1.0])
        pts = [0.08 * d(a) + 0.78 * z, 0.20 * d(a + bend * 0.25) + 0.62 * z, 0.34 * d(a + bend) + 0.38 * z,
               0.48 * d(a + bend * 0.3) + 0.12 * z, 0.60 * d(a) + 0.05 * z, 0.66 * d(a + curl) + 0.11 * z]
        radii = [r * f for f in (1.0, 1.0, 0.8, 0.6, 0.43, 0.27)]
        name = f"tentacle_{j + 1}"
        k.path(name, pts, radii)
        side = "l" if a > 1e-6 else "r" if a < -1e-6 else "c"
        twin_a = -a
        twin = None if side == "c" else f"tentacle_{angs.index(min(angs, key=lambda q: abs(q - twin_a))) + 1}"
        posed = a in pair or (-a) in pair
        sym = "centre" if side == "c" else ("pair_posed" if posed else "pair")
        root = 0.17 * d(a) + 0.72 * z
        k.appendage(name, "tentacle", side, sym, root, pts[-1], "round", (2 * r, 2 * r), False, 2 * r, "chain",
                    path=[root] + pts[1:], twin=twin, angle=a, touching=bool(a in pair))
    k.beside = (0.36, -0.30, 0.55)
    k.notes = "Tentacles instead of legs: no feet; neighbours touch. Each is a chain; touching is not a root."
    return k.build(shells, dict(n=n, touch=touch, r=r))


def horns_asym(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, stub: float = 0.35,
               big_side: str = "l", reset: bool = True):
    """10. A head with ONE large horn (sideways then up, pointed) and a broken short stub on the
    other side (blunt, flat end, `stub` of the big horn's length): an asymmetric pair."""
    k = _start("horns_asym", "humanoid", voxel, scale, reset)
    _humanoid(k)
    xb = 1 if big_side == "l" else -1
    sb, ss = ("l", "r") if xb == 1 else ("r", "l")
    big = [(0.04 * xb, 0, 1.75), (0.10 * xb, 0, 1.79), (0.18 * xb, 0, 1.84), (0.23 * xb, -0.01, 1.93),
           (0.22 * xb, -0.03, 2.03)]
    k.path(f"horn_{sb}", big, [0.038, 0.034, 0.026, 0.015, 0.004])
    L = float(np.sum(np.linalg.norm(np.diff(np.array(big), axis=0), axis=1)))
    root = np.array([0.04 * -xb, 0, 1.75])
    end = root + _unit((-xb * 0.06, 0, 0.04)) * max(stub * L, 0.03)
    k.tube(f"horn_{ss}", root, end, 0.038, 0.032)
    k.appendage(f"horn_{sb}", "horn", sb, "pair_asym", (0.08 * xb, 0, 1.78), big[-1], "round", (0.07, 0.07), False,
                0.06, "rigid", path=[(0.08 * xb, 0, 1.78)] + big[2:], twin=f"horn_{ss}")
    k.appendage(f"horn_{ss}", "horn", ss, "pair_asym", (-0.08 * xb, 0, 1.78), tuple(end), "round", (0.07, 0.07),
                False, 0.065, "rigid", path=[(-0.08 * xb, 0, 1.78), tuple(end)], twin=f"horn_{sb}", broken=True)
    k.notes = "An asymmetric pair: mirroring would copy the big horn over the stub (or the stub over it)."
    return k.build(shells, dict(stub=stub, big_side=big_side))


# ----------------------------------------------------------------------------- quadruped

def _quadruped(k: Kit, tail: bool = True, ears: bool = True, leg_r: float = 0.06) -> None:
    """A four-legged animal (1.25 m to the top of the head), body along Y, head forward (-Y)."""
    B = "body"
    k.ball(B, (0, 0, 0.75), 1.0, (0.16, 0.45, 0.18))                # barrel
    k.ball(B, (0, -0.32, 0.78), 1.0, (0.17, 0.20, 0.20))            # chest
    k.ball(B, (0, 0.33, 0.78), 1.0, (0.16, 0.18, 0.18))             # hips
    k.path(B, [(0, -0.40, 0.84), (0, -0.55, 1.02), (0, -0.63, 1.13)], [0.10, 0.08, 0.07])   # neck
    k.ball(B, (0, -0.70, 1.17), 1.0, (0.09, 0.13, 0.09))            # head
    k.ball(B, (0, -0.83, 1.13), 1.0, (0.06, 0.08, 0.06))            # muzzle
    for x, s in ((1, "l"), (-1, "r")):
        for y, fb in ((-0.30, "f"), (0.32, "b")):
            name = f"leg_{fb}{s}"
            pts = [(0.10 * x, y, 0.72), (0.105 * x, y + (0.02 if fb == "f" else -0.04), 0.38), (0.10 * x, y, 0.06)]
            k.path(name, pts, [leg_r * 1.25, leg_r, leg_r * 0.75])
            k.ball(name, (0.10 * x, y - 0.02, 0.035), 1.0, (0.055, 0.07, 0.035))
            k.limbs[name] = {"kind": "leg", "side": s, "symmetry": "pair", "twin": f"leg_{fb}{'r' if s == 'l' else 'l'}",
                             "root": (0.10 * x, y, 0.62), "tip": (0.10 * x, y - 0.02, 0.0),
                             "path": [(0.10 * x, y, 0.62)] + pts[1:] + [(0.10 * x, y - 0.02, 0.0)]}
        if ears:
            k.ball(f"ear_{s}", (0.07 * x, -0.66, 1.28), 1.0, (0.032, 0.013, 0.075),
                   rot=np.array([[math.cos(0.3 * x), 0, math.sin(0.3 * x)], [0, 1, 0],
                                 [-math.sin(0.3 * x), 0, math.cos(0.3 * x)]]))
            k.appendage(f"ear_{s}", "ear", s, "pair", (0.06 * x, -0.66, 1.22), (0.10 * x, -0.66, 1.35), "slot",
                        (0.06, 0.026), True, 0.026, "chain", twin=f"ear_{'r' if s == 'l' else 'l'}")
    if tail:
        t = [(0, 0.46, 0.86), (0, 0.60, 0.84), (0, 0.70, 0.70), (0.03, 0.74, 0.48), (0.05, 0.75, 0.36)]
        k.path("tail", t, [0.035, 0.03, 0.025, 0.02, 0.016])
        k.appendage("tail", "tail", "c", "centre", (0, 0.50, 0.86), t[-1], "round", (0.07, 0.07), True, 0.05, "chain",
                    path=[(0, 0.50, 0.86)] + t[1:])
    k.core = (0.0, 0.0, 0.75)
    k.beside = (0.32, 0.0, 0.45)


def quadruped(voxel: float = 0.008, scale: float = 1.0, shells: int = 0, tail: bool = True, ears: bool = True,
              leg_r: float = 0.06, reset: bool = True):
    """11. A quadruped on all fours: four legs, neck forward, tail, small ears. No arms, no
    T-pose: the humanoid joint guess has nothing to hold on to."""
    k = _start("quadruped", "quadruped", voxel, scale, reset)
    _quadruped(k, tail, ears, leg_r)
    k.notes = "Four legs, head forward: limbs are legs (4), the tail is the only chain behind."
    return k.build(shells, dict(tail=tail, ears=ears, leg_r=leg_r))


ZOO = {
    "bat_wings": bat_wings,
    "bird_wings": bird_wings,
    "one_wing": one_wing,
    "dorsal_fin": dorsal_fin,
    "shoulder_cannon": shoulder_cannon,
    "two_tails": two_tails,
    "trunk": trunk,
    "cape": cape,
    "tentacles": tentacles,
    "horns_asym": horns_asym,
    "quadruped": quadruped,
}
