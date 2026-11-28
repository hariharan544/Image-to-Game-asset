# Fix selected: auto and manual fixes on part of the new mesh (Step 4)

Design for the lead, revised after the adversarial critique (section 18 lists what changed). Scope:
the new (low) mesh after Step 4 has run and before Approve, plus what happens when it is used
after Steps 4b-8. Every claim marked (E#) or (R#) was measured in Blender 5.3 (bpy module) with the
scripts in `fixkit/exp_fixtools/` (section 16); (C#) marks the critique's own measurements in
`fixkit/exp_crit_fixtools/`. The design reuses what the add-on and the parallel dent-gate work
already have. New code goes into one module (`blender_scripts/forge_bpy/fixkit.py`) and one add-on
file (`blender_addon/forge_send/fix_ui.py`), plus the groundwork in F0 (section 14).

## 0. In plain words (for the director)

- In Step 4, after a run, you can click on the new mesh in Edit Mode: faces, an edge line or points.
  Then press **Auto fix**. Forge looks at that spot and the ring around it, compares it with the
  original, and repairs only that spot. It repairs:
  - a dent or a bump the original does not have;
  - a fold;
  - long thin triangles;
  - a crease of the original cut across by big faces (the stepped notch at the bull's mouth corner);
  - quads that jump in size.
- If you would rather do it yourself, there are tools for the selected spot: **Smooth on surface**,
  **Snap to original**, **Follow crease**, **Denser here**, **Coarser here**, **Match other side**
  and **Keep as is**.
- **Follow crease** needs two clicks: select the point where the crease starts and the point where
  it ends. Forge finds the crease between them on the original and shows it as a line. Then you
  press [Use it], or [Use the other line] if it picked the wrong one.
- **Both sides** is on for mirrored bodies. A fix on one mouth corner is then made on the other
  corner too, and each side is checked on its own.
- A fix is kept only if it measurably gets closer to the original and the faces keep a good shape.
  If it does not, the spot stays as it was and Forge tells you why in one line. Every fix can be
  undone, with Ctrl+Z or with **Undo last fix**.
- **Find problems** works in the background, with a progress row and [Stop]. It lists the 10 worst
  spots, worst first, and **Next** takes you to each one.
- If you run Step 4 again, Forge asks once whether to keep the edits you made with Blender's own
  tools. Your fixes are then put back after the run, and the areas you marked **Keep as is** come
  back exactly as you left them. Where that is not possible, Forge says where and why.
- **Approve** checks the mesh again after any fix or edit. A hole or a doubled face made since the
  run blocks Approve and is shown.
- Painting the lips full red and running again cannot be undone spot by spot. When Forge sees thin
  triangles along the edge of full-red paint, it says: make the red lighter (orange) and run Step 4
  again.
- Later, when the face kit cuts the mouth open and builds teeth, tongue, eyes and lids (Step 4b),
  the new inside faces have no original under them. The fix tools leave them alone.
- Fixing after Step 5 keeps your UVs whenever the fix stays inside one UV piece. The detail bake
  (Step 6) then runs again on the graphics card, and your painted colour is kept.
- The RTX 4080 Super: these fixes are small and take under a second on the processor, so the
  graphics card would not make them faster. It is already used where it helps, in the Step 6 bake
  (OptiX). The one real speed-up found is on the processor: reading the original into a lookup
  about 5 times faster (section 12). It also speeds up Step 4 itself.
- How long: the first set you can use (Auto fix with the crease repair, the panel and Find
  problems) is about 14 agent-days on the critical path, 19 in all. The rest (Denser, Coarser,
  Match other side, re-runs, use after Step 5) is about 15 more (section 14).

## 1. What the screenshots show, and what that asks of the design

- 91.webp / 92.webp and the dent work's crop_85: the faceted notch is at the mouth corner, where the
  upper lip's overhang turns. Large quads run across the turn diagonally, so no edge line follows
  the crease there, and the corner is drawn by a few flat facets (`dent/DIRECTOR_WIREFRAME.md`,
  causes 1 and 2). Along the straight part of the mouth line an edge loop does follow the crease.
- This is not a dent the dent gate can see. `density._face_gaps` excuses a face whose original
  under it is not one smooth sheet (it bridges a crease), and its allowance `3 x e x turn / 8`
  grows with the turn. A sharp corner is exactly where it looks away. The kit therefore has its own
  findings for it (4.4: **crease cut across** and **bend in the wrong place**), and a repair rung
  that gives the corner its edge line (5, L4).
- 93.png: after painting the lips full red and re-running, both mouth corners show dark streaks
  (long thin triangles) and the quads round the mouth are uneven. The reasons are in the code:
  - full red is an edge factor of 4, i.e. 16x the quads (`density.qr_colours`, `qr_factors`);
  - with a map, `_qr_part` turns `adapt_quad_count` off, so the total stays at the budget and the
    red area takes its quads from everywhere else;
  - a 16x-to-1x jump over a few rings makes Quad Remesher end loops at the jump (triangles and
    poles);
  - `carve` then adds its own edge splits on top (E11: carve and the fit raise needle faces 3.7x
    and valence-6 poles from 0 to 4.5 per 1000 faces).
- Two lessons for the tools:
  - A global repaint plus a re-run is a blunt, global re-roll. A local fix must change only the
    spot, keep its border fixed and verify against the original.
  - The kit cannot locally undo a 16x density ramp. Coarser here is unproven (X3) and Rebuild is
    for small selections. For 93.png the honest answer is a row that says "make the red lighter and
    run Step 4 again" (7.4), and the detail-paint design's ramp instead of a hard red edge.

## 2. Where it sits in the step flow

```
Step 4  Run retopology -> [review] -> Fix part of the new mesh (this design) -> Approve (re-checked)
                                   \-> Run again: hand edits asked, fixes replayed, kept areas grafted (sec. 9)
Step 4b Face kit (sibling DESIGN_face_kit.md): cuts the mouth, builds bag, teeth, tongue, eyes, lids
Step 5+ approved -> Step 4 header gets a small [Fix] next to [Change] (sec. 10)
```

What the director does, step by step:

1. Step 4 has run. In the Step 4 box, **Select the area** puts the body's new mesh in Edit Mode
   (face select, wireframe overlay on, originals hidden). Or **Find problems** runs in the
   background and then selects the worst spot.
2. The director clicks faces, an edge line or points. Any select mode works. For Follow crease,
   two points.
3. **Auto fix**, or one of the tools. The changed faces stay selected, and one to three rows say
   what changed, with numbers before and after.
4. **Show before** shows the old patch as an orange wire ghost. **Compare with original** (the
   existing button) now also works in Edit Mode.
5. **Approve**. The mesh is checked again (4.8), and the fix log goes into the approve log
   (training data for the reviewer AI).

## 3. Principles, as applied here

| Standing rule | How the kit follows it |
|---|---|
| Improve the tool, never fix one model | Every rule is a measured ratio or an angle (sec. 4.3). No body kind, no names, no per-model numbers. Tests run on cartoon and realistic bodies, animals, wings, one-sided parts and a side tail (sec. 13). |
| Holds for any body | Each vertex is compared with the surface Step 4 actually fitted it to: the mirrored body, its own cut-off part (a tail, a one-sided horn), or the unmirrored original at a weld (4.2). Lookups respect facing and reach, as `conform` does, so thin sheets (wings, ears) never snap to their far side. Faces with no original (the face kit's mouth bag, lids) are left alone. |
| Ratios of measured sizes | `e_loc` (the ring's median edge), `tol = 0.0012 x part size`, the chord rule `sqrt(8 x turn radius x tol)` for how small faces must be to follow a curving crease, angle floors in degrees. |
| Fail toward less change | Every tool runs on a copy and passes one gate (4.5), measured against the Step 4 result, so repeated fixes cannot drift. Move-only tools put back each vertex that fails. Topology tools are all or nothing per patch. A refusal leaves the mesh bit-identical. The border ring never moves. |
| Deterministic | Stable element ids (`forge_id`), mesh order everywhere (`rescue._in_order`), new elements sorted by position, ties to the least change. Tested twice per tool and in the reverse-order suite (4.6). |
| Plain words, rows of 44, few questions | At most one point-and-click question per tool, and only when there are two real choices (sec. 11). |
| Fits the step flow | Step 4 rows; Approve re-checks. Change resets later steps, except what the kit can prove still holds (UVs, colour paint, the face: sec. 10). |

## 4. Shared machinery (fixkit.py)

### 4.1 Selection -> patches

- The selection is read from the edit bmesh (`bm = bmesh.from_edit_mesh(low.data)`), in any mode:
  - faces: the selected faces;
  - edges: the faces on both sides of each selected edge;
  - points: the one-ring of faces round each selected vertex. Exactly two selected points are the
    start and end of a crease for Follow crease (6.3).
- The working patch is the selection grown by **one ring**. Its outer border (vertices with a face
  outside the patch) is pinned, so nothing outside the patch can move. The rows say "N faces
  changed (M beyond your selection, to blend in)".
- Islands are faces sharing a vertex (union-find, as the dent gate's `_islands`). They are ordered
  by their lowest `forge_id`, and each is fixed on its own, in that order.
- **Left out of every patch, and pinned:**
  - faces with `forge_made != 0`: geometry Forge built with no original under it (the face kit's
    mouth bag, inner lips, lids, sockets; 4.7). Their vertices are pinned, so the slit and rim
    loops never move;
  - vertices with `forge_fit_src == 0` (no fit record: 4.2);
  - faces marked **Keep as is**. Auto fix skips them and says so. The manual tools ask once: "3
    faces here are kept as they are. [Fix them too] [Leave them]".
- **Size cap:** a patch over 15% of the part's faces is refused: "That is N% of the body: select a
  smaller area, or use Run retopology for big changes".
- **Shape check (Rebuild and the graft only):** the patch must be a disc, with exactly one border
  loop and Euler characteristic V - E + F = 1. A band round a horn root, tail, finger or wing rim has
  two loops and Euler characteristic 0 (R4), and is refused: "This goes all the way round: select
  one side of it."
- **Both sides** (6.5): on a mirrored part, the twin patch is found and fixed after the selected
  one, as its own transaction.

### 4.2 The original: per-vertex fit surface, mirror-aware, cropped, cached (`Target`)

**What "original" means for each vertex.** It is the surface Step 4 fitted that vertex to. That
is not the same surface everywhere. `_qr_one`:
- fits the body to the high made symmetric from the chosen side (`split_off`, then
  `density.symmetrize(backup, side)`);
- fits each cut-off part (tail, one-sided horn, a part kept asymmetric) to its own unmirrored piece
  (`conform(piece.data, src)` with `src = pme.copy()` from `split_off` of the unmirrored copy);
- lays the weld band on the unmirrored full original (`rescue.weld(..., full_backup or backup)`);
- falls back to the unmirrored original when Quad Remesher fails or mirroring is turned off.

A body-wide `{mirror, x0}` cannot tell these apart. The bull test body has its tail to one side
(`bodies.bull(tail_side=0.30)`). Snapping a tail vertex to the mirror image of the other side would
pull it toward a tail that is not there, and a gate using the same reference would accept it.

**F0 writes the record:** a POINT INT attribute `forge_fit_src` on the low.

| Value | Meaning | Target queries |
|---|---|---|
| 0 | no record: an element made later with no fit, or an unknown | none. The vertex is pinned and not judged |
| 1 | the mirrored body | on the kept side: the high, cropped to triangles on the kept side of `x0`. On the mirrored side: `reflect(p)` against the same crop, with the hit reflected back (normal included). With U5, vertices in `forge_keep` regions are written as 2 instead |
| 2 | the unmirrored whole original (weld band, fallback, no mirror, shape-rescue `no-mirror` run) | the whole high |
| 3 + k | cut-off part k, fitted to its own piece | the high's faces whose corners all carry `forge_split == k` (`density.SPLIT_ATTR`, a POINT attribute the high keeps) |

Where F0 writes it in `retopo._qr_one`:
- after `_fit()` on the body: 1 if `mirror`, else 2;
- on each piece mesh after `conform(piece.data, src)`: 3 + k. `rescue._weld` appends the piece into
  the body bmesh with `from_mesh`, which keeps the values (R2);
- in `rescue._weld`: 2 on every vertex `_bridge` lays on `full_me`. This must be written there:
  R2 shows that `subdivide_edges` copies a neighbour's value into new vertices, which would
  otherwise label the band as body or piece;
- on the failure fallback (`not ok`): 2 everywhere;
- `tidy`'s `remove_doubles` keeps the first of two merged points' values, the `x0` shift
  (`obj.data.transform`) keeps all of them (R2). Either merged value is right, since a doubled point
  lies on both surfaces.

The F0 whitelist (4.7) keeps `forge_fit_src`, `forge_crease` and `forge_made` on the low, and drops
every high-only attribute (`forge_split` among them).

**The step 4 report** also stores `fit_target: {mirror: "left"|"right"|"", x0, side}` and
`low_fp`, so the kit reproduces the crop and the reflection exactly.

**No mirrored copy of the high is built.**
- **Per patch (fixes):** the high's arrays are read once per session (`foreach_get`; E9: 0.08 s per
  328k triangles). Per patch, the triangles within `4 x e_loc` of the patch and of its mirror image
  are selected with numpy, separately for each fit source the patch uses. Each crop gets a
  `BVHTree.FromPolygons` (E9: 0.03 s for 2.5k triangles, 20k nearest queries in 0.04 s).
- **Whole part (Find problems, and Step 4's own fit):** `BVHTree.FromObject(high, depsgraph)`,
  which is built in C. C7 measured 0.29 s against 1.4 s from Python lists on 1.3M triangles. R8
  confirmed that its hit index names the polygon (200/200 hits on a quad, triangle and n-gon mesh),
  which carve's per-polygon strictness and the `forge_split` crop need, and that it works in the
  object's local space. A guard checks that the evaluated mesh has the same polygon count as
  `high.data` (no modifiers). Otherwise it falls back to `FromPolygons`.
  - For mirrored bodies a second, kept-side tree is built once. The kept-side faces are written
    into a temporary mesh with `foreach_set`, then `FromObject` is called on it, and the mesh is
    deleted.
- **Cache:** a module dict keyed by `(high name, vertex count, face count, fit_target)`. It is
  cleared by `prepare_retopo`, `undo_retopo` and a `load_post` handler.
- **Gotcha:** Compare with original moves the high aside (`location.x`). Low coordinates are
  brought into the high's local space with its matrix, with that offset removed, the same rule as
  `prepare_retopo`.
- **Lookup rules:** the same as `conform` and the dent gate.
  - A hit counts only if it faces the vertex (`FACING = 0.2`) and lies within reach `4 x e`.
  - A ray hit farther than `STAND_FOR = 1.5 x` the nearest point (plus `FIT_SLACK x e`) is not this
    vertex's surface. The nearest facing point is used instead.
  - So a wing or an ear never snaps to its far side.

### 4.3 Local size and tolerances (all ratios or angles)

| Name | Definition |
|---|---|
| `e_loc` | median edge length of the faces in the two rings outside the patch |
| `size` | bounding-box diagonal of the part (as `carve` and `shape_loss` use) |
| `tol` | `0.0012 x size` (the carve / crease_kept / dent gate tolerance) |
| chord allowance of a face | `DENT_RATIO (3) x e x turn / 8`, turn = the original's normal turn under the face (`_face_gaps`) |
| chord rule for a crease | a crease that turns with radius `rho` (from the traced line's curvature) is followed within `tol` by straight edges no longer than `sqrt(8 x rho x tol)` |
| `ANGLE_FLOOR` | 20 deg: no fix may make a corner below 20 deg unless the Step 4 result already had a smaller one in that region, and then not smaller than that |
| `FLAT` | 160 deg: no fix may make a corner above 160 deg unless the Step 4 result already had a larger one there, and then not larger than that |
| needle | a face corner under 12 deg (E11: 0.72 per 1000 faces on a clean QuadriFlow mesh, 2.65 after fit + carve) |
| flat corner | a quad corner over `FLAT` (0.72 -> 2.56 per 1000) |
| long face | longest / shortest edge of a face over 4 (0.99 -> 4.06 per 1000) |
| density jump | a face's mean edge over 2x, or under 0.5x, the median of its neighbours' (0.27 -> 1.50 per 1000) |
| sharp crease of the original | at a point, the original's normal turns at least 25 deg across `+- e/16`, sampled every `e/40` across the low edge. R5b: sampling every `e/4` missed every one |
| crease followed | a crease point lies within `tol` of a low edge (the `crease_kept` rule) |

### 4.4 The checks: what is wrong in a patch (`diagnose`)

`diagnose(bm, patch, target)` returns findings `{kind, faces, size_mm, severity, words}`, sorted by
kind and then by `forge_id`. Made faces (`forge_made`) and pinned vertices are never judged.

1. `defect`: open, broken or loose edges, stacked faces, doubled points (`rescue.mesh_defects`,
   `stacked_faces`, `doubled_points`, run on the patch's own elements).
2. `dent` / `bump`: `density._face_gaps` on the patch faces (dent gate, chord allowance).
3. `fold`: a face whose normal points against the original's normal under it (dot < 0), or a
   dihedral over 100 deg where the original turns less than 45 deg under that edge. A dihedral
   alone is not a fold: a clean QuadriFlow mesh has 29 such faces at the sharp lip join (E11).
4. `crease cut across` (the director's notch): points of a sharp crease of the original (4.3) that
   lie within the patch but farther than `tol` from every low edge. Crease points come from the
   high (see 7.2). This is found without a selection.
5. `bend in the wrong place` (faceting): a low edge that bends by at least 20 deg where the original
   turns less than half as much across it (`+- e/8`), with a sharp crease of the original within
   one `e` of it. R5b, on a synthetic sharp-cornered crease under a 20 x 20 quad grid: 8 edges bend
   by 20 deg or more at the corner, and 4 of them are bends in the wrong place. They bend 25.6-30.9
   deg while the original turns 0.0-5.3 deg across them, with the real crease 0.55-0.7 `e` away.
   These are the stepped facets.
6. `needle`, `long face`, `flat corner` (4.3). Faces with a `forge_crease` edge (carve's and Follow
   crease's own lines, 4.7) are skipped for these three unless a corner is under 8 deg: carve
   makes them on purpose.
7. `pole on a crease`: an inner vertex of valence other than 4 whose faces a crease crosses.
8. `density jump` (4.3), inside the patch and across its border.
9. `painted full red` (an annotation, not a repair target): needles or density jumps along the
   edge of a region whose detail-map factor (`QR_Density` on the high under the patch) is at least
   0.9 of full red. It carries the 93.png advice (7.4).

### 4.5 One gate for every tool (`verify`)

`verify(state, patch, target, goal)` compares the patch faces, plus the face ring whose vertices
may have moved, in three states:
- before: just before this fix;
- after: the candidate;
- base: `FORGE_fixbase_<part>` (the low exactly as Step 4 left it), for the same region. The base
  region is the base faces whose centre lies within `e_loc` of the patch faces (a KD-tree on base
  face centres, cached per part).

Gates G4 and G6 are measured against the base. That is what stops ten small fixes in one area from
drifting step by step (the critique's 1.02^10 case). A candidate passes only if **all** hold:

| Gate | Rule |
|---|---|
| G1 nothing outside moves | every vertex and face outside the patch, and every made or pinned element, keeps its coordinates and corners bit for bit. Compared by `forge_id` (4.6), not by index |
| G2 no new defects | open, broken or loose edges, stacked faces and doubled points do not grow (counted on the patch plus one ring; the whole-mesh count is re-run at Approve, 4.8) |
| G3 no new folds | the fold count (4.4) on the patch does not grow |
| G4 fit not worse | the both-ways RMS gap (`density._closer`'s measure) is at most 1.02x the base region's, and at most 1.02x the state before. Coarser here uses its own bound: no `_face_gaps` island at the new size |
| G5 no new dent or bump | `_face_gaps` on the changed faces is empty, or fewer and smaller than before |
| G6 shape not worse | worst corner >= min(base worst, `ANGLE_FLOOR` 20 deg); flattest corner <= max(base flattest, `FLAT` 160 deg); no face under 0.3x its own area before. Needle, long-face, flat-corner and density-jump counts are not above before. Density jumps on the patch's border ring are exempt for Denser and Coarser, as long as the jump between neighbours is at most 2.5x. The triangle count does not grow, except where the tool states it (Follow crease cut, Denser) |
| G7 goal reached | per tool (sec. 6). Auto: at least one finding resolved, and none added |

How a failed gate is handled:

- **Move-only tools** (Snap, Smooth, Follow crease slide, Match by positions) put back moves one
  vertex at a time, in `forge_id` order, each judged among its neighbours as they are by then. A
  move stays only if, for the vertex's faces:
  - worst corner >= min(their worst before, 20 deg), flattest <= max(their flattest before, 160 deg),
    and no face under 0.3x its area before. The old rule checked only the smallest angle, which let
    a slide flatten quads into near-triangles. R3 on a quad grid, with the crease at 10/20/30/45 deg
    to the quads: 4/8/12/16 corners went over 160 deg under the old rule, and 0 at every angle with
    the flattest-corner rule. R6 on the mouth-corner head: 2 corners at up to 173.8 deg became 0;
  - its fit, by the tool's own rule: Snap and Follow crease use the dent work's `_keep_closer`
    (strictly closer both ways, no deeper dig). Smooth uses the slack rule in 6.1.
  - After the per-vertex pass, the patch must still pass G4 against the base. If it does not, the
    kept moves that cost the most fit are put back one at a time until it does.
- **Topology tools** (clean triangles, Follow crease cut, Denser, Coarser, Rebuild, Match by
  topology) are all or nothing per patch. If the gate fails, the patch's copy is thrown away.

### 4.6 Transactions, Edit Mode, undo, stable ids, determinism

- **Edit Mode reads (R1).** In Edit Mode the Mesh datablock keeps the mesh as it was when Edit
  Mode was entered. After a fix written back to the edit mesh, `density.fingerprint(me)`,
  `exact_hash(me)` and `me.copy()` all still returned the old 49-vertex mesh, while the edit bmesh
  had 50. Two remedies, both measured:
  - `fixkit.sync(ob)` calls `ob.update_from_editmode()` before any copy, fingerprint or hash. After
    it the Mesh is current, and the edit bmesh wrapper stays valid;
  - `fixkit.bm_arrays(bm)` reads coordinates, edges, corner counts and corners straight from the
    edit bmesh, in the same layout as `density._mesh_arrays`. Its hash equals `exact_hash` of the
    synced Mesh (R1). F0 splits `density.fingerprint` and `exact_hash` into an array core
    (`fingerprint_arrays`, `hash_arrays`) fed by either source.
  - Rule: every snapshot, undo copy, log fingerprint and test assertion in Edit Mode uses
    `bm_arrays`, or `sync` first.
- **Transaction (E12):**
  1. Give every vertex and face a `forge_id` int layer: its index + 1. The bmesh default 0 then
     means "made by this op".
  2. `work = bm_edit.copy()`. The tool runs on `work`, and `verify` checks it.
  3. If it passes: `work.to_mesh(tmp)`, then `bm_edit.clear()`, `bm_edit.from_mesh(tmp)` and
     `bmesh.update_edit_mesh(me)`. Selection and attributes survive (E12).
  4. If it fails: `work.free()`. The edit mesh is untouched, bit for bit.
- **No operator that needs the active object's edit mesh** runs inside a transaction. Rebuild's
  grid fill is pure bmesh (6.4, R4). `bpy.ops.mesh.fill_grid` is not used.
- **Operator:** `FORGE_OT_fix` (`forge.fix`) with `bl_options = {"UNDO"}`, without `REGISTER`.
  Blender then pushes an undo step but shows no Adjust Last Operation panel. That panel would
  re-run the tool with other settings and repeat side effects undo does not track (undo copies, the
  log, recipes). The `tool` property is `HIDDEN | SKIP_SAVE`. It never leaves Edit Mode, so Blender's
  own Ctrl+Z restores the previous edit mesh. This is deliberately not `forge.step`, which forces
  Object Mode.
- **Forge's own stack:**
  - Before each applied fix: `sync(ob)`, then a copy of the low mesh is stored as
    `FORGE_fixundo_<part>_<k>`, with a fake user so it survives a save. The last 8 are kept (about
    2 MB each at 30k triangles).
  - The low exactly as Step 4 left it is `FORGE_fixbase_<part>`.
  - **Undo last fix** restores the top copy into the edit bmesh (`bm.clear()`, `bm.from_mesh(copy)`,
    `update_edit_mesh`), bit-exact (R1), without leaving Edit Mode. **Undo all fixes** restores the
    base the same way.
  - These are removed on Run retopology and Undo retopology.
- **Ctrl+Z and the log stay in step.** Each log entry stores the ordered fingerprint of
  `bm_arrays` before and after. Before any tool runs, the current fingerprint is compared with the
  log:
  - it equals the last `after`: in step;
  - it equals an earlier entry's `before` or `after`: the director used Ctrl+Z, and the log and
    stack are cut back to there;
  - it matches nothing: the director edited with Blender's own tools, and an entry
    `{tool: "hand"}` is added (sec. 9 says how a re-run treats it).
- **Determinism:**
  - Every bmesh op gets its input as a list in `forge_id` order. Bmesh elements are never iterated
    as a set (the comment in `carve` explains why).
  - After a topology op, elements are sorted with `bm.verts.sort(key=...)` and `bm.faces.sort`:
    old ones by `(0, forge_id)`, new ones (`forge_id == 0`) by
    `(1, quantised position, neighbours' names)`, the way `density._vertex_names` tells apart
    points on one spot. `.index` is never trusted across an op, since ops renumber it.
  - Dijkstra breaks ties by `forge_id`. Candidates run in a fixed order, and ties go to the fewest
    moved vertices, then the fewest new faces.
  - Ops that may depend on memory order (precedent: `extrude_edge_only`) are checked by X1. Any
    that fails is redone in Python (precedent: `rescue._extrude_edges`).

### 4.7 Per-element data, and how a topology fix carries it

| Data | Lives on | Carried how |
|---|---|---|
| `forge_split`, plan `forge_keep`, `forge_island`, `forge_ledger_row` (plan), `forge_strict`, `QR_Density`, `forge_horn_plan`, `forge_split_names`, `forge_plan_mirror`, plan fingerprints | the **high** | Not touched: fix tools never write the high. A test asserts `density.exact_hash(high)` is unchanged after every tool. |
| Leftovers of the above on the **low** | low | F0: `retopo._finish_part` keeps only a whitelist of attributes and mesh properties on the low, and removes **object** properties the low inherited from the high through `common.duplicate` (`obj.copy()` copies ID properties): `forge_fix_recipes`, `forge_face_recipe`, `forge_face_marks`, plan properties. |
| `forge_fit_src` | low, POINT INT | 4.2. A new vertex takes the value of the old patch face its position projects into. 0 is never given to a vertex of a fitted face |
| `forge_crease` | low, EDGE BOOL | written by `carve` (F0) on the edges it splits along a crease, and by Follow crease on its line. A new edge on a crease chain keeps it. Clean triangles, collapse, Coarser and the F9 pass leave these edges alone (5, L2) |
| `forge_made` | low, FACE INT8 | 0 = has an original under it. 1 = made by the face kit (mouth bag, inner lips, lids, sockets). 2 = made by any other Forge builder. Written by the builder. Never written by the fix kit, which never builds on it |
| `forge_ledger_row` on the low (after U14) | low, FACE/POINT int | a new element takes the label of the old patch face its centre projects into. A patch across a label border keeps the border: new faces are labelled per side of the old border edge chain. If that fails, the label comes from the high's row at the nearest high point (U14's own transfer, run on the patch only) |
| `forge_fix` (id of the last fix that made the face), `forge_fix_keep` | low, FACE int | set by the kit. New faces take the patch's value |
| `forge_id` | low, POINT/FACE int, transient | written before each op, removed before write-back |
| UV maps | low, CORNER float2 | Only when the patch lies in one UV island: no seam on or inside its edges. Seams are found from the UV values (two loops of an edge whose UVs differ), not only from `edge.seam`, since `uv_layout` works from values too. Each new or moved vertex gets **one** UV per island: interpolated once, from the old face its position projects into (`BMLoop.copy_from_face_interp` on one loop, from a `bmesh.ops.duplicate` copy of the old patch), then copied to all its loops in that island. Per-loop interpolation could pick different old faces for loops of one vertex and leave a hidden split (E10 measured the per-loop interpolation itself). |
| deform weights (after Step 8), colour attributes | low | `BMVert.copy_from_face_interp(old_face)` (E10), then `skin._cleanup_weights(obj, max_influences, min_weight, deform, continuous=True)` on the patch's vertices, so interpolated weights stay within the export profile's influence limit (4 for Unity mobile) and are normalised |
| seams, sharp edges | low, edge flags | a new edge on an old seam chain keeps the flag |
| low fingerprint | Step 4 report `low_fp`; `uv_rep.low_fp`, `bake_rep.low_fp` (F0) | recomputed after every fix. `steps.uv_fingerprint()` counts faces only, so it misses a move-only fix; F0 adds the ordered fingerprint to it |

After Step 5, every `join_triangles` call passes `cmp_seam=True, cmp_uvs=True` (C1: both default to
False in Blender 5.3), so it never joins across a UV seam.

### 4.8 Approve re-checks the mesh

`stages_late.do_retopo_approve` today checks only `missing_lows()`. The run's report holds the
open-edge, broken-edge, stacked and doubled counts from `_qr_one`'s final gate, and a deleted face
or a stacked face made since then would pass unseen. New rule:

- If any low has a fix log entry, or its ordered fingerprint differs from the report's `low_fp`,
  Approve first runs `rescue.mesh_defects`, `stacked_faces`, `doubled_points` and `C.tri_count` on
  that low. Approve runs through `forge.step`, which leaves Edit Mode, so the Mesh is current.
- The Step 4 rows are refreshed with the new counts.
- If open edges, broken edges, stacked faces or doubled points grew since the run, Approve is
  blocked with the row "2 open edges since your edits." and the buttons [Show] [Undo last fix].
  [Show] is the existing `do_retopo_show_defects`.
- A triangle count over the budget is a warning row, as today.

## 5. Auto fix

`auto_fix(bm, patch)`, per island:

1. `findings = diagnose(...)`. With no findings, the row is "Nothing wrong found here (0.2 mm
   from the original, no thin triangles)", and the mesh is not touched.
2. A ladder of candidates. Each starts from the result of the last accepted rung, and each is
   verified (4.5). The ladder stops as soon as no findings are left:

| Rung | When | What (calls) | Evidence |
|---|---|---|---|
| L0 tidy (patch only) | `defect` | On the patch's own elements: `bmesh.ops.remove_doubles(verts=patch verts, dist=rescue.same_spot_tolerance)`, `dissolve_degenerate(edges=patch inner edges)`, the stacked-face drop limited to patch faces, `holes_fill(edges=patch boundary edges that are mesh boundaries)`. Winding: each patch face is made to agree with the pinned faces across shared edges, by a flood from the border and `bmesh.ops.reverse_faces` on those that disagree. `rescue.tidy` itself is not called: it works on the whole mesh (remove_doubles on every vertex, `recalc_face_normals` on every face) | `rescue.tidy` source |
| L1 snap | `dent`, `bump` | Snap to original (6.2), per-vertex verified | the dent gate's put-back |
| L2 clean triangles | `needle`, `long face`, triangles | `bmesh.ops.join_triangles(faces, angle_face_threshold=40 deg, angle_shape_threshold=40 deg, cmp_seam=True)`, with crease edges protected: on the `work` copy, every `forge_crease` edge is temporarily flagged as a seam, so `cmp_seam` refuses to join across it, and the seam flags are restored after. `rotate_edges` on a triangle pair, when the flip raises its smaller min angle and the edge is not a crease edge. `collapse` of the shortest edge of a remaining needle, when both ends are inside the patch and neither end is on a crease edge. `dissolve_degenerate(dist=1e-3 x e_loc)` | E5: triangles 22 -> 18 and 26 -> 16 at the two mouth corners, inner poles 13 -> 9, fit unchanged. C8: without protection, join_triangles erased 6 of carve's 147 crease triangles. A test asserts that the crease edge count does not change (13) |
| L3 relax | uneven quads, `flat corner`, after L2 | Smooth on surface (6.1). Crease vertices slide along their crease only | E5 / R7 (6.1) |
| L4a crease slide | `crease cut across`, `bend in the wrong place`, `pole on a crease` | Follow crease, slide mode (6.3). The crease's two ends are where the crease points of the finding leave the patch | R5: bends in the wrong place 4 -> 0, crease within tol 59% -> 65%, gap 2.37/3.49 -> 1.95/2.97 (x1e-3), worst corner 53.4 -> 47.8 deg, flattest 152.3 deg, +0 triangles. R6 (mouth-corner head): 6% -> 81% within tol, 0 corners over 160 deg |
| L4b crease cut | the crease still under 80% followed, and the faces it crosses longer than the chord rule allows (4.3) | Follow crease, cut mode (6.3): denser along the crease, relax, slide, cut with straight chords, relax | R5: crease within tol 59% -> 85%, gap 2.37/3.49 -> 1.53/1.85, worst corner 23.1 deg (above the 20 deg floor), +26 triangles, 1 bend left |
| L5 rebuild | `density jump`, `fold` left, poles left | Rebuild here at 1x (6.4), only when the patch is a disc and its border loop has at most 36 edges (about 9 faces across) | E3 + R4 (6.4) |

3. If no rung resolves everything, the best verified state wins: fewest findings, then the
   smallest fit RMS, then the fewest changed faces. If no rung passes the gate at all, nothing
   changes.
4. Report: one to three plain rows per island. The place words are only those Forge has:
   - the part's own name for a cut-off part ("the tail");
   - on the body, a region word from `density.REGION_NAMES` (`body`, `head`, `arms`, `hands`,
     `legs`, `feet`), placed by `density.region_labels` from the joint estimate, as the dent gate's
     `_name_dent_places` does;
   - where the joint estimate does not fit the body (a snake, a fish, wings: `joints.estimate`
     reports no limbs), the part name alone. There is no "mouth corner" word: nothing in Forge
     knows where a mouth is before the face kit's marks (Step 4b), and the face kit is the only
     place that will name it.
   - Example rows (each at most 44 characters):
     - "Head: crease now followed (85%, was 59%)"
     - "0.3 mm off the original (was 1.6 mm)"
     - "14 faces changed, +26 triangles"
     - "Left as it was: every repair made it worse"
     - "No clear crease here: use Follow crease"

Auto fix with nothing selected refuses: "Select an area first, or press Find problems". It never
fixes the whole body silently.

## 6. Manual tools

Each tool works on the selection plus one ring, as in 4.1. Each is verified with 4.5, can be
undone with 4.6, and writes a log entry and a recipe (sec. 8). With **Both sides** on, each tool
also runs on the twin patch (6.5).

### 6.1 Smooth on surface

- Tangential Laplacian, in numpy, on the patch's inner vertices with the border pinned:
  `d = mean(neighbours) - p`, then `d -= n * (d . n)`, then `p += 0.5 d`. Then `Target.nearest`
  (facing, the vertex's own fit source). Six rounds.
- `bmesh.ops.smooth_vert` is not used: it moves in 3D and shrinks curved areas.
- Vertices on a `forge_crease` edge move only along their crease line.
- **Put-back rule (slack, then the patch bound):**
  - per vertex, in `forge_id` order: keep the move if its faces' both-ways gap is no worse than
    `FIT_SLACK x e` (the chord slack `conform` already allows), their shape improves (worst corner
    up, or edge-length spread down), they dig no deeper than `tol` (the dent work's `_dig`), and the
    corner and area rules of 4.5 hold;
  - then G4 against the base. If the patch's both-ways gap is over 1.02x the base region's, the
    kept moves that cost the most fit are put back one at a time until it holds.
  - Why: the strict rule (strictly closer both ways) puts back most tangential moves, since a
    relax on an already fitted mesh changes the fit by tiny amounts either way. R7 on the
    mouth-corner head, with the current dent code: strict put back 12 of 20 and 13 of 19 moves. It
    still raised the worst corner 22.9 -> 33.3 deg at one corner, and left the other at 17.1 deg.
    The slack rule alone put back 0 of 20 and 4 of 19, reached the same corners (33.8, 17.1 deg),
    but lost 3-7% of fit. Hence slack per vertex, with the patch-level fit bound on top.
- **Goal G7:** the worst angle rises, or edge spread (edge-length CV) falls, with G4 holding.

### 6.2 Snap to original

- Each inner vertex goes to its own `Target` (4.2), as `conform.project` does: along the normal
  both ways, the nearest facing hit within reach, with the `STAND_FOR` rule.
- Then one light relax and a re-snap. Then per-vertex put-back with `_keep_closer` (check 0) and
  the corner and area rules of 4.5.
- **Goal:** the both-ways RMS gap falls by at least 2%, or a dent or bump island goes.

### 6.3 Follow crease (an edge line along a crease of the original)

**1. The crease line, from two clicks (`trace`).**
- **Input:**
  - two selected points are its start and end;
  - with a face or edge selection, the start and end are the two crease points of the
    selection's strongest crease where it leaves the patch (crease points: 4.3 and 7.2);
  - from Auto fix, those of the finding.
- **Trace on the original:** Dijkstra over the high's edges inside the ellipse whose foci are the
  two clicks (sum of distances at most the click distance + 2 `e`). The cost of an edge is
  `length x (1 + 9 x (1 - min(1, |dihedral| / d99)))`, where `d99` is the 99th percentile of the
  dihedrals in that ellipse. Each click first snaps to the sharpest high vertex within `0.5 e` of
  it. The path is smoothed by two 3-point averages and resampled every `e / 4`.
- **Measured:**
  - R5, on a synthetic crease with a corner of radius 1.2 `e` and clicks 0.3 `e` off it: mean
    0.015 `e` from the true crease, max 0.117 `e`, 86% within `tol`. The straight line between
    the clicks, which is what the old "principal axis of the selection" fallback gave, was mean
    0.71 `e` and max 1.29 `e`.
  - R6, on the dent work's mouth-corner head (clicks 0.3 E off the true groove floor): mean
    0.88 mm, max 3.38 mm. The straight line was mean 1.78 mm and max 2.85 mm. The max is at the
    snapped ends, so the trace's end points are dropped when they lie more than `e / 2` from the
    next smoothed point.
- **Second line:** the same Dijkstra with the first path's edges costing 10x gives a second line.
  If its mean sharpness is at least 0.7x the first's and it lies more than `e` away on average,
  **[Use the other line]** is offered.
- **Display:** a temporary wire curve, `FORGE_fix_crease`, drawn in front, with the row
  "Crease found: 21 mm long." and the buttons [Use it] [Use the other line]. Nothing changes until
  [Use it].
- The per-sample profile finder of the first version (41 rays across a rough path, narrowest scale
  first) stays, as the depth check: a traced line counts only where its profile dips or rises more
  than `tol / 4` against the chord. It is no longer used to find the line.

**2. Slide mode (least change, tried first).**
- Find the low edge path nearest the crease: Dijkstra over the low's edges between the low
  vertices nearest the crease's two ends, cost = length + 4 x distance to the crease line, kept
  within `2.5 e` of it.
- Each path vertex moves to its nearest crease point, then onto its `Target`. Then two rings of
  neighbours are relaxed (6.1).
- Per-vertex put-back with the worst-corner, flattest-corner and area rules (4.5).
  - R3, straight crease on a quad grid at 0/10/20/30/45 deg to the quads: 0 corners over 160 deg
    at every angle (the old slide: 0/4/8/12/16 at up to 180 deg). Worst corner 69.7/62.1/57.8/
    50.5/53.9 deg. Crease within `tol`: 100/89/76/64/62%.
  - R6, the mouth-corner head with the two-click trace: crease within `tol` 6% -> 81% (mean
    3.58 -> 1.18 mm), corners 43.1-117.8 deg, 0 over 160 deg, 1 move put back. The ungated slide
    reached 94% but left 2 corners at up to 173.8 deg.
- **Rejected: staircase removal** (split the quad at each path corner along its diagonal, then
  slide). R3: one triangle per step (+4 to +16), crease within `tol` only 73/62/53/0%, worse than
  the gated slide at every angle. The 0% at 45 deg is the gate refusing the shifted diagonals.
- Slide writes `forge_crease` on the path edges whose two ends lie within `tol` of the line.

**3. Cut mode (if slide leaves the goal unmet).**
- **Denser along the crease first, only where needed.** The faces the crease crosses are
  subdivided (`bmesh.ops.subdivide_edges(edges=their edges, cuts=1, use_grid_fill=True,
  quad_corner_type="INNER_VERT")`). This happens only if their edges are longer than the chord
  rule's `sqrt(8 x rho x tol)`, where `rho` is the traced line's turn radius there. One level, at
  most two.
  - Ring faces with more than 4 corners, or a corner over 170 deg (a split edge's midpoint), are
    triangulated (`BEAUTY`).
  - New vertices go onto `Target`. Then Smooth on surface on the new vertices and the ring.
  - R5: subdividing alone dropped the worst corner to 15.7 deg; with the relax, 21.3 deg.
- **Then slide (2), then cut with straight chords.**
  - Each low edge the crease crosses is split at the crossing (`bmesh.utils.edge_split`). If the
    crossing is within 0.15 of an end, that end is slid onto the line instead, through the gate.
  - The new point goes onto `Target`.
  - Each face then holding two crease points that are not already joined is split between them
    with `bmesh.utils.face_split(face, a, b)`. This is the `_groove_pair` rule, restricted to the
    patch (a `faces=` argument is added to `density.carve`, with crossings from the line instead
    of per-edge depth sampling).
- **Then** the dent work's `_cut_beside` depth clamp, L2 (crease-protected) and one more relax.
- **Measured (R5), the whole cut mode:** crease within `tol` 59% -> 85%, both-ways gap 2.37/3.49
  -> 1.53/1.85 (x1e-3), bends in the wrong place 4 -> 1, worst corner 23.1 deg, +26 triangles. The
  same cut without the relax steps gave 13.3 deg, which the 20 deg floor refuses.
- **Rejected: `face_split(..., coords=polyline points)`** (the critique's suggestion). R5: the
  crease was followed 100%, but corners fell to 0.0 deg, 13 new bends in the wrong place appeared,
  and +46 triangles. The extra points on the split leave the faces on both sides as n-gons that
  must be triangulated into slivers. Densifying until straight chords meet the chord rule does the
  same job with sound faces.
- The new line's edges get `forge_crease`. The row gives the triangle change.

**4. Goal G7:** the share of crease points within `tol` of a low edge rises to at least 0.8, or by
at least 0.25. No new bend in the wrong place, and the dent-gate check finds nothing new.

**5. What Follow crease is not.** It makes an edge path along one crease. Closed lip loops,
eyelid rims and the mouth slit are built by the face kit (sibling design 6.2-6.4), which calls
this trace and slide for its mouth line.

### 6.4 Denser here / Coarser here / Rebuild here (local topology)

- **Denser here (2x edges = 4x quads):**
  - `bmesh.ops.subdivide_edges(edges=patch inner + border edges, cuts=1, use_grid_fill=True,
    quad_corner_type="INNER_VERT")`.
  - The ring's pentagons, and any face with a corner over 170 deg, are triangulated with
    `bmesh.ops.triangulate(quad_method="BEAUTY", ngon_method="BEAUTY")`. E1: 43 faces became 205,
    with 18 pentagons in the ring, min angle 39.7 deg (flat patch).
  - New vertices go onto `Target`, then L3 (6.1).
  - Goal: the patch's median edge is 0.4-0.6x before, fit not worse. The border-ring density jump
    is exempt from G6 up to 2.5x (4.5).
  - The row gives the triangle change and the new total against the budget ("+324 triangles:
    29,121 of 30,000"). Going over the budget is a warning, not a block.
- **Coarser here (0.5x):**
  - Walk the edge rings across the patch (the opposite edge of a quad is
    `loop.link_loop_next.link_loop_next.edge`). Dissolve every other ring inside the patch with
    `bmesh.ops.dissolve_edges(edges, use_verts=True)`, in both directions, skipping rings that
    hold a `forge_crease` edge. Then triangulate any pentagon at the border, then L3.
  - `bmesh.ops.unsubdivide` is not used. E1: on a QuadriFlow patch it removed only 14 of 3,232
    faces.
  - Goal: the median edge is 1.6-2.4x before. G4 uses the chord bound at the new size: no
    `_face_gaps` island. The border-ring jump is exempt up to 2.5x.
  - Experiment gate X3 before shipping. It is not offered as the answer to a full-red paint
    ramp (7.4).
- **Rebuild here (1x)**, Auto's L5 only, not a button:
  - Requires a disc patch (4.1) whose border loop has at most 36 edges.
  - Delete the patch (`bmesh.ops.delete(context="FACES_ONLY")`), `holes_fill` to one n-gon,
    `bmesh.ops.inset_region(thickness=0.9 e_loc)`, then delete the inner n-gon.
  - **Grid fill in bmesh, with no operator and no mode switch (R4):**
    1. Order the inner loop. If it has an odd number of edges, first split its longest edge
       (`edge_split` at 0.5), which leaves one triangle in the inset ring.
    2. Start the loop at its sharpest-turning vertex. Cut it into four sides of `a, b, a, b`
       edges, with `a = n // 4` and `b = n // 2 - a`.
    3. Call `bmesh.ops.grid_fill(bm, edges=side_0 + side_2)`. The op finds the two rails itself.
    - R4: a 16-edge hole gave 16 quads at 90 deg with no open edge left. Started at an arbitrary
      vertex, the same call made 16 faces but left 8 open edges, so the corner start is required,
      and G2 catches any miss. A 96-face sphere cap (one loop, Euler characteristic 1) gave, after
      the inset, a 64-quad grid with 0 open edges and worst corner 19.0 deg before relax.
    - `bmesh.ops.grid_fill` given the whole loop makes nothing (E1). That is why the first version
      used the operator.
  - Then onto `Target`, then L3. The 20 deg floor of G6 applies after the relax.
  - **The limit, restated as a selection width:**
    - E3's radii (0.18 / 0.3 / 0.45 on edges of about 0.065) were about 6, 9 and 14 faces across,
      not "3, 4 and 7 quads" as the first version said (the critique's arithmetic).
    - E3 measured min angles of 37.6 and 29.8 deg after relax at about 6 and 9 across, and 2.2 deg
      at about 14 across. That was with the operator's own span choice. R4's corner-start fill is
      to be re-measured at 14 across in X2.
    - Until then the rule is a border loop of at most 36 edges (about 9 faces across). The refusal
      rows say: "Too wide to rebuild here." / "Select up to about 9 faces across."
- **Rejected engines (measured):**
  - QuadriFlow on the cut-out patch gives good quads (min 69 deg) but moves every border vertex
    (E3: 0 of 36 kept).
  - Bridging back with `bmesh.ops.bridge_loops` between loops of unequal size gives only triangles
    (E4: min angle 2.5-11.6 deg).
  - A bigger rebuild waits for experiment gate X2: QuadriFlow with a collar, retried until the
    trimmed loop matches the hole's vertex count, then a one-to-one weld.

### 6.5 Match other side, and Both sides

**Match other side** (copy the selected patch from the other side):
1. **The original must be symmetric there.**
   - Up to 2,000 points of the original under the patch are mirrored across `x0` (U2's frame
     `{x0, yaw}` when present, else `density.mirror_plane` of the high, cached with the high's
     vertex count).
   - The cropped `Target` gives each one's distance to the original.
   - It passes if at least 95% lie within `max(3 x noise, tol)`, with noise = the body's median
     mirror distance below its 80th percentile (U2's definition, cached).
   - Else it refuses: "The original is not the same on both sides here (up to 6 mm different): use
     Snap to original."
   - Vertices with fit source 3 + k (a one-sided part) are never matched.
2. **The twin map:**
   - For every patch and border vertex, its twin is the nearest low vertex to `reflect(p)`
     (`mathutils.kdtree`), within `0.25 e_loc`.
   - Case A: the map is one to one, and every patch face maps to a low face (reversed winding).
     Each patch vertex gets the reflected position of its twin, with no topology change. This is
     the common case, since Step 4 runs Quad Remesher with X symmetry on mirrored bodies.
   - Case B: only the border ring maps. The patch faces are deleted, the twin patch's faces are
     copied (`bmesh.ops.duplicate`, `bmesh.ops.transform` with the mirror matrix,
     `bmesh.ops.reverse_faces`), and their border vertices are merged onto the ring's twins
     (`bmesh.ops.pointmerge`, pair by pair).
   - Otherwise it refuses: "The mesh here differs from the other side: select a bigger area or use
     Auto fix."
3. **Verify** against the original (G1-G6). Goal: the patch's both-ways gap is no worse than the
   twin's own gap plus 10%.
4. The source side is the side not selected, and the row says "copied from the left side". A patch
   on the middle line, with twins inside itself, is refused with that reason.

**Both sides** (a checkbox, on by default when the part's fit source is the mirrored body):
- After a fix on the selected patch passes, the twin patch (the twin map's image of the selection,
  grown by one ring) is fixed by the same tool, with the same settings. For Follow crease, the two
  clicks are reflected.
- Each side is its own transaction and its own gate (4.5), with its own reflected `Target`
  queries. One side failing does not undo the other. The rows say: "Left: fixed. Right: left as it
  was (it got farther from the original)."
- Order: the selected side first, then the twin. Deterministic.
- Hidden when the selection touches the middle line, or when the twin map does not cover the twin
  patch.
- This is what the bull needs: its defect is at both mouth corners.

### 6.6 Keep as is

- `forge_fix_keep = 1` on the patch faces. It toggles: select kept faces and press it again to
  release them.
- The row says "kept by you: 1 area (head)".
- Auto fix, Find problems, the replay after a re-run, and the optional tidy-up pass (WP F9) never
  change kept faces.
- A re-run grafts the kept area back exactly (sec. 9).
- Steps 5-9 move no low geometry. Step 9's LOD decimation works on copies. A later option could
  give it the keep mask as a vertex group with low collapse weight (not in this design).

### 6.7 Undo last fix, Undo all fixes, Show before

- Undo last fix and Undo all fixes are as in 4.6.
- **Show before:** a temporary object `FORGE_fix_before` holds the old patch faces from the last
  undo copy. It is drawn as an orange wire, in front, and is not selectable. It toggles, and is
  removed by the next fix, by Approve and by `stop_cleanup`.

## 7. Find problems (no change, selection only)

### 7.1 Runs in the background

- `fixkit.find_problems(part)` is a generator driven by the existing runner
  (`stages_late.run(st, label, fn, on_done)`, timers, `job_running()`). It yields after each chunk
  of about 0.1 s of work, and the row shows "Looking for problems: 40% [Stop]". Stop goes through
  `steps.stop_cleanup`. Find problems changes nothing, so stopping leaves nothing to undo.
- **Cost on the bull (4.9M-triangle original, about 30k-face low), extrapolated from C6 and C7:**
  - the whole-original tree: `BVHTree.FromObject` about 1.1 s;
  - the mirrored kept-side tree about 0.6 s;
  - `_face_gaps` about 6 s per 30k faces (C6: 0.39 s per 2,000);
  - the per-face shape checks about 1 s;
  - the crease checks about 1-2 s.
  - In all about 10 s, in the background. The trees are cached for the fixes that follow.

### 7.2 What it looks for

- **Everything in 4.4**, over the whole part, except what is left out: made faces, kept faces,
  pinned vertices, and needle, long and flat findings on faces with a `forge_crease` edge.
- **Crease points of the original, for the whole part:**
  - candidate high edges are those whose dihedral is at least 25 deg (numpy, from face normals and
    the edge-face table);
  - each candidate's midpoint passes the sharpness test of 4.3 at the low's local `e`;
  - the points are cached per high;
  - each is then checked against the low (within `tol` of a low edge). Runs of at least 3
    unfollowed points along the crease form a `crease cut across` finding.

### 7.3 What it shows

- **Islands** (`_islands`), ranked by visible severity: worst gap (mm) x island area / `e_loc`^2.
  Ties go to the finding count, then the lowest `forge_id`.
- **Only the top 10 are listed and selected.**
  - The design's own E11 rates after fit + carve add up to about 10.8 flagged faces per 1000.
    That is about 320 faces and likely more than 100 islands on a 30k low. Most of them are
    carve's intended crease triangles, which 7.2 now leaves out.
- **Rows** (at most 4 lines), using only the place words Forge has (5, item 4):
  - "12 spots found, worst first (10 shown):"
  - "head: 3 creases cut across, 1 dent"
  - "body: 2 thin-triangle spots"
- **Next** and **Previous** select one island and frame it (`view3d.view_selected` in a
  temp-override, as `do_retopo_show_defects` does).

### 7.4 The painted-red advice (93.png)

When islands of needles or density jumps lie along the edge of full-red paint (4.4, item 9),
Find problems and Auto fix add, once per run:
- "This area is painted full red. It takes"
- "quads from the rest and leaves thin"
- "triangles where the red ends. Make it"
- "lighter (orange) and run Step 4 again."

The fix kit does not try to undo a 16x ramp locally. The sibling detail-paint design's falloff
ramp is the cure at the source.

## 8. What Forge stores, and where

| What | Where | Type | Notes |
|---|---|---|---|
| `forge_fit_src` | low mesh | POINT INT | 4.2 (F0) |
| `forge_crease` | low mesh | EDGE BOOL | carve's and Follow crease's lines (F0, F4) |
| `forge_made` | low mesh | FACE INT8 | geometry with no original; written by the face kit (1) and any later builder (2) |
| `forge_fix` | low mesh | FACE INT | id of the fix that last made or changed the face (0 = Step 4's own) |
| `forge_fix_keep` | low mesh | FACE INT8 | 1 = kept by the director |
| `forge_fix_log` | low object | JSON string | `[{id, tool, sides, island, where, faces_before, faces_after, tris_delta, fit_mm: [before, after], findings: [before, after], put_back, fp_before, fp_after, recipe}]` |
| `FORGE_fixundo_<part>_<k>`, `FORGE_fixbase_<part>` | `bpy.data.meshes`, fake user | Mesh | undo stack (8) and the Step 4 result, copied after `sync` (4.6) |
| `forge_fix_recipes` | **high** object | JSON string | for re-runs: `[{id, tool, params, sides, region: {pts (<= 400 surface points of the patch, in the high's local space), e_loc, normal}, keep, patch (kept areas only: vertices + faces, <= 2,000 faces), crease (the traced line), made_with: {budget, side, detail (the detail-map factors at the region's points), high_nv}}]`. It lives on the high because the high never changes after Step 3. F0 strips it from every low (4.7) |
| `retopo_rep.parts[p].fixes` | the Step 4 report | dict | `{count, kept, replayed, not_replayed: [{where, why}], hand: {count, kept: bool}}` for the rows |
| `fit_target`, `low_fp` | Step 4 report (F0) | dict / str | so the kit reproduces the fit target, and later steps see a changed low |
| approve log | `stages_ui._log` | as today | the fix log goes with the Step 4 approval (training data) |

## 9. A re-run of Step 4 with fixes present

- **Before the run:**
  - A row under Run retopology: "Your fixes: 4 (1 kept as is). They are put back after the run."
  - A checkbox **Put my fixes back**, on by default.
  - **Hand edits are asked about, never kept silently.** Hand edits are found by comparing the low
    with `FORGE_fixbase`: faces whose vertices moved more than `tol`, or whose topology changed,
    outside any logged fix. If there are any, one question: "You changed 2 places with Blender's
    own tools. Keep them after the run? [Keep them] [Let Step 4 redo them]". A slip of G or X by a
    non-modeller is then not grafted back after every re-run. [Keep them] turns each place into a
    kept-area recipe.
- **After the run:** after `_qr_one` and its final gate, the recipes are replayed in id order
  (`fixkit.replay(low, high)`).
  - **Is the recipe still what the director meant?** It is skipped, with a row, if:
    - its region's detail-map factors changed by more than 0.1. The director repainted there,
      and the new paint is the newer intent;
    - the budget changed by more than 10%, for Denser and Coarser;
    - the mirror side changed;
    - its stored surface points no longer lie within `tol` of the high, which happens if the high
      was changed under it (`high_nv` is advisory).
    - The row reads: "Not re-done at the head: you repainted there".
  - **Map the region** to the new low: faces whose centre lies within `max(e_old, e_new)` of the
    recipe's points, with normals agreeing (dot > 0.5).
  - **Tools other than Keep** run again on that patch, through the same gate. If a recipe's
    findings are already gone in the new mesh, it is skipped: "already fine here".
  - **Keep as is, a graft:**
    1. The stored patch must be a disc (4.1), with one border loop B. If it is not, it is not
       grafted and the row says why.
    2. Remove the new faces covering the kept patch: centres within `0.5 e_new` of its surface,
       projecting inside its border. The removed set must also be a disc, leaving one hole loop H.
       Otherwise it grows by one ring (up to 4 tries) until it is.
    3. Insert the kept patch as stored, with its `forge_fit_src` and `forge_crease` values.
    4. If `|H| == |B|`, `bmesh.ops.bridge_loops` gives quads. If not, the removed set grows or
       shrinks by one ring (up to 4 tries, smallest first) until the counts match.
    5. If they still differ, the longest edges on the **new** side are split until they match, and
       the faces this makes are triangulated. The kept patch is never altered. This costs
       `|H - B|` triangles, reported.
    6. Relax only the strip and one ring of the new mesh, snap to `Target`, then verify. G1 here
       means the kept patch must be bit-identical.
    7. If the new density differs from the kept patch by more than 0.6-1.6x, one question: "The
       new mesh is 2.1x coarser at the head: [Put my kept area back anyway] [Leave the new mesh]".
  - A graft or replay that fails its gate leaves the new mesh, and says where and why. The recipe
    stays, so it can be tried again.
- **Report rows:** "Put back: 1 kept area, 3 fixes. Not re-done: 1 (already fine there)."
- **Run for selected parts only:** parts that are not re-run keep their lows and every fix as they
  are. The re-run part replays its own recipes.
- **With the U6 ledger:** replay runs after `prepare` and the fit, and never changes the plan or its
  fingerprints. A kept area on a part the new plan cuts off (a tail now separate) is grafted onto
  whichever new mesh covers it, the body or the welded part.
- **Experiment gate X4:** a graft after re-runs at budgets x0.8 and x1.2.

## 10. Used after Step 4b, 5, 6, 7 or 8

- After Approve, the Step 4 header shows a small **Fix** button next to **Change**. It opens the Fix
  box without resetting anything until a fix is actually applied.
- The first applied fix shows one confirm row first, listing what must be redone (below). An answer
  of No changes nothing.
- The kit then reopens Step 4 through a new `reopen(st, "retopo", keep=...)`. `keep` lists the later
  results the kit has proven still valid. They go to "review" instead of "todo", with a row saying
  why.

| Kind of fix | Step 4b face | Step 5 UVs | Step 6 detail bake | Step 7 colour paint | Step 8 rig |
|---|---|---|---|---|---|
| any fix whose patch, plus one ring, touches no vertex of a made face (`forge_made`) | kept: the made faces and their loops are bit-identical (G1), and the face kit's whole-kit gate is re-run on the head (face-kit sec. 7, last row). Step 4b -> review: "face checked after your fix" | (by kind, below) | (below) | (below) | (below) |
| a patch within one ring of a made face | Step 4b -> todo. The face recipe makes the rebuild one click (face-kit sec. 13). The confirm row says so | (below) | (below) | (below) | (below) |
| move-only (Snap, Smooth, Follow crease slide, Match by positions) | as above | kept, then checked: per-face UV stretch on the changed faces at most 1.15x before, and no UV overlap among the patch's faces and their island (new `metrics.uv_patch_check`; `metrics.uv_metrics` has only whole-object figures). Step 5 -> review: "UVs carried over your fix: checked" | must run again. With painted colour, detail maps only (`bake.run_iter` with `DETAIL_MAPS`: normal + AO), on the GPU | kept: texture space unchanged | weights unchanged (same vertices). Step 8 -> review: "run the pose test again" |
| topology inside one UV island | as above | carried (4.7: one UV per vertex per island), then `uv_patch_check`. Step 5 -> review | as above | kept | weights interpolated and clamped to the influence limit (4.7). Step 8 -> review |
| topology across a UV seam | as above | stale: Step 5 -> todo. The last engine and settings are remembered | todo (all maps) | at risk. The confirm says: "your colour painting near the fix will not line up: [Fix anyway] [Cancel]" | todo: skin again (the joints are kept) |

- This amends the face-kit design's sec. 13 ("Fix selected after 4b reopens Step 4, so the face
  goes to todo"): with the `forge_made` mask, a fix away from the face no longer costs the face.
- The bake's `fit_cage` cache is already cleared at the start of `run_bake`, so a moved low is
  re-measured there.
- The UV compare table goes stale through the fingerprint added in F0.

## 11. The panel (Step 4 box, after a run; every row at most 44 characters)

```
Fix part of the new mesh
[Select the area]        [Find problems]
  Looking for problems: 40%       [Stop]
  12 spots found, worst first (10 shown):
  head: 3 creases cut across, 1 dent
  body: 2 thin-triangle spots
[< Previous]     2 of 10        [Next >]
[x] Both sides (this body is mirrored)
[            Auto fix selected            ]
Tools for the selected area:
[Smooth on surface]   [Snap to original]
[Follow crease]       [Match other side]
[Denser here]         [Coarser here]
[Keep as is]          [Undo last fix]
Last fix: head, both sides
  crease followed 85% (was 59%)
  0.3 mm off the original (was 1.6 mm)
  14 faces changed, +26 triangles
[Show before]  [Compare with original]
Fixes: 3 (1 kept as is)  [Undo all fixes]
```

- Buttons that need a selection are greyed (`poll`) outside Edit Mode. Their tooltips say "Select
  faces, an edge line or points on the new mesh first". Follow crease's tooltip says "Select the
  two points where the crease starts and ends (or an area across it)".
- `retopo_compare` is added to `FORGE_OT_step`'s list of actions that do not force Object Mode.
- The rows use `stages_late._row` (wraps at `PANEL_WIDTH = 44`). Tool tooltips go into
  `ACTIONS`-style descriptions.
- Questions are limited to these point-and-click answers:
  - Follow crease: [Use it] [Use the other line];
  - kept faces in a manual selection: [Fix them too] [Leave them];
  - before a re-run with hand edits: [Keep them] [Let Step 4 redo them];
  - after Step 4b or 5: [Fix anyway] [Cancel];
  - a re-run at another density: [Put my kept area back anyway] [Leave the new mesh].
- An optional entry in the Edit Mode right-click menu (`VIEW3D_MT_edit_mesh_context_menu`):
  "Forge: Auto fix".

## 12. Speed and the RTX 4080 Super

| Work | Where it runs | Time (measured or extrapolated) |
|---|---|---|
| one fix on a 50-300 face patch | CPU (bmesh + numpy + cropped BVH) | under 0.5 s per mouth corner (E5, R7) |
| crop lookup per patch | CPU | 0.03 s build (E9) |
| whole-original lookup | CPU, `BVHTree.FromObject` (built in C) | 0.29 s per 1.3M triangles against 1.4 s from Python lists (C7); about 1.1 s on the bull's 4.9M |
| Find problems | CPU, in the background | about 10 s on the bull, then cached (7.1) |
| re-bake after a fix | **GPU** (Cycles OptiX, `bake._setup_cycles`) | as Step 6 today |

- **The real speed-up is on the CPU.** `density.source_tree` builds the whole original's tree
  from Python lists today. Step 4's `conform`, `carve` and `crease_kept` use it, and so would Find
  problems. F0 replaces it with `BVHTree.FromObject` (guarded as in 4.2), which is about 4.8x
  faster for the same hits (C7). That speeds up every Step 4 run on the director's PC too.
- **Blender's Python API has no GPU path** for BVH queries or bmesh, and Quad Remesher is a CPU
  engine. The fixes are under a second already.
- **The bake.** `bake._setup_cycles` sets `d.use = True` on every device the backend lists, and
  that can include the CPU next to the RTX under OptiX. The bake may then run hybrid, which is
  often slower for a bake than the GPU alone. Nothing reports which devices actually baked.
  - X8 on the director's PC: time one Step 6 bake with OptiX only (CPU device off) and with
    OptiX + CPU, and keep the faster as the default.
  - Step 6 then shows the device in a row: "Baked on the graphics card (OptiX)".

## 13. Tests (tests/test_fixkit.py, plus panel tests in tests/test_stage_late.py)

**Fixtures and running time.**
- A low is made the way the dent repro makes one: `retopo._quadriflow` with a fixed seed, then
  `density.conform`, `carve` and the dent gate. For mirrored and cut-off cases it goes through
  `_qr_one` with the fake Quad Remesher (`tests/fake_qr.py`), so `forge_fit_src` is written the
  real way.
- Each body's low is built once per session (a `scope="session"` fixture, cached by body and
  options). C8 measured 14 s for mouth_head alone. Each test works on a copy.
- The full matrix (about 10 bodies x 5 defects x 2 scales, the fresh-process determinism and the
  reverse order) is marked `@pytest.mark.slow` and runs in the nightly sweep (F10). The default run
  covers mouth_head, bull, bat_wings and one zoo body, and stays within a few minutes.

**Bodies:**
- the dent work's `bodies.mouth_head` (to be merged with the dent gate), for mouth corners;
- `bodies.bull(tail_side=0.30)` (cartoon, a side tail) and `bodies.biped`;
- a new `bodies.crease_corner()`: R5's plateau, whose sharp edge turns at a corner of radius
  1.2 `e`;
- `bodies_zoo` humanoid (realistic), quadruped (animal), bat_wings and one_wing (thin sheets,
  one-sided), chibi (cartoon), dorsal_fin (a sheet on the middle line), horns_asym and naga
  (asymmetric originals).

**Injected defects** (deterministic):
- push 5 inner vertices `4 x tol` inward (dent);
- split a quad from a corner to 0.05 along the far edge (needle);
- move a vertex past its neighbour (fold);
- subdivide one quad twice (density jump);
- the mouth-corner low before carve, and `crease_corner`'s grid (crease cut across, bends in the
  wrong place).

| Test | Asserts |
|---|---|
| `test_auto_fix_removes_each_injected_defect[body x defect]` (slow beyond the default four bodies) | the finding is gone; G1-G6 hold; elements outside the patch bit-identical by `forge_id`; `exact_hash(high)` unchanged |
| `test_target_follows_fit_source` | bull with the tail to one side, mirrored: tail vertices carry 3 + k and weld-band vertices carry 2. Snapping a tail vertex lands on the real tail (distance to the unmirrored high under 1e-6 x size), not on the reflected image, which differs by more than `tol` there. A body vertex on the mirrored side lands on the reflected kept side |
| `test_edit_mode_snapshots_are_current` | in Edit Mode after a fix: the undo copy, the log's `fp_after` and `bm_arrays`' hash all match the edit bmesh, and differ from the Mesh as it was on entering Edit Mode (R1) |
| `test_refused_fix_changes_nothing` | a forced gate failure (a monkeypatched candidate that sinks the patch) leaves the **edit bmesh** hash (`bm_arrays`) unchanged and gives the plain reason |
| `test_auto_fix_mouth_corner_measured` | on mouth_head (E5/R7 numbers as floors): triangles down, worst angle up, both-ways gap not above 1.02x base, no dent-gate island |
| `test_crease_corner_faceting` | `crease_corner`: the finding lists bends in the wrong place. L4a removes them with +0 triangles. L4b brings the crease within `tol` to at least 0.8, with worst corner at least 20 deg and the triangle delta in the row (R5 numbers as floors) |
| `test_slide_never_flattens[0, 10, 20, 30, 45 deg]` | quad grid: 0 corners over 160 deg; crease within `tol` at least the R3 values minus 5 points |
| `test_trace_two_clicks` | `crease_corner` and mouth_head: the traced line within 0.15 `e` (synthetic) / 3.5 mm (mouth_head) of the truth at its max, and better than the straight line on its mean |
| `test_crease_edges_survive_cleanup` | after carve on mouth_head, L2, collapse and the F9 pass leave the `forge_crease` edge count unchanged |
| `test_made_faces_untouched` | a head with `forge_made` faces (a simulated bag): every tool, Auto fix and Find problems leave those faces and their loop vertices bit-identical, and report nothing on them |
| `test_rebuild_bmesh_only` | Rebuild runs with no operator and no mode switch; 0 open edges; a fill started off-corner is refused by G2; a tube band is refused with "goes all the way round" (R4) |
| `test_gates_relative_to_base` | ten successive Smooth fixes on one area: the both-ways gap never exceeds 1.02x the base region's, and the worst corner never goes below min(base worst, 20 deg) |
| `test_follow_crease_slide_and_cut` | mouth_head: crease share within `tol` at least 0.8 after cut mode; slide mode keeps the topology; cut mode adds the triangles the row states |
| `test_denser_coarser_ratios` | median edge in [0.4, 0.6] / [1.6, 2.4] of before; the ring outside bit-identical; triangle delta reported; the border jump exempt up to 2.5x |
| `test_match_other_side_and_both_sides` | biped with a one-sided injected dent: case A positions equal the reflected twin within `1e-6 x size`. horns_asym at the horn: refused with the measured difference. Both sides on bull's mouth region: both sides fixed, each logged; one side forced to fail leaves the other fixed |
| `test_keep_as_is_survives_rerun` | protect a patch, re-run Step 4 (fake QR, budget x1 / x0.8): patch bit-identical, gate passed, row present; at x0.5 the question is raised |
| `test_replay_recipes_after_rerun` | Snap, Follow crease and Denser recipes re-done or "already fine"; deterministic; a Denser recipe whose region was repainted is skipped with its row |
| `test_hand_edits_asked` | a vertex moved outside the kit: the question appears before a re-run; [Let Step 4 redo them] grafts nothing; [Keep them] grafts it |
| `test_approve_rechecks_mesh` | a face deleted by hand in Edit Mode: Approve is blocked with the open-edge row, and the counts are refreshed |
| `test_undo_stack_and_ctrl_z_sync` | Undo last / Undo all give the exact earlier hash; a log is cut back when the mesh equals an earlier `fp_before` |
| `test_data_carry` | UV map + deform group + int label on the low: Rebuild inside one UV island gives one UV per vertex per island (no hidden split), no overlap, stretch at most 1.15x; weights within the influence limit and normalised; a patch across a seam (found from UV values) marks UVs stale; after Step 5 `join_triangles` never joins across a seam |
| `test_low_has_no_high_props` | after Step 4 the low carries no `forge_fix_recipes`, face recipe or plan object properties, and only whitelisted attributes |
| `test_operator_has_no_redo_panel` | `FORGE_OT_fix.bl_options == {"UNDO"}`; the tool property is `HIDDEN` and `SKIP_SAVE` |
| `test_later_steps_reset` | after Step 5 approved: move-only -> uv review, bake todo; across a seam -> uv todo; colour kept flag. After Step 4b: a fix away from the face keeps 4b (review); a fix next to the bag sends it to todo |
| `test_deterministic[tool]` (slow) | each tool twice in one process and once in a fresh process: same `exact_hash`; also in `--reverse-order` |
| `test_scale_invariant[0.01, 100]` (slow) | same findings, same decisions, coordinates scaled |
| `test_find_problems_on_step4_output` | calibrated on **real Step 4 output** (fit + carve + dent gate) of mouth_head and three zoo bodies: at most 10 islands shown; the mouth corners are in mouth_head's top 3; no carve crease triangle is listed; the generator yields at least every 0.2 s; Stop leaves the mesh untouched |
| `test_fix_speed` | a 300-face auto fix with the lookup cached: under 2 s (CI limit 5 s) |
| panel: `test_fix_rows_fit_44`, `test_fix_buttons_by_status` | every row at most 44 characters; buttons greyed outside Edit Mode; Fix visible after Approve |

## 14. Work packages (in order; S = up to 1 agent-day, M = 2-3, L = 4-5)

| Id | Title | Size | Depends on |
|---|---|---|---|
| F0 | Groundwork in Step 4: `forge_fit_src` written in `_qr_one` / `_weld` / fallback; `forge_crease` written by `carve`; the low whitelist for attributes, mesh properties and object properties; `fit_target` + `low_fp` in the report; `uv_fingerprint` with the ordered fingerprint; `fingerprint_arrays` / `hash_arrays` split; `source_tree` on `BVHTree.FromObject` with the polygon-count guard; Compare with original works in Edit Mode | M | - |
| F1a | `fixkit.py` core: selection -> patches (made / pinned / kept left out, disc test), `Target` (per-vertex fit source, kept-side crop and reflection, crop trees, FromObject whole tree, cache), `diagnose` (all kinds including crease cut across and bend in the wrong place), `verify` (G1-G7 against before and base), transactions with `forge_id`, `sync` and `bm_arrays`, determinism | L | F0; dent gate merged (`_closer`, `_face_gaps`, `_keep_closer`, `_dig`) |
| F1b | Undo stack, log and fingerprint sync, hand-edit detection, data-carry registry (fit source, crease, labels, one UV per vertex per island, weight clamp, `cmp_seam` / `cmp_uvs`) | M | F1a |
| F2 | Move-only tools + Auto fix v1: Snap, Smooth on surface (slack + base bound), clean triangles with crease protection (L2), patch-only L0, the ladder L0-L3, plain-words report with real place words | M | F1a |
| F3 | Panel + `forge.fix` operator (`UNDO` only): Select the area, Find problems as a background generator (ranking, top 10, Stop, global crease points), Next/Previous, Keep as is, Undo last / all, Show before, Both sides checkbox, rows; Approve re-check (4.8) | M | F1a (UI can start alongside F2) |
| F4 | Follow crease: two-click trace + second line + wire display, gated slide, cut mode (densify by the chord rule, relax, straight-chord cut via `carve(faces=...)`, relax), L4a / L4b in Auto, the painted-red advice; `bodies.crease_corner` | L | F2 |
| F5 | Denser here, Coarser here (after X3), Rebuild here with the bmesh grid fill and the disc test; X2 for larger | M | F2 |
| F6 | Match other side + Both sides: plane + symmetric-original test (U2 field when present), twin map, cases A/B, refusals, per-side transactions | M | F1a (U2 optional) |
| F7 | Re-runs: recipes on the high, validity checks (paint, budget, side, surface), replay after the run, graft of kept areas (disc test, count-matched stitch), the hand-edit question, rows | L | F2, F4, F5, F6 |
| F8 | After Steps 4b-8: `uv_patch_check` (per-face stretch, overlap, seams from UVs), weight carry checks, `reopen(..., keep=...)` including the face, detail-only re-bake path, confirm rows | M | F1b, F5 |
| F9 | Optional: Step 4 tidy-up pass, the ladder's L2/L3 on faces carve and the dent gate touched (E11: carve raises needles 3.7x), crease-protected, verified, kept and made faces skipped | S | F2, dent gate |
| F10 | Cross-body sweep: zoo + mouth_head + bull side tail + crease_corner, injected defects for every tool, scale and determinism matrix under `slow`, session fixtures, timing; the director's-PC check sheet (X5, X6, X8) | M | runs alongside; final after F7 |

**Order:** F0 -> F1a -> (F1b, F2 and F3 in parallel) -> F4 -> (F5 and F6 in parallel) -> F7 ->
F8 -> F9. F10 grows with each package.

**First usable release: F0-F4.** It holds Auto fix with Snap, Smooth, clean triangles and the crease
repair, the panel and Find problems. That covers the director's own notch (crease cut across at
the mouth corner, both sides) and the thin triangles in 93.png, with the painted-red advice.
- Critical path F0 -> F1a -> F2 -> F4: about 2.5 + 4.5 + 2.5 + 4.5 = 14 agent-days.
- All of F0-F4: about 19 agent-days.
- F5-F10: about 15 more.

## 15. Risks

1. **The trace can pick the wrong crease** where two creases run close (a lip line and a fold
   beside it) or a crease fades into a join.
   - The line is shown before anything changes, and [Use the other line] offers the runner-up.
   - The depth check drops stretches with no real crease, and the slide's per-vertex gate stops a
     wrong pull.
   - R6's max error (3.38 mm) sat at a snapped end, which is why ends that stray are dropped.
2. **Crease thresholds** (25 deg sharp, 20 deg bend, sampling every `e/40`) are set on two bodies
   (R5, R6).
   - F10 calibrates them on the zoo's Step 4 output.
   - A Tripo original's noise can look sharp at small `e`. The scale-steady test, plus runs of at
     least 3 points, are the guard. The calibration test fails if a clean body lists any crease
     finding.
3. **Cut mode adds triangles** (+26 per corner in R5) and needs the relax to keep the 20 deg floor.
   - On a coarse Unity budget the budget row warns.
   - Both sides doubles the cost, and the row shows it.
4. **Large rebuilds are poor with grid fill** (E3: 2.2 deg at about 14 faces across), and bridging
   unequal loops gives only triangles (E4). Rebuild is limited to about 9 faces across until X2.
5. **A graft after a re-run at another density** makes a triangle strip or fails its gate. The one
   question, plus the stored recipe, covers it, but the director may need to fix again.
6. **Edit Mode undo versus Forge's log:** Edit Mode undo does not restore object properties. The
   fingerprint sync (4.6) handles it; Ctrl+Z, and the `UNDO`-only operator pushing a step, still
   have to be checked in windowed Blender (X6).
7. **Bmesh ops that depend on memory order** (precedent: `extrude_edge_only`): `subdivide_edges`,
   `join_triangles`, `collapse`, `dissolve_edges` and `grid_fill` are unproven here. X1 runs each
   twice and in reverse order; any that fail are redone in Python.
8. **Fit-source record gaps:** a future Step 4 path that builds geometry without writing
   `forge_fit_src` leaves 0 (pinned, not judged). That is safe, but the kit then cannot fix there.
   `test_target_follows_fit_source` checks that a Step 4 low has no 0 outside made faces.
9. **Thin sheets and tight joins** (wings, ear rims, horn roots): nearest-surface can land on the
   wrong wall. The `FACING`, `STAND_FOR` and reach rules apply, and part vertices search only their
   own part. Tests cover bat_wings, one_wing and the horn roots.
10. **Mirror tool and Both sides on tilted or off-centre bodies, or posed pairs:** the plane comes
    from the measured `x0` (U2's yaw when present). The symmetric-original test refuses anything
    else, and Both sides hides when the twin map does not cover the twin.
11. **Hidden staleness after Steps 4b-8:** handled by `low_fp` in every later report (F0). Until F8
    lands, the kit resets all later steps (today's `reopen`).
12. **Budget creep:** Denser and cut mode add triangles locally, with no global rebalance. The row
    shows the total against the budget, and Step 4's over-budget row (already present) warns.
13. **Dependencies in flight:**
    - the dent gate's functions (not yet merged);
    - U2's field and U5/U6 (`forge_keep`, ledger);
    - U14's `forge_ledger_row` on the low;
    - the face kit's `forge_made`.
    - The kit works without U2-U14, using today's mirror plane and no row labels, and plugs them
      in when they land. The carry rule for row labels is tested with a fake label now.
14. **The bake device change** (X8) could make the bake slower on some PCs. It is measured on the
    director's PC first and kept only if faster.
15. **Director confusion with Edit Mode select modes:** Select the area sets the mode, overlay and
    visibility. Every tool accepts faces, edges or points, and the tooltips say so. Follow crease
    asks for two points, which is a click and a Shift-click.

## 16. Experiments run, and the gates still needed

First version (`fixkit/exp_fixtools`):

| # | Script | Result |
|---|---|---|
| E1/E2 | `e1_ops.py`, `e2_fill.py` | `bmesh.ops.grid_fill` given a whole single hole loop makes no faces. `bpy.ops.mesh.fill_grid` fills it with all quads, but corners reach 5.8 / 10.8 / 1.9 deg. `subdivide_edges(cuts=1, use_grid_fill, INNER_VERT)`: 43 -> 205 faces, 18 pentagons in the ring, min 39.7 deg. `unsubdivide` on a QuadriFlow patch: 3,232 -> 3,218 faces. QuadriFlow accepts an open patch. |
| E3 | `e3_local.py` | Step 4's own patch: min 80 deg, edge CV 0.02-0.04. Fill_grid + pinned relax: min 0.5-1.8 deg. Inset + fill_grid + relax: 37.6 / 29.8 / 2.2 deg at radii 0.18 / 0.3 / 0.45 (about 6 / 9 / 14 faces across). QuadriFlow on the cut-out: min 69 deg, CV 0.07, 0 border vertices kept. |
| E4 | `e4_bridge.py` | `bridge_loops` between unequal loops: 33 / 62 / 94 triangles, min angle 11.6 / 2.5 / 4.6 deg. |
| E5 | `e5_mouth.py` | mouth_head, QuadriFlow low 11,117 faces, fit = conform + carve + dent gate. join_triangles 22 -> 18 and 26 -> 16 triangles. Relax + snap, strict put-back: worst angle 16.0 -> 19.3 and 15.1 -> 20.9 deg; gaps down; 7/23 and 19/33 moves put back. Under 0.5 s per corner. |
| E6-E8 | `e6_crease.py`, `e7_crease.py`, `e8_crease.py` | Crease finder and slide with an **oracle hint** (low vertices near the true line, ordered along it): 4.62 -> 1.26 mm mean, 59% within tol. Superseded by R3, R5 and R6. |
| E9 | `e9_speed.py` | full BVH from Python lists: 0.5 s per 328k triangles. Numpy crop + BVH: 0.03 s for 2.5k triangles; 20k queries in 0.04 s. |
| E10 | `e10_interp.py` | face interpolation carries UV, deform weight and an int face label |
| E11 | `e11_calib.py` | per 1000 faces, QuadriFlow alone -> after fit + carve + dent gate: needle 0.72 -> 2.65; flat corner 0.72 -> 2.56; long face 0.99 -> 4.06; density jump 0.27 -> 1.50; valence >= 6: 0 -> 4.5; dihedral > 100 deg: 29 -> 47 faces |
| E12 | `e12_edit.py` | Edit Mode write-back (copy -> verify -> `bm.clear()` + `from_mesh` + `update_edit_mesh`) keeps the selection and face attributes |

After the critique (`fixkit/exp_fixtools`, `r*.py`):

| # | Script | Result |
|---|---|---|
| R1 | `r1_editsync.py` | In Edit Mode after a written-back fix, the Mesh still had 49 vertices and an unchanged `exact_hash`, while the edit bmesh had 50. After `ob.update_from_editmode()`: 50, hash changed, edit bmesh still valid. `bm_arrays` hash = synced Mesh hash. Restoring a snapshot in Edit Mode (`clear` + `from_mesh` + `update_edit_mesh`) is bit-exact, and the object stays in Edit Mode. |
| R2 | `r2_fitsrc.py` | A POINT INT attribute survives `from_mesh` appending a piece (16/16 values each side), `to_mesh` and `mesh.transform`. `subdivide_edges` gives new vertices a neighbour's value (so the weld band must be written explicitly). `bm.verts.new` gives 0. `remove_doubles` keeps the first point's value. |
| R3 | `r3_slide.py` | Quad grid, crease at 0/10/20/30/45 deg. Old slide: 0/4/8/12/16 corners over 160 deg (up to 180). Gated slide (worst >= min(before, 30), flattest <= max(before, 160), area >= 0.3x): 0 at every angle, worst corner 69.7/62.1/57.8/50.5/53.9 deg, crease within tol 100/89/76/64/62%, no triangles. Staircase removal + gated slide: +0/4/8/12/16 triangles, crease within tol 100/73/62/53/0%. |
| R4 | `r4_gridfill.py`, `r4b_debug.py` | `bmesh.ops.grid_fill` with two opposite sides of one hole loop, started at the sharpest corner: 16 quads at 90 deg, 0 open edges. Started at an arbitrary vertex: 16 faces, 8 open edges left. Sphere cap of 96 faces (1 loop, Euler 1), inset + side fill 8/8/8/8: 64 quads, 0 open edges, worst 19.0 deg before relax. A band round a tube: 2 loops, Euler 0. |
| R5 | `r5_facet.py` | Synthetic plateau, sharp edge turning at a corner of radius 1.2 e, 180k-triangle original, 20 x 20 quad low on it. Two-click trace: mean 0.015 e, max 0.117 e (straight line: 0.71 / 1.29 e). Step 4 low: 4 bends in the wrong place, crease within tol 59%, corners 53.4-121.9 deg, gap RMS 2.37/3.49 (x1e-3). Gated slide: 0 / 65% / 47.8-152.3 / +0 / 1.95/2.97. Densify only: worst 15.7 deg (+20 triangles); with relax 21.3. Densify + relax + slide + straight cut + relax: 1 / 85% / 23.1-138.0 / +26 / 1.53/1.85. The same without relax: 13.3 deg. Cut with `face_split(coords=...)`: 100% followed, but 13 bends in the wrong place, corners 0.0-176.1, +46. Straight cut on the coarse low alone: 61%. |
| R5b | `r5b_diag.py` | At R5's corner, 8 low edges bend by at least 20 deg; 4 bend 25.6-30.9 deg where the original turns 0.0-5.3 deg across them, with the sharp crease 0.55-0.7 e away. Sampling across every e/4 found none; every e/40 finds all 4. |
| R6 | `r6_e8.py` | E8 re-run on mouth_head with a two-click hint (clicks 0.3 E off) and the gate on. Before: crease 3.58 mm mean, 6% within tol. Trace: mean 0.88 mm, max 3.38 mm (straight line 1.78 / 2.85). Ungated slide: 94% within tol, 2 corners over 160 deg (up to 173.8). Gated slide: 81% within tol, mean 1.18 mm, corners 43.1-117.8, 0 over 160, 1 put back. |
| R7 | `r7_smooth.py` | E5 again with the current dent code. Strict put-back: 12/20 and 13/19 moves put back; worst corner 22.9 -> 33.3 and 17.1 -> 17.1 deg; gaps 0.531/0.526 -> 0.521/0.543 and 0.607/0.758 -> 0.601/0.755 mm. Slack rule alone: 0/20 and 4/19 put back; worst 33.8 / 17.1; gaps 0.539/0.567 and 0.628/0.809 (3-7% worse). |
| R8 | `r8_fromobject.py` | `BVHTree.FromObject` on a mesh of triangles, quads and an n-gon: the hit index names the polygon under the hit (200/200), in the object's local space with the object moved (200/200). |

Critique's own (`fixkit/exp_crit_fixtools`): C1 API check (`join_triangles(cmp_seam=False,
cmp_uvs=False)` defaults, `face_split(coords=)`), C2 Edit Mode staleness, C4 slide on diagonal
creases, C6 Find problems cost, C7 `FromObject` vs lists, C8 join_triangles against carve's
triangles, C9 `face_split` signature.

Gates still to pass before the matching package ships:

- **X1:** determinism of each topology op used, including `grid_fill` (twice, fresh process,
  reverse order).
- **X2:** QuadriFlow + collar + count-matched weld for patches over about 9 faces across; R4's
  corner-start grid fill measured at 14 across.
- **X3:** Coarser here by dissolving alternate edge rings on QuadriFlow and Quad Remesher patches.
- **X4:** graft after re-runs at x0.8 and x1.2 budget.
- **X5:** on the director's PC, the bull's mouth corners (both sides) on the 4.9M original: Auto fix
  and Follow crease (times, before/after screenshots, crease share).
- **X6:** Ctrl+Z round trip in windowed Blender with the `UNDO`-only operator.
- **X7:** the crease thresholds calibrated on the zoo's Step 4 output (F10).
- **X8:** the Step 6 bake with OptiX only against OptiX + CPU on the director's PC.

## 17. How this fits the rest

- **Dent gate (in parallel):** it repairs what Forge's own fit makes, automatically, over the whole
  mesh. This kit is the director's local tool and reuses the gate's checks. The gate cannot see the
  mouth-corner notch (sec. 1). The kit's crease findings and L4 can, and F9 can later run them
  automatically after Step 4.
- **Detail map paint (sibling DESIGN_detail_paint.md):** for a local problem, the kit replaces
  "paint and re-run". The paint design should still tell the director that red takes quads from
  everywhere else, and that a jump from full red to white makes thin triangles. The kit's 7.4 row
  points there.
- **Face kit (sibling DESIGN_face_kit.md, Step 4b): mouth cut, mouth bag, teeth, tongue, eyes and
  lids.**
  - **Order:** the face kit cuts on the **low**, after Step 4 is approved, in its own step 4b. The
    high is never changed. So every recipe stored on the high stays valid, and the per-recipe
    surface check (sec. 9) is the safety net. `docs/research/mouth.md` planned the slit on the high
    before retopology; the face-kit design superseded that, and this kit follows the face-kit
    design. If the slit ever moves onto the high, recipes whose surface points no longer lie on the
    high are skipped with a row, and the rest replay as usual.
  - **No original here:** the face kit writes `forge_made = 1` on every face it builds or rebuilds
    (bag, inner lips, lids, sockets), in addition to its own `forge_kit` kind. This is a one-line
    request to the face-kit design. The fix kit then leaves those faces out of every patch, pins
    their vertices (the slit and rim loops), never snaps or smooths them onto the closed Tripo
    surface, and never reports them as dents.
  - **What it reuses from here:** the trace and gated slide for its mouth line (Follow crease
    gives the edge path; the face kit splits it into the slit and builds the loops), `verify`,
    transactions, recipes and data carry.
  - **Fix after 4b:** no longer always costs the face (sec. 10).
- **U5-U7 and U14:** the kit reads `forge_keep` (written into `forge_fit_src` as 2) and the frame
  for its `Target`, carries `forge_ledger_row` on the low, and never changes the plan or its
  fingerprints.

## 18. Changes after critique

**Changed (high):**
- **Wrong surface for cut-off parts.** `Target` no longer mirrors everything outside `forge_keep`.
  F0 writes `forge_fit_src` per vertex (mirrored body / whole original at welds and fallbacks /
  part k), and `Target` reflects and crops to the kept side only for the mirrored body. Part
  vertices search only their own part. `_weld` must write the band explicitly, since
  `subdivide_edges` copies neighbour values (R2). New test on the bull's side tail (4.2, 13).
- **Stale Edit Mode data.** Every snapshot, undo copy, log fingerprint and test reads
  `bm_arrays(bm)` or calls `ob.update_from_editmode()` first. Undo restores into the edit bmesh
  without leaving Edit Mode. All of it is measured (R1, 4.6).
- **Slide flattening quads.** The per-vertex gate now checks the worst corner, the flattest corner
  (160 deg) and face area. R3 and R6 show 0 corners over 160 deg. E8's oracle hint is replaced by
  the two-click trace, re-measured on mouth_head with the gate on (R6).
- **The director's own defect.** New findings `crease cut across` and `bend in the wrong place`
  (R5b), found over the whole part. New rungs L4a (gated slide) and L4b (densify along the crease
  by the chord rule, relax, slide, straight cut, relax), measured on a sharp turning crease (R5:
  59% -> 85% followed, gap down 35-47%, worst 23.1 deg, +26 triangles). Rebuild's limit is
  restated as a selection width (about 9 faces across), with the director told what to select.

**Changed (medium):**
- **Rebuild:** a bmesh-only grid fill (sides from the sharpest corner) replaces
  `bpy.ops.mesh.fill_grid` (R4).
- **Gates against the Step 4 result:** G4 and G6 are measured against `FORGE_fixbase` for the
  region, so repeated fixes cannot drift. G6 uses a 20 deg floor and a 160 deg ceiling.
- **Smooth:** a slack per-vertex rule plus the patch-level fit bound (R7).
- **Find problems:** runs as a background generator with progress and Stop. It ranks spots, shows
  the top 10, skips carve's crease triangles and made faces, and is calibrated on real Step 4
  output.
- **Face kit:** a `forge_made` mask; the order follows the face-kit design (cut on the low in 4b,
  the high untouched); Follow crease no longer claims to make loops.
- **Hand edits:** asked about once, never sticky by default. Approve re-runs the final gate and
  blocks new openings (4.8).
- **Follow crease input:** two clicks with a trace on the original, a shown line and
  [Use the other line].

**Changed (low):**
- Crease edges are marked (`forge_crease`) and protected in L2, collapse, Coarser and F9.
- Density jumps on the border ring are exempt for Denser and Coarser, up to 2.5x.
- Disc test before Rebuild and grafts.
- Data carry:
  - one UV per vertex per island;
  - weights clamped by `skin._cleanup_weights`;
  - `cmp_seam` / `cmp_uvs` after Step 5;
  - `uv_patch_check` for per-face stretch and overlap;
  - seams found from UV values.
- Operator and undo:
  - `UNDO` only, with the tool property `HIDDEN` and `SKIP_SAVE`;
  - L0 works on the patch only;
  - `forge_id` stable ids.
- Recipes:
  - skipped when the paint, budget, side or surface changed;
  - plan and fix object properties stripped from lows.
- Speed: `BVHTree.FromObject` (R8 confirms polygon indices) in F0, and the bake device check (X8).
- Rows use only the place words Forge has.
- Work packages: F1 split into F1a (L) and F1b (M), session fixtures, and the slow marker.
- Gaps the critique listed, now covered:
  - a **Both sides** option on mirrored bodies (6.5);
  - the painted-red guidance for 93.png (7.4).

**Rejected, with reasons:**
- **Staircase removal before the slide** (split the corner quad along its diagonal). Measured in R3:
  it adds one triangle per step and follows the crease worse than the gated slide at every angle
  (73/62/53/0% against 89/76/64/62%). The gated slide alone already removes the flat corners.
- **Cutting with `face_split(coords=polyline points)`.** Measured in R5: corners fell to 0.0 deg,
  with 13 new bends in the wrong place and +46 triangles. Densifying until straight chords meet the
  chord rule, and then cutting straight, gives 85% followed at 23.1 deg with sound faces.
- **The critique's exact smooth rule** (keep a move when the fit is within slack and the shape
  improves), taken alone. R7: it kept almost every move, but cost 3-7% of fit without raising the
  worst corner further than the strict rule did. It is adopted only with the patch-level G4 bound
  on top.
- **"The worst angle may not drop" taken literally.** On a regular quad grid (every corner 90 deg)
  it would refuse every repair. The floor is min(base worst, 20 deg), measured against the Step 4
  result, which bounds both the single step and the drift.
- **Faceting as the dihedral between neighbouring faces against the original's turn between their
  centres** (the critique's wording). Where a face straddles the crease, its centre lands on either
  side, so that comparison is noisy. The finding uses the original's turn *across the low edge
  itself* at `+- e/8`, plus a sharp crease within one `e`, which R5b showed picks out exactly the
  stepped facets.
