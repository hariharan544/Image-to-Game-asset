# Face kit: open mouth, mouth bag, teeth, tongue, eyeballs and eyelids (Step 4b)

Design for the lead, revised after the adversarial critique (section 19 lists what changed). It
covers the face kit, which turns Step 4's closed head into one that Auto-Rig Pro's face rig can
use: the mouth opens and the eyes blink and turn. It sits between Step 4 (retopology) and Step 5
(UVs).

Every claim marked (E#) was measured in Blender 5.3 (bpy module) with the scripts in
`fixkit/exp_facekit/` (section 18). E3 is the post-critique experiment (`e3_fixes.py`, run as
`e3_grid.sh`); it re-measures every critique finding and every fix below. Claims about Auto-Rig
Pro cite the probe (`docs/research/arp_3_79_probe.json`, ARP 3.79.17 on the director's PC) or
the 3.77.33 source in the scratchpad (`arp_src/src`). An item marked [probe] must be confirmed on
the director's PC before it is relied on.

The kit reuses two sibling designs and duplicates neither:
- `fixkit/DESIGN_fix_tools.md` (Fix selected): the `Target` lookup on the whole original
  (`BVHTree.FromObject`, cached), `verify` (G1-G7), transactions with `forge_id`, Follow crease,
  the `forge_made` mask, and the reopen rules of its section 10.
- `fixkit/DESIGN_detail_paint.md` (honest detail paint): `creases.auto_lines` (vectorised valley
  lines), `density.make_field` (the one owner of `QR_Density`), asked-vs-got, and the crease
  guides it hands to Quad Remesher.

New code goes into:
- `blender_scripts/forge_bpy/face_marks.py`: finds the mouth and eyes on the original;
- `blender_scripts/forge_bpy/face_kit.py`: builds them on the low, and the manual face tools;
- `blender_scripts/forge_bpy/face_parts.py`: teeth, tongue and eyeball meshes;
- a `face` stage in `blender_addon/forge_send/stages_late.py`, with its steps in `steps.py`;
- small changes in `uv.py` (Step 5), `bake.py` (Step 6), `finalize.py`, `arp_rig.py`,
  `motion_check.py` (sections 8-11).

## 0. In plain words (for the director)

- After you approve Step 4, a new box opens: **Step 4b · Face**. Press **Find the face**.
- Forge marks the mouth line in red and each eye with a ring. If it is sure, you only check
  them. If not, it asks at most three point-and-click questions: the mouth's two corners, the
  middle of one eye, and teeth or no teeth.
- Then **Build the face**. Forge:
  - cuts the mouth open along the lip line;
  - builds the inside of the mouth, hidden in the head;
  - adds upper and lower teeth and a tongue, sized to the mouth;
  - replaces each eye with an eyeball that can turn. It sits a little deeper than the painted
    eye surface (8% of its size), so the lids have room to close over it;
  - makes the skin round each eye into lids that close over the eyeball.
- Nothing is kept unless it passes its checks. The checks are: every new piece is inside the
  head, nothing pokes through the skin, and looking into the open mouth shows the inside, never
  a hole. A piece that fails is left out and one row says why. **Remove the face** puts the head
  back exactly as Step 4 left it.
- **Edit the face** opens hand tools for when Forge gets something wrong: select edges along the
  lips and press **Use as the mouth line**; select the faces of an eye opening and press
  **Use as the eye opening**; move or size the teeth, tongue or an eyeball with Blender's own keys,
  then **Check the face**. Every edit is checked the same way and undone if it fails.
- The face costs about 1,350 triangles of the 30,000 for Unreal (4.5%), more for a long snout
  (it grows with the length of the mouth line). The rows show the exact number.
- A helmet, mask or face with no mouth gets **Skip the face**, and the rig then moves the head as
  one piece, as today.
- In Step 8 the rig opens the jaw and closes the lids. **Check it automatically** also tests that
  the mouth opens without tearing and shows its inside, the teeth stay inside, the lids cover
  the eyes when closed, the brow and cheeks do not move with a blink, and the eyeball never pokes
  through a lid.
- The RTX 4080 Super: the face kit's work is about a second of processor time, so the graphics
  card cannot speed it up. The card does the work where it helps, in Step 6, where the new
  eyeball fronts and the inside of the mouth get their colour.

## 1. What the director asked, and what the screenshots show

- The request: "at last we need to cut the mouth open and add teeth, tongue and eyes with
  eyelids etc." and "add manual and auto fix and edit option for selected face, line or
  vertices". Today `arp_rig.add_extras` turns the face bones off "until the face has a cut mouth
  and separate eyes" (arp_rig.py:856-857). The rig spec offers Jaw opens or Full face only then
  (SPEC_final 5.1, 9.4). This kit unlocks those two modes. The select-and-use tools of 6.10 are
  the face's share of the "manual fix" request; the rest is the sibling Fix selected design.
- The bull (fixkit/89.webp, 90.webp):
  - The mouth is a wide U-shaped smile crease on a cartoon muzzle. The red in the screenshots is
    the director's detail-map paint over it.
  - The eyes are large sculpted bulges, each with a raised lid ring round it.
  - Both are closed surfaces: no cavity, no separate eyeball. The face sits on a neckless head of
    about 4.9 million triangles.
- The mouth corner is where Step 4 left the faceted notch (dent/DIRECTOR_WIREFRAME.md). E3 shows
  the same kind of fault decides whether the mouth can be cut cleanly: a slit that runs along two
  sides of one face (an L-step) makes the inner lip cross the skin (sec. 6.2, E3).

## 2. Where it sits in the step flow

Flow (not panel text):

- **Step 4, before Run:** the row "Face: mouth and 2 eyes found [Show]". The marks come from the
  original.
- **Step 4, Run retopology:** keeps room and density for the face (sec. 5). Then review, Fix
  selected, Approve.
- **Step 4b, Face:** Find the face, then any questions, then Build the face, then the review rows,
  Edit the face if needed, then Approve or Skip.
- **Later steps:** Step 5 UVs (sec. 6.9, with its own work package), Step 6 bake (sec. 8),
  Step 8 rig with face modes and checks (sec. 9-10).

**Why its own step, after Step 4 Approve and before Step 5:**
- The cut changes topology, so it must come before UVs (Step 5) and the bake (Step 6).
- It needs the final low: after the director's own fixes and the Approve.
- It needs its own Approve and Change, so a director who wants no face can skip it without
  touching Step 4.

**Name and number:**
- The stage id is `face`. `stages_late.ORDER` becomes
  `["brief", "assemble", "repair", "retopo", "face", "uv", "bake", "colour", "rig", "export"]`,
  and `TITLES["face"] = ("4b", "Face (mouth, eyes)")`. "4b" keeps every later number as the
  director, the guides and the test sheets know them.
- `draw_late` walks a hard-coded tuple (stages_late.py:1298-1310). It becomes
  `ORDER[ORDER.index("retopo"):]`, so the face box sits between Step 4 and Step 5 and gates
  Step 5 through `prev_ok`.
- `ForgeStageState` (stages_ui.py:74) gets `face: EnumProperty(items=STATUS, default="todo")` and
  `face_rep: StringProperty(default="{}")`.

**Saved projects (migration).** The add-on's existing `load_post` handler (`stages_late._on_load`,
stages_late.py:1591) gets one rule, run once per file (`st.face_rep` empty):
- if `st.uv` is not `todo` (the project went past Step 4 before 1.16): `st.face = "approved"` and
  `face_rep = {"skipped": true, "why": "made before 1.16"}`. Every later box stays as it was, and
  the 4b box shows "Face kit not built (made before 1.16)" with **Build the face**, which reopens
  Step 4b like Change.
- else `face` stays `todo`.
- Test: a .blend saved with Steps 5-9 approved and no `face` property opens with Steps 5-9 still
  approved (sec. 15).

**What Change does (one replay behaviour):**

| Action | Effect |
|---|---|
| Change on Step 4 (`reopen(st, "retopo")`) | Forge first restores the head from `FORGE_facebase_<part>` and removes the kit objects, so Step 4's own tools work on the clean head. `face` and every later step go to todo. The recipe (marks, answers, the director's face edits) stays on the high. After Step 4 is approved again, the 4b box shows **Build the face again** (one click; nothing replays by itself) |
| Fix selected after 4b (sibling sec. 10) | A fix whose patch plus one ring touches no `forge_made` element keeps the face: the made faces stay bit-identical, the whole-kit gate (sec. 7) re-runs, and Step 4b goes to review. A fix near the face goes through the row above (restore, fix, Build the face again) |
| Change on 4b | Steps 5-9 go to todo. The head goes back to the base only on **Remove the face** or **Build the face again** |
| Skip the face | `face = approved`, `face_rep = {"skipped": true, "why": ...}`. Step 8's face row says "Head moves as one (face skipped in Step 4b)" |
| Step 4 re-run while marks exist | as Change on Step 4: the base copy is restored first, the kit is never built on top of an old cut |

**The face marks before Step 4 runs.**
- `plan_parts` (steps.py:317) already measures the original before Run. It now also calls
  `face_marks.find(high, J)` (sec. 4) and shows one row.
- The marks let Step 4 reserve triangles for the kit and feed the face region into the density
  field (sec. 5).
- If Step 4 already ran without marks (the bull today), Step 4b finds them itself and densifies
  only the rim edges it needs (6.4). The budget row says what that costs.

## 3. Principles, as applied here

| Standing rule | How the kit follows it |
|---|---|
| Improve the tool, never fix one model | Detection runs on measured shape: valley lines, sphere fits with normals, shells, colour. A body kind only picks the default answer (beak for a Bird body plan). Tests run on 14 face bodies (sec. 15), including a long jaw, side eyes and an almond eye |
| Any body | Cartoon muzzle, human, long jaw (dog, horse, crocodile), beak, no teeth, closed, sleepy, almond, side eyes, one eye, painted eyes, chibi, helmet, modelled-open mouth, more than two eyes. The face region is the head part, not "faces front", so side eyes and the sides of a long mouth are in it |
| Thresholds are ratios | Mouth sizes are ratios of the corner chord W, of the mouth line's own depth L_U and of the room measured inside the head; eye sizes of the eye radius r; tolerances of the head size and the local edge `e_loc`. E3 at x1 and x100 gives the same pass/fail and outcome class (sec. 18) |
| Fail toward less change | Every piece is built on a copy, verified against the whole original (sec. 7) and dropped if it fails. Bag vertices step back. The slit shortens at a corner before it gives up. The rim projection is put back if it makes a corner under 20 deg. A refused kit leaves the head as Step 4 left it |
| Deterministic | Python extrusion (`rescue._extrude_edges`), elements in `forge_id` order, Dijkstra ties by index. E3 run twice: identical JSON (sec. 18) |
| Plain words, rows of 44, few questions | At most 3 questions, all point-and-click (sec. 12) |
| Fits the step flow | Own box, Approve, Change, Skip, migration of saved files, one replay rule (sec. 2) |

## 4. Finding the face (`face_marks.py`, on the original)

### 4.1 Frame and face region
- **Head part.** From the U10 part map when it is wired into the product. Today it lives only on
  `feat/u10-partmap` ("not wired into the product yet"), so FK1 falls back to what the branch
  has: `joints.estimate` (`J["head"]`, `J["_skull_base"]`) and `density.region_labels(V, J) == 1`
  (the head label `uv.face_seam_guard` already uses).
- **Face region = the whole head part**, every facing. The v1 filter `n . front > 0.2` is gone:
  it cut out side eyes (birds, fish, horses) and the sides of a long mouth line. Facing only
  breaks ties between equal candidates (front first).
- **Front and mirror.** Front is settled in Step 2 (rig spec WP5); `density.mirror_plane` gives x0.
- **Inside tests use the whole original.** `rescue._parity_inside` needs a closed surface; on an
  open crop it gave wrong answers for the bag's back rings (critique C4). The kit uses the
  sibling's `Target` whole-original tree (`BVHTree.FromObject`, built in C: 0.29 s per 1.3M
  triangles, about 1.1 s on the bull, cached per session and keyed on the high's fingerprint).
  Crops are used only for nearest-point lookups, never for inside tests.
- **Sizes.** `H_head` and `w_head` are measured on the head part. Every threshold below is a ratio
  of these, of W, of L_U, of r, or of `e_loc`.

### 4.2 The mouth line
1. **Candidate lines.** `creases.auto_lines` from the detail-paint design (its 3.3): valley depth
   at the scale of a face quad from smoothed coordinates (`density._smooth`), a band above
   `0.25 x tol`, then a valley-preferring path through each band piece. It is vectorised numpy:
   1.4 s per 655k vertices (their E3c), so about 0.5 s on the bull's head part. This replaces v1's
   per-sample BVH crease field, which needed about 1.9M Python queries (critique C5: about 18 s).
2. **Score each line**, and pick the best:
   - length / `w_head` >= 0.2;
   - mean valley depth / tol;
   - mirror overlap: the line's mirror image across x0 lies on itself (a mouth that crosses the
     middle) or on a twin line;
   - height: below the eye marks (or below 0.55 `H_head` without eyes) and above the chin;
   - its corner chord turns less than 30 deg from the mirror plane's normal.
   - **sure** = 1 - (runner-up score / winner score), clamped to [0, 1].
3. **Corners.** The line's ends, where the valley fades below `tol / 4` for 2 samples running,
   refined with the narrow profile (the dent repro's fade model).
4. **No crease (a painted mouth).** The same tracer on luminance (the high's Tripo texture through
   its UVs, or vertex colours): a dark line 25% below the median within 2 widths. sure <= 0.6, so
   the director is asked.
5. **Mouth already open (modelled cavity).** The rig spec's `mouth_open` test (SPEC_final 5.3). The
   kit cuts nothing; the cavity's entrance loop on the low becomes the slit (6.8).
6. **Mouth depth L_U.** The largest distance of the mouth line from its corner chord, measured in
   the plane normal to the chord. A frontal smile has L_U about 0.35 W (E3 bull: 0.36); a long
   jaw has L_U above W (E3 long snout: 1.75). It sets the bag frame (6.3).

### 4.3 Jaw hinge and chin
- **Chin.** The lowest point of the head's front outline before the neck (rig spec chin rule),
  stored for ARP's chin keys (`arp_chin_loc`, `arp_chin_pos_vec`).
- **Hinge guess.** Behind the throat point T of 6.3 by 0.3 W, on the mirror plane, clamped inside
  the head (parity on the whole original, clearance 0.1 W). sure <= 0.5: Step 8 asks for the
  jaw-hinge click as the rig spec plans. The kit uses the guess only for its computed opening test.

### 4.4 The eyes
Seeds, best first:
1. **A separate eyeball shell** (U2's census: near-spherical shells crossing the head surface).
2. **A convex cap** (the usual Tripo eye, and the bull's): clusters of samples whose two principal
   curvatures are both positive and within a ratio of 0.6, cap radius in [0.03, 0.35] x `w_head`,
   anywhere on the head part. Mirrored across x0 when the body is symmetric.
3. **Painted eyes**: a dark disc of radius rho inside a bright ring of up to 2.5 rho (sure <= 0.6).
4. **The director's click** (6.10 and sec. 12): a surface point. `marks.joint_from_click` does not
   exist on the branch yet (rig context WP9-10), so FK2 uses a plain `scene.ray_cast` from the
   mouse, the same as the detail-paint design's Draw a line.

**Sphere fit (changed after the critique).** From the seed:
1. Grow a seed disc of 20 vertices. Fit centre and radius from points **and normals**
   (`c + r n_i = p_i`, least squares). On a small patch this is well conditioned where the
   points-only fit is not.
2. Grow by residual, not by rings: a neighbour joins when it lies within 1.5% r of the current
   sphere and its normal faces away from the centre (dot > 0.9); refit; stop when none joins.
   The region then takes the aperture's own shape (round, almond, sleepy).
3. E3 on the bull-like head: centre error 1.1% of r, radius +0.5%, RMS 0.37% of r, 340 vertices,
   aperture half-angle 56-59 deg. v1's ring growth gave 2.5-3.9%, +1.7-3% and 49 deg, because it
   stopped at the first ring that crossed the lid crease.
4. Side eyes (E3 `--side-eyes`): centre 0.4% of r, radius -0.1%, aperture 69-73 deg.

**Aperture curve.** The boundary of the grown region, stored as the polar angle per azimuth in
the eye frame (64 bins, median, circular moving average of 5). This is what the cut follows (6.4).

**Round or not: by the sphere fit only.** An eye is round when the fit RMS is <= 2% of r. The
aperture's shape never decides it: an almond human eye on a round eyeball is round, with almond
lids. v1's "aperture aspect > 1.4 = eye shell" rule is removed.

### 4.5 Kinds, and what each one gets

| Found | Detected by | Default | Director can change to |
|---|---|---|---|
| Crease mouth (bull, human) | 4.2 valley line | cut + bag + teeth + tongue | no teeth; no face |
| Long jaw (dog, horse, crocodile) | L_U >= W | as above; the bag runs back along the snout (6.3) | no teeth |
| Painted mouth (no crease) | luminance line, sure <= 0.6 | ask "Is the red line the mouth?" | click the corners; no face |
| Modelled open mouth | `mouth_open` | no cut; bag only if shallower than 0.3 W; teeth and tongue if none are modelled | keep as modelled |
| Beak | Brief body plan = Bird, or slit dihedral > 60 deg over >= 70% of it | cut + narrow bag; no teeth; tongue; stiff halves (6.7) | lips that bend |
| Round eye, any aperture shape | sphere fit RMS <= 2% r | eyeball + lids | keep as modelled |
| Very open eye (aperture half-angle > 65 deg; bulging side eyes) | the curve | eyeball + lids; Step 8 reports the blink coverage (E3: 88-90%) | keep as modelled |
| Non-round eye | fit RMS > 2% r | **eye shell** (6.4 step 7): blinks, does not turn | keep as modelled |
| Closed eye (sculpted shut) | a lid-line valley across a convex lid, no cap | keep closed | "Open them" |
| Painted eye | seed 3 | ask | make real eyes; keep painted |
| One eye (cyclops) | one mark on x0 | eyeball + lids, ARP left eye only (sec. 9) | |
| More than two eyes | more than 2 marks | the largest mirrored pair; the rest stay as they are, in one row | pick the pair by clicking |
| Small chibi face | W / `e_loc` < 8, or rim length / `e_loc` < 12 | local densify (6.4); the row states the triangles | build anyway |
| Helmet, mask, faceless | no mouth line with sure >= 0.3 and no eye mark | **Skip the face** offered first | point at the mouth |

### 4.6 Sure, and when to ask
- sure >= 0.7: shown, not asked. 0.3-0.7: shown with **Yes** / **No, I will click it**. Below
  0.3: the question asks for clicks.
- The face takes at most 3 questions, counted in sec. 12.

### 4.7 Speed (extrapolated; FK-X5 measures on the PC)
- Whole-original tree: about 1.1 s on the bull (sibling C7), once per session.
- Candidate lines on the head part: about 0.5 s (vectorised; detail-paint E3c rate).
- Sphere fits: numpy on a few thousand points, under 0.1 s.
- Find is about 2 s on the bull. Build is about 1 s (E3's whole run, including making the test
  original and its QuadriFlow low, took 3.6-6.6 s).

### 4.8 What is stored (on the high, which never changes after Step 3)
- `forge_face_marks` (JSON object property on the high):
  - version, `made_with: {high_nv, high_fp}` (`density.fingerprint`), frame `{x0, front}`;
  - mouth: `{kind: crease|painted|open|beak|none, line: [<=200 pts, high-local], corners: [a, b],
    W, L_U, sure, source: measured|clicked|selected}`;
  - eyes: `[{side: l|r|mid, kind: ball|shell|cap|painted|closed, centre, r, axis, frame: [xe, ue],
    aperture: [64 polar angles], sure, source}]`;
  - `hinge`, `chin`, `head: {H, w}`.
- `forge_face_answers`: `{skip, teeth: auto|yes|no, beak: auto|yes|no, eyes: build|keep,
  closed_eyes: keep|open, extra_eyes: [...]}`.
- `forge_face_edits`: the director's face edits from 6.10 as positions on the high (selected
  mouth line as a polyline, selected eye opening as its curve, piece transforms relative to the
  piece's built frame), so Build the face again replays them.
- Validity follows the horn-plan rule: if `high_nv` or the fingerprint differs, the marks are
  stale, found again, and clicks and edits are re-applied by position.

## 5. Step 4 changes (only when marks exist)
- **Room.** `retopo` gets `face_headroom = kit_estimate / budget`. The body part's QR target
  becomes `budget x (carve_headroom - face_headroom)` (carve_headroom 0.94, retopo.py:666). The
  estimate uses the measured loop lengths, not a fixed loop (sec. 11). Row: "Room kept for the
  face: 1,350 triangles".
- **Density: one owner.** The face region enters the detail-paint design's field as an automatic
  contribution: `make_field` composes `forge_auto x plan x paint x turn_factor`, and the face kit
  adds a plan factor of up to 1.41 (2x the quads) along the mouth line and round each eye rim out
  to 1.5 r, which `make_field` then caps (R) and grades (g = 0.3) like any paint. The kit never
  writes `QR_Density` itself and never calls `density.boost` (which the detail-paint design
  replaces). The director's own paint wins over it, as paint wins over the plan today.
- **Asked vs got.** The detail-paint `asked_vs_got` runs on the face region as an area of its own
  and is stored in the Step 4 report (`density.areas["face"]`). 4b reads it: when the eye rims
  got fewer than 16 vertices or the mouth line is followed by an edge over less than 50% of its
  points, the kit densifies locally (6.4) and the row says so.
- **Edge guides.** The mouth line and the eye rims are passed as crease guides through the
  detail-paint design's encoding (`sharp_edge` + `use_normals` on the proxy, its 3.4). That is
  gated by its PC probe; until then guides are not encoded. v1's own material-split guide is
  dropped (one encoding, one probe).
- **Not measured yet:** the ramp and guides on the bull through Quad Remesher (FK-X3, with the
  detail-paint probe). The kit does not rely on them: E3 builds a clean face on an unguided
  QuadriFlow low.
- Without marks (Step 4 already ran), nothing changes in Step 4.

## 6. Building on the low (`face_kit.py`)

### 6.1 Transactions and gates
- Each part of the kit is a sibling transaction (fixkit 4.6): `work = bm.copy()`, build, `verify`
  plus the kit gates (sec. 7), then `to_mesh` on pass or `free()` on fail.
- Order: mouth, then each eye, then the separate pieces. One part failing does not stop the
  others; the rows say which parts were built.
- `FORGE_facebase_<part>` keeps the head low before the first part (a mesh datablock with a fake
  user). **Remove the face** restores it bit for bit and deletes the kit objects.
- Every element made by the kit is in the sibling's `forge_made` mask, so later Fix selected runs
  know what not to touch.
- New elements get their `forge_id` by the sibling's sort rule (quantised position, then
  neighbours), so a rebuild gives the same ids.

### 6.2 The mouth cut
1. **The line on the low.** Sibling Follow crease between the low vertices nearest the two mark
   corners: slide mode, then cut mode (its L4a/L4b), each through its gates. G3 (no fold against
   the original) matters here: E3's stand-in slide without it left folded skin at the corner.
2. **The slit gates** (new). On the chosen edge path:
   - **No L-step.** No face may hold three consecutive path vertices (the path running along two
     sides of one face). Any that remain after Follow crease's cut mode are split along their
     diagonal (`bmesh.ops.connect_verts` on the outer two vertices) and the path takes the
     diagonal: one more triangle per step.
   - **Monotone.** The position along the mouth line (arc parameter) increases strictly from
     corner to corner; a hook at an end is trimmed one edge at a time, up to 2 edges.
   - E3 shows the L-step gate is the one that matters. On the bull-like head, 11 of 25 path edges
     were L-steps. With the gated slide and no L-step split: 2 wall/skin crossings at x1 and 4 at
     x100 (v1's FK-X2 problem). With the split: 0 at both scales. On the long snout (critique C3):
     24 crossings with the critic's settings (the critic measured 23), and 0 with the split. With no slide at all there were
     no crossings either, which pins the cause on stepping, not on the bag.
   - The side test v1 proposed (the two faces of each path edge on opposite sides) found nothing
     on either head; it is kept as a cheap assertion, not relied on.
3. **Split.** `bmesh.ops.split_edges(bm, edges=path_edges, use_verts=False)`: one boundary loop of
   2 x path edges, the two corner vertices shared (E1, E3).
4. **Open the slit by a measured gap** (new, for Step 5). Each doubled pair moves apart along the
   local `across_i` (slit tangent x original normal, towards the upper lip): upper +delta, lower
   -delta, corners never move. `delta = max(0.01 x e_loc, 4 x rescue.same_spot_tolerance(me))`.
   - Why: Step 5's UVgami pre-flight (`uv._uvgami_ready`, uv.py:355) counts doubled points and
     runs `rescue.tidy`, which welds same-spot points and rebuilds what is left. E3 without the
     gap: 36 doubled points, tidy welded 18, dropped 2, rebuilt 2, and 17 of 132 kit vertices
     were gone with no error. With the gap: 0 doubled points, tidy never runs, every kit vertex
     kept. The gap is 7x UVgami's same-spot tolerance at x1 and far more at x100.
   - The gap is 1% of an edge (0.1 mm on the bull), a dark hairline at rest, which is where the
     mouth line is drawn anyway.
   - If `delta > 0.1 x e_loc` (a model a few centimetres tall), the kit refuses with "Model too
     small for a face (Step 2 height)".
5. **Halves.** The loop is ordered from corner a. Upper half = the side whose neighbour faces lie
   along +`across`. Each loop vertex stores `forge_kit_side` (+1 upper, -1 lower, 0 corner) and
   its arc parameter `u` (0 at corner a, 1 at corner b, along its own half).

### 6.3 Inner lips and mouth bag (changed after the critique)
**Frame, per mouth, from measured sizes:**
- W = corner chord; `x_ax` = corner a to corner b; o = the chord's middle.
- **Inward axis b.** Blend of two directions by `lam = clamp((L_U / W - 0.15) / 0.35, 0, 1)`:
  the mouth's own depth direction (from the mouth line's deepest point towards o: along the snout
  for a long jaw) and the v1 direction (mouth centre to head centre, made normal to `x_ax`).
  E3: bull L_U/W 0.36, lam 0.6, b = (0, 0.97, 0.25); long snout L_U/W 1.75, lam 1, b = +Y.
- **Throat point.** `T = o + b x D_t` with `D_t = max(0.85 W - L_U, 0.35 W)`, capped at half the
  room inside the original from o along b (a ray on the whole-original tree). E3: 0.49 W and
  0.35 W.
- **Seam curve.** `S(u) = T + x_ax x (u - 0.5) x 0.6 W`. Upper and lower vertices with the same
  `u` meet there.
- **Across.** Per vertex, `across_i` at the slit, turning towards the mouth plane's normal
  `n_m = x_ax x b` over the rings.

**Rings** (each made by `rescue._extrude_edges` on the current loop, then placed):

| Ring | Position | Half-opening across (times sign) |
|---|---|---|
| 1 inner lip (wet line) | slit point + 0.10 W x (0.35 + 0.65 G) along the local inward normal (made normal to across) | 0.08 x W/2 x max(G, 0.35) |
| 2 bag front | ring 1 + 0.26 x (S(u) - ring 1) | 0.32 x W/2 x max(G, 0.35) |
| 3 bag middle | ring 1 + 0.67 x (S(u) - ring 1) | 0.40 x W/2 x max(G, 0.35) |
| 4 seam | S(u) | 0 |

- G = sqrt(1 - (2u - 1)^2): 0 at the corners, 1 at the middle of each half.
- Each half-opening is capped at 0.4 x the room along `+-across` inside the original (a ray), so
  a thin jaw gets a flat bag instead of a bag through the chin.
- On a frontal mouth this reproduces v1's rings (depth 0.1/0.3/0.6/0.85 W, lateral keep
  1/0.92/0.8/0.6). On a long jaw every lip vertex moves towards the throat and the middle, so the
  palate and floor span the whole snout.

**Placement is verified per vertex** with steps x1, 0.7, 0.5, 0.35, 0.25, 0.15, 0.1 on the
opening, then the depth. A spot is accepted only if:
- it is inside the original (parity on the **whole-original** tree, not a crop: critique C4);
- its distance to the original is at least `min(0.2 x its depth, e_loc)`;
- the segment from its previous-ring vertex crosses no original face (`ray_cast`, starting
  `max(1e-5 x size, 4 x delta)` along, so the slit gap is not counted as a crossing).
- A vertex with no spot takes the mean of its two ring neighbours and is checked again; still
  failing, the ring is refused (sec. 7).

**Pillowcase seam.** Each lower ring-4 vertex is welded to the upper ring-4 vertex with the
nearest `u`, one to one (`bmesh.ops.weld_verts`). v1 matched by lateral coordinate, which on a
long jaw pairs two points of one side: E3 measured Euler 0 (a broken surface) that way. Then the
two seam ends: the corner's ring-4 vertex is welded into its seam neighbour, else it keeps only two
faces and those two fold onto each other (E3: 2 groups of stacked faces, which Step 5's
pre-flight also counts). Anything left open is closed with `holes_fill`.

**Face gate.** BVH overlap of the new wall faces against the skin faces; pairs sharing a vertex
are left out. Any crossing pulls the ring vertices involved halfway back towards the previous ring,
up to 6 rounds; still crossing = the bag is refused.

**E3 results** (gated slide, L-step split, throat frame, opened slit):

| Head | Loop | Bag triangles | Inside | Crossings | Euler | Unplaced | Rays at 20 deg jaw |
|---|---|---|---|---|---|---|---|
| bull-like x1 | 38 | 300 | 94/94, >= 1.12 e from the skin | 0 | 2 | 0 | 54/54 bag, 0 inside of skin |
| bull-like x100 | 40 | 316 | 99/99 | 0 | 2 | 0 | 57/57 bag |
| long snout x1 | 106 | 844 | 264/264, >= 0.75 e | 0 | 2 | 0 | 125/156 bag, 31 out through the far side of the opening, 0 inside of skin |
| long snout x100 | 110 | 876 | 274/274 | 0 | 2 | 0 | 127/162 bag, 0 inside of skin |

- Cost: 7.9-8.0 triangles per slit-loop vertex on every run, so the budget estimate is
  `8 x loop vertices`, from the measured mouth-line length / `e_loc` (sec. 11).
- **Jaw share.** `forge_jaw_share` per vertex: upper half 0, lower half 1, seam 0.5 (for the rig,
  sec. 9).

### 6.4 The eyes (changed after the critique)
1. **Aperture on the low, cut by the stored curve.** Candidate faces: centre within 1.25 r of the
   eye centre and polar angle below the curve at its azimuth (not a cone at the largest angle).
   The connected piece holding the face nearest the axis is the disc; it is deleted
   (`FACES_ONLY`), then wire edges and loose vertices. The rim must be one simple loop.
2. **Rim onto the curve.** Each rim vertex moves along the original's surface to the curve's polar
   angle at its azimuth (a ray from the eye centre in that direction, first hit on the whole
   original), after 3 passes that even out the azimuth steps along the rim.
   - Gate: the worst corner of the faces touching the rim stays >= min(its value before, 20 deg),
     else every rim vertex is put back. E3: worst corner 24-42 deg after the move over 18 rims;
     never put back.
   - E3: residual against the curve 5.5-9.3 deg std before (v1's radial rule; the critic measured
     7-8 deg), 0 after, on 16-26 vertex rims.
   - The same no-L-step rule as the slit: no skin face may hold three consecutive rim vertices.
     E3's two worst lid-stretch outliers (7.5x and 11.4x on the side eyes) were triangles holding
     3 rim vertices at a lid corner.
3. **Rim count.** An even count of at least 16 for Unreal (12 for a Unity-only job). Too few: the
   longest rim edges are split at their middles (`bmesh.utils.edge_split`) and the outer face is
   split with `connect_vert_pair`, about 1-2 triangles per added vertex. E3: 16 and 18 on the
   bull-like head (2.7k faces), 24 and 26 at 6k faces, 20 on the side eyes.
4. **Corners.** The rim pair (i, i + N/2) whose chord lies most nearly along the eye's horizontal.
5. **The eyeball sinks instead of the rim rising** (new). v1 pushed the rim out to r + g. On a
   bulge eye the skin just outside the aperture is the eyeball's own surface, so the raised rim
   stood proud of the skin and the pocket had no room: E3 measured 2-5 pocket vertices outside
   the original and 8-12 crossings that way. Now:
   - the rim stays on the original's surface;
   - the eyeball radius is `r_ball = min(r - g, d_skin - g)`, where `d_skin` is the nearest skin
     outside the rim (front half, within 1.6 r), and g = 0.08 r. The visible eye surface moves in
     by g (2 mm on the bull's 27 mm eye). The bake puts the original's iris onto it (sec. 8);
   - an eye whose `r_ball` would be under 0.85 r is refused: "Lids too thin to hold an eyeball".
6. **Truncated eyeball** (new). A UV sphere (16 x 10) of radius `r_ball` with its poles on the eye
   axis. It is cut off past polar angle `aperture + 25 deg of look + 30 deg` and closed flat,
   because that part is never seen. E3: 190 triangles at a 59 deg aperture, 222 at 73 deg (v1:
   288). Unity: 12 x 8 cut the same way.
7. **Pocket (closed socket), with gates** (new).
   - Rings every <= 25 deg of polar angle from the rim to 155 deg, then a back pole. The ring
     radius is raised against the chord sag: `R_p = (r_ball + g/2) / cos(half the face diagonal
     angle)`.
   - Each pocket vertex is clamped inside the original: `R_i = min(R_p, d_i - 0.25 g)`, where `d_i`
     is the distance to the original along its own direction (whole-original tree).
   - Gates, all against the whole original and the kit:
     - every pocket vertex inside the original, at least 0.25 g from its surface;
     - no pocket face crosses the skin, the mouth bag or the other pocket;
     - **the eyeball crosses no head face at rest and turned 25 deg up, down, left and right**
       (BVH overlap of the posed eyeball against the head). This replaces v1's "nearest pocket
       face >= r + g/2", which a truncated eyeball does not need behind its cut.
   - E3, on 18 eyes over 9 runs (bull-like at 2.7k and 6k faces, x1 and x100, g 0.08 and 0.12,
     four lid rules, long snout, side eyes), and 6 more at g = 0.12 r: pockets 100% inside (clearance 0.22-0.29 r), 0 pocket crossings,
     0 eyeball crossings at rest and at all four looks. Cost: 236-326 triangles for both eyes'
     lid margins and pockets.
   - A head too thin behind the eye (the back pole cannot fit at 0.25 g) flattens the pocket's
     back to the measured depth; the eyeball's cut moves forward with it as long as the cut stays
     behind `aperture + 25 deg`. Otherwise the eye is kept as modelled: "No room behind this eye".
8. **Eye shell (non-round eye).** The cap faces of the low are copied before the delete and
   closed behind (one ring and a fan), weighted rigid to the head, no eye bone. Its lids use the
   shell's own surface instead of a sphere: the lid gap is measured as the signed distance from
   each lid vertex to the shell (BVH nearest + normal) instead of `|p - c| - r`; the rest of the
   gates and checks are the same. It blinks but does not turn.
9. **Painted eyes, "Make real eyes".** The aperture comes from the colour disc, scaled to
   1.25 rho; the eyeball goes at the measured depth (r = 1.6 rho); then steps 1-7.
10. **Closed eyes, "Open them".** The lid line becomes the aperture (2 x the valley width round the
    line); the eyeball goes behind at r = 0.6 x the line's length; the lids rest closed and
    Step 8's eye check tests opening instead of closing.

### 6.5 Teeth (`face_parts.teeth`)
- **Arch.** The upper slit half projected onto the mouth plane (`x_ax`, b), offset inward by
  1.3 x the ring-1 depth, trimmed by 10% at each end; the lower arch is 0.92 x the upper.
- **Cartoon** (Step 1 `art_style` = cartoon): one band per arch, a rectangle swept along the
  arch, 14 segments, 116 triangles (E2); height 0.12 W, thickness 0.05 W. Unity: 8 segments, 68.
- **Realistic:** `n = clamp(round(arch length / 0.09 W), 6, 16)` bevelled boxes per arch on a gum
  strip.
- **Placement.** Upper tips 0.01 W below the slit plane, lower tips 0.01 W above it.
- **Fit gate (corrected).** A point is in the mouth when it is inside the original **and not**
  inside the head low with its bag: the cavity is an inward fold of a closed surface, so parity
  on the head alone calls it outside (critique C2-4). Every tooth vertex must be in the mouth and
  at least 0.02 W from the bag walls (BVH nearest).
  - E3: the cavity's middle point is "outside the head" by v1's rule and "in the mouth" by the new
    one; the head's centre and a point in front of the face are not in the mouth by the new rule.
    On a stand-in tooth band, v1's rule passed 3 of 72 points (bull) and 39 of 168 (long snout);
    the new rule passed 69/72 and 129/168. The rest are the stand-in's own points outside the
    walls, which the scale-down below handles.
  - On failure the arch scales by 0.85, 0.7, 0.55, then is dropped: "No room for teeth behind
    the lips".
- **Objects:** `<asset>_teeth_upper`, `<asset>_teeth_lower` (ARP `SEPARATE` teeth, sec. 9).

### 6.6 Tongue (`face_parts.tongue`)
- On the bag floor along b: length 0.75 x (bag depth at the middle), width 0.55 x the lower
  arch's inner width, thickness 0.35 x its width, top 0.03 W below the lower teeth. A UV sphere
  10 x 8 (140 triangles, E2) with the front 30% tapered. Unity 8 x 6, 80.
- Its centre line in 3 equal segments gives ARP's `tong_01..03_ref.x`.
- The same fit gate as the teeth.

### 6.7 Beak mode
- The cut and bag as in 6.2-6.3, half-opening x 0.6. No teeth; a tongue only when the inner width
  is at least 0.25 W.
- **Stiff halves.** Each skin vertex near the slit takes the side of the nearest slit half by
  distance over the surface (multi-source Dijkstra from the two halves, bag excluded).
  `forge_jaw_share` is 1 on the lower beak and 0 on the upper; the rig leaves the lips bones out.

### 6.8 Mouth already open
- The cavity entrance on the low (where the surface turns inward by more than 45 deg along the
  `mouth_open` band) is the slit loop; halves by `across`, no split.
- A bag is added only when the cavity is shallower than 0.3 W (the floor faces are replaced from
  their rim by 6.3). Teeth and tongue only when nothing inside rises above 0.05 W: "Teeth found
  in the model: kept".

### 6.9 Objects, materials and UVs, and Step 5 (new work package FK5b)
- **Kit objects:** `<asset>_eye_l`, `<asset>_eye_r`, `<asset>_teeth_upper`,
  `<asset>_teeth_lower`, `<asset>_tongue`. `forge_role` "low", `forge_part` "eye_l" and so on,
  `forge_kit` = the kind, `forge_kit_of` = the head's part id, `forge_uv_fixed` = True (a new
  property). Parented like props, kept out of `detachable_parts`.
- **Materials.** The head keeps its material; the bag, inner lips, lid margin and pocket are head
  faces. All kit objects share `M_<asset>_face` with one small texture set (512 Unreal, 256 Unity).
- **UVs written by the kit:** eyeball front projection with the iris centre at (0.25, 0.75), both
  eyes sharing it; teeth bands in the right-top quarter; the tongue in the bottom half.
- **Step 5 changes (FK5b):**
  - `uv._run` drops `forge_uv_fixed` lows from `lows` before `_uvgami_unwrap` and before the
    Blender unwrap and pack loop; `uv.compare` drops them too. v1's "one line in the part loop"
    was not enough: UVgami runs on all lows first.
  - The head stays in the UVgami batch. Its slit pairs are apart by delta (6.2), so
    `_uvgami_ready` finds nothing to weld and UVgami's position matching is not ambiguous.
  - `face_seam_guard` leaves out vertices of `forge_kit` 2 (bag) and 4 (socket) faces, so the
    guarded face island does not swallow the inside of the mouth.
  - Seams on the slit loop and both rim loops (`edge.seam = True`) before the unwrap, so the inner
    lip, bag and lid margin are their own pieces and never stretch the face's islands.
  - Hidden pieces pack small: after the unwrap, islands made only of `forge_kit` 2 faces are
    scaled to 0.5 and of `forge_kit` 4 faces to 0.25 about their centres. Blender's
    `pack_islands` keeps relative scales. UVPackmaster runs with `normalize_scale = True` today
    (uv.py:943), which would undo it; for heads with kit faces it is set False after Forge's own
    `average_islands_scale` [probe on the PC: UVPackmaster 4 keeps pre-scaled islands with
    normalize off; FK-X6].
  - The director's current UV layout is otherwise unchanged.
  - Tests (sec. 15): Step 5 on the UVgami path (fake UVgami) and the Blender path keeps the slit
    loop count, the bag face count and the pocket face count, and the kit objects' UVs bit-exact.

### 6.10 Manual face tools: "Edit the face" (new: the director's "manual fix" for the face)
All tools run in Edit Mode on the head (or Object Mode for pieces), as sibling transactions with
`verify` and the kit gates, and are recorded in `forge_face_edits` so Build the face again
replays them. Each is one undo step (`forge.face_tool`, `bl_options = {"UNDO"}`, like the
sibling's `forge.fix`).

| Tool | Input | What it does | Verified by | On failure |
|---|---|---|---|---|
| **Use as the mouth line** | selected edges on the head (one open chain) | the mouth is rebuilt on that chain: slit gates (6.2), split, gap, bag, pieces | the chain is one simple open path with 3+ edges and both ends on skin; then every mouth gate | nothing changes; row names the gate ("The selected line crosses itself", "The mouth's inside would go through the chin") |
| **Use as the eye opening** | selected faces on the head (one disc) | those faces become the aperture of the nearest eye mark: its curve is re-measured from the selection's boundary, then 6.4 | disc test (one boundary loop, no holes); every eye gate | nothing changes; row |
| **Mouth corner here** | one selected vertex near a corner | moves that corner of the mouth line there and rebuilds the mouth | as Use as the mouth line | nothing changes |
| **Check the face** | after the director moved, turned or sized the teeth, tongue or an eyeball with G / R / S | re-runs that piece's gates: in the mouth, clearance, no crossing; eyeball crossings at rest and the 4 looks | as each piece's gate | the piece goes back to its last checked transform; row "Teeth moved back: they came through the lip" |
| **Fix the face** (auto) | nothing, or a selected piece | re-runs the step-back rules on that piece (bag vertex step-back, teeth scale-down, rim projection) from the current state | the same gates | keeps the better of before and after |
| **Undo last edit** | | restores the head and kit objects before the last face tool (the sibling's stack, `FORGE_faceundo_<k>`) | bit-exact | |

- Selections are read with the sibling's `bm_arrays` / `sync` rule (Edit Mode data is stale until
  `update_from_editmode`).
- Blender's own edits on the head (outside these tools) are detected by the sibling's fingerprint
  log as `{tool: "hand"}`; Approve re-runs the whole-kit gate on them.

## 7. How each piece is verified

| Piece | Gate (all must pass) | On failure |
|---|---|---|
| Mouth line | sibling G1-G7 (Follow crease); no L-step after the diagonal split; monotone arc parameter | trim up to 2 edges per corner; else no mouth, with the row "Could not follow the mouth line at a corner" |
| Slit | one boundary loop, 2 x path edges long, corners shared; every doubled pair apart by delta; `rescue.doubled_points` on the head is 0 | no mouth |
| Bag | closed manifold; Euler characteristic unchanged; no stacked faces (`rescue._bm_stacked`); every placed vertex inside the whole original with its clearance; no wall/skin crossing; normals outward (share >= 0.99) | step back per vertex; then a 0.7x shallower bag; then no mouth |
| Opening (computed 20 deg jaw about the guessed hinge) | rays cast along the local outward normal at 25/50/75% between each upper/lower slit pair: 0 may hit the inside of the skin. A ray that hits nothing has passed out through the opening again (the head and bag form one closed surface, so there is no other way out) and is allowed. v1 forbade it, which a long jaw seen from the side breaks | as the bag. E3: 0 inside-of-skin hits on every run |
| Eye aperture | rim is one simple loop; even count >= 16 (Unreal); no L-step on the rim | grow by one ring (up to 2), else keep the eye as it is |
| Rim on the curve | worst corner of rim faces >= min(before, 20 deg) | put the rim back (cut by the curve, not projected) |
| Pocket | inside the whole original with 0.25 g clearance; no crossing with skin, bag or the other pocket | flatten the back; else keep the eye as it is |
| Eyeball | r_ball >= 0.85 r; no crossing with the head at rest and at 4 looks of 25 deg; front within 2% r RMS of the original cap, after the sink g is taken off | eye shell; else keep the eye as it is |
| Lids (computed blink, sec. 9.4 weights) | coverage >= 99% of rays inside the aperture; front lid vertices >= 1.0 r_ball from the centre; lid-band stretch graded (10.2); skin beyond the lid band moves <= 0.05 r | raise g to 0.12 r once (the eyeball sinks to 0.88 r); else build the eyeball without lids (eye stays open) |
| Teeth / tongue | every vertex in the mouth (inside the original and not inside the head low) with 0.02 W clearance to the bag; no crossing with the bag | scale 0.85 / 0.7 / 0.55, then drop |
| Whole kit | compared by a vertex map, not by index: every surviving original vertex (by `forge_id`) keeps its position except the slit pairs (moved by delta), the rim vertices (moved to the curve) and vertices of the sibling Follow-crease patch recorded in the log; the faces outside the slit and rim neighbourhoods keep their corners. Plus the sibling's two-sided surface-change gate (PLAN principle 2) on the visible skin outside the slit and the apertures | restore `FORGE_facebase` |

## 8. Step 6 bake: the kit route (FK7, now size L)
Today's `bake.run_iter` cannot do this. `high_for(low)` matches by `forge_part`, so every kit
object is "skipped: no high mesh" (bake.py:1306-1312, common.py:69-74); `_bake_material(low)`
clears a low's materials and makes `M_<part>_bake` with its own full-size image (bake.py:47-52);
and `fit_cage` takes `need` over every sample, so kit faces push the cage at the slit and rim
vertices, which they share with lip and lid skin (bake.py:422-458; the hidden mask is applied
only to the failing count at bake.py:521-522).

**Changes:**
- **Mark.** `forge_kit`, a FACE INT8 attribute on the head low: 0 skin, 1 inner lip, 2 bag, 3 lid
  margin, 4 socket. The `forge_made` mask covers the same faces.
- **Kit objects map to the body's high.** `common.high_for` checks `forge_kit_of` first, so an
  eyeball bakes from the head's high.
- **One shared kit image.** In `run_iter`, kit objects are baked in one pass into
  `T_<asset>_face_<map>` (512 or 256) with their fixed UVs. `_bake_material` gets a `keep=True`
  route for them: the bake image node is added to `M_<asset>_face` and removed after, and the
  material is never cleared.
- **Kit faces out of the cage fit.** `fit_cage` masks samples on `forge_kit` 1-4 faces out of
  `need` and `room` before the per-face and per-vertex maxima, not only out of the failing count.
  Test: the cage push on the lip texels with the kit built is within 5% of the push on the same
  texels without the kit (sec. 15).
- **No rays for kit faces 1-4.** They are added to the hidden mask `_hidden_tris` feeds, and
  filled by `face_kit.fill_colours(img, raster)` after `_apply_validation`:
  - inner lip: the median baked colour of the skin texels next to the slit, 15% darker;
  - bag: a depth gradient from the inner-lip colour to (0.35, 0.08, 0.08) linear, or to the
    painted mouth colour when the mouth line is dark in the original; AO 1 - 0.7 x depth / bag
    depth; flat normal;
  - lid margin: the rim's skin colour, 30% towards (0.8, 0.45, 0.45);
  - socket: (0.05, 0.03, 0.03), AO 0.2.
- **Eyeball front: baked from the original** through the cage, on faces inside the aperture
  curve; the outer 10% of the aperture is left out so painted lashes stay off a turning eyeball;
  the rest of the ball gets the sclera colour (median baked colour between 0.6 and 0.9 of the
  aperture, else (0.92, 0.92, 0.90)). The eyeball is g deeper than the original's eye surface, so
  the cage reaches out at least g there; `fit_cage`'s `need` covers it (the gap is measured, not
  assumed).
- **Teeth, gums, tongue:** plain defaults (0.93, 0.91, 0.84), (0.75, 0.35, 0.38),
  (0.80, 0.38, 0.40), editable with the eyedropper in Step 7.
- **GPU.** The eyeball front bake runs inside Step 6's Cycles bake on the RTX (OptiX). The fills
  are numpy on the image arrays, under 0.1 s.
- **Row:** "Inside of mouth and eyes: plain colours".

## 9. Step 8 rig: what Auto-Rig Pro gets

### 9.1 Face mode
| Kit result | Default face mode | ARP options (through `arp_limb_options.set_limb_options(rig, "head_ref.x", changes)`) |
|---|---|---|
| skipped or nothing built | Head moves as one | `facial` off (today) |
| mouth only | Jaw opens | `facial=True, facial_mouth=True, facial_teeth=<teeth>, facial_tongue=<tongue>`, every other `facial_*` False, `skull_bones=False` |
| mouth + eyes | Full face | as above plus `facial_eye_l/r` per eye built, `eyelids_amount = 3` if the rim has >= 16 vertices else 1, `lips_amount = 2` if each lip half has >= 10 slit vertices else 1 |
| beak | Jaw opens | `lips_amount = 0`, `auto_lips=False`, `facial_teeth=False` |
| animal body plan | (same) | `muzzle=True` |

- Every `facial_*` option the kit does not place is sent as False (mouth.md 5: they default True).
- The face switch is the one the probe saw refused on a fresh rig; the rerun probe tests whether
  showing the reference bone first fixes it [probe, FK0].

### 9.2 Reference bones from the kit's landmarks
Unchanged from v1 (ARP Smart's own rules, auto_rig_smart.py:4285-4560): eyelid bones from the rim
at 25/50/75% of each half and the corners; lips from the slit at the middle and at 1/3 and 2/3;
`jaw_ref.x` from the hinge to the chin; teeth from the arches; `tong_01..03_ref.x` from the tongue's
centre line.

### 9.3 Scene properties and bind
- Before `arp.bind_to_rig`: `arp_eyeball_type = "SEPARATE"`, `arp_eyeball_name`,
  `arp_eyeball_name_right`, `arp_teeth_type = "SEPARATE"`, `arp_teeth_name`,
  `arp_teeth_lower_name`, `arp_tongue_name` (names from the probe's `scene_props`).
- `finish()` selects the kit objects with the body (arp_rig.py:301-307).
- `auto_rig.eyelids_borders_data.left_borders / right_borders` set to the rim loops
  (`[[index, world co], ...]`, what ARP's own Set button stores) [probe].
- **Bind engine for heads with a kit [probe, FK0].** The bag and pockets are faces inside the head.
  ARP's heat-map bind can let internal faces block bone visibility, which could starve the outer
  chin and lips of jaw weight. ARP 3.79.17 also offers `PSEUDO_VOXELS` (the probe: bound a
  4,048-vertex body in 1.4 s, every vertex weighted, log "improve jaw weights"). FK0 binds the
  test head with the kit both ways and compares the jaw weight on the outer chin and lower lip
  against a head without the kit; the engine closer to the no-kit weights becomes the default for
  heads with a kit.
- Where ARP cannot skin a piece (one eye; eyes off with teeth on), Forge weights it 100% to
  `c_eye.l`, `c_teeth_top.x` / `c_teeth_bot.x` or `tong_0k.x`, those bones' `use_deform` off
  during the body bind.
- `settle_appendages`, `_cleanup_weights` and the props loop skip kit objects.

### 9.4 Forge's face weights (after the bind; verified, put back if worse)
- **Inside the mouth:** `forge_kit` 1 and 2 vertices get `forge_jaw_share` to `jawbone.x` and the
  rest to `head.x` (or `c_skull_01.x`).
- **Lids: by distance over the surface from the rim (changed after the critique).**
  - `d_u`, `d_l`: multi-source Dijkstra over skin edges (pocket and bag excluded) from the upper
    and lower rim halves.
  - Lid weight `w(d) = 1` for `d <= 0.15 r` (the lid margin), then a smoothstep to 0 at `d2`.
  - `d2 = clamp(0.9 x B, 0.5 r, 0.8 r)` per lid, where B is the surface distance from that rim
    half to the brow ridge (upper) or the cheek ridge (lower): the first convex ridge line of
    `creases` (negative valley score) along the surface. Never past the brow.
  - If a brow or cheek that close (d2 forced under 0.8 r) leaves coverage under 99% (E3 at
    d2 = 0.5 r: 97.6%), d2 grows in steps of 0.1 r up to 0.8 r and the row says "The brow
    moves a little with the blink" (yellow), with the measured movement.
  - Corners: upper weight `w(d_u) x s`, lower `w(d_l) x (1 - s)`, with
    `s = smoothstep((h + 0.1 r) / 0.2 r)` and h the height in the eye frame. The two lids blend
    over a 0.2 r band instead of splitting by sign.
  - Pocket rings follow their lid by the same blend, fading to 0.5 past `aperture + 40 deg`; the
    back pole stays with the head.
  - **E3** (round eye, 59 deg aperture, upper lid turning 78 deg):

    | Rule | Coverage (aperture) | Front lid / r_ball | Lid stretch max (p95) | Skin beyond the band, max move |
    |---|---|---|---|---|
    | v1 radial (1 within 1.35 r, to 0 at 2.3 r) | 100% | 1.09 | 3.4-3.7 (2.9) | **1.47-1.62 r** (the brow moves) |
    | surface, d2 = 0.5 r | 97.6% | 1.08-1.09 | 3.7-4.4 (3.5-3.7) | 0 |
    | surface, d2 = 0.8 r | 100% | 1.06-1.07 | 2.7-4.0 (2.6-2.9) | 0 |
    | surface, d2 = 1.2 r | 100% | 1.06-1.09 | 3.5 (2.7-3.1) | 0 |
    | d2 = 0.8 r, g = 0.12 r | 100% | 1.11-1.12 | 2.7-4.0 | 0 |
    | d2 = 0.8 r, 2x denser low | 99.7%, 100% | 0.977, 1.045 | 4.7-5.1 (3.8-4.0) | 0 |
    | d2 = 0.8 r, x100 | 100%, 99.6% | 1.007, 1.081 | 3.8-3.9 | 0 |
    | d2 = 0.8 r, side eyes (73 deg) | 88-90% | 0.988-1.06 | 7.5-11.4 (3.7-3.8) | 0 |
    | g = 0.12 r on the three eyes that dipped (6k faces, long snout, side eyes) | 99.4-100%; side eyes 92-93% | 1.022-1.033 | unchanged | 0 |

  - Reading: the surface rule stops the brow and cheek moving (the critic's main finding: 1.45-
    1.66 r, reproduced as 1.47-1.62 r) and keeps full coverage on round eyes. 3 of 16 eyes dip
    under 1.0 r_ball at the front with g = 0.08 r (0.977-0.988); at g = 0.12 r all three clear
    it (1.022-1.033), which is why the gate retries at 0.12 r. Side eyes with a 73 deg aperture
    do not close fully (sec. 10).
  - Lid stretch has a floor set by the shape: the upper rim must travel `T = r x theta_u` (about
    1.4 r on the bull-like eye, the lid turning 78 deg), and the band can only be B long, so a
    linear falloff stretches at least `1 + T / (d2 - 0.15 r)` (about 3.1-3.3 here). The measured
    p95 is 2.6-4.0, within 1.25x of that floor on every round eye. Very open cartoon eyes
    therefore stretch their lids about 3x when fully closed; sec. 10 grades it against the floor,
    and risk 4 says what would reduce it.
  - A per-azimuth closing was also tried (E3 `--lid-sub 1`, three tweak bones per lid with the
    corners fixed): coverage dropped to 94-95%, so the single main rotation stays the default.
- **Beak:** lower beak 100% `jawbone.x`, upper 100% `head.x`.
- **Gate.** The Step 8 face checks (sec. 10) run with ARP's weights and with Forge's. Forge's are
  kept only when they pass and ARP's fail, or both pass and Forge's have a lower lid-band stretch
  and no skin moved beyond the band. Ties go to ARP's (less change). The row says which was kept.

### 9.5 Fallback when ARP refuses the face switch
As v1: `cc_jaw`, `cc_eyelid_top.l` / `cc_eyelid_bot.l` / ..., `cc_eye.l` / `cc_eye.r` (a `cc_`
bone exports in all four profiles, probe `socket_export`), weighted with 9.4's rules. Row:
"Auto-Rig Pro's face bones are not available: Forge added a simple jaw and lids".

## 10. Checks after rigging (Step 8, `motion_check` additions)
Two clips join `steps.CLIPS`: **Mouth** and **Blink and look**, under **Check it automatically**.

### 10.1 Mouth
- **Opening direction measured:** pose `c_jawbone.x` (or `cc_jaw`) a small step each way; "open"
  moves the lower slit's middle away from the nose along -`across`. (E1: the assumed sign put the
  jaw into the head.)
- **Three openings:** lip gap 0.15, 0.30 and 0.45 x W, by bisection on the controller.
- **Per opening:**
  - rays along the local outward normal into the opening: any that hits the inside of the skin is
    red, "a hole shows inside the mouth". Rays passing out through the far side are fine (7);
  - skin stretch at the corners (`principal_stretch` on the slit's neighbour faces, the clip's
    usual limits);
  - **teeth:** upper teeth vertices stay in the posed mouth (inside the posed original-shape
    proxy, the rest head deformed by the same skinning, and not inside the posed head low). Lower
    teeth move within 5% of the jaw bone at their centre;
  - no crossing faces between lips, teeth and tongue (`crossing_pairs`, shrink 0.98).

### 10.2 Blink and look
- **Close.** Pose the lid controls until the upper rim's middle meets the lower rim's middle 70% of
  the way down (bisection; axes [probe]).
- **Coverage:** rays from in front over the eyeball disc that lie **inside the aperture curve**
  (21 x 21 grid) must hit lid skin before the eyeball on >= 99%. The disc outside the aperture is
  skin at rest and is reported separately.
- **Penetration:** lid vertices in front of the eye's equator stay >= 1.0 r_ball from the centre.
- **Lid stretch, graded against the shape's floor:** p95 of `principal_stretch` over lid-band
  triangles. Green <= 2.0 (`LIMITS["stretch"][1]`). Yellow <= 1.3 x the floor
  `1 + T / (d2 - 0.15 r)`, with the row "Very open eyes: the lids stretch 3x to close". Red above
  that: the weights are worse than the shape needs.
- **Nothing else moves:** skin beyond the lid band (surface distance > d2 from both rims, within
  2.5 r) moves <= 0.05 r. Above that is red: "The brow moves with the blink". This catches ARP's
  heat-map weights as well as Forge's.
- No folds on the lid skin (`crossing_faces`). Half closed (35%): the same tests.
- **Look:** `c_eye.l/.r` turned +-25 deg each way; the eyeball crosses no head face (E3: 0 at all
  four looks on every body) and at least 30% of the iris disc stays visible.
- The computed blink of the 4b gate (sec. 7) uses the same tests.
- Rows, for example: "Mouth opens 3 ways: no tearing, no holes", "Left eye closes: lids cover it".

## 11. Export budget (Step 9)

| Piece | Unreal (30k) | Unity (8k) | From |
|---|---|---|---|
| Mouth bag + inner lips | 8 x slit-loop vertices (E3: 7.9-8.0). Bull-like 38-40 vertices = 300-316; long snout 106-110 = 844-876 | decimated with the head, kit loops protected | Step 4 room |
| Lid margins + pockets, both eyes | E3: 236-326 | with the head | Step 4 room |
| L-step splits on slit and rims | 1 per step (E3: 3-9) | with the head | |
| Rim densify (only when Step 4 had no marks) | 1-2 per added rim vertex | with the head | over budget, shown |
| 2 eyeballs (truncated) | 2 x 190-222 | 2 x about 110 | own objects |
| Teeth (cartoon) | 2 x 116 | 2 x 68 | own objects |
| Teeth (realistic) | about 2 x 400 | about 2 x 200 | own objects |
| Tongue | 140 | 80 | own object |
| **Total (cartoon, bull-like)** | **about 1,350 (4.5%)** | **about 550 (7%)** | |
| **Total (cartoon, long jaw)** | **about 1,900 (6%)** | **about 750 (9%)** | |

- The Step 4 estimate uses the measured mouth-line length / `e_loc` and rim length / `e_loc`, not a
  fixed 50-vertex loop.
- **Unity decimate.** Kit objects are not decimated: their Unity versions are generated at the
  counts above with the same UVs. The head's copy gets the `forge_decimate` group (0 on the slit,
  inner-lip ring, rims and pocket ring 1), `mod.vertex_group = "forge_decimate"`. E2: a weight-0
  band of 64 vertices kept exactly in place at ratio 0.3, 0 of 64 without the group.
- **LODs.** `finalize.lods` decimates every `low` (finalize.py:18-38), which would take a cartoon
  tooth band from 116 to about 29 triangles at LOD2. Kit objects are skipped there; their LOD1/LOD2
  are generated at the Unity counts and at half of them. The head's LODs use `forge_decimate`.
- **ARP export:** `arp_full_facial = True` for Unreal Full face, False for Unity (ARP moves facial
  weights to `head.x` and the jaw). Engine-side code looks for `c_jawbone` and avoids "head" in
  custom names (mouth.md pitfalls 9, 10).
- **Manifest:** `face: {mode, mouth, eyes, teeth, tongue, tris: {unreal, unity}, materials}`.

## 12. The panel (Step 4b box; every row at most 44 characters)

Before Find:
```
Step 4b · Face (mouth, eyes)
Gives the rig a mouth that opens and eyes
that blink and turn. Skip it for a helmet,
a mask or a face that never moves.
[            Find the face            ]
[Skip the face]
```

After Find (bull, sure marks):
```
Mouth: lip line found (red)       [Show]
Eyes: 2 found, round, 27 mm       [Show]
Teeth:             [Teeth]  [No teeth]
The face adds about 1,350 triangles
  (room was kept for it in Step 4)
[           Build the face            ]
[Skip the face]
```

Questions, one at a time in the viewport header, at most 3 in all:
1. **Mouth** (only below sure 0.7): "Is the red line the mouth?" [Yes] [No, I will click it].
   No: "Click the two corners of the mouth." (either order: the mouth is mirrored). With no crease
   between them, the same question goes on: "Now click the middle of the lips." The clicks are
   one question.
2. **Eyes** (only below sure 0.7): "Click the middle of one eye. The other one follows." Painted
   eyes ask instead: "These eyes are painted on." [Make real eyes] [Keep painted]. No left or
   right is ever asked, so the character's left and the screen's left cannot be confused.
3. **Teeth or beak:** "Teeth inside the mouth?" [Teeth] [No teeth]. When the brief says Bird or the
   slit is a hard rim, this question is "Is the mouth a beak?" [Beak] [Lips] instead (a beak has
   no teeth), so the count stays at 3.

After Build:
```
Mouth: cut open, with its inside hidden
  in the head (11 mm from the skin)
Teeth: upper and lower
Tongue: on the floor of the mouth
Eyes: 2 eyeballs that turn, with lids
  (16 points round each eye)
The face added 1,346 triangles
Opening checked: no holes inside
Blink checked: lids cover the eyes
[Show the inside]  [Remove the face]
[          Edit the face           ]
[              Approve               ]
```

Edit the face (6.10):
```
Edit the face. Select on the head, then:
[      Use as the mouth line       ]
[      Use as the eye opening      ]
[        Mouth corner here         ]
Moved the teeth, tongue or an eye?
[         Check the face           ]
[ Fix the face ]  [ Undo last edit ]
```

- **Show the inside** toggles X-ray with the head at 30% alpha, the inside of the mouth in red and
  the kit objects shown.
- A refused piece shows one yellow row with the reason, for example "No room for teeth behind the lips".
- Saved before 1.16: "Face kit not built (made before 1.16)" with **Build the face**.

## 13. What happens to later steps, and re-runs
- **Step 5:** FK5b (6.9): kit objects left out of UVgami and the packer; the slit gap keeps
  `tidy` away; seams on the slit and rims; hidden pieces small.
- **Step 6:** the kit route (sec. 8). `fit_cage`'s cache is cleared at the start of `run_bake`.
- **Step 7:** kit objects can be painted like any low.
- **Step 8:** face mode, options, reference bones, scene properties, bind engine, weights and
  checks (sec. 9-10).
- **Step 9:** sec. 11, LODs included.
- **Recipe:** `forge_face_recipe` on the high: marks, answers, `forge_face_edits`, kit version,
  per-part outcomes ("teeth scaled 0.85").
- **Re-runs and reopen:** one rule (sec. 2): any reopen of Step 4 restores the clean head first;
  after Step 4 is approved again the box offers **Build the face again**, which replays the recipe
  in one click. Nothing is rebuilt without that click.
- **Fix selected after 4b:** the sibling's sec. 10 with the `forge_made` mask: a fix away from the
  face keeps it (4b -> review), a fix near it goes through the reopen rule.

## 14. The RTX 4080 Super
- **Face kit build:** CPU, about a second; bmesh and BVH have no GPU path in Blender's Python API.
- **Finding the face on the 4.9M original:** about 2 s (4.7), all of it C-built BVH and vectorised
  numpy. The one place speed was at stake, v1's per-sample crease field (about 18 s), is replaced
  by the vectorised valley lines (detail-paint 3.3), not moved to the GPU.
- **Step 6:** the eyeball fronts and everything else bake with Cycles on the GPU (OptiX). The
  sibling's X8 checks whether the CPU device should be turned off during the bake.
- **Step 8 checks:** CPU numpy (LBS, rays, BVH), as the existing motion checks.

## 15. Tests

**New test bodies** in `tests/bodies_zoo.py`, a `face_head(kind, scale)` family, voxel-fused and
Taubin-rounded like E1/E3:
1. `muzzle` (bull-like): U mouth crease, two eye bulges with a raised lid ring each.
2. `human`: nearly straight mouth crease, recessed eyes with a lid crease above each.
3. `long_jaw` (new): E3's long snout (muzzle 2.3x along the face axis, U line to +-115 deg).
4. `beak`: a cone beak split by a sharp crease, side eyes.
5. `side_eyes` (new): eyes on the sides of the head (E3 `--side-eyes`; aperture 70-73 deg).
6. `almond` (new): round eyeballs under two lid shells leaving an almond aperture (aspect about
   2.5). Must be built from a finer original than E1's 3 mm voxels: E3's attempt at 2 mm left too
   few points on the visible eyeball for a fit (sec. 18), so this body is 1 mm or a mesh-level lid.
7. `sleepy`: eye caps with a 20 deg vertical aperture.
8. `smile_no_teeth`, 9. `closed_eyes`, 10. `cyclops`, 11. `painted`, 12. `chibi` (W / e = 6),
   13. `helmet`, 14. `open_mouth` (a modelled cavity 0.6 W deep).

Plus `bodies.bull` with the dent repro's groove as a regression body. The low stand-in is
QuadriFlow as in E1/E3, or `fake_qr` where the tests need speed.

**`tests/test_face_marks.py`**

| Test | Asserts |
|---|---|
| `test_mouth_found_on_crease_bodies` | muzzle, human, long_jaw, beak, smile: line within 2 x tol of the truth over >= 90%; corners within 0.08 W; sure >= 0.7 |
| `test_painted_mouth_asks` | painted: found by luminance, sure < 0.7, the question shown |
| `test_eyes_sphere_fit` | muzzle, human, sleepy, side_eyes, almond, beak: centre within 3% r, radius within 3%, RMS <= 1% r (E3: 1.1%, 0.5%, 0.37%; side eyes 0.4%, 0.1%) |
| `test_face_region_is_head_part` | side_eyes and beak eyes are found without a click; long_jaw's mouth line reaches its corners |
| `test_round_by_fit_not_aperture` | almond -> kind ball (round), not shell |
| `test_kinds` | closed -> closed; cyclops -> one mid eye; helmet -> Skip offered first; open_mouth -> open |
| `test_marks_ratios` | marks at x0.01 and x100 equal x1's / scale within 1e-6 relative (marks are measured on the original, no remesh involved) |
| `test_inside_uses_whole_tree` | on all 14 bodies, 200 points round each mouth: the kit's inside test equals parity on the whole original; a crop is never passed (C4) |
| `test_marks_stale` | after changing the high, marks are found again and clicks and edits re-applied |

**`tests/test_face_kit.py`**

| Test | Asserts |
|---|---|
| `test_slit_no_l_steps` | after the slit gates no face holds 3 consecutive slit vertices; with the split off, the bull-like and long_jaw bodies show wall/skin crossings (E3: 2-24), with it 0 |
| `test_mouth_cut_topology` | one loop of 2 x path edges; corners shared; bag manifold; Euler unchanged; no stacked faces |
| `test_bag_inside_and_clear` | every bag vertex inside the whole original with its clearance; 0 wall/skin crossings (E3: 0 on muzzle and long_jaw at x1 and x100) |
| `test_long_jaw_bag` | long_jaw: 0 unplaced, 0 crossings, Euler 2, 0 rays inside the skin at 20 deg (E3) |
| `test_opening_shows_inside` | 20 deg computed jaw: 0 rays hit the inside of the skin on every face body |
| `test_cavity_definition` | a point in the cavity is "in the mouth"; the head's centre and a point in front of the face are not (E3) |
| `test_teeth_tongue_fit` | teeth and tongue built on muzzle and long_jaw; the thin-jaw variant scales, then drops with its row |
| `test_step5_keeps_the_mouth` | after the kit: `doubled_points` 0; `uv._uvgami_ready` returns no fixes; Step 5 on the UVgami path (fake UVgami) and on the Blender path keeps the slit loop count, bag and pocket face counts, and the kit objects' UVs bit-exact; without the gap, `tidy` removes kit vertices (E3: 17 of 132) |
| `test_rim_on_curve` | rim residual against the curve < 2 deg std; worst rim corner >= 20 deg; no L-step on the rim; on sleepy and almond the rim follows the non-round curve |
| `test_pocket_gates` | pocket inside the whole original (>= 0.25 g); 0 crossings with skin, bag, other pocket; eyeball 0 crossings at rest and the 4 looks (E3: 18 of 18 eyes) |
| `test_lid_weights_surface` | the lid rule moves no skin beyond d2 (0.0 r) and covers >= 99% inside the aperture on muzzle, human, almond, at two densities; v1's radial rule moves the brow (E3: 1.47-1.62 r) |
| `test_lid_stretch_floor` | p95 lid stretch <= 1.3 x the floor `1 + T / (d2 - 0.15 r)` on every round eye |
| `test_beak_stiff_halves` | lower beak jaw share 1, upper 0 by surface distance |
| `test_fail_toward_less_change` | forced failures (bag through the chin, eye too coarse, no room behind the eye) leave the head as Step 4 left it (by vertex map) with one row each |
| `test_remove_face` | Remove restores the base copy bit for bit and deletes the kit objects |
| `test_manual_tools` | Use as the mouth line on a hand-picked chain gives a mouth; a self-crossing chain is refused with its row and no change; Use as the eye opening on a selected disc; teeth moved through the lip go back on Check the face; Undo last edit restores bit-exact |
| `test_deterministic` | built twice in one process and in two: identical fingerprints (E3: identical JSON) |
| `test_scale` | x0.01 / x1 / x100 with `fake_qr` (or the x1 low scaled with the original, so every scale has the same low): same pass/fail and the same outcome class per piece; sizes / scale equal within 1e-6. Not "identical counts" across separate remeshes: E1/E3 show QuadriFlow lows differ by scale |
| `test_rebuild_after_step4_rerun` | reopen Step 4 restores the clean head; Build the face again replays answers and edits |
| `test_unity_protected_loops` | the decimate group keeps the slit and rim loops exactly (E2) |
| `test_lods_skip_kit` | `finalize.lods` leaves kit objects at their generated LOD counts |

**Bake, panel, migration, rig tests**
- `tests/test_bake.py`: `high_for` maps kit objects through `forge_kit_of`; one shared kit image;
  `M_<asset>_face` survives the bake; the lip texels' cage push with the kit is within 5% of the
  push without it.
- `tests/test_stage_late.py`: every face row <= 44 characters; 4b buttons by status; a saved file
  with Steps 5-9 approved and no `face` keeps them approved and shows the 1.16 row; `draw_late`
  walks `ORDER`; Change on 4 restores the base and resets 4b; Skip leaves the head untouched; the
  director-path strings pass the jargon list (SPEC_final 10.6).
- ARP (`tests/test_arp_limb_options.py`, `tests/fake_arp.py`): facial payload per mode (every
  unplaced `facial_*` False), scene properties before the bind, kit objects selected for the bind,
  the bind engine choice, the `cc_` fallback.
- **On the director's PC:** `forge arp-probe --only face` (FK0), sec. 16.

## 16. Work packages (S = up to 1 agent-day, M = 2-3, L = 4-5)

**Dependencies and their real state (not "done"):**

| Needed | State on the branch | Until it lands |
|---|---|---|
| Sibling F-core: `Target` (FromObject whole tree), `verify`, transactions, `forge_id`, `forge_made`, Follow crease | design only (DESIGN_fix_tools.md F0-F2) | FK3/FK4 cannot merge; FK1 builds its own FromObject tree with the same guard |
| Detail-paint D2 `make_field`, `creases.auto_lines`, asked-vs-got | design only (DESIGN_detail_paint.md D1-D5) | FK1 uses a local copy of the valley tracer; FK6 waits |
| U10 part map | on `feat/u10-partmap`, not wired | `joints.estimate` + `density.region_labels` |
| `marks.joint_from_click` (rig context WP9-10) | not on the branch | `scene.ray_cast` click |
| Rig context WP2 brief (face row) | not on the branch | FK8 reads `art_style` and `asset_kind` from today's Step 1 |
| Dent fix (mouth-corner notch) | in progress | FK3 tests use the E3 heads, which have no notch |
| ARP face switch on a fresh rig | refused in the probe; rerun pending | the `cc_` fallback (9.5) |

| # | Id | Title | Size | Depends on |
|---|---|---|---|---|
| 1 | FK0 | Director's-PC probe: face switch after `show_ref`; `eyelids_borders_data`; bind with eyeball/teeth/tongue names; **HEAT_MAP vs PSEUDO_VOXELS jaw weights with a bag inside**; jaw and lid control axes; full facial on/off bone lists; `cc_` fallback; UVPackmaster pre-scaled islands (FK-X6) | S | the ARP rerun |
| 2 | FK1 | `face_marks.py`: head-part region, valley lines and mouth score, L_U, corners, normal-seeded residual sphere fit, aperture curve, kinds, hinge and chin, sure, storage | M | detail-paint tracer (or local copy) |
| 3 | FK2 | Step 4b panel: stage `face` in `ORDER`, `draw_late` over `ORDER`, migration in `_on_load`, rows, Show, questions (3), Skip, Remove, reopen restores the base | M | FK1 |
| 4 | FK3 | Mouth: Follow crease call, slit gates (L-step split, monotone), split, measured gap, throat frame and rings, whole-tree placement gate, arc-parameter seam and seam ends, face gate, ray gate, attributes | L | sibling F-core, FK1 |
| 5 | FK4 | Eyes: cut by curve, rim onto the curve with put-back, rim L-steps and count, sunk and truncated eyeball, pocket with clamps and gates, look crossings, eye shell with signed-distance lids | L | sibling F-core, FK1 |
| 6 | FK5 | Teeth, tongue, eyeball meshes per engine; cavity-based fit gates; kit material and atlas UVs | M | FK3, FK4 |
| 7 | FK5b | Step 5: kit objects out of UVgami, the packer and compare; seam guard skips kit faces; seams on slit and rims; hidden islands small; Step 5 tests on both paths | S-M | FK3, FK4, FK0 (UVPM) |
| 8 | FK6 | Step 4: face headroom from measured loop lengths; face region as a `make_field` plan factor; asked-vs-got for the face; guides through the detail-paint encoding | S | FK1, detail-paint D2 |
| 9 | FK7 | Step 6 kit route: `high_for` via `forge_kit_of`; shared kit image with `keep` materials; kit faces masked in `fit_cage` need/room; hidden-mask fills; eyeball-front mask; tests | **L** | FK3-FK5 |
| 10 | FK8 | Step 8 ARP: modes, options, reference bones, scene properties, bind engine choice, eyelid borders, surface lid weights with corner blend, put-back by the new checks, `cc_` fallback | L | FK0, FK3-FK5 |
| 11 | FK9 | Step 8 checks: Mouth and Blink-and-look clips; ray rule; cavity-based teeth check; coverage inside the aperture; stretch graded against the floor; beyond-band displacement; look crossings | M | FK8 |
| 12 | FK10 | Step 9: Unity kit variants, `forge_decimate` (export and LODs), kit objects skipped in `finalize.lods`, `arp_full_facial` per profile, manifest | S | FK5, FK8 |
| 13 | FK11 | 14 face bodies (incl. long_jaw, side_eyes, almond at a finer original), test files, determinism and scale sweeps, director check sheet | M-L | grows with each package |
| 14 | FK12 | Edit the face: Use as the mouth line, Use as the eye opening, Mouth corner here, Check the face, Fix the face, Undo; `forge_face_edits` replay | M | FK3, FK4, sibling F-core operator and undo stack |

**Order:**
1. FK0 and FK1 in parallel; FK2 next to them.
2. FK3 and FK4 once the sibling's F-core lands (FK3 also benefits from the dent fix).
3. FK5, FK5b and FK12.
4. FK6 when the detail-paint field lands.
5. FK7.
6. FK8, then FK9.
7. FK10.
- FK11 grows with each package; the long_jaw, side_eyes and almond bodies must exist before FK3
  and FK4 merge.

**When (lean mode, one builder and one reviewer):**
- The sizes add up to about 38 agent-days (v1 said 20-28; the Step 5 package, the bake route at L,
  the reworked bag and lid frames, the manual tools and three more test bodies add about 10).
- Calendar: after the sibling's F-core lands, the geometry half (FK1-FK5b, FK12) is reviewable in
  about 3 weeks; the bake and rig half (FK7-FK10) about 3 weeks after that, if FK0's probe answers
  are back. That is about 6-7 weeks after F-core, which itself follows the started work in
  PLAN.md's order (finish the started work, then Fix selected and the face kit, then the tool
  bugs, then rigging).

## 17. Risks
1. **ARP's face switch refusal.** Mitigation: the `cc_` fallback (9.5), measured to export.
2. **Mouth corners on the real bull.** E3 resolved the crossings on two test heads by the L-step
   split, but the bull's notch is a different fault (dent). FK-X2: 0 crossings on the bull groove
   and muzzle bodies before FK3 merges.
3. **Lips with triangles.** Each L-step split adds a diagonal on the lip (E3: 3-9). The sibling's
   cut mode should leave few; the row counts them; the dent fix and QR guides (FK-X3) reduce them.
4. **Lid stretch on very open cartoon eyes.** The shape sets a floor of about 3x (sec. 9.4); a
   wider band moves the brow, a narrower one stretches more. Mitigations to measure later: a
   hidden lid fold (an extra loop tucked under the brow at rest that unrolls when the lid closes)
   or ARP's lid tweak bones posed by Step 8. Until then the row says it plainly (yellow).
5. **Very open eyes (> 65 deg aperture) do not close fully** by rotating lids (E3: 88-93% on side
   eyes). Reported, not hidden; a per-azimuth closing did not help (E3).
6. **The eyeball sinks by g.** The visible eye moves in by 8% of its size (12% after the retry).
   The bake keeps the original's iris, and the lid margin then reads as lid thickness. A director
   who dislikes it can keep the eyes as modelled.
7. **Front lid penetration at fine densities** (E3: 3 of 16 eyes at 0.977-0.988 r_ball with
   g = 0.08 r). The gate retries at g = 0.12 r, which cleared all three (1.022-1.033).
8. **Heat-map bind with internal faces** may starve the outer chin of jaw weight. FK0 compares
   PSEUDO_VOXELS; 9.4's put-back covers what remains.
9. **UVPackmaster and pre-scaled islands** (FK-X6). If it rescales them anyway, the hidden pieces
   cost normal texel density (a few percent of the head's texture).
10. **Almond and sleepy eyes are not measured yet.** The fit method handles their shape by design
    (residual growth); the almond body at a finer original is a merge gate for FK4.
11. **Detection false positives** (a scar, a visor slit). The sure score and the question; the kit
    never builds without a visible mark the director can reject.
12. **Bone and draw budget.** Full facial adds about 60-90 bones in Unreal [FK0 counts them]; Unity
    stays small after ARP's weight transfer. One extra material section.
13. **Timing on the PC** is extrapolated (FK-X5).

## 18. Experiments (`fixkit/exp_facekit`), and the gates still needed

**E1, `e1_head.py`** (v1). Cartoon muzzle head (cranium, muzzle, two eye balls of radius 26 mm),
voxel-fused at 3 mm, Taubin-rounded, a 4 mm deep U-shaped mouth crease; QuadriFlow low of 2,661
faces. Results are in v1 (`exp_facekit/DESIGN_face_kit_v1_before_critique.md`, sec. 18); the
critique re-ran it (`exp_crit_facekit/`).

**E2, `e2_decimate.py`.** Decimate with a protected vertex group (64/64 kept at ratio 0.3, 0/64
without); part costs (eyeball 16 x 10 = 288, cartoon teeth 116 / 68, tongue 140 / 80).

**E3, `e3_fixes.py` (= `e3_base.py` + `e3_tail_mouth.py` + `e3_tail_eyes.py`), grid in `e3_grid.sh`.**
E1's head and low, plus the critique's long snout (`--snout 1`), side eyes (`--side-eyes 1`) and an
almond attempt (`--almond 1`). Flags select v1 or the revised rule for each step, so each fix is
measured against what it replaces. 3.6-6.6 s per run. Run twice: identical JSON.

| Step | v1 rule | Revised rule |
|---|---|---|
| Slit, crossings (bull-like x1 / x100) | gated slide, no L-step split: 2 / 4 | L-step split: 0 / 0 (11 of 25 path edges were L-steps; 6 splits) |
| Slit, crossings (long snout) | critic's config: 24, wall gate never converged | 0 |
| Step 5 pre-flight on the cut head | 36 doubled points; `tidy` welded 18, dropped 2, rebuilt 2; 115 of 132 kit vertices left | gap delta = 0.01 e (7x the same-spot tolerance): 0 doubled, `tidy` not run, all kept |
| Stacked faces from the pillowcase | 2 groups at the seam ends | 0 (seam ends welded) |
| Bag on the long snout | lateral-coordinate weld: Euler 0, 1 unplaced | throat frame + arc weld: Euler 2, 0 unplaced, 264/264 inside, 0 crossings, 0 rays inside the skin, 844 triangles |
| Bag on the bull-like head | (v1: 400 triangles, 2 crossings) | 300 triangles (shorter loop after splits), 94/94 inside, 0 crossings, 54/54 rays |
| Cavity point (middle of ring 2) | parity on the head: outside | in the original and not in the head: in the mouth; head centre and a point in front: not |
| Stand-in tooth band in the mouth | 3/72 (bull), 39/168 (snout) | 69/72, 129/168 |
| Eye fit | ring growth: centre 2.5% r, r +1.7%, aperture 49 deg | normal seed + residual growth: 1.1%, +0.5%, RMS 0.37% r, aperture 59 deg |
| Rim against the curve | radial: 5.5-12 deg std | on the curve: 0; worst rim corner 24-42 deg (gate 20) |
| Pocket (rim raised to r + g) | 2-5 pocket vertices outside the original, 8-12 crossings | eyeball sunk by g, rim on the skin, clamped pocket: 100% inside, 0 crossings (18 eyes) |
| Eyeball vs head at rest and 4 looks | (not measured) | truncated eyeball, 190-222 triangles: 0 crossings on all 18 eyes |
| Lid weights | radial: brow moves 1.47-1.62 r | surface, d2 = 0.8 r: brow 0; coverage 100% on round eyes; table in 9.4 |
| Side eyes, 73 deg | | blink covers 88-90% (92-93% inside the aperture at g = 0.12 r); per-azimuth closing gave 94-95% on the round eye, worse than the single rotation's 100% |
| Almond eye | | not measured: at 2 mm voxels the visible eyeball had too few points for the seed fit (normals pointed the wrong way at the slit). Needs a finer original (FK11) |

Each row's JSON is in `exp_facekit/e3_*.json` (`e3_geo08.json` is the default revised run;
`e3_lid_radial.json`, `e3_geo05.json`, `e3_geo12.json`, `e3_geo08_g12.json`, `e3_geo08_f6000.json`,
`e3_geo08_s100.json`, `e3_snout.json`, `e3_side_eyes.json`, `e3_det_a/b.json`). The mouth-only
comparisons (v1 vs revised slit, bag and Step 5) were printed by the same script with
`--bag old`, `--slit-open 0`, `--diag 0`, `--slide 1` and `--relax 4`.

**Gates still needed**

| Gate | Where | What passes |
|---|---|---|
| FK-X1 | PC, FK0 | face switch on after `show_ref`; `eyelids_borders_data` reachable; eyeballs, teeth, tongue skinned by scene names; control axes recorded |
| FK-X2 | here, FK3 | 0 wall/skin crossings on the bull groove and muzzle bodies after Follow crease and the slit gates |
| FK-X3 | PC, with the detail-paint probe | the face plan factor and mouth/rim guides through QR: rim vertex counts and the mouth-line edge follow on the bull, asked vs got |
| FK-X4 | here then PC, FK8/FK9 | jaw open at 3 gaps and blink pass on the bull with ARP's or Forge's weights |
| FK-X5 | PC | Find on the bull's 4.9M original under 5 s; Build under 2 s |
| FK-X6 | PC, FK0 | UVPackmaster 4 keeps pre-scaled kit islands with `normalize_scale` off |
| FK-X7 | here, FK4 | almond and sleepy bodies at a finer original: fit within 3%, rim residual < 2 deg, coverage >= 99% inside the aperture |
| FK-X8 | PC, FK0 | HEAT_MAP vs PSEUDO_VOXELS jaw weight on the outer chin and lips with the bag inside |

## 19. Changes after critique

**High problems: all fixed, each re-measured in E3.**
- **Step 5 welded the mouth shut.** The slit pairs now open by a measured gap
  (`max(0.01 e_loc, 4 x same-spot tolerance)`), so `_uvgami_ready` finds nothing and UVgami's
  position matching is not ambiguous (E3: without the gap 17 of 132 kit vertices lost; with it,
  none). The pillowcase seam ends are welded so no stacked faces reach the pre-flight. A Step 5
  work package (FK5b) takes kit objects out of UVgami, the packer and compare, keeps the seam
  guard off kit faces and packs hidden pieces small. Tests on both Step 5 paths.
- **Lid weights moved the brow.** Replaced by surface distance from the rim, bounded by the brow
  or cheek ridge, with a 0.2 r corner blend. E3: brow movement 1.47-1.62 r -> 0, coverage still
  100% on round eyes. The Blink check and the 4b gate now test lid-band stretch (graded against
  the floor the shape sets) and movement of skin beyond the band. The thresholds were re-measured
  at g = 0.08 and 0.12, two densities and two scales; g = 0.12 is the retry.
- **The bag frame failed on long jaws.** Rings now move each lip vertex towards a throat seam set
  from the mouth's own depth L_U and the room inside the head (one formula that reproduces v1 on
  a frontal mouth); the seam welds by arc parameter. E3 also found that most of the critic's 23-24
  crossings came from L-steps in the slit, now split. Long snout: 0 crossings, 0 unplaced, Euler 2,
  0 rays inside the skin, at x1 and x100. The face region is the head part, so side eyes and long
  mouth lines are in it. The budget scales with the measured loop (8 triangles per loop vertex).
  long_jaw, side_eyes and almond bodies are added and must exist before FK3/FK4 merge.
- **The teeth gate rejected every tooth.** "In the mouth" is now inside the original and not
  inside the head low; the same definition is used in Step 8's teeth check. E3 confirmed both the
  failure (3/72) and the fix (69/72), with a unit test.

**Medium problems: fixed.**
- **Crop parity:** every inside test uses the whole-original tree (sibling `Target`, FromObject,
  about 1.1 s on the bull, cached); crops are for nearest lookups only; a test compares them.
- **Pocket gates:** pocket clamped inside the original with clearance; no crossing with skin, bag
  or the other pocket; the eyeball sinks by g and is truncated past where it can be seen; the
  eyeball is tested against the head at rest and 4 looks. E3: 18 of 18 eyes pass, where the
  raised-rim version left pocket vertices outside and 8-12 crossings.
- **Jagged rim and almond eyes:** cut by the stored curve, rim projected onto it along the
  original's surface and relaxed, put back if a corner drops under 20 deg (E3: residual 0, worst
  corner 24-42 deg). Round versus not is decided by the sphere fit only. The new fit grows by
  residual, so the region takes the aperture's shape. The almond body itself is still unmeasured
  (FK-X7).
- **E1's numbers failed its own gates:** re-measured. Coverage is now counted inside the aperture
  (the critic's suggestion, with the reason that the disc outside it is skin at rest); with the
  sunk eyeball the round eyes reach 99.4-100%. The front-lid gate failed on 3 of 16 eyes at
  g = 0.08 r, hence the retry at 0.12 r, which cleared all three (1.022-1.033 r_ball). Side eyes fail coverage and
  are reported as such.
- **Step 6:** FK7 is now L, with a kit route (high via `forge_kit_of`, one shared image,
  materials kept) and kit faces masked out of `fit_cage`'s need and room, with a 5% test on the lip
  texels.
- **Two owners of the density field:** the kit no longer writes `QR_Density` or calls `boost`; the
  face region is a plan factor in `make_field`, with asked-vs-got recorded for it; guides go
  through the detail-paint encoding. The claim that the ramp gives enough edges is withdrawn until
  FK-X3 measures it.
- **Saved projects and reopen:** migration in `_on_load`; `draw_late` walks `ORDER`; one replay
  rule (reopening Step 4 restores the clean head, and the face is rebuilt only on a click).
- **Scale and timing claims:** `test_scale` asks for the same pass/fail and outcome class on one
  low scaled with the original, not identical counts; the per-sample crease field (about 18 s) is
  replaced by the vectorised valley lines; Find is restated as about 2 s, extrapolated, with FK-X5.

**Low problems: fixed.** Panel rows rewritten in plain words; no left/right question; the beak
question replaces the teeth question; the clicks are counted against the 3-question budget. The
whole-kit gate compares by vertex map and exempts exactly the moved slit, rim and Follow-crease
vertices, with the two-sided surface gate on visible skin. Dependencies are listed with their real
state and fallbacks; kit objects skip `finalize.lods`.

**Missing items: added.** Step 5 package (FK5b); manual face tools (6.10, FK12); long-jaw,
side-eye and almond bodies; surface lid weights and the new Blink limits; pocket gates; rim on the
curve; the bake restructure; migration and the stage tuple; reopen behaviour; one density owner;
the FK0 bind-engine probe (PSEUDO_VOXELS exists in 3.79.17); lids for the eye shell (signed
distance to the shell); a schedule of about 38 agent-days.

**Rejected or changed from the critique's suggestion, with reasons.**
- **Lid band of 0.3-0.5 r.** Measured: 0.5 r covered 97.6% and stretched more (p95 3.5-3.7); 0.8 r
  covered 100% with p95 2.6-2.9. The band is `clamp(0.9 x B, 0.5 r, 0.8 r)`, bounded by the brow
  as the critic asked, but not as short as suggested.
- **"Stretch within the clip's limits".** Not achievable for a full blink of a very open eye: the
  shape sets a floor of about 3x (sec. 9.4). The check grades against that floor and says so in
  plain words, rather than failing every cartoon eye or hiding the stretch.
- **Pocket "nearest face >= r + g/2" everywhere.** Replaced by the direct test (the eyeball crosses
  no head face at rest and at 4 looks) plus truncating the never-seen back of the eyeball. Behind
  the cut there is nothing for the pocket to clear, and the full-sphere version needed the eyeball
  to sink 13% (E3).
- **Skipping the slit in `doubled_points` / `tidy`.** Not done: special-casing Forge's own
  clean-mesh gate would also let a real fault at the mouth through, and UVgami's position matching
  would still be ambiguous. The measured gap fixes both.
- **"0 rays may escape".** Dropped for an opening: a ray passing out through the far side of an
  open long jaw is correct (the head and bag are one closed surface). Holes are rays that see the
  inside of the skin.
- **Per-azimuth lid closing** (tried while fixing coverage): coverage fell to 94-95%; not used.
