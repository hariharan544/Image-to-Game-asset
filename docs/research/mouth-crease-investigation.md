# Mouth crease loss: investigation (Fable diagnosis, research, second opinion)

## Diagnosis

DIAGNOSIS: right-side mouth groove washed out in Step 4 retopology

I read the code but could not run Blender here (no bpy), so nothing below is measured. The millimetre figures assume a bounding-box diagonal of about 4 m and a head area of about 4 m²; script V1 at the end prints the real ones.

Files read:
- /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/retopo.py (`_qr_part`, `_run_qr`)
- /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/density.py (`detail_score`, `write_qr_density`, `boost`, `shape_loss`, `region_labels`, `conform`)
- /home/user/Image-to-Game-asset/blender_addon/forge_send/steps.py (`prepare_retopo`, `ensure_detail_maps`, `run_retopo`)
- /home/user/Image-to-Game-asset/tests/test_retopo_shape.py

## Conclusion

The groove is narrower than one quad, Quad Remesher is given nothing that tells it where the groove runs, and the final run is unmirrored, so each side gets independent topology. The left side happened to get an edge loop along the groove bottom; the right did not. Nothing downstream can notice or repair that: the shape check cannot see a 5-10 mm groove, and the conform relax makes a misaligned groove worse.

More density tweaks will not fix this reliably. The fix that does not depend on Quad Remesher's edge flow is an error-driven local refinement after the fit (change A).

## Causes, ranked

### 1. Groove is below quad size, with no flow guidance and no mirror (high confidence)

- **Quad size:** 22,928 tris is about 11,500 quads, roughly 5,700 on the head, which gives a mean head edge of about 25 mm.
- **Density ceiling:** `qr_density` at strength 0.8 gives at most 2^1.4 = 2.64x, times the head factor 1.5^0.8 = 1.38, clipped to 4x. After the sqrt that is edges at best 2x shorter, about 13 mm.
- **What the groove needs:** a 10-20 mm wide V-groove needs three loops across it (rim, bottom, rim), so about 5-8 mm spacing across the groove, and the loops must run along it.
- **No direction signal:** `_qr_part` sets `autodetect_hard_edges = False`, `use_normals = False`, `use_materials = False`. The colour map only scales quad size; it does not steer edge direction.
- **Independent sides:** `_run_qr` sets `obj["forge_symmetry_x"] = False` and reruns unmirrored as soon as the mirrored run loses the curved tail (`lost_ratio >= max_lost`). For this bull that always happens.
- **Fits the history:** a loop along the bottom keeps the groove (left); diagonal crossing gives the earlier zigzag; vertices straddling it give the smooth cheek (right).
- **Cost is not the issue:** about 1.2 m of groove at 4 strips of 30 mm-long quads is roughly 300-400 triangles. It is an alignment problem, not a budget problem.

### 2. The shape check cannot see the groove (certain from the code, given the assumed size)

- **Tolerance too coarse:** `shape_loss` uses `tol_rel = 0.008` of the bounding-box diagonal, about 32 mm, and 0.35x on the face, about 11 mm. A 5-10 mm groove bridged by a flat quad never exceeds that.
- **Area threshold dilutes it:** `face_max_lost = 0.004` needs 0.4% of all head samples lost; one side's groove is around that share or less.
- **Retry gets consumed:** `run_retopo` passes `shape_retries: 1`, and face refinement only runs when `lost_ratio < max_lost`. If the tail still counts as lost after the unmirrored run, the single retry goes to the "shape lost" branch.
- **Conform skipped on that branch:** `if face_only and args.get("conform", True)` means the "shape lost" rerun is never fitted, so the final mesh there is raw Quad Remesher output plus rescue.
- **Test does not cover it:** `test_flattened_face_detail_is_refined_not_rebuilt` uses a pocket of 0.58% of size with `conform: False`. It passes while the real case, about 0.2% deep, is invisible.
- **Which branch ran:** the method string in the Step 4 report tells you: `quadremesher(no-mirror)`, `(shape-fixed)`, `(face-refined)` or `(rescued)`.

### 3. Conform relax pulls vertices out of narrow grooves (likely, medium confidence)

- **Mechanism:** `conform` first drops a vertex over the groove onto the groove floor, which is good. Each of the 2 relax rounds then moves it `0.5 * delta` tangentially towards its neighbours' average and reprojects.
- **When it hurts:** where a loop follows the groove the neighbours are symmetric and the vertex stays. Where flow crosses the groove, the neighbours sit on one cheek and the vertex slides several millimetres onto the wall or rim.
- **Fits the history:** it would turn the earlier zigzag into the current smooth cheek, and relax arrived with commit a3acb5a.
- **Not at fault:** the 4% projection limit (about 15 cm, generous) and the nearest-point fallback (only used when both rays miss).

### 4. Density at the groove is too narrow to act, and thin parts take more than intended (medium-low)

- **Band too thin:** `_detail_one` spreads the score by only 4-8 smoothing passes on a mesh with about 2.6 mm edges, so the red band is 10-20 mm wide, under one target quad. Quad Remesher's size field cannot change within a sub-quad band, so the effective boost at the groove is far below 4x.
- **`boost` is 16x, not 4x:** it paints pure red `(1,0,0)`. With the sqrt convention, where colour is an edge-length factor, pure red means edges 4x shorter, which is 16x density. The docstring says "4x denser quads". Tail and ears (`ensure_detail_maps`, rings=2) therefore take 16x, and with `adapt_quad_count = False` that comes out of the face.
- **Same narrowness on the retry:** the face-refine boost band is about 6+3 rings, roughly 25 mm, one quad wide.

### 5. Source or labelling asymmetry (lower, cheap to rule out)

- **Source may differ:** `asymmetry()` uses `tol_rel = 0.006`, about 24 mm, so "3.9% asymmetric" says nothing about a 5-10 mm groove. The right groove may be shallower in the Tripo mesh, and `detail_score`'s 50th-98th percentile normalisation would then score it lower.
- **Region labels may differ:** `region_labels` calls a vertex head only if `z > neck_z` and `|x| < sh_x`. On a wide, low-hanging muzzle, or a slightly turned head, one mouth corner can fall into "body" (weight 0.7, non-strict) or "arms" (0.9).

### Ruled out

- **Sampling stride:** about 2.45M vertices over 300k samples is a stride of 8, and hits are dilated back.

## Code changes, in order of value

### A. Error-driven local refinement after conform (the real fix)

New function `density.carve(low_me, src_me, region_mask, tol_abs)`, called after every final `conform` in `_run_qr`.

1. For every edge of the new mesh in the head, ray-cast from its midpoint along ± the interpolated normal to the original.
2. If the gap exceeds about 0.08% of size (about 3 mm), mark the edge.
3. Run `bmesh.ops.subdivide_edges(bm, edges=marked, cuts=1, quad_corner_type='STRAIGHT_CUT')` and triangulate any n-gons left.
4. Project the new vertices onto the original with the existing `project`, and do not relax them.
5. Run two passes; the second catches the rims.
6. Cap added triangles at about 5% of the budget and lower the Quad Remesher target by that amount.

Why it works regardless of flow: every edge that bridges the groove gets a vertex on the groove floor, and the cut pattern joins neighbouring midpoints, so the valley becomes a continuous edge chain. It also works on the mouth-corner pocket and lid creases, mirrored or not.

The catch is a strip of triangles along the mouth instead of pure quads, and a groove slightly wider than the original. The normal bake sharpens it.

### B. Make the check see grooves

- **steps.py `ensure_detail_maps`:** compute `score = dens.detail_score(me)` once. Write `strict = np.where(lab == 1, 0.35, 1.0); strict[(lab == 1) & (score > 0.5)] = 0.10`, about 3 mm.
- **`shape_loss`:** return `face_lost_left` and `face_lost_right` (split by sign of x), using detailed face samples as the denominator, and show both in the panel.
- **`_run_qr`:** let the face branch run even when `lost_ratio >= max_lost`, and always conform after a rerun unless a rescue follows.
- **New test:** add a case to tests/test_retopo_shape.py with a groove 0.2% of size deep and conform on.

### C. Feature-aware relax in `conform`

After computing `delta`, freeze vertices that sit in a concavity:

```python
depth = ((co - avg) * nrm).sum(axis=1)
el = np.linalg.norm(co[a] - co[b], axis=1).mean()
delta[depth < -0.1 * el] = 0.0
```

Alternatively set `relax=0` for strict-region vertices.

### D. Fix the density scale

- **`boost`:** paint `qr_colours(np.sqrt(4.0))`, i.e. `(1, 0.667, 0.667)`, for appendages. Keep pure red only for the face-refine pass.
- **Band width:** dilate face boosts to at least 3 target edge lengths. Compute rings from the target edge length divided by the source edge length, not a fixed 3.

### E. Optional: give Quad Remesher real guidance

- Extract the concave valley line on the head (signed version of `_detail_one`: the sign of `(n_b - n_a)·(p_b - p_a)`).
- Mark it either as sharp edges with `s.use_normals = True`, or as a material border at the valley bottom with `s.use_materials = True`.
- I am going from memory of Quad Remesher's documentation for those two options; test on the PC before relying on them. Change A is still needed as the safety net.

### F. Optional: keep mirroring

- Detach the tail up front (the `appendages` module already finds it) and remesh it as a rescue piece.
- The body can then stay mirrored and both mouth sides get identical topology.
- That removes the left/right lottery, but not the alignment issue on its own.

## Cheap verification on the director's PC

**V1. One script, no rerun (covers causes 1, 2 and 5).** Paste into Blender's Python console after Step 4:

```python
import bpy, numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
low = max((o for o in bpy.data.objects if o.get("forge_role") == "low"), key=lambda o: len(o.data.polygons))
hi = next(o for o in bpy.data.objects if o.get("forge_role") == "high" and o.get("forge_part") == low.get("forge_part"))
me, lm = hi.data, low.data
n = len(me.vertices); co = np.empty(n*3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
size = float(np.linalg.norm(co.max(0) - co.min(0)))
st = np.empty(n, np.float32); me.attributes["forge_strict"].data.foreach_get("value", st)
tree = BVHTree.FromPolygons([v.co.copy() for v in lm.vertices], [tuple(p.vertices) for p in lm.polygons])
idx = np.flatnonzero(st < 0.999)[::4]
d = np.array([tree.find_nearest(Vector(co[i]))[3] for i in idx]) * 1000
el = [(lm.vertices[e.vertices[0]].co - lm.vertices[e.vertices[1]].co).length for e in lm.edges]
print("size m", round(size, 3), "| body tol mm", round(8*size, 1), "| face tol mm", round(2.8*size, 1), "| median new edge mm", round(1000*float(np.median(el)), 1))
for name, sel in (("x>0", co[idx, 0] > 0), ("x<0", co[idx, 0] < 0)):
    dd = d[sel]
    print(name, "head samples", int(sel.sum()), "| >3mm", int((dd > 3).sum()), "| >5mm", int((dd > 5).sum()), "| >face tol", int((dd > 2.8*size).sum()), "| max mm", round(float(dd.max()), 1))
```

What confirms what:
- Causes 1 and 2: the washed-out side shows hundreds of samples over 3-5 mm but about zero over the face tolerance, and the median edge is well above the groove width.
- Cause 5: very unequal "head samples" between the two sides means the head labelling is lopsided.

**V2. Cause 3.** Change the default in `conform` to `relax: int = 0` and rerun Step 4 once. If the right groove comes back, even as a zigzag, relax is the eraser.

**V3. Causes 4 and 5.** Press "Show detail map" and compare the two mouth lines. Equal red on both sides means the source and map are fine, pointing back to causes 1-3. A paler right side means the source groove is shallower or mislabelled. Also check whether the tail and ears are pure red.

**V4. Change A.** After implementing it, rerun V1. The ">3mm" counts should drop to near zero on both sides for a few hundred extra triangles.

**V5. Change E.** Hand-paint a second material on the lower lip side of the right groove on the original, set `use_materials = True`, and run once. A loop on the groove means the guidance works and is worth automating.

## Research

RESEARCH REPORT: keeping a narrow mouth groove through automatic retopology

Reliability note: findings come from web-search summaries plus two GitHub READMEs I could fetch. exoside.com, blenderartists.org and blendernation.com are outside this session's allowed network domains, so I could not read the official Quad Remesher (QR) manual or the forum threads in full. Nothing here was tested in Blender 5.3; "headless" verdicts are inferences from how each tool is exposed.

## 1. Why this keeps happening (my reading, supported by the sources)

- **QR has no guide-curve tool.** The unofficial FAQ says there is no equivalent of ZBrush's ZRemesher Guide brush. Density painting only changes quad size; it does not steer where edge loops run.
- **Density painting is known not to rescue small facial features.** In the Blender Artists QR thread, users report eye and mouth corners getting low priority, and that painting density around the eye "didn't help much"; they concluded that guides were what was missing.
- **A groove needs an edge along its floor.** A groove narrower than about two quad widths only survives if an edge loop runs along the valley bottom. If quads cross it diagonally (the earlier zigzag) or bridge it rim to rim (the washout), no amount of conform or relax will bring it back.
- **Left versus right is chance.** In an unmirrored run the flow field happened to align with the groove on the left and not on the right.
- **The shape check may be blind to it (hypothesis).** A groove shallower than the tolerance (0.8% of size, about 0.28% in strict areas) passes a distance test. Worth checking against the actual groove depth.

## 2. Options surveyed

| Approach | Keeps a narrow crease? | Headless in 5.3 | Cost |
|---|---|---|---|
| QR `use_materials` (material border as guide) | Yes: the unofficial FAQ says QR places edge loops on material boundaries (equivalent to ZBrush Keep Groups). One forum user found it worked where hard-edge detection and normal splitting did not. | Yes, already a property in `_run_qr` (currently False) | None, QR already owned |
| QR `use_normals` (sharp edges / split normals) | Partly: documented workaround for hard edges, but users call it inconsistent | Yes, property exists (currently False) | None |
| QR `autodetect_hard_edges` | No for organic grooves; angle-based and most often reported unreliable | Yes | None |
| QR density paint | No on its own (see above) | Already in use | None |
| QR sculpt face sets as guides | Unconfirmed; forum posts say it was promised for a future release | Unknown | None |
| QRemeshify (QuadWild + Bi-MDF) | Yes in principle: README says edges marked seam or sharp, material borders and face-set borders guide the flow; the QuadWild paper guarantees feature lines are reproduced by construction. A 2026 paper notes wavy flow on organic features such as a nose. | Unverified. Blender 4.2+, Windows tested, Linux/macOS "still testing"; operator name and quad-count control not documented. Input should be under 100k triangles. | Free, GPL-3 |
| quadwild-bimdf command-line binaries | Same engine; accepts a `.sharp` feature file and a dihedral threshold | Yes via subprocess; prebuilt for Linux, Windows, macOS | Free, GPL-3 |
| QuadriFlow (built into Blender) | No: only "Preserve Sharp" (angle-based, has a bug report for holes); no way to guide the field | Yes | Free |
| Instant Meshes | No: batch mode takes only a crease angle (`-c`); orientation brushes are GUI-only | Yes via subprocess | Free |
| ZRemesher with guide curves | Yes, the proven manual method (closed rings around mouth and eyes) | No, needs ZBrush and hand-drawn curves | ZBrush licence |
| QuadGuide (new, Oct 2026) | Built around drawn edge-loop guides | Unknown | Paid |
| Quadify Ultra, NexTopo, QuadForge, Quadmend | Vendor claims of feature-edge preservation, all angle-based and unverified; Quadify Ultra wraps the same QuadWild engine | Scripting undocumented | Quadify Ultra about $150 |
| R3DS Wrap / template fitting | Best possible topology if a bull template exists | Has console and Python scripting, but needs a matching template and landmarks per creature | Commercial; price not found |
| RetopoFlow | Manual tool | No, interactive | Paid |
| Crease-line extraction (ridge/valley lines) | This is the missing input, not a remesher: Yoshizawa et al. crest lines (C++ available), Hildebrandt et al. 2005, a libigl-based project | Yes with numpy or libigl; `density.py` already computes two-scale curvature | Free, developer time |
| Post-snap of vertices to feature lines | Standard late fix (the QuadWild paper describes it as what most methods do; the PRS paper aligns edges to a curve with vertex moves plus edge flips) | Yes, pure bmesh | Free, developer time |

## 3. Recommendations

**A. Give QR a real guide: valley line to material border, with `use_materials=True`.** This is the main fix.
1. On the original mesh (or a decimated proxy), extract the concave valley polyline of the mouth groove and corner pocket from the existing curvature data.
2. Do it once on the combined left and mirrored-right data, so both sides get the same guide even where the right side's signal is weaker.
3. Assign a second material so the border runs along the valley floor, not along the rims. A strip spanning rim to rim would make QR bridge the groove flat. Better still, two thin strips either side of the valley line give three loops: rim, floor, rim.
4. Keep the density paint so the flanking loops stay tight.
5. If material borders prove too weak, add `use_normals=True` with the same edges marked sharp.

Risks: the unofficial FAQ suggests cutting clean loops before assigning materials on messy meshes, so a jagged border on raw Tripo triangles may need smoothing first; the extra loops cost triangles, but there is headroom (22.9k of 30k).

**B. Force left/right consistency.** The asymmetry comes only from the tail. Split the tail off as its own part (or use the existing rescue path) and run head and body with `symmetry_x=True`, then conform each side to its own original. Combined with A, the groove is guided and identical on both sides.

**C. Add a feature-aware post-pass and fix the detector.** This is the safety net and works with any engine.
1. After QR, find the edge path in the new mesh closest to the valley polyline and snap those vertices onto the valley floor, with neighbours snapped to the rims.
2. Pin those vertices during `density.conform`, and make its relax step tangential-only. The current relax plus nearest-point fallback is likely pulling floor vertices up to the rims.
3. Where no edge path follows the line, cut the polyline into the low-poly locally with bmesh edge splits. This leaves a few triangles near the mouth but holds the silhouette.
4. Add a check that `shape_loss` can't miss: compare normals or curvature sign along the valley line, or compare left against mirrored right. Fail the run if the groove is absent.

**Fallback engine:** if A fails in QR, try QRemeshify or the quadwild-bimdf binaries on the head part only, with the valley edges marked sharp. It is the only free engine that treats user-marked lines as hard constraints, but Blender 5.3 support, quad-count control and organic-shape quality are all unverified, and it needs a decimated input.

**Not recommended:** QuadriFlow, Instant Meshes, RetopoFlow and template wrapping, for the reasons in the table.

One thing to check with the director: a Blender Artists post (found via search, not read in full) says QR 1.4.1 is the last download and that the Exoside site has been down. The add-on still works locally as far as I know, but new QR features such as face-set guides should not be counted on.

## Sources
- Unofficial QR FAQ: https://www.blendernation.com/2019/10/18/quad-remesher-auto-retopologizer-for-blender-unofficial-faq/
- QR thread, small features and density: https://blenderartists.org/t/quad-remesher-auto-retopologizer/1170913?page=29 (also ?page=28, ?page=31)
- QR update/status thread: https://blenderartists.org/t/quad-remesher-add-on-update/1647735
- QR 1.3 user doc (not readable from here): https://www.exoside.com/quadremesherdata/QuadRemesher_1.3_UserDoc.pdf
- ZRemesher guides: https://novedge.com/blogs/design-news/zbrush-tip-zremesher-guides-for-predictable-edge-loop-topology ; https://www.zbrushcentral.com/t/zremeshing-eyelids-and-lips/333113 ; https://www.zbrushcentral.com/t/zremesher-guides-issues/320946
- Maxon ZRemesher "Keep Creases" caveat: https://help.maxon.net/c4d/2027/en-us/Content/html/OREMESH-ID_OBJECTPROPERTIES.html
- QRemeshify: https://github.com/ksami/QRemeshify ; https://superhivemarket.com/products/qremeshify
- quadwild-bimdf: https://github.com/cgg-bern/quadwild-bimdf ; QuadWild: https://github.com/nicopietroni/quadwild ; paper: https://vcg.isti.cnr.it/publication/2021/PNACT21
- Papers noting QuadWild behaviour on organic features: https://arxiv.org/pdf/2605.26062 ; https://arxiv.org/pdf/2405.13745
- Blender devtalk on Bi-MDF: https://devtalk.blender.org/t/retopology-min-deviation-flow-in-bi-directed-graphs-for-t-mesh-quantization/30763
- QuadriFlow: https://docs.blender.org/manual/en/dev/modeling/meshes/retopology.html ; https://projects.blender.org/blender/blender/issues/70546 ; https://devtalk.blender.org/t/quadriflow-improvements/10616
- Instant Meshes: https://github.com/wjakob/instant-meshes ; flags: https://opensource.adobe.com/lagrange-docs/cpp/structlagrange_1_1remeshing__im_1_1_remeshing_options.html
- Crest and feature lines: https://www2.riken.jp/brict/Yoshizawa/Research/Crest.html ; https://page.mi.fu-berlin.de/polthier/articles/feature/featureSGP05.pdf ; https://github.com/Bushite/Smooth-Feature-Lines-Extraction
- Feature snapping: https://arxiv.org/html/2311.18494v1 ; https://graphics.rwth-aachen.de/media/papers/resample1.pdf
- QuadGuide: https://blenderartists.org/t/quadguide-quad-remesher-where-you-draw-the-edge-loops/1656365
- Other add-ons: https://superhivemarket.com/products/quadify-ultra ; https://superhivemarket.com/products/quadmend ; https://superhivemarket.com/products/nextopo-auto-quad-remesh-lods--baking-for-blender/docs
- R3DS Wrap console/Python: https://www.russian3dscanner.com/docs/WrapX/wrapConsole.html
- RetopoFlow: https://github.com/CGCookie/retopoflow

Relevant local code: /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/retopo.py (lines 315-337 set the QR options; `use_materials` and `use_normals` are False at 323-324; symmetry at 327) and /home/user/Image-to-Game-asset/blender_scripts/forge_bpy/density.py (detail_score, conform, shape_loss).

## Second opinion

SECOND OPINION: right-side mouth groove washed out in Step 4

Nothing here was run: this session has no `bpy` and no Quad Remesher (QR), so the review is from reading the code and the code sketches are untested. Files read: `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/retopo.py`, `/home/user/Image-to-Game-asset/blender_scripts/forge_bpy/density.py`, `/home/user/Image-to-Game-asset/blender_addon/forge_send/steps.py`, `/home/user/Image-to-Game-asset/tests/test_retopo_shape.py`.

## Verdict

Stop trying to make QR place the loop. Add a local repair pass after the fit that cuts the groove into the new mesh wherever the mesh bridges it, and gate it with a per-side crease number. That is the diagnosis's change A, with four corrections below. The research's main fix (material border as a QR guide) should be a 10-minute manual experiment, not the plan.

The structural fault neither report names: the pipeline's only repair tool is "re-run the whole remesher with a different map". Each re-run re-rolls the topology of the entire head, so fixing one spot can lose another. That is why the tweaks never converge. The repair has to be local and able only to add detail.

## Review of the diagnosis

**Holds up (checked in code):**
- QR gets no direction signal: `_qr_part` sets `use_materials`, `use_normals` and (when painted) `autodetect_hard_edges` to False; the colour map only scales quad size.
- The shape check is too coarse for a narrow groove: `tol_rel` 0.008, times 0.35 on the face, and `face_max_lost` 0.004 is a share of all head samples.
- The "shape lost" re-run is never fitted (`if face_only and args.get("conform", True)`), and nothing is fitted after a rescue.
- `boost` paints pure red, which under the sqrt convention in `write_qr_density` is 16x density, not the 4x in its docstring.
- The detail band width is set in edge hops on the source, so on a 4.9M-triangle mesh it is narrower than one target quad.

**Weak or wrong:**
- **Millimetre figures.** They rest on an assumed 4 m diagonal. The conclusion does not need them: head quads and the groove are the same order of size, so alignment decides the outcome.
- **"Left got lucky."** Plausible but unproven. Two other explanations fit equally: the right groove is shallower in the Tripo source, or the face-refine re-run stole quads (see "missed" below). The Step 4 method string and "Show detail map" separate these.
- **Relax as the eraser (cause 3).** Relax moves a vertex half the tangential offset, twice, then reprojects. It can slide a vertex out of a groove narrower than that slide, but it cannot explain a full washout alone. Cheap to test with `relax=0`.
- **Change A as written misses grooves.** It tests only the edge midpoint. A groove narrower than half an edge can cross at the quarter point and go unseen. It also ignores a groove that ends inside a quad (the mouth-corner pocket).
- **Change A would be undone.** `_finish_part` decimates when the count exceeds budget x 1.05. The bull is at 22.9k of 30k so there is room today, but the code must reserve headroom explicitly.
- **Change B's 0.10 strict factor.** It tightens detection but still triggers a full re-run, which is the re-roll problem again.

## Review of the research

- **Material-border guide.** The evidence is a 2019 unofficial FAQ and forum posts that could not be opened. Automatic extraction of one clean valley polyline on an AI mesh is the hard part and is understated: fur strokes, lids and nostrils all give valley lines, and each false line splits QR's result into patches.
- **"Two thin strips either side."** Material strips narrower than a target quad are likely to give slivers or density spikes. I would not do this.
- **"Make relax tangential-only."** It already is (`delta -= nrm * (delta * nrm).sum(...)`).
- **"Nearest-point fallback pulls floor vertices up."** It is used only when both rays miss, which does not happen over a groove.
- **QRemeshify / quadwild.** Input under 100k triangles, unverified on Blender 5.3, no confirmed quad-count control. Not worth a detour now.
- **Correct and useful:** QR has no guide curves, density painting is known not to rescue small facial features, and post-snapping or cutting to feature lines is the standard late fix.

## What both missed

1. **Re-runs are re-rolls.** The face-refine re-run paints pure red with `adapt_quad_count` off, so the extra quads come out of the rest of the head, possibly the other mouth side.
2. **Face bones are off in the rig** (commit ac345b0). Triangles and poles along the mouth line therefore cost nothing in deformation; the usual objection to a cut-in crease does not apply.
3. **One source BVH per part.** `conform` rebuilds a tree over 4.9M triangles from Python lists on every call; the new pass should share it.
4. **Mirror takes one half.** A mirrored run gives the same topology on both sides, not correct topology; it removes the left/right difference only.
5. **No number for the director.** The panel shows nothing that says "mouth kept, left/right".

## The plan, in order

**Step 0. Read-only checks on the director's PC (15 minutes).**
- Note the Step 4 method string: `(no-mirror)`, `(face-refined)`, `(shape-fixed)` or `(rescued)`.
- "Show detail map": compare red on the two mouth lines. A paler right side means the source or the head labelling differs.
- Run the diagnosis's V1 script (its object lookup by `forge_role == "high"` is unverified; adjust if it finds nothing).

**Step 1. Add `density.carve` (the fix).** Signature: `carve(low_me, src_me, tree, tol_rel=0.0012, passes=2, samples=5, max_add=0.06, min_edge_rel=0.0015) -> {"added": int, "splits": int}`.
1. Work in a `bmesh` of the new mesh. Restrict to the strict region: take the hit face index from the ray, look up `forge_strict` on that source polygon's first vertex, skip if it is 1.0.
2. For each edge longer than `min_edge_rel * size`, sample 5 points along it. At each, ray-cast both ways along the interpolated vertex normal (reach 2% of size) and keep the signed gap.
3. If the largest gap on the edge exceeds `tol_rel * size`, mark the edge with that sample's hit point. Convex cheek curvature gives a sagitta far below this tolerance, so only real creases trigger.
4. Sort marks by gap, truncate to the triangle allowance, then `ne, nv = bmesh.utils.edge_split(e, e.verts[0], t); nv.co = hit`.
5. For every face holding two new, non-adjacent vertices, `bmesh.utils.face_split(f, a, b)`. Joining the crossing points face by face is what turns the valley into a continuous edge chain.
6. For faces whose centre gap exceeds the tolerance with no marked edge (the corner pocket), `bmesh.ops.poke` and set the centre to the hit point.
7. Triangulate any face left with more than four vertices, `normal_update`, and repeat once. The second pass puts vertices on the rims where the walls bulge above the new chords.
8. Never relax or reproject the new vertices afterwards.

**Step 2. Wire it in `_run_qr`.**
- Add `_fit(obj, backup, args, tree)` = `conform` then `carve`, and call it everywhere `conform` is called now.
- Track a `fitted` flag and call `_fit` once more at the end if the last mesh was not fitted (the shape-fixed and rescued branches).
- Reserve room: `target = budget * 0.94 / 2`, so the carve never trips the `_finish_part` decimate.
- Because `carve` runs before `shape_loss`, the face-refine re-run fires only when the carve could not close the gap. That removes most re-rolls.
- Pass `conform_relax` through `args` so `relax=0` can be tried without a code edit.

**Step 3. A per-side crease number.**
- In `shape_loss`, add `fine_lost_left` and `fine_lost_right`: the share of strict-region samples farther than 0.12% of size from the new mesh, split by sign of x.
- Put both in `report[...]["shape"]` and show them in the panel as "face creases kept: left N%, right N%".

**Step 4. Small fixes.**
- `boost`: paint `qr_colours(np.sqrt(4.0))` for appendages; keep pure red for face refinement only.
- Detail band: set smoothing passes from target edge length divided by source edge length, not a fixed count.

**Step 5. Optional, after steps 1-3 are proven.**
- Keep the mirror when the only loss is a thin appendage: go straight to the tail rescue from the mirrored run. Both sides then match. The risk is the rescue seam, so judge it on a real run.
- Manual QR guide experiment (the diagnosis's V5): hand-assign a second material below the right mouth line, `use_materials = True`, one run. Automate only if a loop appears on the groove.

## Test without the real QR

Add `test_narrow_groove_survives_on_both_sides` to `tests/test_retopo_shape.py`, with the same monkeypatched `_qr_part` pattern as the existing tests.

- **Source:** icosphere, subdivisions 7. A smile-shaped groove on the front, on both +X and -X: for `0.15 < |x| < 0.6`, `y < 0`, push vertices inward by `depth * (1 - (d/w)^2)` where `d = |z - z0(|x|)|`, `w = 0.02`, depth 0.3% of the bounding diagonal. Mark `y < 0` strict with `write_strict(..., 0.35)`.
- **Stand-in QR:** replaces the mesh with a coarse quad sphere, edge about `4w`, rotated 25 degrees about the Y axis so its rows cross the groove diagonally at a different phase on each side. It ignores the density colours completely; that is the worst case for QR.
- **Run:** `_run_qr` with `conform` on.
- **Measure:** `kept(side)` = share of source groove-floor vertices (`d < 0.25w`) within 0.1% of size of the final mesh.
- **Assert:**
  - `kept(left) >= 0.9` and `kept(right) >= 0.9`.
  - Triangles at most 1.06 x the stand-in's count; no face with more than four vertices; every edge manifold; `"+decimate"` not in the method.
- **Control in the same test:** with `args["carve"] = False`, `kept` on at least one side is below 0.5. Tune the stand-in until this holds, otherwise the test proves nothing.
- **Second small test:** a groove that ends inside one quad is recovered by the poke path.

The existing `test_flattened_face_detail_is_refined_not_rebuilt` runs with `conform: False`, so it stays valid.

## What cannot be guaranteed

- **QR itself.** No setting makes QR follow a soft organic crease. It has no guide curves, and the material-border route is unverified.
- **Clean quads at the mouth.** The carved line is a strip of triangles and a few poles. With face bones off this does not affect animation; it would matter if facial animation is added later, and then the mouth needs hand-drawn or guided loops.
- **A crisp groove.** At this budget the groove is a V of three edge chains, slightly wider and softer than the original. The normal bake supplies the sharpness.
- **Silhouette.** A mouth line barely changes the outline. The gain shows in close-ups, raking light and the unbaked grey view.
- **First-time tuning.** `tol_rel` will likely need one adjustment on the real bull, and a noisy source could trigger cuts on fur strokes; the 6% cap bounds that.
- **This review.** It is unrun. The first proof is the new test passing in Blender, then the per-side numbers on the bull.

## What the director should expect

After steps 1-3: a visible groove on both sides for roughly a few hundred extra triangles, a panel line reporting left and right crease retention, and fewer full re-runs. If the right side still reads low after that, the cause is the source mesh or the head labelling, and step 0 will already have shown which.
