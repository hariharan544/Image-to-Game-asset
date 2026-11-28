# Honest detail painting, crease lines and the GPU question (Step 4) - revised

Design for the lead, revised after the adversarial critique (section 10 lists every change).
Scope: what the director's full-red lips did to the bull's mouth (stated as a hypothesis to be
settled), the logic errors around Forge's detail map, a paint tool whose numbers can be trusted
(a separate paint layer, presets, a cap, gradation only where the director asked for something,
the cost before the run, "asked vs got" measured on Quad Remesher's own result), crease lines
that are shown first and used only after evidence, how this joins the fix kit's local tools,
and an honest answer on the RTX 4080 Super.

Code read (read-only): `blender_scripts/forge_bpy/density.py`, `retopo.py`, `rescue.py`,
`bake.py`, `uv.py`, `sysinfo.py`, `body_plans.py`, `blender_addon/forge_send/steps.py`,
`stages_late.py`, `stages_ui.py`, `jobs/_setup/addon_probe.json`,
`docs/research/mouth-crease-investigation.md`, `tests/fake_qr.py`, `tests/zoo_baseline.py`,
`tests/test_retopo_shape.py`, `tests/bodies_zoo.py`. Sibling designs: `fixkit/DESIGN_fix_tools.md`
(the fix kit) and `fixkit/DESIGN_face_kit.md` (the face kit). Screenshots: `fixkit/89-93`,
`dent/crop_85.png`.

Experiments (Blender 5.3.0 bpy, numpy 2.5.5, 4 shared cores). Scripts are in the appendix.

- First round: E1 (cap and gradation of the size field), E2 (Blender 5.3 API facts), E3 (crease
  line from rough clicks), E3c (automatic crease line), E4 (false lines on zoo bodies), E5 (Python
  loop vs Geometry Nodes).
- The critique's checks: C1-C10 (`fixkit/exp_crit_density`).
- Revision round: R1 (crease lines on a face with eyelids, nostrils and a muzzle fold; numpy CSR
  adjacency), R2/R2b (a Quad Remesher stand-in that honours the map), R4 (mirror flag, byte copy,
  mirroring paint across the measured middle), R5 (gradation seeded from paint only, on the zoo
  chibi).

Quad Remesher (QR) is not available here. Every claim about what QR does with an input is marked
**(PC probe)** and is settled by the probe in section 5.

---

## 0. In plain words (for the director)

- **What we know.** Red paint meant "16 times the quads here", with no limit and a hard edge
  where the paint stopped. Forge's own map never asks for more than 4 times. The dark streaks at
  the mouth corners are long thin triangles that **Forge's crease cutting** makes after Quad
  Remesher has run. The dent check being built now repairs those. Denser lips give the crease
  cutting more edges to cut, so more streaks.
- **What we think, and will check.** Quad Remesher could not honour a request that strong on a
  band that thin. A short test on your PC (about 10 minutes, one click) measures what it really
  does with paint, before Forge changes any Quad Remesher setting.
- **Painting, made safe.** Your paint goes on its own layer, so Forge's map and your requests
  never mix. Four buttons set the brush for you: **More** (4x the quads), **A bit more** (2x),
  **Fewer** (half), **Erase**. Forge softens the border of what you paint, and nowhere else.
- **Numbers you can trust.** Before you run, Step 4 says what your paint costs ("lips: +1,240
  triangles, the rest about 3% fewer"). After the run it says what Quad Remesher really delivered,
  measured before Forge's own crease cutting touches the mesh ("lips: asked 4x the quads, got
  1.7x").
- **Fixing one spot.** For a local problem use the fix kit's buttons on the new mesh (Denser here,
  Coarser here, Follow crease). They change only what you selected. A tick box lets the same
  selection also count as paint for the next full run.
- **Crease lines.** Forge finds the creases of the face (the mouth line, rings round the eyes, the
  muzzle fold) and shows them. Until the PC test proves Quad Remesher follows them, they are shown
  only and change nothing.
- **The RTX 4080 Super** already does the baking and PartUV's AI split. Quad Remesher, UV
  packing, Auto-Rig Pro and Forge's checks run on the processor, and none of them has a GPU path
  we can use. What will help is using all processor cores and doing less work (section 4).

---

## 1. What happened at the mouth: facts, then a hypothesis

### 1.1 Facts (from the code)

1. **The brush.** `Paint` (`stages_late.do_retopo_map_paint`) enters Vertex Paint on
   `QR_Density`, Quad Remesher's own colour code. No preset, palette or strength is set. Full red
   decodes (`density.qr_factors`) as edge factor 4 (16x the quads per area, if QR reads the colour
   as an edge factor, as `write_qr_density`'s comment records from an earlier bull run). The
   automatic map never asks for more than edge factor 2: `qr_density` clips to [0.25, 4] and
   `write_qr_density` takes the square root.
2. **The budget.** `_qr_part` turns `adapt_quad_count` off whenever a map exists. The total stays
   at the target, so painted quads come from everywhere else. Model arithmetic (QR's fixed total,
   colours read as edge factors): full red on a head that is 10% of the surface would give the
   head 64% of the quads and every other area 2.5 times fewer. The panel shows none of this.
3. **Then the fit.** After QR, `_fit` runs `conform`, then `carve`. Carve splits edges at the
   groove floor, joins the split points face by face and triangulates the n-gons left over
   (`density.carve`). The long thin triangles in `93.png` are carve's. The dent gate being built
   in parallel repairs them.
4. **Nothing measures the paint.** The report has total triangles and the humanoid region split.
   There is no number per painted area.

### 1.2 Hypothesis H1 (to be settled, not a finding)

The lip band is less than one white quad wide. A request of 16x against about 2.6x around it
cannot be met inside the band without rows of transition, and either:

- (a) QR places that transition on the painted border, which converges at the mouth corners, or
- (b) QR's own smoothing averages the thin band away. In `fixkit/exp_density/crop91_mouth.png`
  the lips' quads look about cheek-sized, which fits (b) better than (a).

(a) and (b) may both hold in different places (corners vs mid-lip), or neither. Two things settle
it:

- the pre-fit snapshot (2.5): asked vs got measured on QR's raw result, before carve, on the next
  real run of the bull;
- the PC probe's density trial (section 5).

**Withdrawn from the first version:**

- The "36 times too steep" figure. The raw steepness of a painted border is a resolution artefact:
  1.3, 5.4 and 10.7 per unit distance at 41k, 655k and 2.6M vertices (E1).
- The claim that g = 0.3 is "what QR can grade". It is an assumption until the probe measures it.

### 1.3 Logic errors (current code)

| # | Where | What is wrong | Effect |
|---|---|---|---|
| L1 | `retopo._qr_part` | `autodetect_hard_edges = not painted`. The comment gives the reason for organic bodies ("the angle detector smooths away soft creases; the map handles them"). But `ensure_detail_maps` writes a map on **every part**, props included, whenever Detail focus > 0, so the switch follows "a map exists", not "this part is organic". | QR's hard-edge detection is off on every part with a map, props too. Whether that is right for props is open (L11). |
| L2 | same | `adaptive_size` goes 50 to 75 when a map exists, and the map is itself a curvature map (`detail_score`). | Curvature may be counted twice (nostrils and ear rims very dense, `dent/DIRECTOR_WIREFRAME.md`). Settled by the probe, not changed before. |
| L3 | same | `adapt_quad_count` off with a map. | Painted quads come from the rest with no feedback (1.1.2). |
| L4 | `stages_late` Paint, panel | No brush preset, no limit, no scale. | The natural choice, pure red, means 16x the quads. |
| L5 | `density.boost`, called by the shape check | Forge's own refinement paints **full red** (edge factor 4) over the lost spots grown by **3 source rings** (2-5 mm, not a ratio of any measured size). | Forge repeats the director's request automatically, on a speck. |
| L6 | `retopo._qr_one` shape check | The refined re-run is accepted whatever it gives. `shape_loss` is measured again but never compared with the first run. | Breaks "never make the mesh worse". |
| L7 | `steps.ensure_detail_maps` | The map is made only when missing, and the strength it was made with is not recorded. | **Moving Detail focus does nothing once a map exists.** Only Reset applies it. |
| L8 | same, plus `Reset` | Paint and the automatic map share one attribute. | Reset erases the paint, and Forge cannot tell paint from map (no cost, no asked vs got). |
| L9 | `rescue._submesh` (via `split_off`) | Cut-off parts and rescue pieces are built without the colour attribute. | A piece goes to QR with no map and in another regime (adaptive 50, hard edges on, `adapt_quad_count` on). Paint on a tail is ignored. **Not changed here before the probe** (section 7, D12). |
| L10 | `density.symmetrize`, Vertex Paint | In 5.3, Vertex Paint mirrors with the **mesh** flag (`Object.use_mesh_mirror_x`, which is `Mesh.use_mirror_x`), not `Paint.use_symmetry_x` (C2, C3; the 5.3 toolbar and header draw `ob.use_mesh_mirror_x`). The brush mirrors about local x = 0, while Forge mirrors about the measured middle x0 (`mirror_plane`, up to 3% of the size). `symmetrize` copies the kept side's colours over the other side. | Paint on the replaced side is lost. A brush mirror would be off by 2·x0, more than a lip band (R4: overlap with the true twin 0.07). |
| L11 | props | Props get a map, so (L1) their hard-edge detection is off. The comment at `retopo.run` ("props are often hard-surface: keep edges") guards `_fuse` only, not QR's detector. | Open question for the probe. The first version wrongly read that comment as intent for QR. |
| L12 | `steps._replan_horns` | "Painted over since" is a 0.05 difference on the shared attribute. | Works today. With a separate paint layer the director no longer paints `QR_Density`, so the test reads "not painted" and the horn plan stays in `QR_Density`, while the director's paint lives in `Forge_Paint` and wins in the field. |
| L13 | `do_retopo_map_paint`, `prepare_maps_job` | Paint calls `prepare_maps` synchronously. Show's job yields once and then runs the whole of `prepare_maps` in one timer tick. | Both freeze Blender with no Stop on a 5M-vertex original (detail score and parts plan: a minute or more). |
| L14 | `steps.paint_setup` (Step 7) | `scene.tool_settings.unified_paint_settings` does not exist in 5.3 (E2, C8). | "Paint selected part" raises AttributeError on the director's 5.3 when the palette has colours. |
| L15 | `density.vertex_factors` | Max over corners. | A border vertex reports the strongest neighbouring colour. Gone with a POINT paint layer. |
| L16 | `steps.clay_lows` | Removes only `QR_Density`. The QR-failure fallback low is a reduced copy of the original. | Any further Forge colour layer reaches the FBX as vertex colours, and `Mesh.use_mirror_x` set on the original is carried into lows by `copy()` (R4a). |

---

## 2. The fix: detail paint with honest numbers

### 2.1 Data: what Forge stores and where

Rule: **the automatic map stays exactly as today.** On a body nobody painted, the bytes QR
receives are byte-identical to today's (a hard test, 6.4). Everything the director asks for lives
in its own layer and changes only the vertices it touches.

On the **original body mesh** (`p.data`, the hidden high that is also the bake source):

| Name | Kind | Written by | Meaning |
|---|---|---|---|
| `QR_Density` | CORNER byte colour, as today | `ensure_detail_maps` and `_paint_horns`, unchanged | The automatic map plus the horn plan, QR's colour code. **Never painted by the director any more.** |
| `Forge_Paint` | POINT byte colour (white by default, C9) | the director (Vertex Paint), migration, the fix kit's "also for the next full run" | The director's requests, Forge's code (2.2). White = no request. |
| `forge_field` | POINT float | `density.make_field` | The final edge factor (for Show, the cost rows and the tests). |
| `forge_touched` | POINT bool | same | Vertices whose final factor differs from the automatic one (painted areas and their graded rings). |
| `forge_paint_area` | POINT int | same | Painted area id (0 = none). Connected pieces of non-white paint, numbered by (side, plan part, area, centroid), so deterministic. |
| `Forge_Show` | POINT byte colour | `make_field` | Display only: the final field in Forge's scale (2.2), the layer Show displays. Never painted. |
| `me["forge_detail_strength"]` | float | `ensure_detail_maps` | The Detail focus the map was made with (L7). |
| `me["forge_mirror_x0"]` | float | `plan_parts` (already calls the mirror logic) | The measured middle, `density.mirror_plane(me)`. |
| `me["forge_field_key"]` | string | `make_field` | Staleness key (2.3, step 6). |
| `me["forge_paint_cost"]` | JSON string | the Done-painting job | Cost rows' numbers, read in draw. |
| `me["forge_guides"]` | JSON list | crease lines (section 3), the fix kit's Follow crease, the face kit | `[{id, name, how: auto/drawn/fix/face, closed, pts, w, use: show/density/encode}]`, points resampled every L/4 in the high's local space. |

**QR's input is computed inside the run, never stored stale.** In `retopo._qr_one`, on the low's
working copy (`backup`), after the mirror shift and before `symmetrize`, and again once the
body's QR target is known (2.3). The original's `forge_field` serves Show and the cost rows only.
So QR always gets a field made from the current paint, budget, plan and guides, whatever happened
in the panel.

On the **Step 4 report** (`st.retopo_rep`, per part):

- `"qr_settings"`: every QR call's settings (body, pieces, rescue, re-runs);
- `"qr_raw"`: asked vs got and guide follow measured on QR's raw result (2.5);
- `"carve"`: what crease cutting added;
- `"timing"`: seconds per pass.

**Migration** (old .blend files with paint inside `QR_Density`):

1. **Find the old strength.** A 1-D search over strength s in [0, 1] (golden section, 20 steps)
   minimises the median of |log2(vertex_factors(QR_Density) / auto_s)| over body vertices outside
   the horn plan. Old files did not record the strength (L7), and assuming today's slider misreads
   the whole detailed area as paint.
2. **Split.**
   - m = old / auto_s.
   - Where |log2 m| > 0.15, outside the horn vertices, write m clipped to [0.5, 2] into
     `Forge_Paint`.
   - Horn vertices that `_replan_horns`' existing "painted over since" test calls painted are
     migrated the same way. The other horn vertices keep the plan.
3. **Rewrite** `QR_Density` with `ensure_detail_maps(s, recompute=True)` plus the horn plan, and
   record `forge_detail_strength = s`.
4. **Tell the director**, in one row: "Your earlier paint is on its own layer now, at most 4x the
   quads."

### 2.2 Paint buttons with safe presets

`Forge_Paint` uses QR's colours at **half the strength**: the same look, but full red means 4x
the quads, not 16x. It is decoded continuously, so brush falloff and blending behave:

- red side (r ≥ 0.99): m = 2^(1 − min(g, b)), from 1 (white) to 2 (red);
- cyan side (r < 0.99): m = 2^−(1 − r), from 1 to 0.5 (cyan).

`Forge_Show` uses the same scale for the final field (red = 4x the quads relative to white,
saturating beyond), so "red" means the same thing everywhere the director looks. `QR_Density` is
transport only and is never shown.

| Button | Brush colour (sRGB) | m (edge) | Shown as |
|---|---|---|---|
| More | (1, 0, 0) red | 2.0 | 4x the quads |
| A bit more | (1, 0.5, 0.5) pink | 1.41 | 2x the quads |
| Fewer | (0.5, 1, 1) light cyan | 0.71 | half the quads |
| Erase | (1, 1, 1) white | 1 | as Forge decides |

Blender calls, checked in 5.3 (E2, C1-C3, C8), in a new `steps.paint_mode(preset)`:

```python
o = body original; select_only(o); o.hide_set(False)
me.color_attributes.active_color_name = "Forge_Paint"   # POINT BYTE_COLOR, created white if missing
bpy.ops.object.mode_set(mode="VERTEX_PAINT")
vp = bpy.context.scene.tool_settings.vertex_paint
ups = vp.unified_paint_settings                          # 5.3: per mode; the scene-level one is gone
ups.use_unified_color = True; ups.color = PRESET[preset]
if vp.brush: vp.brush.color = PRESET[preset]             # use_unified_color is deprecated for 6.0
ups.use_unified_strength = True; ups.strength = 1.0
vp.palette = forge_palette()                             # bpy.data.palettes "Forge detail": 4 swatches
# symmetry (L10): the brush mirrors about local x = 0, Forge about x0
o["forge_prev_mirror_x"] = o.use_mesh_mirror_x
x0 = me.get("forge_mirror_x0", 0.0)
o.use_mesh_mirror_x = mirrored and abs(x0) <= 0.1 * L_face   # brush error 2|x0| <= a fifth of a quad
```

- **Symmetry is Forge's job, not the brush's.** For a mirrored body, `make_field` combines each
  painted vertex with its twin across x0 (2.3, step 2). Paint on either side counts, on both
  sides, about the measured middle. The brush mirror is only a viewing convenience. It is turned
  on only when x0 is within a tenth of a face quad of the local x = 0, and the previous value is
  restored on Done painting and when the director leaves the mode. R4, a lip-sized spot with
  x0 = 1.5% of the size: Forge's twin overlaps the true twin 0.75 (limited by the mesh
  resolution), the brush's mirror 0.07.
- `clay_lows` and the export also set `low.data.use_mirror_x = False` (R4a: `copy()` carries it).
- When paint on the two sides differs, the stronger request wins on both sides, and a row says:
  "Your paint differs left and right: the stronger one is used on both sides."
- Operator allowlist: `stages_late.execute` already skips `mode_set(OBJECT)` for
  `retopo_map_paint`. The four presets and `retopo_paint_done` join it, so presets switch without
  leaving Vertex Paint.
- **Show is disabled while painting.**
  - All Step 4 buttons share one operator with an `action`, so a per-class poll cannot single
    Show out. Instead the panel draws the Show row with `row.enabled = False` in VERTEX_PAINT,
    with the row "Press Done painting first".
  - `do_retopo_map_show` also refuses in VERTEX_PAINT, before `execute`'s `mode_set(OBJECT)`
    would leave the mode.
  - The active colour attribute is never changed in Vertex Paint, so a stroke made through
    Forge's buttons always lands in `Forge_Paint`.
- **Strokes in the wrong layer.** If the director enters Vertex Paint through Blender's own mode
  menu while Show is on, strokes would go into `Forge_Show`. `make_field` records a hash of the
  `Forge_Show` bytes it writes. The next Show or Run job compares, rebuilds the layer, and shows
  the row "You painted on the map view, which is not used: paint with the Paint buttons".

**Done painting**:

- A button, shown while in Vertex Paint. Its job:
  1. restores `use_mesh_mirror_x`;
  2. returns to Object mode;
  3. runs `make_field` (a generator, one yield per pass);
  4. writes `Forge_Show` and the cost rows.
- **Leaving the mode any other way** (Tab, the mode menu) is caught by a watcher, never by draw.
  Entering paint registers `bpy.app.timers.register(_paint_watch, first_interval=0.5)`. While
  the body is in VERTEX_PAINT it returns 0.5. Once it is not, it restores the flag, starts the
  same job through `run()` (a timer may write ID data, draw may not) and returns None. A
  `load_post` handler unregisters it.
- **Undo inside paint** (Ctrl+Z) needs no special case: the staleness key (2.3, step 6) sees the
  changed bytes.

**Paint entry no longer freezes (L13).**

- `prepare_maps` becomes a generator with one yield per pass: detail score per part, region
  factors, write, then `plan_parts` with yields at its existing loop boundaries.
- `prepare_maps_job` delegates to it with `yield from`.
- Paint starts that job when the map or plan is missing, and enters paint mode in its `on_done`.
- Any pass still longer than 2 s without a yield is listed in the report's timing, so it can be
  split later.

### 2.3 The field: automatic × paint, mirrored, capped, graded only near paint

`density.make_field(me, target_tris, R=2.0, g=0.3)`. Every number is a ratio of a measured size.

1. **Compose.**
   - f_auto = vertex_factors(QR_Density), today's automatic map plus horn plan, decoded per
     vertex.
   - f = f_auto × m, where m comes from `Forge_Paint` (1 where white).
   - Later sources (the face kit's ramp, drawn-line turns: 3.5) enter as extra m factors, each
     gated.
2. **Mirror** (mirrored bodies only):
   - Build a `mathutils.kdtree.KDTree` over the **painted** vertices P, mirrored to (2·x0 − x, y, z).
   - Candidates are vertices inside the mirrored bounding box of P, grown by one source edge.
   - Each candidate within 1.5 local source edges of a mirrored painted point takes the stronger
     of its own m and that point's m (in |log2 m|).
   - The KD tree holds only painted points, so the cost scales with the paint, not with the
     5M-vertex mesh.
3. **Areas.** Label the connected pieces of painted vertices by BFS on the painted subset of the
   CSR adjacency (2.3a), numbered deterministically.
4. **Cap per area.**
   - Each area A has its **own** size L_A = L0_auto / median(f_auto[A]), where L0_auto is the
     white edge of the automatic map at this budget. This replaces the first version's circular
     definition.
   - Its ring S: unpainted vertices within 1.5·L_A of A (a bounded Dijkstra from A).
   - f_A = clip(f_A, median(f_S)/R, median(f_S)·R). **R = 2.0 edge ratio by default** (4x the
     quads relative to the surroundings), set by the probe later.
   - **No ring** (the director painted the whole part, or "Fewer" inside "More" filled the gap):
     cap against the part's median f_auto instead.
   - If the paint covers ≥ 90% of a part's area, the row says "Painting everything changes
     nothing: raise Triangles instead". At a fixed total, uniform paint is a no-op.
   - The automatic values are not touched by the cap.
5. **Grade only from the paint** (seeded). Edge length L = L0/f.
   - **"More" areas.** A multi-source Dijkstra starts at the painted vertices with their capped L
     and spreads outward: L′(v) = min(L(v), min over u in A of (L(u) + g·d(u, v))). It stops where
     the spread value exceeds max L in the window. It only ever refines. An unpainted vertex
     changes only when it lies in a painted area's ring.
   - **"Fewer" areas.** The seeds are the ring's vertices, and the spread goes **into** the
     painted area only. The coarse request is softened at its own border, never around it.
   - **g = 0.3 per unit distance by default** (a quad at most about 1.3 times its neighbour).
     This is an assumption until the probe's hard-vs-graded trial.
   - **The automatic map's own steepness is left exactly as today.** Whole-field grading changed
     12-34% of an unpainted chibi in the critique's C6, so it waits behind the probe (D13).
   - R5, the zoo chibi at 138k vertices with a lip-sized "More" spot (0.05% of the surface):
     - outside the spot, 0.12% of the surface changes by more than 5% (the graded ring, out to
       3 local quads);
     - the white edge grows ×1.001 (the cost to the rest);
     - under 0.01 s.
6. **L0 by fixed point, and the key.**
   - L0 = sqrt(2·Σ a·f′² / target_tris), the formula `_rigid_factors` uses. It is iterated with
     steps 4-5 until L0 changes by less than 0.1%, at most 3 passes (R5: 1 pass).
   - `me["forge_field_key"]` = SHA-1 of: the `Forge_Paint` bytes, target_tris, the Detail
     strength, the plan fingerprint (`forge_plan`, the split ids' hash, the horn plan), the
     guides in use, x0, R, g and the code version.
   - Show and the cost rows recompute in their job when the key differs.
   - Inside the run, the QR input is always recomputed for the real target, in two goes:
     - Once before `symmetrize`, steps 1-4. These are ratios, so the twin sides agree, and
       `symmetrize` carries POINT float attributes (C8). Step 4's ring radius uses L0 at the
       part's whole target, which `_qr_one` knows from its first line. The cut-off pieces'
       later share changes that radius by less than sqrt(2), and it is only a neighbourhood
       size.
     - Once when the body's target is known, steps 5-7, right before `_qr_part`.
   - A count-correction re-run whose target moved by more than 5% recomputes step 5 for the new
     L0 (it is local, so cheap).
7. **Write QR's input** on the low's working copy, never on the original:
   - copy `QR_Density`'s bytes unchanged (R4b: a byte copy through `color_srgb` is exact);
   - overwrite only the corners of `forge_touched` vertices with `qr_colours(f′)`.
   - With no paint, `forge_touched` is empty and QR's input is today's bytes.
   - Vertices that `split_off` adds (plug and lid) get no float value (C8: a new vertex reads 0).
     Before use, each takes the value of its nearest original vertex, never 0. `qr_colours(0)`
     divides by zero.

#### 2.3a CSR adjacency, shared

`density.csr(me)` builds compressed adjacency once per mesh with numpy:

- `argsort` of the doubled edge list, then `searchsorted` offsets;
- int32 neighbours and float32 lengths;
- cached by (`me.session_uid`, vertex and edge count), dropped at the end of the job.

R1, 655k vertices: **0.13 s and 37 MB of arrays**, against 2.2 s and +651 MB for Python lists
(C7). At 5M vertices that is about 1 s and 280 MB. Blender's Python has no scipy (C7), so
Dijkstra, BFS and component labels run on these arrays with `heapq`, bounded to the window they
need. The fix kit and the crease lines use the same helper.

E1 numbers (a thin "lips" band, 0.15% of the surface, model arithmetic):

| Request | Band quads | Rest of the body |
|---|---|---|
| none | 22 | – |
| today's full red | 340 | edges ×1.011 |
| capped to 2x edge and graded | 86, plus a ring of 0.8% of the surface | edges ×1.010 |

### 2.4 The cost before running (in the budget view)

`density.paint_cost(me, f_auto, f_final, areas, parts, target)` uses QR's fixed-total model:
quads in X = Q · Σ_X a·f² / Σ a·f². It is computed in the Done-painting job and stored as
`me["forge_paint_cost"]`.

**Naming.** Rows are per painted area and per plan part, in plain words:

- an area is named by its side and the plan part it lies on ("lips (both sides)", "the tail",
  "left horn"), with part names from `plan_parts` / `appendages.plain_name` (tail, horn, ear,
  wing...);
- the rest of the body is "the body";
- humanoid region names (head, arms, hands, legs, feet from `region_labels`) are used only when
  Step 1's `asset_kind` is `biped`. A quadruped's hooves are never called hands.

**Units.** Ratios are always in quads ("4x the quads"). Counts are in triangles, the budget's own
unit. Edge lengths are never shown.

```
Your paint: 2 areas, +1,240 triangles
   lips (both sides): 310 > 1,550
   taken from the rest: about 3% fewer
   (the body -520, the tail -300, ...)
   capped: you asked for more than 4x the
   quads next to it, now 4x (Show)
```

Rows wrap at 44 characters through `_row`/`_wrapped`. The capped row appears only when the cap
changed something ("capped to 3x" when a partial cap applies). Fewer-paint gives the reverse:
"+N triangles to the rest".

### 2.5 After the run: asked vs got, on QR's own result

The critique showed (C10) that measuring after the fit is meaningless: carve alone turned a
uniform quad sphere with no density change into lips that read 4.08x finer. So:

- **Pre-fit snapshot.**
  - In `_qr_one`, right after every successful `_qr_part` (first run, count-correction re-run,
    refinement re-run) and before `_fit`: `raw = keep_tmp(obj.data.copy())`.
  - `fit["tree"]` (the source BVH that carve builds anyway) is built here, earlier, at the same
    cost.
  - The last accepted run's snapshot is kept as `FORGE_qrraw_<part>` (fake user, about 30k
    triangles) until Approve or Undo retopology.
  - A **Show Quad Remesher's result** toggle in review swaps it in, so a screenshot can tell QR's
    work from Forge's crease cutting.
- **`density.asked_vs_got(backup, raw, f_final, areas, tree)`** on the snapshot:
  - Each raw vertex is labelled with the area of its nearest source face's first vertex
    (`tree.find_nearest`), with `conform`'s facing test (normal dot > 0) so thin sheets do not
    label from the wrong side.
  - An edge with both ends in area k belongs to k.
  - got_k = (ring median edge / area median edge)², the quad ratio.
  - asked_k = (median f′ over k / median f′ over its ring)².
  - The same is done per plan part against the planned share.
- **Verdict.** GOOD if log(got) ≥ 0.75·log(asked), otherwise WARN. The 0.75 is a default to be
  calibrated from the probe and from the jsonl log. An area with fewer than 8 raw edges reads
  "smaller than about 2 quads: paint a wider area".
- **Carve's share, separately.**
  - `fit["carve"]` already counts its splits. Each split is attributed to the nearest painted
    area or crease line.
  - Row: "Forge's crease cutting added 226 triangles at the mouth: the dent check repairs thin
    ones".

```
Painted areas (Quad Remesher's result):
   lips: asked 4x the quads, got 1.7x
   Quad Remesher did not make it this
   fine: paint a wider area, or raise
   Triangles
```

One line per run goes to `jobs/<job>/qr_density_log.jsonl` (asked, got, area size in quads,
border steepness, QR settings). This is the calibration data for R, g and the verdict.

### 2.6 Forge's own refinement (the shape check), verified with tolerances

This replaces `boost(..., edge_factor=4, rings=3)` (L5) and the blind acceptance (L6).

- **Footprint.** The lost spots are grown by geodesic distance (bounded Dijkstra on CSR) to at
  least one local quad edge L_local, never a fixed ring count. The footprint is written as
  "More" (m = 2) into a temporary `Forge_Paint` copy on `backup` and goes through `make_field`,
  so it is capped and graded like the director's paint.
- **Keep the better.**
  - Run 1's result and metrics stay in memory.
  - The re-run is accepted only if `face_lost` drops by at least 25% and none of the others gets
    worse beyond its tolerance:

    | Metric | Tolerance |
    |---|---|
    | `shape_loss.lost_ratio` | at most 1.05x run 1, plus 0.0002 absolute |
    | `crease_kept` | at least run 1 − 1 percentage point (it is a subsample, rounded to 0.1) |
    | open edges | not more |
    | the dent gate's worst dent, once that gate exists | at most 1.1x |
    | guide follow, only when guides are encoded (D7c) | at least run 1 − 5 points |

  - The probe measures QR's run-to-run spread (the same input twice) and replaces these defaults
    with 2x the measured spread.
  - Otherwise run 1 goes back (`_replace_mesh(obj, keep)`), with the row "A denser re-run did not
    help: the first result is kept".
- The first version's "use the guides instead" branch exists only once guides are encoded
  (D7c). Before that, it would cost a QR run for no change.

### 2.7 Selections on the new mesh: the fix kit's buttons, one set

There is **one set of buttons**: the fix kit's **Denser here**, **Coarser here** and **Follow
crease** (`DESIGN_fix_tools.md` 6.3-6.4). They act locally on the selected faces, edges or
vertices of the new mesh, are verified by the kit's gate, and are replayed after a full re-run
(fix kit section 9). This design adds no second "More / Fewer / Crease here" row.

What this design adds to the kit:

- **A tick box under Denser / Coarser here: "Also ask for this in the next full run".**
  - When ticked, the same selection is mapped onto the original by `density.footprint(low_me,
    sel, tree)`: the selected faces' corners and centres, then `tree.find_nearest`, then
    geodesic growth until the footprint covers the selection's area.
  - The kit's preset (Denser = More, Coarser = Fewer) is recorded into `Forge_Paint`, and the
    cost rows update.
  - It records only, and runs nothing.
  - The row under it: "A full run makes the whole new mesh again; your fixes are put back after
    it."
- **Follow crease stores its line.** The kit's crease polyline (6.3, step 1) is appended to
  `me["forge_guides"]` with `how: "fix"` and `use: "show"`. A full re-run then shows the line,
  and after D7c can encode it.
- **The shared helpers** `density.footprint` and `density.csr` live in `density.py`, used by both
  designs.

### 2.8 Panel and later steps

Step 4 box (rows wrap at 44, at most 4 buttons per row):

```
Triangles (Unreal)            30000
Detail focus                  0.80
Detail map: red = 4x the quads, cyan = 1/4
[Show / hide]  [Reset map]
Paint on the original (your own layer):
[More] [A bit more] [Fewer] [Erase]
(while painting)
Painting: More, 4x the quads
Paint one side: Forge copies it across
the middle.                [Done painting]
(after Done: cost rows, 2.4)
Crease lines (shown only, for now):
   mouth line                 [Remove]
   ring round the left eye    [Remove]
[Show lines] [Draw a line]
Extra parts found: ...
[Run retopology]
(after the run: result rows, asked vs got,
 crease cutting, then the fix kit's rows)
```

- **Tooltips.** Reset map: "Make the detail map again from the shape (your painting is kept)".
  An **Erase all paint** button with a confirmation dialog sits beside Erase.
- **Detail focus (L7).** When the slider differs from `forge_detail_strength`, the map is remade
  at the next Show, Paint or Run (inside their jobs). Paint is untouched.
- **Rows that appear when needed:**
  - pieces (L9, until D12): "Paint on the tail is not used yet: cut-off parts get Forge's own
    sizes";
  - stale paint after a run: "Run again to use your new paint".
- **Later steps.** Painting and lines change nothing until Run. Run already resets Steps 5+
  (`_start_step(st, "retopo")`). In review, Approve stays allowed with stale paint: the result is
  valid, it just does not include the new paint. Undo retopology keeps paint and lines.
- **Export hygiene (L16).** `clay_lows`, the QR-failure fallback and the export strip every
  colour attribute and generic attribute whose name starts with `Forge_`, `forge_` or
  `QR_Density`, and set `use_mirror_x = False`.

---

## 3. Crease lines: shown first, used after evidence

### 3.1 What QR 1.3 on the director's PC accepts (`addon_probe.json`)

Bridge 1.3.0, `Scene.qremesher`:

- target_count, adaptive_size, adapt_quad_count;
- use_vertex_color, painted_quad_density;
- **use_materials** (edge loops on material borders);
- **use_normals** (split normals and sharp edges as hard edges);
- **autodetect_hard_edges** (angle based, with no angle setting exposed);
- symmetry_x/y/z.

Operators: remesh, facemap_to_materials, license_manager, reset_scene_prefs. There are no guide
curves and no per-region settings, so **every setting applies to the whole input mesh**.

### 3.2 Decision

- **No QR setting changes before the probe.** The body keeps today's settings. So do props (the
  first version turned their angle detector on; that is now behind the probe's prop trial, D12),
  pieces and rescue pieces.
- D0 only puts every call through one function, `retopo._qr_settings(kind, has_map)`, which
  **returns today's values unchanged** and records them in the report.
- **Hard-edge detection cannot be "on for the face only".** It is global and its threshold is
  hidden. On a 2.5M-vertex AI mesh, angle detection sees millimetre triangles, and the same
  argument applies to soft Tripo props (plush, rope, fruit). The probe decides per kind.
- **Guides are handed to QR only on the proxy, and only after the probe.**
  - Primary encoding: `sharp_edge` on guide edges plus `use_normals`. In Blender the custom
    normals live in `custom_normal` (E2), which must be removed from the proxy first, or every
    imported normal seam becomes a guide.
  - Material strips (`use_materials`) are a probe variant only. An open line needs a strip, and
    the strip's second border is an unwanted parallel loop.
  - The face kit's FK-X3 (material split along the mouth and eye rings) is the same trial. The
    two designs share one probe trial.

### 3.3 Finding the lines

`creases.auto_lines(me, region, L_face, tol)`, in a new module
`blender_scripts/forge_bpy/creases.py`, all on `density.csr`:

1. **Valley depth at a face-quad scale.**
   - Smooth the coordinates with `density._smooth` for (L_face / (2·e_src))² passes.
   - val = (smoothed − p)·n.
   - Band = val > 0.25·tol (tol = carve's 0.0012·size), inside the strict region (the face's
     `forge_strict`), with `plan_parts`' part-root exclusion.
2. **Components** by BFS on the band subset only.
3. **Classify before tracing** (new):
   - **Closed crease.** The component has a hole: a piece of its complement, inside the
     component's bounding ball, that does not reach the ball's rim, with equivalent radius
     sqrt(area/π) ≥ 0.5·L_face.
     - Judged by area, not perimeter. A perimeter-only test called the mouth "closed" at 164k
       vertices, because a thin slit inside its band was long enough (R1, first try; the
       loop then ran along both walls, 35% on the floor).
   - **Open line.** No such hole. It is traced end to end and kept only if:
     - the **traced** length is ≥ 2·L_face (the first version tested the component's box against
       L_face, C4);
     - and the band is line-like: the cross extent over the along extent (PCA) is < 0.5, unless
       the traced length is ≥ 4·L_face.
   - **Pit.** Otherwise: rejected and shown nowhere. A pit's detail is the detail score's job.
4. **Trace.**
   - Open: the valley-preferring shortest path between the component's two farthest points
     (E3's cost: length × (1 + 20·(1 − v̂)), v̂ normalised by the window's 99.5th percentile, ties
     by vertex index).
   - Closed: a first path a → b between far points, then a second a → b with the first path's
     interior forbidden within 2·w. The loop is the first path plus the second reversed.
5. **Groove width w per line**, measured: the band's area / (2 × traced length), clamped to
   [e_src, L_face]. It sets the tracer window (0.75·d + 3·w), the forbid width and the snap
   radius of Draw a line (2.5·w). E3's synthetic constant is gone.

**R1: a head with an open mouth line, two closed eyelid rings, two nostril pits and an open
muzzle-fold arc**

At 655k vertices:

| Crease | Result | Floor covered | Points on the floor |
|---|---|---|---|
| mouth | open, 17.8 L_face | 100% | 97% |
| muzzle fold | open, 15.0 L_face | 100% | 98% |
| left eyelid | closed loop, 18.3 L_face, closes | 100% | 98% |
| right eyelid | closed loop, 18.5 L_face, closes | 100% | 98% |
| nostrils | rejected (traced 1.6-1.8 L_face) | – | – |

Time: CSR 0.13 s, valley depth 1.6 s, classify and trace 0.9 s.

- At 164k vertices the result is the same, with coverage of 87-100%.
- With nostrils twice as wide, one is rejected as a pit (aspect 0.98) and the other as short.
- The first version's tracer gave 5 lines on this kind of head, with half-rings and lines across
  the nostrils (C4).

**On the head, the face kit's marks come first.** The face kit finds the mouth line (its 4.2) and
the eye rings (its 4.4) with its own scoring and sureness. When it has run, its lines are stored
in `forge_guides` with `how: "face"`, and an auto line within 2·w of a face line is dropped as a
duplicate. Auto lines cover the rest: muzzle folds, brow creases, the beak border and creases on
other parts.

**Gate.** Until the probe (D6) and the face test bodies (D7b) pass, auto lines are **shown only**.
They do not feed density, carve, the dent gate or QR. Their `use` stays "show". The director can
press **Use this line** on a listed line to make it "density" (3.5), which is an explicit request
like paint.

**Drawn by the director.** **Draw a line** reuses the fix kit's surface click and its crease
finder (fix kit 6.3, step 1: the multi-scale profile across the path).

- Each click is a `scene.ray_cast`, snapped to the deepest valley vertex within 2.5·w, and
  consecutive points are joined by the tracer.
- Backspace removes a point, Enter keeps the line, Esc cancels. Clicking the first point again
  closes the line.
- E3, clicks 0.6 w off the floor: 81% of points on the floor and 93% round the corners (plain
  shortest path: 29% and 0%).
- Drawn lines are "density" at once: the director asked for them.

**Display and removal.**

- A temporary edges-only object "Forge crease lines", drawn in front and parented to the original,
  removed on Approve.
- Each listed line has its own **[Remove]**. Names come from the plan part and side ("ring round
  the left eye", "crease on the tail").

**Mirroring.** For a mirrored body, lines on the kept side are mirrored about **x0** (2·x0 − x),
not x = 0. A line drawn on the replaced side is moved to the kept side the same way, with a row
saying so.

### 3.4 Encoding on the proxy (only once the probe says it works)

In `_qr_part`, after `only_qr_density(proxy.data)`:

```python
me = proxy.data
if "custom_normal" in me.attributes: me.attributes.remove(me.attributes["custom_normal"])
for n in ("sharp_edge", "sharp_face"): ...remove if present
me.shade_smooth()
edges = creases.snap_to_mesh(me, guides)      # points every L/8 -> nearest proxy vertex -> short paths
mark = np.zeros(len(me.edges), bool); mark[edges] = True
me.attributes.new("sharp_edge", "BOOLEAN", "EDGE").data.foreach_set("value", mark)
s.use_normals = True; s.autodetect_hard_edges = False   # or the material variant, per the probe
```

- Guides are stored as 3D polylines and re-snapped to whatever mesh QR gets (mirrored, split).
- The original and the low never get sharp edges or extra materials, so the bake source stays
  untouched.
- Pieces get no guides until D12.

### 3.5 The corner: density from the line's own turn (accepted and drawn lines only)

A chain of edges of length L following a curve of radius ρ is off the curve by the sagitta
L²/(8ρ). To stay within carve's tolerance the edges must satisfy **L ≤ sqrt(8·ρ·tol)**, the
sagitta rule `_rigid_factors` already uses for horns.

- `turn_factor` measures ρ along each line in use as "density": the circumradius of three points
  spaced L_local apart.
- Within L_local of points where L_local > sqrt(8ρ·tol), it sets m_turn = L_local /
  sqrt(8ρ·tol).
- These vertices join `forge_touched` and are seeds for the gradation, capped by R like paint.
- Auto lines in "show" contribute nothing.

### 3.6 Verification and fallback (only with encoded guides)

After a run with encoded guides, **guide follow** is measured on the **raw snapshot** (2.5), so
carve's cuts cannot count as following.

- Follow = the share of each line's points (every L/4) within tol of a raw-mesh edge, per side
  ("mouth line: an edge follows 92% (left 95%, right 89%)").
- If a line's follow is below 50% **and** the quads are worse than a guide-free run's (share of
  quads with angles outside 60-120°, poles within 2 L of the line, against the tolerances of
  2.6), Forge re-runs without guides and keeps the better result.
- Carve and the dent gate always run after the fit as the last local fix.

### 3.7 Toward the open mouth (face kit)

- The face kit cuts the mouth along its own lip line, through the fix kit's Follow crease and its
  gate.
- `forge_guides` is the one store for those lines (`how: "face"`), so Step 4 shows them, and after
  D7c can encode them so QR lays a loop along the cut.
- The face kit's density ramp along the mouth line and round the eyes (its section 5) enters
  `make_field` as a seeded source of type "face". It is capped and graded like paint, instead of
  being written into `QR_Density` with `density.boost`. That keeps the automatic map untouched
  and puts the ramp in the cost rows.

---

## 4. GPU (RTX 4080 Super) and CPU: what can really go faster

| Stage | Heavy work | Runs on now | Can the GPU speed it up? | What helps instead |
|---|---|---|---|---|
| 1 Brief | LLM supervisor (optional) | Ollama on the GPU | already | – |
| 2 Assets | Tripo | Tripo's cloud | no (remote) | – |
| 3 Geometry clean | weld, voxel solid (OpenVDB), decimate | CPU (voxel multi-threaded) | no | more cores |
| 4 Detail map | `detail_score`, joints, parts plan | CPU, mostly one core | no practical GPU path | cache the plan; fewer passes |
| 4 Quad Remesher | the QR engine | CPU | **no**: QR has no GPU setting | (PC trial) a decimated QR input |
| 4 Fit / carve / shape check / lines | BVH queries in Python loops; Dijkstra on CSR | one core | no practical path | Geometry Nodes queries use every core (E5: 5.9 s to 1.89 s on 4 cores, identical results); CSR instead of Python lists (R1/C7: 0.13 s instead of 2.2 s) |
| 5 UVs | UVgami, xatlas | CPU | no | – |
| 5 UVs | PartUV AI split | **CUDA** (`uv.py`) | already | keep the AI part downloaded |
| 5 UVs | UVPackmaster 4 | CPU engine as far as we know | probably no: check its Preferences for a device list | all cores |
| 6 Detail bake | Cycles bake | **GPU: OptiX, then CUDA** (`bake._setup_cycles`) | already | (PC trial) GPU devices only: today every listed device gets `use = True`, the CPU included; also try `render.use_persistent_data` |
| 6 Forge's bake passes | fit_cage, `_validate_hits`, raster, inpaint | CPU | no practical path | GN or vectorised queries |
| 7 Colour | texture paint; re-bake | viewport GPU; Cycles GPU | already | – |
| 8 Rig | Auto-Rig Pro, motion checks | CPU | no | – |
| 9 Export | FBX, previews | CPU; previews on the GPU | previews already | – |

**Honest answer.** The GPU already does everything Blender and the add-ons let it do: the bake,
PartUV's AI, local AI and the viewport.

- Blender's Python does offer compute shaders (`gpu.compute`). But a BVH, Dijkstra or QR
  replacement on them is not a practical project, so there is **no practical GPU path for these
  checks**.
- What is real:
  1. per-pass seconds in every report (D0);
  2. bake on GPU devices only (D9);
  3. per-point loops moved to Geometry Nodes, which use all cores (D10);
  4. CSR arrays instead of Python adjacency (in D2/D7a);
  5. a smaller QR input trial (D11).
- **Before promising any gain from cores:** `sysinfo.run` adds `os.cpu_count()` and the processor
  name to `blender_report.json` (D0). E5's 3x was measured on 4 cores. The PC's count decides what
  the director should expect.

---

## 5. The PC probe: what Quad Remesher really does (the director clicks once)

`forge_bpy/qr_probe.py`, started like the ARP probe (`forge setup-blender --probe-qr`, or a "Test
Quad Remesher" button in Forge's setup panel). It writes `docs/research/qr_probe.json`.

**P0. QR's own colour code, with no runs.**

- The probe reads the bridge's Python: the source lines of the module that defines
  `painted_quad_density` and where it turns into a colour (`inspect.getsource` around the
  property's update callback, or the brush code).
- It sets `painted_quad_density` to 0.25, 0.5, 2 and 4 and records the vertex-paint brush colour
  the bridge sets.
- This settles "edge factor or density" from QR's own code. Today that rests on one earlier bull
  measurement (`write_qr_density`'s comment).

**Test bodies** (deterministic, in `forge_bpy/fixture.py`, about 200k triangles each):

- **D-body**: a sphere with six bands at least 6 white quads apart. Widths 1 and 3 quads, each
  asking m = 1.41, 2 or 4. Each band is measured against its own ring, so one run gives six
  results.
- **G-body**: E3's hooked-groove head (a mouth line with 90° corners) plus two eyelid rings.
- **P-body**: a box-like prop with a map.
- **T-body**: `curled_tail` (for the mapped-pieces gate, D12).

**Runs, all measured on the pre-fit snapshot:**

| Trial | Runs | Measured |
|---|---|---|
| Density: D-body, hard borders, adaptive 50 and 75 | 2 | asked vs got per band; poles within 2 L of a border; sliver share |
| Density: D-body, graded borders (g = 0.3), adaptive 50 and 75 | 2 | the same: hard vs graded decides g and D13 |
| Noise: D-body hard at 50, again | 1 | QR's run-to-run spread, sets the 2.6 tolerances |
| Guides: G-body with none; autodetect on; sharp_edge + use_normals; material strip + use_materials | 4 | guide follow per side; corner dent (the dent gate's metric); crease_kept; quad-angle share; extra triangles |
| Props: P-body, autodetect on vs off | 2 | share of the box's sharp edges kept within tol |
| Pieces: T-body, piece unmapped (today) vs mapped (D12's budget) | 2 | quad size at the root on both sides; tail weld outcome |

13 QR runs. QR takes roughly 20-40 s on 200k triangles, so **about 10 minutes** in total. The file
records each run's real time.

**Forge reads the probe file:**

- **R**: the largest m whose got ≥ asked^0.75 (default 2).
- **g**, and whether whole-field grading helps (D13).
- **adaptive_size**: L2 is changed only if 50 gives better asked vs got and no worse crease
  numbers.
- **The guide encoding**: the variant with follow ≥ 90% on both sides and no worse corner dent;
  none if neither works.
- **autodetect** for the body and for props, and whether pieces move to the body's regime.
- **The tolerances** of 2.6.

With no probe file Forge keeps every QR setting exactly as today.

---

## 6. Tests (all in Blender; QR stand-ins where QR is needed)

### 6.1 A stand-in QR that honours the map (new, before D2)

`tests/fake_qr.py` gains `remesh_by_field(target_tris)`, used by `zoo_baseline` and the density
tests instead of `_decimate_to(2·target)`, which ignores the map (C-critique):

1. Decode QR_Density on the input to f per vertex, then the level q = round(log2 f) in {-1, 0, 1, 2}.
2. Fixed total: white triangles = target · Σa / Σ a·4^q.
3. Decimate (collapse, no group) to that count.
4. For levels 1 and 2: `bmesh.ops.subdivide_edges(cuts=1, use_grid_fill=True)` on edges whose
   midpoint's nearest source vertex has q ≥ level. The new points go onto the source (BVH
   nearest). The ring's n-gons are triangulated (BEAUTY).
5. Level −1: a second Decimate with a vertex group over the cyan area.

R2b, a 41k-vertex source, target 2,000 triangles:

| Band asks | rest/band edge | Triangles |
|---|---|---|
| f = 2 | 2.00 | 1,996 (the rest's edges 9% longer: the fixed total, visible) |
| f = 4 | 3.88 | 1,848 |
| f = 1 or 1.41 | 0.97 (no change; the stand-in works in powers of 2) | 2,000 |

It is deterministic and takes 0.06 s.

- **Rejected: Decimate with a vertex group** (R2). It is not proportional: a band weight of 0.95
  already gives 3.2x, 0.2 gives 7.6x. With 0/1 weights the weight-0 side never collapses (19,036
  faces against a 1,024 target).

### 6.2 Test bodies

New fixtures in `tests/bodies.py`:

- `hooked_groove_head(sub=9, w=0.02, depth=0.008)`: E3's head, front marked strict.
- `face_head(sub=9, variant)`: R1's head, which has a mouth line, two eyelid rings, two nostril
  pits and a muzzle fold.
  - `variant="beak"` replaces the mouth with a cone beak on the front. Its junction with the head
    is a ring valley.
  - `variant="wide_nostrils"` doubles the pit radius.
  - Each returns its truth: floor masks per crease, open or closed, and the expected count.
- `painted(body, spot)`: puts a lip-sized "More" spot (1.5 local quads radius) on a zoo body's
  head front, or on its tail.

### 6.3 New files

`tests/test_detail_paint.py`, `tests/test_creases.py`, about 4 minutes in total. Plus additions to
`test_stage_late.py`, `test_retopo_shape.py`, `test_appendages.py` and `test_zoo_bodies.py`.

### 6.4 Tests

1. **Decode.** Preset colours give m = 2, 1.41, 0.71, 1. Blends are monotone. Bytes round-trip.
2. **Unpainted = today (hard).** On every zoo body and on `face_head`, with no paint and auto lines
   present, the QR input bytes on the low copy equal today's `QR_Density` bytes, compared
   channel by channel. `forge_touched` is empty.
3. **Migration.**
   - A map made at strength 0.4 with old full-red lips, read with the slider at 0.8: the
     estimate is 0.4 ± 0.05.
   - `Forge_Paint` is "More" on the lips only.
   - Horn vertices: painted-over horns migrate, the other horns keep the plan.
4. **Detail focus (L7/L8).** Strength 0.8 to 0.4 recomputes the map at the next Show or Run.
   `Forge_Paint` is byte-identical before and after. Reset keeps paint.
5. **Field.**
   - Inside each painted area's window, the growth per unit distance is ≤ g + 1e-6.
   - Outside every window the field is bit-identical to f_auto.
   - Each area is ≤ R × its ring median.
   - No-ring case: the cap is against the part's median, and the "painting everything" row
     appears.
   - "Fewer" grades inward only.
   - Same ratios at scale ×0.01 and ×100.
   - Deterministic (hash of `forge_field` across two runs).
   - L0 converges in ≤ 3 passes.
6. **Mirror (L10).** A body offset so that x0 = 2% of the size, painted on +X only:
   - the QR input is symmetric about x0 (twin overlap ≥ 0.7 at test resolution);
   - entering paint sets `ob.use_mesh_mirror_x` only when |x0| ≤ 0.1·L_face, and the old value
     is back after Done and after `_paint_watch` sees the mode change (the watcher is called
     directly in the test);
   - every low has `use_mirror_x == False`.
7. **Cost.**
   - Predicted triangles over the plan parts sum to the budget within 1%.
   - On a quadruped zoo body no row says "hands" or "arms". On a biped the humanoid names appear.
   - Rows are ≤ 44 characters, use quads for ratios, triangles for counts, and no edge-length
     words.
8. **Asked vs got is QR's own** (the critique's C10).
   - Uniform quads over the mouth groove with no density change, run through the real `_fit`:
     the report's got is < 1.2x (WARN), although post-carve edges would read about 4x.
   - With `remesh_by_field` and a band asking f = 2: got 2.0 ± 0.2 (GOOD).
   - The raw snapshot mesh exists until Approve.
9. **Stand-in.** R2b's numbers as assertions (ratio 2.0 ± 0.15 for f = 2, total within 10%,
   deterministic).
10. **QR settings, record only (D0).** `fake_qr` snapshots `scene.qremesher` per call. On
    `curled_tail` and a prop, every call's settings equal today's values (body: adaptive 75, no
    autodetect, `adapt_quad_count` off with a map; piece: adaptive 50, autodetect on,
    `adapt_quad_count` on). The report lists them.
11. **Refinement verified (L5/L6).**
    - `boost` is never called with edge_factor > R, and the footprint is ≥ L_local wide.
    - A stand-in that returns a **worse** mesh on the second call: the first result is kept,
      with the "did not help" row.
    - A re-run within tolerance on every other metric but `face_lost` down 30%: accepted.
12. **Creases, auto.** On `face_head`:
    - exactly 4 lines;
    - the mouth and the muzzle fold open, each covering ≥ 90% of its floor with ≥ 90% of points
      on the floor;
    - both eyelids closed: first point equals last, ≥ 95% distinct, ≥ 90% coverage;
    - nostrils absent; `wide_nostrils` also gives no nostril line.
    - On `beak`: the hard assertion is that no open line covers less than 85% of a closed truth
      crease (no half-rings). The beak ring's expected result is measured in D7b and then fixed
      in the test.
    - On zoo `chibi`, `chibi+ai`, `relief_scar+ai` and `humanoid_raised_arm+ai`: 0 lines.
13. **Auto lines change nothing (gate).** With auto lines found and the gate closed, the QR input
    and carve's input are byte-identical to a run without lines.
14. **Creases, clicks.** Clicks 0.6 w off give ≥ 80% of points on the floor and ≥ 90% round the
    corners, deterministically. A plain shortest path is the control (< 50%). w is measured from
    the band, not a constant.
15. **Encoding (D7c).** The proxy has `sharp_edge` only on guide edges and no `custom_normal`.
    The original's and the low's fingerprints are unchanged.
16. **Turn density.** A drawn line with ρ = 3 L0 gives f near the turn ≥ L0/sqrt(8ρ·tol), or the
    R cap. An auto line in "show" gives no change.
17. **Panel.**
    - Draw writes nothing (no ID writes; the Done job starts from the watcher).
    - In VERTEX_PAINT the Show row is disabled and `do_retopo_map_show` refuses. The active
      colour attribute is unchanged by every paint action.
    - Bytes changed in `Forge_Show` give the "painted on the map view" row, and the layer is
      rebuilt.
    - Presets work in VERTEX_PAINT.
    - Each line has its own Remove.
    - L14: `paint_setup` works on 5.3.
18. **Staleness.** Changing `Forge_Paint` bytes after Done (a simulated Ctrl+Z) changes the key.
    Show recomputes, and Run's QR input reflects the current paint whatever the stored field
    says.
19. **Export hygiene (L16).** After a normal run and after the QR-failure fallback, lows and the
    FBX carry no `Forge_*`/`forge_*`/`QR_Density` attribute.
20. **CSR.** Same neighbours and lengths as a Python adjacency on a small mesh. Labels and
    Dijkstra results are identical to the list version.

**Zoo gate.** `zoo_baseline` fast mode with `remesh_by_field`:

- unpainted bodies give identical results before and after D2 (their input is byte-identical);
- `painted(...)` variants show quads moving into the spot and the rest coarsening by the
  predicted share;
- Step 4 problem points do not rise on any body.

---

## 7. Work packages (order and size; S = up to 1 agent-day, M = 2-3, L = 4-5)

| ID | Title | Size | Depends on |
|---|---|---|---|
| D0 | Record only: one `_qr_settings` returning today's values for every call; settings, per-pass timing and the pre-fit snapshot hook in the report; `sysinfo` core count | S | – |
| D1 | Paint layer `Forge_Paint`, presets, palette, `Done painting` plus `_paint_watch` timer, mesh-flag mirror save and restore, Show on `Forge_Show` and disabled in paint, migration with strength estimate, Detail focus fix, `prepare_maps` as a yielding generator, `paint_setup` 5.3 fix, export hygiene (L4, L7, L8, L10, L13, L14, L16) | M | – |
| D1b | `fake_qr.remesh_by_field`; `zoo_baseline` uses it; the "unpainted = today" byte test | S | – |
| D2 | `make_field`: compose, mirror about x0, areas, cap (own-size ring, no-ring fallback), seeded grading, L0 fixed point, staleness key, QR input written in `_qr_one` (touched corners only, nearest-fill for new vertices); `density.csr` | M | D1, D1b |
| D3 | Cost rows per area and plan part (humanoid names only for bipeds) | S | D2 |
| D4 | Asked vs got and carve's share on the raw snapshot; "Show Quad Remesher's result"; rows; jsonl | M | D0, D2 |
| D5 | Shape-check refinement through the field, geodesic footprint, keep-the-better with tolerances (L5, L6) | M | D2, D4 |
| D6 | QR probe on the PC: P0 colour code, 13 runs on multi-band bodies, noise; Forge reads the file | M (+ about 10 min of the director's PC) | D0; can start in parallel with D1 |
| D7a | `creases.py`: valley depth, classification (closed, open, pit), open and closed tracing, measured w, storage, display, per-line Remove, Use this line, Draw a line (with the fix kit's finder), mirror about x0. Auto lines show only. | M | D2 (`csr`) |
| D7b | `face_head` fixtures (lids, nostrils, muzzle fold, beak, wide nostrils) and tests 12-14 | S | D7a |
| D7c | Behind D6 and D7b: encoding on the proxy, guide follow on the raw snapshot, fallback; turn factor for accepted and drawn lines | M | D6, D7a, D7b, D2 |
| D8 | Fix-kit integration: "Also ask for this in the next full run" tick box, `density.footprint`, Follow crease storing its line, the face kit's ramp as a field source | S | D2, fix kit F2/F4/F5 |
| D9 | Bake on GPU devices only, plus a timing trial on the PC | S | – |
| D10 | (after D0 timings) Geometry Nodes queries for shape_loss, conform and carve probes | M | D0 |
| D11 | (optional) QR input reduction trial on the PC | S | D6 |
| D12 | Behind D6: per-kind settings from the probe (props' autodetect, adaptive_size); mapped pieces with a root-normalised budget (Σ a·(f/f_root)² / edge_root², field normalised to 1 at the plug, nearest-fill for plug and lid vertices) and a tail-weld regression in `test_appendages` | M | D6, D2 |
| D13 | Behind D6's hard-vs-graded trial: whole-field grading, only if it helps | S | D6, D2 |

**Order:**

1. **D0, D1b and D1 in parallel.** D6 starts right after D0, because it needs the director's PC.
2. **D2, then D3 and D4, then D5.**
3. **D7a after D2, then D7b.** D7c, D12 and D13 only after D6's answer.
4. **D8** once the fix kit's F2/F4/F5 exist. **D9** any time.
5. **D10 and D11** only after measured timings.

---

## 8. Risks

1. **QR's real response is unknown here.** Edge factor vs density, graded vs hard borders, and the
   effect of guides are reasoned or taken from one earlier bull measurement. D6 measures them.
   Until then no QR setting changes and nothing changes for unpainted bodies (test 2). The
   director's paint becomes bounded, softened at its border and measured.
2. **Gradation near paint costs quads.** The ring takes budget (R5: ×1.001 on the white edge for
   a lip-size spot; E1: a 0.8% ring for a thin band). If QR grades by itself anyway, the
   gradation is cost without gain. D6's trial decides, and the cost rows show it.
3. **The verdict thresholds (0.75, R, g, tolerances) are defaults.** They are labelled as such
   in the code, recorded with every run in the jsonl log, and replaced by the probe's numbers.
4. **Auto lines on real Tripo faces.**
   - R1 is a synthetic face. Fur strokes, scales and stitching on real meshes may make more band
     pieces.
   - Mitigations:
     - classification (closed, open, pit);
     - the length rule on the traced line;
     - the face kit's marks take precedence on the head;
     - lines are shown only until the gate;
     - a WARN and no use beyond "show" if more than 6 lines are found on a face.
   - The beak border's expected result is not yet measured (D7b).
5. **Guides may split QR's result into patches or add poles at line ends.** They are encoded only
   after the probe, verified on the raw snapshot, and the guide-free result is kept when worse.
6. **Paint speed on a 5M-vertex original.** This is Blender's Vertex Paint, as today. The POINT
   byte layer is the lightest option, and the fix kit's tick box avoids painting the original at
   all.
7. **Brush assets in 5.x.** `vertex_paint.brush` is None until the mode has been entered once, and
   `use_unified_color` is deprecated for 6.0. Forge sets the unified colour, the palette and the
   brush colour when a brush exists. Tests cover 5.3.
8. **The mode watcher.** Timers do not run in background tests, so the watcher's logic is a plain
   function the tests call. A crash mid-paint leaves `use_mesh_mirror_x` on, so `load_post` and
   Run both restore it from `forge_prev_mirror_x`.
9. **Migration.** The strength estimate can be wrong on a body painted almost everywhere. The
   migration row says what was converted, and Erase all paint undoes it.
10. **Time and memory.**
    - The field and its passes are bounded by the paint's neighbourhood (R5: < 0.01 s).
    - CSR costs about 1 s and 280 MB at 5M vertices.
    - The paint hash reads about 80 MB.
    - Auto lines take about 3 s at 655k, roughly linear in vertices for the valley depth.
    - All of it runs as yielding jobs with Stop.

---

## 9. Answers for the director's other points (pointers, not this design's scope)

- "Manual and auto fix for selected faces, lines or vertices" is the fix kit
  (`DESIGN_fix_tools.md`). This design shares its selection mapping and adds the tick box (2.7).
- "Cut the mouth open, add teeth, tongue, eyes with eyelids" is the face kit
  (`DESIGN_face_kit.md`). This design stores its lines and turns its ramp into a capped, graded
  field source (3.7).
- "The default UV looks good": nothing here touches Step 5.
- "Use the RTX 4080 Super only if possible": section 4.

---

## 10. Changes after critique

**High**

| Critique point | Change | Where |
|---|---|---|
| Asked vs got and guide follow measured after carve (C10: carve alone reads 4.08x) | Measured on a pre-fit snapshot of QR's raw result, with the source tree built earlier at the same cost. The snapshot is kept until Approve, with a "Show Quad Remesher's result" toggle. Carve's share is reported separately. The probe uses the same pre-fit measure. | 2.5, 3.6, 5, test 8 |
| Paint symmetry flag wrong in 5.3; mirroring about x = 0 instead of x0 | Forge mirrors paint and guides about the measured x0 in `make_field` (R4: overlap 0.75 vs the brush's 0.07). The brush uses `ob.use_mesh_mirror_x` only when |x0| ≤ 0.1·L_face; it is saved and restored; lows get `use_mirror_x = False` (R4a: `copy()` carries the flag). Test 6 uses an offset body. | 2.2, 2.3 step 2, test 6 |
| Whole-field grading changes unpainted bodies (C6: 12-34%) | Grading is seeded only from painted vertices (and later accepted lines and face-kit ramps). The automatic map is untouched, and QR's input is byte-identical for unpainted bodies by construction: untouched corners are copied (R4b exact). R5: 0.12% of the chibi changes, all in the ring. Whole-field grading is D13, behind the probe. | 2.1, 2.3 step 5, test 2 |
| Auto lines turn closed creases into half-lines; pits become lines; `2·Lf` vs `Lf` | Components are classified before tracing: closed (hole by area, ≥ 0.5 L_face radius), open (traced length ≥ 2 L_face, line-like) or pit (rejected). Closed loops are traced with two paths. R1: mouth and muzzle open, both eyelids closed loops, nostrils rejected, 97-100% on the floor. Auto lines are shown only until D6 and the face fixtures pass. `face_head` with beak and wide-nostril variants added. | 3.3, D7a/D7b, tests 12-13 |
| "More / Fewer / Crease here" duplicate the fix kit with a global effect | Removed. One set of buttons, the fix kit's, local. This design adds a "also ask for this in the next full run" tick box that only records paint, with a row about full runs. Follow crease stores its line in `forge_guides`. | 2.7, D8 |

**Medium**

| Critique point | Change | Where |
|---|---|---|
| The zoo gate and fake QR ignore the map | `fake_qr.remesh_by_field`, proportional by construction (R2b: 2.00 for f = 2, total kept). The Decimate vertex-group idea was measured and rejected (R2). The zoo gate gets painted variants. | 6.1, D1b |
| Mapped pieces break the root-size match; new vertices get 0 | Pieces stay as today until D12 (probe plus tail-weld regression). D12's budget is Σ a·(f/f_root)²/edge_root² with the field normalised at the plug. Every new vertex is filled from the nearest original vertex, never 0. A row tells the director tail paint is not used yet. | 2.3 step 7, 2.8, D12 |
| Staleness; Done detected in draw | A staleness key (paint bytes, target, strength, plan, guides, x0, R, g, version). QR's input is always computed inside `_qr_one` for the real target. Show and cost recompute when stale. A `bpy.app.timers` watcher catches leaving the mode. L0 is iterated to a fixed point (R5: 1 pass). | 2.1, 2.2, 2.3 step 6, test 18 |
| Two layers, two colour codes, Show while painting | Show is disabled in Vertex Paint and shows a display layer, `Forge_Show`, in Forge's scale. The active attribute is never changed while painting. QR_Density is never shown. | 2.1, 2.2, test 17 |
| Diagnosis stated as fact | Split into facts (1.1) and hypothesis H1 (1.2). "36x too steep" and "g = 0.3 is what QR grades" withdrawn. The director is told plainly that the streaks are Forge's crease cutting, handled by the dent gate. | 0, 1 |
| Props' autodetect switched in D0 without evidence; L1/L11 misread | D0 is record-only and changes no value. Props, pieces and rescue keep today's regime until D12. L1 and L11 rewritten (the comment gives the organic reason; the `retopo.run` comment guards `_fuse` only). | 1.3, 3.2, D0, D12 |
| Keep-the-better without tolerances; guides branch before encoding | Per-metric tolerances (lost_ratio 1.05x + 0.0002, crease_kept −1 pp, open edges not more, dent ≤ 1.1x once it exists), replaced by 2x the probe's measured run-to-run spread. The guides branch only with encoded guides. | 2.6, 5 |
| Humanoid region names on every body | Rows per painted area and per plan part (tail, horn, ear, wing). Humanoid names only when `asset_kind == "biped"`. | 2.4, test 7 |
| Speed and memory: adjacency and one-tick jobs | numpy CSR (R1: 0.13 s and 37 MB at 655k, against 2.2 s and +651 MB). BFS and Dijkstra on CSR, bounded. `prepare_maps`, `make_field` and lines are yielding generators. | 2.2, 2.3a, 3.3, 8 |

**Low**

| Critique point | Change |
|---|---|
| Cap edge cases | The ring is defined by the area's own automatic size; with no ring, the cap is against the part's median; a "painting everything changes nothing" row. |
| Forge layers reaching the export | L16: strip all `Forge_*`/`forge_*`/`QR_Density` layers and the mirror flag from lows and before export (test 19). |
| Units and modeller words | Ratios in quads, counts in triangles (the budget's unit), no edge lengths. "Capped to N x". One Remove per line. No "edge loop" or "3D cursor" in rows. |
| Groove width w a constant | Measured per line as band area / (2·length), clamped to [e_src, L_face]. |
| Migration misreads the strength; horn paint dropped | 1-D strength estimate first; horn paint kept by `_replan_horns`' existing test. |
| Probe size understated; `painted_quad_density` unused | Multi-band bodies, 13 runs, about 10 minutes, plus P0: reading the bridge's colour code and brush colour with no runs. |
| GPU wording; cores unchecked | "No practical GPU path" (`gpu.compute` exists); `sysinfo` reports the core count before any promise. |

**Rejected or changed from the critique's suggestion, with reasons**

- **A display layer of auto × paint to paint on** (one suggestion for the two-layer trap). Painting
  on a composed layer and dividing by the automatic map afterwards mixes paint and map again (L8)
  and breaks when the map is remade. Instead, the director paints a clean request layer, and Show
  (after Done) shows the composed result in the same scale.
- **"Copy the kept side's paint across x0" only when one side is painted.** Combining both sides,
  with the stronger request winning, covers that case and also the case where the director paints
  both sides slightly differently. Paint on the "replaced" side is therefore never lost.
- **One unit for everything.** Ratios are in quads, as suggested. Absolute counts stay in
  triangles, because the budget field and the game engines count triangles, and quads there would
  make the director convert.
- **msgbus for the mode change.** A one-shot-per-tick timer was chosen. msgbus notifications for
  `Object.mode` depend on the event loop and cannot be tested in background Blender, while the
  timer's function can be called directly.

---

## Appendix: experiments

Folders: `fixkit/exp_density` (E*, R*) and `fixkit/exp_crit_density` (C*, the critique's). Run
with the test bpy Python: `python <script> [args]`.

- `e1_grade.py <sub>`: the size field, cap and gradation on an icosphere with a thin band.
  - Raw growth per unit distance: 1.3 / 5.4 / 10.7 at 41k / 655k / 2.6M vertices (a resolution
    artefact). After grading: 0.30.
  - Grade time 0.4-0.6 s at 655k and 4.7-7.1 s at 2.6M, for the whole field (now only near
    paint).
- `e2_api.py`, `e2b.py`, `e2c_normals.py`: Blender 5.3 facts.
  - `tool_settings.unified_paint_settings` is gone; the per-mode one works.
  - `faces.new` corners get white, and `bmesh.ops.symmetrize` copies the kept side's colours.
  - A `sharp_edge` attribute splits `corner_normals`, and custom normals live in `custom_normal`.
- `e3_crease.py 9`: clicks 0.6 w off the floor. Plain path: 29% on the floor, 0% round the
  corners. Valley path: 81% / 93%.
- `e3c_trace.py 9`: the first version's automatic line on a plain groove (97.6% on the floor). On
  a real face it fails (C4).
- `e4_false.py`: no false lines on zoo bodies after the strict region.
- `e5_cpu.py`: 200k nearest-surface queries. Python 5.9 s; Geometry Nodes 1.89 s on 4 cores,
  identical.
- **`r1_face_lines.py <sub> [nostril_radius]`**: CSR adjacency, classification and open/closed
  tracing on a face with a mouth, eyelid rings, nostrils and a muzzle fold.
  - At sub 9 (655k vertices): CSR 0.13 s and 37 MB. Mouth and muzzle open, 100% covered and
    97-98% on the floor. Eyelids closed loops, 100% / 98%. Nostrils rejected (short).
  - With radius 0.07: one nostril rejected as a pit (aspect 0.98), the other as short.
  - At sub 8 (164k): the same classes, 87-100% coverage.
  - The first try, with a perimeter-only hole test, called the mouth closed: hence the area rule.
- **`r2_fakeqr.py 6`**: Decimate with a vertex group is not proportional (weights 0.95 to 0.2
  give 3.2x to 7.6x). Weight 0 never collapses (19,036 faces against a 1,024 target). Rejected.
- **`r2b_fakeqr.py 6`**: the proportional stand-in. f = 2 gives 2.00 (1,996 of 2,000 triangles);
  f = 4 gives 3.88 (1,848); f = 1 or 1.41 gives no change. Deterministic, 0.06 s.
- **`r4_mirror_bytes.py`**:
  - `copy()` carries `use_mirror_x`.
  - A byte copy through `color_srgb` is exact.
  - float32 re-encoding of the automatic map changed 0 of 983,040 channels (kept as a copy anyway,
    so identity holds by construction).
  - Twin across x0 = 1.5% of the size: overlap 0.75 for Forge, 0.07 for the brush's mirror.
- **`r5_seeded_grade.py 0.004`**: the zoo chibi (138k vertices), today's map, 30k budget, a
  lip-size "More" spot.
  - Seeded grading: 0.12% of the surface outside the spot changes by more than 5% (out to 3 local
    quads), against the critique's 11.6% for whole-field grading at the same resolution.
  - White edge ×1.001, 1 fixed-point pass, under 0.01 s.
- The critique's checks:
  - `c2_sym.py`, `c3_objmirror.py`: the 5.3 paint symmetry flags;
  - `c4_face.py`: the old tracer on a face, 5 lines with half-rings;
  - `c6_grade_auto.py`: whole-field grading on an unpainted chibi;
  - `c7_nbr.py`: Python adjacency 2.2 s and +651 MB at 655k;
  - `c8_misc.py`: new vertices read 0; `symmetrize` carries POINT floats;
  - `c10_carve_got.py`: carve alone reads 4.08x.
