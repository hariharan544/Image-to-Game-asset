# Forge universality plan: Steps 4-9 (final, after the judge panel)

Plan file for the lead. The packages are also in `plan_wps.json`, in the same order with the same fields.
Inputs: the zoo baseline (`zoo2/summ.txt`, `bl_fast`, `bl_real`), the three designs (`universal/design_surface.md`, `design_structure.md`, `design_director.md`), the two judge reports, and the rig-context spec (`rig_context/SPEC_final.md`, `wps.json`).

## 0. In plain words

Today Forge's mirror step can quietly copy or delete parts nobody detected: a shoulder pad, a broken horn, a sash, a ponytail, a snake coil, a hand holding a sword.

The plan changes how the decision is made. Forge first measures where the left and right sides really differ, on the surface itself. Everything that differs is kept exactly as modelled, and only matching areas are made symmetric. Nothing is copied or deleted unless you click it.

The plan the panel shows is produced by the same code the run uses, tried out on a copy first. So what you see is what runs. If a run ever comes out different, Forge takes the safer path and tells you in one red line.

A cut can never take a leg or a hand: anything that reaches the ground or is the body itself is refused.

After that comes better part finding (wings, capes and shields in one piece; spikes, fins, tentacles, props), then the skeleton guess: wings, capes and props no longer pull the hips. Then the Step 8 rig card already filled in, point-and-click joints and four-legged animals.

Measured on the test zoo, the target is 782 problem points down to about 380 after the first phase (all mirror damage gone), and to 80 or fewer at the end.

Two things must be checked on your PC before we trust the numbers: speed on your real 5-million-point meshes, and how noisy real AI models are.

## 1. What the baseline says (fast mode, 37 bodies x plain/+ai = 782 points; real mode 379)

| Mechanism | Points (fast) | Bodies |
|---|---|---|
| Mirror copies or deletes undetected parts ('damaged') | 160 | pauldron, horns_asym, sash, ponytail, naga+ai coil |
| Limb cut as a part / limb lost | 40 | weapon_in_hand, shoulder_pauldron |
| Plan != run (the plan says 'separate', split_off refuses) | 54 | one_wing, one_wing_bat, tail_spikes, weapon_up, dorsal_fin_quadruped+ai |
| Symmetry asked, body NOT mirrored | 50 | 16 bodies |
| Quad Remesher X symmetry on with asymmetric parts | 24 | cape, horns, sash, ponytail, pauldron, weapon_up |
| Symmetry blocked needlessly (centred fin) | 12 | dorsal_fin, dorsal_fin_quadruped |
| Loose shell copied or lost 100% (not scored today) | - | bat_wings_shells, quadruped_shells |
| **Step 4 total** | **340** | |
| Skeleton guess off (wings, capes, skirts, props, extra arms) | 116 | 14 bodies; quadrupeds have no skeleton |
| Classified wrong / no class / phantom parts | 43 / 16 / 39 | antlers and cannon as 'ear', legs as 'snout', wings 'back_extra' |
| **Rig total** | **214** | |
| Not found / partly / fragments / merged | 125 / 35.5 / 24 / 43.5 | spikes, halo, skirt, sword; wings in 3-4 pieces; touching tentacles |
| **Detect total** | **228** | |

The zoo's +ai warp is odd in x, so every symmetric body scores asymmetry 0.0000. The tolerance calibration therefore cannot be tested on it; U1 adds an even-in-x noise variant.

## 2. Principles

1. Measure, don't name. Forge decides from measured geometry whether to mirror, protect or cut, and whether Quad Remesher's own symmetry may be on. The measurements are the mirror mismatch, the thickness and the actual cut ring. A detector's name only labels a row and feeds the Rig Brief. Whether a detector found a part never decides whether that part gets damaged.
2. Nothing changes unless the plan says so. The mirror keeps every region that does not match. Nothing is copied or deleted unless the director clicks it, item by item. A label-free postcondition gate (two-sided lost/added between the original and the result) enforces this.
3. One decision, one executor. decide() runs once, in the plan. The same prepare() runs on a copy in the plan and on the backup in the run, and fingerprints prove they did the same thing. The run never decides anything new.
4. Fail toward less change, never more. The order is cut, then keep, then with the body; exact mirror, then keep-around mirror, then none; Quad Remesher symmetry on, then off. Every step down adds a plain-words row. Run is never blocked. A run that differs from its plan takes the safer outcome and says so in one red row.
5. Two versions of the body. Quad Remesher gets the symmetric version (qr_input). Fit, carve, the shape check and the weld get the faithful version (fit_target). The two are identical wherever the sides match.
6. Quad Remesher's X symmetry is on only when its input holds no difference the fit could not put back, i.e. no significant island stays on the body.
7. Tolerances are relative and self-calibrated. The noise floor is 3 x the body's own median mirror distance. Protection resolution comes from the finest export target (30k), and cut / Quad Remesher significance from the chosen budget. Local scale comes from thickness. Results are the same at x0.01 and x100, and no number is set per model.
8. A cut is judged on the ring where it will be made (crease-snapped, shape ratios). A cut never takes a limb: ground terminals plus trunk reachability give a veto.
9. A part joins the body only at its root. Contacts are told apart from roots by geometry. They stay joined in the mesh by default and are split only for skin weights.
10. Universal by descriptors, not kinds. Shape (tube / sheet / blob / shell), attachment (root / slot / along / contact) and symmetry (matched / add-on / differs / posed / off-centre) together cover wings, fins, capes, armour, props and tails.
11. One parts source for Steps 4-9. The ledger travels to the low mesh, the bake, the Rig Brief and the export manifest; Step 8 never re-detects.
12. Determinism first: sorted ids, stable labels, no set order. Any hidden non-determinism shows up as drift, and drift fails safe.
13. Plain words. Every refusal names its measured cause, and every thing Forge found is exactly one row.

## 3. One plan from three designs

### What comes from where

| Area | Taken from | Why (judges' reading) |
|---|---|---|
| Mirror-mismatch field, islands, counterparts | Surface design S1 | Catches everything the zoo scores as damage, including a fused part's bare counterpart patch. No part detector can do that. |
| Pairing by footprint overlap | Director design D1 | Pairs a broken stub with a big horn, where centroid distance does not. |
| Signed residual (sticks out / sinks in) for the class | New, here | Fixes the director design's D2 flaw: a fused pad's bare footprint is itself an island, so 'counterpart is plain body' never holds. |
| Shell census (buried / crossing / touching / loose) | Structure design S0 + director D4 | Cheapest fix for the *_shells bodies (loose shell copied/lost 100% today) and for the halo. |
| Region-preserving displacement mirror; qr_input vs fit_target | Surface design S2 | Topology never changes, so nothing can be copied or deleted, and no surgery means nothing can tear. |
| Fold gate = normal flip + stacked_faces + mesh_defects | Director design D7 | The surface design's BVH self-overlap test would return millions of adjacent-face pairs on a 1M mesh. |
| Two-sided lost/added change gate, coverage per row after Quad Remesher | Director design I2, I7 | Independent, label-free nets. |
| Ledger: decide once, one prepare() executor, fingerprints, Quad Remesher symmetry pinned to the input fingerprint | Director design D5/D6 | Strictest plan == run. |
| Drift = continue with the safer outcome and a red row (not a hard stop) | Surface design S5 | Friendlier, and still safe. Allowed only after the determinism task (U0) is closed and both fingerprints are logged. |
| Ring verdict on the crease-snapped ring | Surface design S4 | No cut ever comes from neck_region's grow-while-thin again, which is what keeps the weapon hand on the arm. |
| Limb guard (ground terminals, reachability, area share) | Director design D3, trunk seed changed | The only design that catches quadruped_shells' 'horn' paint over 94% of the body. Its trunk seed is now the body's thickest point instead of a biped-only box. |
| Posed pairs: the chosen side wins when nothing is kept | Director design D2/D7 | Fixes the surface design's regression: protecting every pose difference would take away what Symmetry Left/Right is for. |
| Thickness/shape part map, per-vertex joint-guess mask | Surface design S8, mask made per vertex | Per-component masking would drop a leg fused to a skirt (the judges' correction). |
| Sub-parts, hollow sheets, girth-or-thickness creases, body-plan matching | Structure design S3-S7 | Used as detection rules and as the R1 research line for WP14/WP15. Not used as the Step 4 vehicle. |
| Through-hand prop cut with a rebuilt grip | Surface design S9 | The director design's 'cut where it leaves the fist' leaves the handle in the hand, so the detachable prop has no grip. |
| Questions inside the rig-context store and its 6-question cap (at most 2 in Step 4) | Director design D9 | One budget, one memory. |
| Lift-off for pads | Director design D12 | Optional, late. It is the only route back to Quad Remesher symmetry for a pauldron. |

### What is dropped, and why
- The structure design's cut-and-zip keep-out mirror. It does topology surgery on every protected boundary, including boundaries that cross the plane, and one failed zipper means no mirror at all.
- The structure design as the Step 4 vehicle. It has 14 packages and would touch 40-70 existing tests. It conflicts with the approved rig-context spec, and its mirror protection depends on node labels. Its proxy, level-set and body-plan ideas move to R1 / WP14 / WP15.
- The director design's 2 x median-edge term in tau. The toy never used it, and at 16 mm it hides a 14 mm sash.
- The director design's stop-the-run on drift. It contradicts 'Run is never blocked'.
- The director design's 35% protected-area cap. The naga would then not be mirrored at all; with the displacement mirror the coil is protected and the rest is mirrored.
- The surface design's rule 'cut any significant island with a feasible ring to keep Quad Remesher symmetry on'. It means more cuts, in Auto too. Here, Auto never cuts just for symmetry.
- The surface design's 'cut and cap contacts by default'. That is a visible geometry change; the default is now to keep them joined and split the weights.
- Grow-while-thin cut candidates (one_sided_parts seeds, neck_region growth) as a source of cuts. They are what cut 18% of the right arm with the sword.


## 4. The Step 4 machine (Phase 1)

### 4.1 Measurements (U2)
- Plane: offset x0 and yaw, robust fit. matched_share < 0.5 means no plane: mode none, and the row gives the share.
- Shells: buried / crossing / touching / loose; self / twin / one-sided. One-sided loose and crossing shells never pass through the mirror.
- Field on about 200k deterministic samples: d = mirror distance with normal agreement; signed s (+ sticks out past the other side).
- Tolerances:
  - noise = median d below the 80th percentile;
  - e_ref = sqrt(A / 15000), the finest export target (Unreal 30k); e = sqrt(A / (budget / 2));
  - tau_keep(p) = max(3 noise, min(0.5 e_ref, 0.25 t(p))).
  - For a ~2 m^2 humanoid (estimate) 0.5 e_ref is about 6 mm at every budget, so a 14 mm sash is protected even at Unity 8k. There 0.5 e is about 11 mm and the sash is only borderline significant.
- Islands: hysteresis 1.5 / 0.75 on f = d / tau_keep, closed and opened 2 rings, minimum area (2 e_ref)^2; hidden islands ignored.
- Significant: depth > max(3 noise, 0.5 e) and area >= 4 e^2. Only significant islands turn Quad Remesher symmetry off, get their own panel row, or become cut candidates. Smaller islands are protected in fit_target and grouped in one row.
- Counterparts by footprint overlap (>= 30%).
- Classes:
  - add-on (island s > 0, counterpart s < 0 or none);
  - both stick out: posed (area, PCA length and thickness within 25%) or differ;
  - off-centre on the middle;
  - loose piece.

### 4.2 Decide, then execute (U3, U4, U6)
Default dispositions:

| Row | Default | Options |
|---|---|---|
| Thin for this budget (2 pi r_stem < 8 e), 'plug' verdict, limb guard ok | cut, remesh alone, weld back (today's tails) | keep with the body |
| Add-on, one side only | keep as it is (protected) | cut it off (if the ring allows), copy to the other side |
| Add-on that is thin for the budget with a 'plug' verdict (a one-sided tail) | cut (today's behaviour) | keep |
| Both sides differ (big horn vs stub) | keep both | use the left/right for both (U18, only if both cut cleanly) |
| Posed pair, nothing else kept (Left/Right) | allow: the chosen side wins (today) | keep its pose |
| Posed pair while something else is kept, or in Auto | keep its pose | make the right like the left anyway (an exact mirror; the row lists what would be copied) |
| Off-centre on the middle (ponytail, sash, coil) | keep as it is | none |
| Loose piece | kept out of the mirror, put back unchanged | none |
| Small differences (not significant) | kept in fit_target, one grouped row | none |
| Held prop (U15) | taken out with a rebuilt grip and a hand socket when the cut is clean, else kept in the hand | leave it in the hand |
| Contact (U11) | stays joined; weights split in Step 8 | separate them (if the waist is clean) |
| Fails the limb guard | not a part: 'looked like a part but is a leg / the body' | none |

In Auto nothing is cut just to keep Quad Remesher symmetry on.

Lattice (finalize, at most 3 rounds, downward only): cut -> keep -> with body; exact -> keep-around -> none; QR on -> off.

Mirror modes:
- exact: density.symmetrize, when no significant island is protected;
- keep-around: the displacement mirror, otherwise;
- none: no plane, or a gate drop.

In exact mode, qr_input is the exact mirror and fit_target is that mirror with the small protected regions projected back onto the original. In keep-around mode both are the displacement mesh, and posed pairs are kept.

Quad Remesher symmetry is on if (Left/Right and qr_input exact) or (Auto and no significant island left). _qr_part checks fp(proxy) == qr_ok_fp before setting it.

### 4.3 Plan == run
- The plan is decide + prepare(copy) + finalize. It stores forge_ledger plus the attributes forge_split, forge_keep, forge_island and forge_ledger_row.
- The run: re-plan if plan_needed, then prepare(backup, ledger), then compare the fingerprints of each piece, qr_input and fit_target.
- On a mismatch, take the safer outcome (part kept in place and protected, QR symmetry off), show one red row and log both fingerprints.
- A body without a plan runs the same two functions.
- A budget change alone re-derives rows and the QR flag without cutting again, unless the thin-for-budget set changes.

### 4.4 Gates
1. Fold: normal flips halve w (3 rounds); stacked_faces and mesh_defects must not grow.
2. Change: two-sided lost/added between the original and fit_target, outside the allow mask.
3. QR symmetry: fingerprint of qr_input.
4. Coverage per row after Quad Remesher (U7).
5. Detachable rows are never welded.


## 5. Detection, skeleton and Steps 6-9 (Phases 2-4)

- **Part map (U10).** Thickness, core and per-vertex shape give parts in one piece (a membrane with its finger bones is one wing) and sub-parts one level down (spikes on a tail, horns and spikes on a head). Descriptors (flatness, elongation, taper, tips, root position) feed the classes. 'Thin for budget' reproduces today's cut set.
- **Attachments (U11).** One root per part; other loops are contacts; 'along' parts (pads, straps) are never cut. Fused parts with two roots are split for labels only. Hollow sheets (skirt) are not contacts.
- **Classes (U12).** Wing, fin, cloth, ear, horn, antler, tail / tentacle / trunk, spike, armour/plate, prop and extra arm come from descriptor rules with margins (sure). Old kind strings stay as aliases.
- **Skeleton.**
  - U13: interim per-vertex mask on today's estimator.
  - WP4: v2 with the same mask as pass 1.
  - WP10: point-and-click joints for everything else.
  - WP13: guided quadrupeds; WP14: the quadruped estimator (with R1 if gated in); WP15: bird, snake, more arms.
- **Steps 6/8/9.**
  - U14: the ledger travels to the low, the bake source per region and the manifest.
  - WP8: every chain-like row rigged, rigid rows stiff.
  - U15 + WP11: detachable props with a rebuilt grip and a socket.
  - U17: contacts split for weights and reported by the motion check; every row gets one Step 8 outcome.

## 6. Work packages in priority order

Order = priority: silent damage first (P1), then detection (P2), then skeleton and rig (P3), then Steps 6/8/9 and the quality options (P4).

Waves (`parallel_group`) are the build schedule. A package starts when its dependencies are done. Packages in the same wave touch different files, so they can be built at the same time; a later-phase package in an early wave never delays an earlier-phase one. Phase-4 packages and R1 are held until wave 5, after the Phase-1 exit gate.

| # | Id | Phase | Title | Effort | Depends on | Wave |
|---|---|---|---|---|---|---|
| 1 | U0 | P0 | Deterministic Step 4 path (closes open task 49) | M | - | W0 |
| 2 | U1 | P0 | Zoo v2: the harness reads the product's own decisions, plus the bodies today's zoo cannot test | M | - | W0 |
| 3 | WP0 | P0 | [rig context] Probe Auto-Rig Pro 3.79.17 on the director's PC | S | - | W0 |
| 4 | WP1 | P0 | [rig context] Section and ray tools (pure numpy) | M | - | W0 |
| 5 | WP2 | P0 | [rig context] Rig brief schema, body-plan templates, plan builder | M | - | W0 |
| 6 | U2 | P1 | Mirror-match field, islands, classes and shell census (new symmetry.py) | M | U1 | W1 |
| 7 | U3 | P1 | Limb guard: a veto on every region Forge cuts, protects, paints or makes rigid (new limb_guard.py) | S | U1 | W1 |
| 8 | U4 | P1 | One cut verdict, measured on the actual crease-snapped ring (new rings.py) | M | U0 | W1 |
| 9 | U5 | P1 | Keep-around mirror: region-preserving displacement, two outputs, fold and change gates | L | U2 | W2 |
| 10 | U6 | P1 | The ledger: one decision, one executor for plan and run, Quad Remesher symmetry from the field | L | U0, U2, U3, U4, U5 | W3 |
| 11 | U7 | P1 | Faithful fit target in the remesh, and coverage per row after Quad Remesher | M | U6 | W4 |
| 12 | U8 | P1 | Step 4 panel: Left-right check rows, Show differences, preview of the real prepared mesh, Run label, plan vs result | M | U6 | W4 |
| 13 | U9 | P1 | Measure Step 4 on the director's PC (timing and real noise) and cache the dry run | S | U6 | W4 |
| 14 | U10 | P2 | Thickness and shape part map (new partmap.py): core, parts in one piece, sub-parts, joint-guess mask | L | U1 | W1 |
| 15 | U11 | P2 | Attachments: root, slot root, along, contact; fused parts split for labels; contacts stay joined | L | U4, U10 | W2 |
| 16 | U12 | P2 | Classes and plain names from descriptors; the ledger's candidates come from the part map | M | U6, U10, U11 | W4 |
| 17 | U13 | P3 | Interim skeleton fix: the joint guess ignores wings, capes, skirts, props and loose shells | S | U2, U10 | W2 |
| 18 | U14 | P3 | The ledger travels: low mesh, bake source per region, export manifest | M | U6, U12 | W5 |
| 19 | WP3 | P3 | [rig context] Measurements that fill the card, pre-filled from the Step 4 ledger | M | WP1, WP2, U6 | W5 |
| 20 | WP4 | P3 | [rig context] Joint estimator v2, with pass 1 = the part-map exclusion | L | WP1, WP2, U13 | W5 |
| 21 | WP5 | P3 | [rig context] Steps 1-2: notes, height meaning, facing | S | WP3 | W6 |
| 22 | WP6 | P3 | [rig context] Auto-Rig Pro limbs from the plan, hinge check after build, export type | L | WP0, WP2, WP4 | W7 |
| 23 | WP7 | P3 | [rig context] Step 8 card and flow; place_joints reads the ledger rows | M | WP2, WP3, WP4, WP6, U14 | W8 |
| 24 | WP8 | P3 | [rig context] Extra parts from the brief: every chain-like row rigged, rigid rows stiff | M | WP0, WP6, WP7, U12 | W9 |
| 25 | WP9 | P3 | [rig context] Joint checks and the question list (Step 4 questions count inside the 6) | M | WP4, WP7, WP8 | W10 |
| 26 | WP10 | P3 | [rig context] Point-and-click answering, overlay, memory, Point and tell (also on Step 4 rows) | L | WP1, WP6, WP9 | W11 |
| 27 | WP11 | P3 | [rig context] Props as sockets (grip frames from Step 4 detached props) | M | WP0, WP6, WP7 | W12 |
| 28 | WP12 | P3 | [rig context] Test failures point back to a joint | S | WP10 | W13 |
| 29 | R1 | P3 | Structure research line: core ring and exact level-set loops on a proxy (numpy, not wired into the product) | M | WP1 | W5 |
| 30 | WP13 | P3 | [rig context] Four-legged animals, guided mode (template pre-filled from the part map) | L | WP0, WP6, WP10, U12 | W14 |
| 31 | WP14 | P3 | [rig context] Four-legged estimator (legs from ground columns and part-map tubes; R1 loops if gated in) | L | WP4, WP13, U10, R1 | W15 |
| 32 | WP15 | P3 | [rig context] Bird (gated), snake, more arms (rows from the part map) | M | WP13, U12 | W16 |
| 33 | U15 | P4 | Held props: through-hand cut with a rebuilt grip and a socket frame (new props.py) | L | WP1, U2, U4, U6, U10 | W6 |
| 34 | U16 | P4 | Wedge plug for slot roots (wings, fins, sails) | M | U4 | W5 |
| 35 | U17 | P4 | Contacts in Step 8: weights split at contacts, motion-check rows, every row gets a rig outcome | M | U11, U14, WP8 | W10 |
| 36 | U18 | P4 | 'Use this side for both' for twins that differ | M | U6, U16 | W7 |
| 37 | U19 | P4 | Lift-off for pads lying on the body: Quad Remesher symmetry back for pauldron, shield, cannon (optional) | L | U5, U6, U7 | W8 |
| 38 | WP16 | P4 | [rig context] Optional local AI read of the concept + Tripo body type (built last) | M | WP2, WP7 | W16 |
| 39 | WP17 | P4 | [rig context] Acceptance on the director's PC (plus the Step 4 checks) | S | WP7, WP8, WP9, WP10, WP11, WP12, U9 | W14 |

**Waves**

- W0: U0, U1, WP0, WP1, WP2
- W1: U2, U3, U4, U10
- W2: U5, U11, U13
- W3: U6
- W4: U7, U8, U9, U12
- W5: U14, WP3, WP4, R1, U16
- W6: WP5, U15
- W7: WP6, U18
- W8: WP7, U19
- W9: WP8
- W10: WP9, U17
- W11: WP10
- W12: WP11
- W13: WP12
- W14: WP13, WP17
- W15: WP14
- W16: WP15, WP16

## P0: Groundwork: determinism, a harness that reads the product's decisions, rig-context foundations

### U0 - Deterministic Step 4 path (closes open task 49)

*Effort M; depends on nothing; wave W0.*

**Modules**

- `blender_scripts/forge_bpy/rescue.py` (split_off, _hide_plugs, _drop_cut_scraps, _loops_of: ordered iteration)
- `blender_scripts/forge_bpy/parts.py` (grow_parts, _finish_part: no set order, stable argsort)
- `blender_scripts/forge_bpy/appendages.py` (_components labels canonical, _name order)
- `blender_scripts/forge_bpy/retopo.py` (_qr_one: sorted split names)
- `blender_scripts/forge_bpy/density.py` (write_split/read_split, _dilate; new fingerprint(me))
- `tests/test_determinism.py` (new)

**Technique**

Audit every set/dict iteration, np.unique, argsort and component labelling on the plan -> cut path and make it order-free:
- component labels renumbered by their smallest vertex index; argsort(kind='stable'); sorted part ids everywhere; no iteration over Python sets;
- sampling by fixed stride (parts._sample) or seeded generators only;
- new density.fingerprint(me) = (nv, nf, sha1 of coordinates rounded at 1e-6 x size, sha1 of face indices). U6 uses it for the plan == run proof.
This is a precondition for U6: a hidden order effect must not be mistaken for plan drift.

**Zoo bodies:** tail_spikes, weapon_up, one_wing, one_wing_bat, dorsal_fin_quadruped, two_tails, trunk

**Acceptance**

- plan_parts + split_off run twice (same process, and in two subprocesses) on all 37 zoo bodies x {auto, left, right} give byte-equal forge_split, forge_plan and piece fingerprints.
- The order-dependent tail-root test passes in forward, reversed and isolated order.
- Behaviour unchanged: zoo totals stay 782.0 fast / 379.0 real; the full existing suite stays green.

**Tests**

tests/test_determinism.py: twice-in-process, subprocess, reversed collection order (conftest flag). Existing test_appendages and test_retopo_shape unchanged.

### U1 - Zoo v2: the harness reads the product's own decisions, plus the bodies today's zoo cannot test

*Effort M; depends on nothing; wave W0.*

**Modules**

- `tests/zoo_baseline.py`
- `tests/bodies_zoo.py`
- `tests/test_zoo_bodies.py`

**Technique**

Harness:
- dry_run calls the product's plan and executor (ledger.decide / ledger.prepare once U6 exists). Until then a shim calls today's rescue.split_off + density.symmetrize, so today's numbers reproduce.
- Auto's Quad Remesher flag is read from the product (ledger qr_symmetry, else low['forge_symmetry_x']), not recomputed as asymmetry < 0.10.
- 'Mirrored' means mode exact OR keep-around (the region-preserving mirror).
- A truth part covered >= 60% by one ledger row counts as found, so measured islands (sash, pauldron, horn stub, coil, sword, halo) count as detection.

New columns (baseline.json and summ.txt):
- unplanned_change, label-free, with the harness's own tau logged next to the product's: original vertices farther than tau from the faithful result, plus result vertices farther than tau from the original, as islands minus the ledger's allowance mask;
- plan_drift (fingerprint mismatch between plan and run);
- island recall on one-sided / pair_asym / centre_asym truth parts; false protection on pair and centre parts;
- limb share of every region the product cuts, protects, paints or makes rigid;
- mirror residual on the matched core;
- loose shells (shell_loose_*) lost/copied, scored like one-sided parts.

New score lines: 'unplanned change' +8, 'plan fingerprint != run' +3, 'action region takes a limb' +5, 'loose piece copied or lost' +4, 'quadruped skeleton off' +4 (joints_hint, 0.08 H).

New bodies, scored in a separate 'zoo v2' total so 782/379 stays comparable:
- humanoid_raised_arm: a fused pair_posed limb (arm_dz 0.2);
- pouch_small: a fused one-sided pad, 25 mm proud, 8 x 6 cm, on the hip;
- relief_scar: a 3 mm one-sided relief, which must NOT get its own protected row;
- the '+ain' variant: AI warp with an even-in-x component (2-4 mm, seeded). Today's warp is odd in x, so every symmetric body scores asymmetry 0.0000, and noise calibration cannot be tested.

**Acceptance**

- On the current product the totals reproduce exactly: fast 782.0 (step4 340 / rig 214 / detect 228), real 379.0. Every per-body problem list is identical.
- The new columns are present. Zoo v2 bodies build with truth labels. On +ain every symmetric body shows asymmetry > 0.
- test_zoo_bodies passes, including the new bodies' truth checks.

**Tests**

test_zoo_bodies.py: new bodies' truth labels; +ain warp not odd in x; shim parity (a stored baseline record re-scores to its stored score).

### WP0 - [rig context] Probe Auto-Rig Pro 3.79.17 on the director's PC

*Effort S; depends on nothing; wave W0.*

**Modules**

- `blender_scripts/forge_bpy/addon_trial.py`
- `docs/research/arp_3_79_probe.json`
- `tests/test_arp_probe_schema.py`

**Technique**

As rig_context/wps.json WP0, scope unchanged. Added: record whether arm_wings and arm duplicates survive build and export. This gates wings as arm duplicates (WP8, WP15). It runs early because WP6, WP8, WP11, WP13 and WP15 read its JSON.

**Acceptance**

As wps.json WP0: the probe writes docs/research/arp_3_79_probe.json on the director's PC, and the schema test passes (skipped when the file is absent).

**Tests**

tests/test_arp_probe_schema.py (exists; extended with the arm_wings keys).

### WP1 - [rig context] Section and ray tools (pure numpy)

*Effort M; depends on nothing; wave W0.*

**Modules**

- `blender_scripts/forge_bpy/sections.py` (new)
- `tests/test_sections.py`

**Technique**

As wps.json WP1, scope unchanged. Scheduled early because U4 (rings.py) reuses loop_props (vector area, PCA aspect, area radius) and U15 (props.py) reuses profile_along and crease_along (area jump ratio 1.8).

**Acceptance**

As wps.json WP1: cut_cylinder, loop_contains, crease_arm_into_box (same at x0.01 and x100), narrowest_wrist_ball, bend_along, ray_spans and inside_parity all pass.

**Tests**

tests/test_sections.py (pure numpy, as specified).

### WP2 - [rig context] Rig brief schema, body-plan templates, plan builder

*Effort M; depends on nothing; wave W0.*

**Modules**

- `blender_scripts/forge_bpy/rig_brief.py` (new)
- `blender_scripts/forge_bpy/body_plans.py` (new)
- `tests/test_rig_brief.py`

**Technique**

As wps.json WP2. Changes:
- brief parts[] gain 'desc' (shape: tube / sheet / blob / shell; attach: root / slot / along / contact; sym: matched / add-on / differs / posed / off-centre) and 'step4' {row id, disposition}, so Step 4's measured facts arrive pre-filled;
- body_plans templates get a match(parts) score over descriptors (two ground-reaching tube twins on the lower core = legs, etc.; the idea is from the structure design). WP3 uses it to pre-fill 'What is it' with a sure value.

**Acceptance**

As wps.json WP2 (merge_precedence, plan_bull, plan_quadruped, plan_snake_bird, extra_ears, chain_bones_scale_free), plus: match() scores the zoo quadruped as quadruped and four_arms as multi-arm from hand-written descriptor fixtures.

**Tests**

tests/test_rig_brief.py (as specified, plus the descriptor match cases).

## P1: Stop silent damage in Step 4: mirroring, plan != run, cuts that take limbs

### U2 - Mirror-match field, islands, classes and shell census (new symmetry.py)

*Effort M; depends on U1; wave W1.*

**Modules**

- `blender_scripts/forge_bpy/symmetry.py` (new: fit_plane, shells, field, islands, classify)
- `blender_scripts/forge_bpy/density.py` (mirror_plane gains yaw; asymmetry, straddles_middle kept as wrappers)
- `tests/test_symmetry_field.py` (new)

**Technique**

Plane:
- Coarse-to-fine fit of offset x0 and yaw about Z on the median nearest-surface distance of a 4k mirrored sample. This extends density.mirror_plane.
- matched_share = share of samples within 3 x that median. Below 0.5 there is no plane: mode none, with the share in the row.

Shells (shell census from the structure design):
- face-graph components; each non-main shell gets a 3-ray parity vote on <= 200 points: buried / crossing / touching / loose;
- a mirror test then classes it self / twin / one-sided. One-sided loose and crossing shells never enter the mirror.

Field (budget-free protection level):
- about 200k deterministic voxel samples (first vertex per cell, cell = sqrt(area / 200k));
- d = |find_nearest(mirror(p)) - mirror(p)|; normal agreement mirror(n_p) . n_hit > 0.3, otherwise unmatched;
- signed s = sign((mirror(p) - hit) . n_hit): + means it sticks out past the other side;
- noise = median d over the samples below the 80th percentile;
- e_ref = sqrt(A / 15000), the quad edge of the finest export target (Unreal 30k); e = sqrt(A / (budget / 2)) for this run;
- tau_keep(p) = max(3 noise, min(0.5 e_ref, 0.25 t(p))), with t from parts.thickness only where d > 3 noise. f = d / tau_keep.

Islands:
- hysteresis: seeds f > 1.5, grow while f > 0.75 on the edge graph (appendages._components); close and open 2 rings (density._dilate);
- drop islands smaller than (2 e_ref)^2; hidden islands (inside another shell) never count;
- each records side (+X / -X / straddles), area, depth, extent, s-share, and where-words (region_labels when the joints pass, else height third + side + front/back);
- significant at THIS budget: depth > max(3 noise, 0.5 e) and area >= 4 e^2.

Counterparts by footprint overlap (director design): footprint = vertices within 2 median edges of the mirrored island points. Two islands pair at 30% overlap either way. This pairs a stub with a big horn, where centroid distance does not.

Class (sets the wording and the default; the geometry decides):
- off-centre on the middle (straddles the plane): ponytail, sash, coil;
- add-on on one side (island s > 0, counterpart s < 0 or none): pauldron, wing, cannon, shield, sword;
- both sides stick out: posed when area, PCA length and mean thickness agree within 25% (raised arm, tentacle pose), otherwise 'differ' (big horn vs stub);
- loose piece.

**Zoo bodies:** shoulder_pauldron, horns_asym, sash_diagonal, ponytail_side, naga, naga_shells, weapon_in_hand, weapon_up, one_wing, one_wing_bat, shoulder_cannon, forearm_shield, loadout, cape, tentacles, tentacles_shells, bat_wings_shells, quadruped_shells, held_staff

**Acceptance**

Recall: islands cover >= 80% of the zoo's mirror-off vertices of every one-sided / pair_asym / centre_asym truth part, plain, +ai and +ain:
- pauldron_l; horn_l distal half and horn_r stub cap; sash; ponytail;
- snake coil; wing_l (one_wing, one_wing_bat); cannon_l; shield_l;
- sword_r; blade_r; staff; halo; the zoo v2 pouch.

False protection: significant protected area < 2% on bat_wings(_shells), bird_wings, four_wings, winged_tail, dorsal_fin(_quadruped), trunk, antlers, hair_spikes, back_spines, skirt, four_arms, chibi, back_hair, dragon, tail_spikes and two_tails, plain, +ai and +ain.

Classes:
- add-on: pauldron, cannon, shield, one wing;
- differ: horns_asym;
- posed: humanoid_raised_arm;
- off-centre: ponytail, sash, coil;
- no island: dorsal fin;
- the loose shells and the halo are classed loose.

Robustness: same islands at x0.01 and x100 and on a body yawed 3 degrees; under 3 s on an 80k-vertex zoo body.

**Tests**

tests/test_symmetry_field.py: pure part on the numpy toys (universal/mirror_toy*.py, director/gate_check.py) with the same verdicts as those toys; bpy part on zoo bodies (recall, false protection, scale and yaw invariance).

### U3 - Limb guard: a veto on every region Forge cuts, protects, paints or makes rigid (new limb_guard.py)

*Effort S; depends on U1; wave W1.*

**Modules**

- `blender_scripts/forge_bpy/limb_guard.py` (new)
- `tests/test_limb_guard.py` (new)

**Technique**

Terminals:
- ground-contact clusters: z < ground + 0.03 H, clustered on a 0.02 H grid, >= 0.1% of the vertices. WP3 imports this same function, so there is one implementation;
- hand tips and head top, only once rig-context joint_check passes for those markers;
- the director's marks.

Trunk seed: the vertex of greatest shape diameter in a 2k deterministic sample (parts.thickness), i.e. the body's thickest point. Not a fixed box: the judges showed the box seed was biped-only.

check(R) fails when:
- R contains a terminal (dilated by the local radius); or
- a BFS from the trunk seed that avoids R misses a terminal; or
- R's area share exceeds one part's allowance (cut 15%, a single kept row 35%; ratios of the body).

A detection that fails is not a part. It is listed under 'looked like a part but reaches the ground / is the body (ignored)'.

Non-standing pose (no ground cluster, or more than 6): the guard refuses any cut above 5% of the body. This is conservative.

**Zoo bodies:** one_wing, one_wing_bat, quadruped, quadruped_shells, dorsal_fin_quadruped, held_staff, weapon_in_hand

**Acceptance**

- No region the product cuts, protects as a row, horn-paints or makes rigid holds >= 5% of a truth limb (new harness column), on every zoo body and side.
- Today's offenders are refused with a plain reason: one_wing 'extra' (both legs + 32% of the body), quadruped 'snout_l/r', quadruped_shells 'horn_l' paint (94% of the body), held_staff 'back_extra', and the weapon_in_hand one-sided cut.
- Ground terminals found: biped 2, quadruped 4, naga 1, tentacles >= 3.
- Same verdicts at x0.01 and x100.

**Tests**

tests/test_limb_guard.py on bodies.biped (tail accepted) and zoo bodies (one_wing extra refused, quadruped legs refused).

### U4 - One cut verdict, measured on the actual crease-snapped ring (new rings.py)

*Effort M; depends on U0; wave W1.*

**Modules**

- `blender_scripts/forge_bpy/rings.py` (new: loops, snap_to_crease, measure, verdict)
- `blender_scripts/forge_bpy/parts.py` (_finish_part ring tests replaced by rings.verdict)
- `blender_scripts/forge_bpy/appendages.py` (cut_ok from the verdict)
- `tests/test_rings.py` (new)

**Technique**

Rings:
- chain the region's boundary edges into loops;
- snap each loop to the concave crease in a +-3 ring band (Dijkstra, edge cost length x exp(-beta x concavity), concavity from smoothed normals as in density._detail_one). Fall back to the unsnapped loop.

Metrics (loop properties from sections.loop_props once WP1 is in):
- number of loops; Q = 4 pi A / L^2; aspect; inscribed width (distance transform on a 96^2 raster); planarity; star (rescue._star_radial); monotone;
- slant against the part axis or sheet plane; neck (length beyond the ring plane / inscribed width); room (inward ray depth / r_eq);
- core: the region holds vertices thicker than 0.5 x parts.trunk_thickness, or a U3 limb terminal. This becomes partmap's core once U10 lands.

Verdict: plug / slot / shell / none, plus the first failing reason in plain words:
- 'it takes part of the body itself';
- 'it is joined to the body in N places' / 'it passes through the hand';
- 'its root lies along the body';
- 'it sits flat on the body: no neck to cut at';
- 'too little body under it to hide the joint';
- 'its root is too irregular to cut cleanly'.

All thresholds are shape ratios, calibrated once on the zoo and then frozen. split_off's own closed-piece and _plug_faults tests stay the final word; the plan runs split_off for real (U6).

**Zoo bodies:** one_wing, one_wing_bat, weapon_up, tail_spikes, dorsal_fin_quadruped, weapon_in_hand

**Acceptance**

- Pure tests on synthetic loops (round, oval, slot, ragged, crescent, root leaving sideways) reproduce the ring_check.py table.
- On the zoo, no 'plug' verdict contains core vertices or a limb terminal; the verdict agrees with split_off on >= 95% of candidates.
- The sword in the fist reads 'it passes through the hand' (2 loops), so the hand stays on the arm.
- The tails of two_tails, trunk, dragon and quadruped stay 'plug', so today's welded cuts do not regress.

**Tests**

tests/test_rings.py: pure synthetic loops; bpy agreement with split_off on zoo candidates.

### U5 - Keep-around mirror: region-preserving displacement, two outputs, fold and change gates

*Effort L; depends on U2; wave W2.*

**Modules**

- `blender_scripts/forge_bpy/symmetry.py` (protect_weights, apply, gate)
- `tests/test_symmetry_apply.py` (new)

**Technique**

Protected set P:
- every island at the protection level (significant or not) plus its counterparts;
- lids (forge_rim) plus their mirror counterparts;
- minus the rows the director allowed (posed pairs, later 'use this side for both').
w = 0 on P, rising to 1 by smoothstep over geodesic 2 tau (edge relaxation with np.minimum.at, capped iterations).

Displacement:
- BVH of the kept side's faces whose vertices all have w = 1;
- for each overwritten vertex with w > 0: target = mirror(find_nearest(mirror(v))), v' = v + w (target - v);
- a target farther than 1.5 tau_keep sets w = 0, so the band grows by itself;
- core vertices within tau of the plane snap to it;
- topology never changes, so nothing can be copied or deleted.

Two outputs:
- exact mode (no SIGNIFICANT island protected): qr_input = density.symmetrize. fit_target = that mirrored mesh with the protected (small) regions projected back onto the original surface: v' = v + (1 - w)(nearest_original(v) - v). Allowed posed rows are not protected, so they stay mirrored in both;
- keep-around mode: qr_input = fit_target = the displacement mesh. Allowed posed rows are downgraded to keep here (decision 2), because the displacement cannot re-pose a limb.

Fold gate (the judges asked for this instead of a BVH self-overlap test):
- a face whose normal flips (n_new . n_old < 0) halves w on its vertices, up to 3 rounds;
- after that, rescue.stacked_faces and rescue.mesh_defects must not increase;
- otherwise the mirror drops one step, with the row 'making it symmetric would fold the surface near <where>: kept as it is'.

Change gate (director design invariant I2):
- two-sided comparison of original and fit_target: lost = original vertices farther than tau from fit_target; added = the reverse;
- an island of area >= (2 e_ref)^2 outside the allow mask drops the mirror one step, with the reason.

Shells: one-sided loose and crossing shells are taken out before and put back unchanged after, with index bookkeeping. Above about 1M vertices the per-vertex find_nearest runs inside the job, with progress.

**Zoo bodies:** shoulder_pauldron, horns_asym, sash_diagonal, ponytail_side, naga, naga_shells, weapon_in_hand, dorsal_fin, dorsal_fin_quadruped, cape, tentacles, tentacles_shells, forearm_shield, loadout, shoulder_cannon, one_wing, one_wing_bat, bat_wings_shells, quadruped_shells

**Acceptance**

Through the U1 harness's apply step (fast, Left and Right, plain / +ai / +ain):
- every one-sided / pair_asym / centre_asym truth part: lost <= 5% and copied <= 5%;
- loose shells: lost and copied 0;
- matched-core mirror residual < tau_keep; 0 flipped faces; open_edges 0;
- keep_as_is_check.py becomes a pure test: inside P 0 mm; outside P the median residual goes 1.59 -> 0 mm; 0 flips;
- a lid off the middle (the _lids_mirror_onto_skin case) is mirrored with no dent;
- a forced full mirror on shoulder_pauldron is caught by the change gate;
- exact mode on humanoid_raised_arm (posed pair allowed): fit_target has the arm mirrored; relief_scar stays as modelled in fit_target.

**Tests**

tests/test_symmetry_apply.py: pure toy; bpy on zoo bodies; an injected fold reverts with its reason; the change gate catches a forced full mirror.

### U6 - The ledger: one decision, one executor for plan and run, Quad Remesher symmetry from the field

*Effort L; depends on U0, U2, U3, U4, U5; wave W3.*

**Modules**

- `blender_scripts/forge_bpy/ledger.py` (new: decide, prepare, finalize, rows, fingerprints)
- `blender_addon/forge_send/steps.py` (plan_parts -> ledger; plan_needed; prepare_retopo reads the ledger's QR flag; prepare_maps)
- `blender_scripts/forge_bpy/retopo.py` (_qr_one pre-remesh block -> ledger.prepare; _qr_part pins symmetry_x; _symmetric_part, _lids_mirror_onto_skin and the run-time one_sided_parts fallback removed)
- `blender_scripts/forge_bpy/density.py` (one_sided_parts, asymmetry, straddles_middle kept as thin wrappers for fixtures)
- `tests/test_ledger.py` (new)
- `tests/test_retopo_shape.py` (rewrites)
- `tests/test_appendages.py` (plan-row rewrites)
- `tests/test_stage_late.py` (QR-flag rewrites)

**Technique**

decide(me, side, budget, answers), in the mirror frame:
1. plane (U2), 2. shells (U2), 3. field, islands and classes (U2).
4. Candidates:
   - thin-for-budget parts (2 pi r_stem < 8 e, retopo.ROUND_EDGES) from today's appendages.find; partmap after U12;
   - one-sided add-on islands with a tube stem;
   - loose shells.
   Each goes through limb_guard.check (U3) and rings.verdict (U4).
5. Default dispositions:
   - thin part + 'plug' + guard ok: cut (today's tails);
   - add-on: keep, and cut only when it is thin for the budget AND 'plug' (today's one-sided tail);
   - differ: keep both;
   - posed: allow (the chosen side wins) when no row is kept; otherwise keep, with [Make the right like the left anyway];
   - off-centre: keep;
   - loose shell: out of the mirror;
   - small differences: kept in fit_target, as one grouped row;
   - in Auto nothing is cut just to keep Quad Remesher symmetry on.
   Director answers override any default.

prepare(me_copy, ledger) is the executor and detects nothing: shells out -> rescue.split_off(cut ids) -> protection weights (+ lids) -> U5 apply in the ledger's mode -> gates -> shells back -> fingerprints (density.fingerprint) of the input, each piece, qr_input and fit_target.

finalize (at most 3 rounds; it only moves down the lattice cut > keep > with body, exact > keep-around > none, QR on > off):
- a refused cut becomes keep (protected), with split_off's words;
- a gate violation moves one mode down, with its row;
- QR symmetry = (Left/Right and qr_input exact) or (Auto and no significant island left); qr_ok_fp = fp(qr_input).

Plan: plan_parts = decide + prepare(copy) + finalize. It stores:
- forge_ledger (JSON): v, side, budget, input_fp, answers, frame {x0, yaw, noise, tau_keep, e}, rows [{id, where, words, class, desc, disposition, default, options, why, dry}], ignored, mirror {mode, why}, qr_symmetry {on, why}, dry {fps, gates, seconds};
- attributes forge_split, forge_keep, forge_island, forge_ledger_row.

plan_needed changes on input_fp, side, answers, decide_version, or a change in the thin-for-budget set. A budget change alone only re-derives the rows and the QR flag; it does not cut again.

Run:
- _qr_one re-plans first (in the job) when plan_needed;
- calls prepare(backup, ledger) and compares fingerprints;
- on a mismatch it continues toward less change: the part that did not cut is kept in place and protected, QR symmetry goes off, and a red row says 'Planned: cut the tail. It did not cut at run time: kept in place, nothing copied or deleted.' Both fingerprints are logged (plan_drift);
- a body with no plan runs decide + prepare (the same functions);
- _qr_part sets symmetry_x only when fp(proxy) == qr_ok_fp.
The executor never decides anything new.

**Zoo bodies:** one_wing, one_wing_bat, weapon_up, tail_spikes, dorsal_fin, dorsal_fin_quadruped, shoulder_pauldron, horns_asym, sash_diagonal, ponytail_side, cape, weapon_in_hand, naga, naga_shells, shoulder_cannon, forearm_shield, loadout, tentacles, tentacles_shells, bat_wings_shells, quadruped_shells, held_staff

**Acceptance**

Zoo, fast and real, auto / left / right, plain / +ai / +ain. Line counts:
- 'plan != run' 54 -> 0 (fast) and 36 -> 0 (real); plan_drift 0 everywhere;
- 'damaged' 160 -> 0; 'limb cut as part' 20 -> 0; 'limb lost' 20 -> 0;
- 'QR X symmetry ON with not-symmetric parts' 24 -> 0; 'blocked needlessly' 12 -> 0;
- 'NOT mirrored' 50 -> <= 6, each naming a measured gate reason;
- loose shells copied/lost 0.

Totals: Step 4 fast 340 -> <= 6; real 168 -> <= 4.

Unchanged where they should be:
- Quad Remesher symmetry stays on in Auto for every body with no significant island: bat_wings(_shells), bird_wings, four_wings, winged_tail, dorsal_fin, trunk, antlers, hair_spikes, back_spines, skirt, four_arms, chibi, back_hair, dragon, tail_spikes, two_tails, quadruped;
- two_tails, trunk, dragon and quadruped keep their welded cuts (cut shares within +-0.01 of baseline).

Zoo v2:
- humanoid_raised_arm with Left/Right is mirrored (the chosen side wins) with QR symmetry on;
- pouch_small is kept (lost and copied <= 5%);
- relief_scar gets no row of its own (grouped) and is not copied.

Contract:
- decide + prepare twice give a byte-equal ledger and fingerprints on all 37 bodies x 3 sides;
- an injected run-time refusal (monkeypatched split_off) keeps the part, the mirror continues, QR symmetry goes off and the red row appears;
- the rewritten tests are green, and the rest of the suite is unchanged.

**Tests**

tests/test_ledger.py: rows, lattice, determinism, drift injection, no-plan fallback.

Rewritten (their meaning changes by design):
- test_retopo_shape::test_a_part_that_cannot_be_cut_is_never_mirrored -> 'is kept as it is while the rest is mirrored';
- ::test_a_part_the_plan_could_not_cut_blocks_the_mirror -> 'is protected and the mirror goes on';
- ::test_a_cut_to_one_side_of_the_middle_is_never_mirrored_onto_bare_skin -> 'lid region kept, no dent';
- ::test_one_sided_detail_turns_mirror_symmetry_off -> the flag comes from the field;
- test_appendages::test_a_part_the_one_sided_cut_takes_does_not_block_the_mirror, and the plan-row tests -> rows from the ledger;
- test_stage_late prepare_retopo symmetry flags.

Kept green unchanged: test_curled_tail_is_cut_at_its_root_and_never_mirrored, test_hard_one_sided_tails_are_still_cut_at_the_root, test_side_choice_never_mirrors_a_prop_beside_the_body, test_a_symmetric_part_that_cannot_be_cut_keeps_the_mirror, test_mirrored_run_that_loses_a_one_sided_part_keeps_the_mirror_and_rebuilds_the_part, and the mirror-plane tests.

### U7 - Faithful fit target in the remesh, and coverage per row after Quad Remesher

*Effort M; depends on U6; wave W4.*

**Modules**

- `blender_scripts/forge_bpy/retopo.py` (_qr_one fit/shape/weld section; _finish_part coverage)
- `blender_scripts/forge_bpy/density.py` (shape_loss(mask=))
- `tests/test_fit_target.py` (new)

**Technique**

Fit target:
- conform, carve, source_tree, shape_loss and the weld/attach checks take the ledger's fit_target. It is identical to qr_input wherever the sides match.

Coverage per row:
- each ledger row's coverage = the share of its original region farther than tau from the final low (shape_loss restricted to the row mask);
- above 2%: a red row 'part of <where> was lost in remeshing' [Show];
- every row reports its coverage.

Detachable rows are never welded: they are attached as their own shell (director invariant I8).

**Zoo bodies:** shoulder_pauldron, sash_diagonal, ponytail_side, horns_asym, naga, naga_shells, one_wing, cape, weapon_in_hand

**Acceptance**

Real mode, every zoo body and side:
- coverage reported for every row;
- truth one-sided parts keep >= 98% of their surface within tau of the original after Quad Remesher (fake_qr);
- no red coverage row on the zoo;
- open_edges 0;
- the quadruped weld-fallback count is no worse than the baseline;
- an injected deletion after Quad Remesher produces the red row.

**Tests**

tests/test_fit_target.py; test_retopo_shape::test_fit_to_original_restores_one_sided_notch stays green.

### U8 - Step 4 panel: Left-right check rows, Show differences, preview of the real prepared mesh, Run label, plan vs result

*Effort M; depends on U6; wave W4.*

**Modules**

- `blender_addon/forge_send/stages_late.py` (_draw_retopo, _retopo_rows, new _parts_rows)
- `blender_addon/forge_send/steps.py` (plan_rows from forge_ledger; show_side -> show_plan_view)
- `blender_addon/forge_send/stages_ui.py` (row-choice, show-region and preview operators; tooltips)
- `tests/test_stage_late.py` (additions)

**Technique**

Rows:
- rows come from the ledger only, so draw() stays read-only;
- wrapped at 44 characters, no internal names;
- groups: made symmetric / kept as it is (where + class + eye) / cut off and joined back / touching / held in a hand / Quad Remesher mirror on-off and why / More (ignored detections);
- at most 5 difference rows; the rest are grouped ('and 3 smaller differences, kept');
- at most 3 rows carry buttons; every row has a safe default, and Run is never blocked;
- the Run label states the plan: 'Run: symmetric from the left, 2 things kept as they are'.

Show differences writes the colour attribute forge_plan_view on the original, with a one-line legend:
- grey unchanged; green made symmetric; orange kept as it is;
- blue cut off and joined back; purple touching;
- red only for an explicit copy choice.

Preview: the dry run's fit_target (and pieces), shown as a temporary display object over the original. It replaces the Mirror-modifier preview, which shows copies that never happen.

After the run: 'Done:' rows in the plan's order. A deviation is the only red row, and it says what was done instead. Coverage per row comes from U7.

**Acceptance**

- For every zoo body and side, plan rows == run rows item by item (stage test with fake_qr).
- Every refusal row names its measured cause.
- Rows are at most 44 characters; a plain-words test forbids back_extra, extra_l2, ids and rig jargon.
- Preview vertex count == the ledger's dry fit_target count.
- The existing safe-in-draw tests stay green.

**Tests**

tests/test_stage_late.py additions (rows per zoo body, plain words, preview, after-run rows).

### U9 - Measure Step 4 on the director's PC (timing and real noise) and cache the dry run

*Effort S; depends on U6; wave W4.*

**Modules**

- `blender_scripts/forge_bpy/step4_cache.py` (new: keyed hidden datablocks)
- `tools/step4_timing.py` (new, run on the PC)
- `docs/research/step4_timing.json`

**Technique**

Timing trial on the director's 1M-5M Tripo meshes, at Unreal 30k and Unity 8k:
- time fit_plane, field, islands, partmap thickness (when present), decide, prepare and apply;
- record the noise floor and island counts. This is the real-noise calibration the zoo cannot give.

Cache: the plan's capped body, pieces, qr_input and fit_target are stored as hidden datablocks keyed by input_fp + cut ids. ledger.prepare uses them when the fingerprints match (a one-line hook added in U12), so the run does not cut twice on big meshes.

Go / no-go:
- targets: field <= 40 s and dry run <= 90 s on 5M vertices;
- if they are missed: fewer field samples, and the displacement computed on a decimated proxy and carried to full resolution by nearest sample.

**Acceptance**

- Numbers recorded in docs/research/step4_timing.json for at least two of the director's real meshes.
- Island counts on real meshes: <= 12 significant islands on a symmetric-looking character (otherwise recalibrate the noise factor, across models, never per model).
- With the cache, the run's pre-remesh block on the 5M mesh takes <= 10 s.
- Zoo dry-run time <= 1.5x today's (1.2-4 s).

**Tests**

Cache hit/miss unit test in tests/test_ledger.py style (new tests/test_step4_cache.py); the timing script itself is a PC trial.

## P2: Detection and classification: parts in one piece, contacts, descriptor classes

### U10 - Thickness and shape part map (new partmap.py): core, parts in one piece, sub-parts, joint-guess mask

*Effort L; depends on U1; wave W1.*

**Modules**

- `blender_scripts/forge_bpy/partmap.py` (new)
- `tests/test_partmap.py` (new)

**Technique**

Thickness: t(v) = shape diameter on <= 100k deterministic samples (parts.thickness), carried to vertices by cell, with a 2-ring median against AI noise. Clearance (one ray along +n) flags sheets lying close to the body.

Core: the connected region(s) with t >= 0.5 T_trunk, where T_trunk is the 90th percentile of t on the largest thick region. No joints needed.

Shape per vertex, at scale 2t: PCA gives sheet (l2/l3 >= 4), tube (l2/l3 < 2 and l1/l2 > 3) or blob; a part takes its majority label.

Parts:
- protrusions are the connected non-core components; one thin connected region is one part (a membrane and its finger bones are one wing);
- sub-parts one level down: inside each protrusion, its own core (t >= 0.5 x its stem thickness) and its protrusions. That gives spikes on a tail, horns/ears/spikes on a head, and the fingers of a wing.

Thin for this budget: 2 pi r_stem < 8 e.

Descriptors per part: shape, length, girth profile, flatness (median t / (2 x median loop radius)), elongation, taper, straightness, tip count, area, and root position on the core (height third, front/back, centre line or side).

exclusion_mask(me, islands) per VERTEX, so a skirt or cape fused to a leg does not take the leg (the judges' correction). It masks:
- sheet vertices of parts attached to the core (wings, capes, skirts);
- vertices of significant one-sided add-on islands beyond their nearest narrowing (held props, shields, cannons; the hands stay);
- loose shells that do not touch the trunk (staff, halo).

**Zoo bodies:** bat_wings, bat_wings_shells, four_wings, winged_tail, one_wing_bat, cape, forearm_shield, hair_spikes, back_spines, tail_spikes, dragon, back_hair, skirt, chibi, quadruped, quadruped_shells, dorsal_fin_quadruped, held_staff

**Acceptance**

Zoo, plain / +ai:
- every truth part with >= 300 vertices overlaps one partmap part with IoU >= 0.6, in one piece (wings, cape, shield, skirt, back hair, ponytail, fin);
- flatness < 0.35 on truth sheets and > 0.5 on truth tubes (numpy check: wing 0.14, arm 0.81);
- sub-parts: hair spikes >= 10/14, back spines >= 5/7, tail spikes >= 3/5, dragon horns 2/2;
- 'thin for budget' selects exactly today's cut parts on two_tails, trunk, dragon and quadruped;
- the core holds <= 5% of any wing, cape or skirt;
- under 5 s on an 80k body.

**Tests**

tests/test_partmap.py: bodies.py fixtures and zoo bodies; scale invariance; the exclusion mask keeps the legs under the skirt.

### U11 - Attachments: root, slot root, along, contact; fused parts split for labels; contacts stay joined

*Effort L; depends on U4, U10; wave W2.*

**Modules**

- `blender_scripts/forge_bpy/partmap.py` (attachments)
- `blender_scripts/forge_bpy/rings.py` (loop normal, passes-by)
- `blender_scripts/forge_bpy/rescue.py` (split_contact: cut a waist loop and cap both sides; only on request)
- `tests/test_attachments.py` (new)

**Technique**

For each attachment loop of a part, take its vector-area normal n (into the part), its radius r_l, and the part's PCA frame within geodesic 3 r_l.

Rules:
- root-like: a tube with |n . e1| > 0.6, or a sheet with |n . e3| < 0.5;
- passes by: more than 25% of those points lie behind the ring plane;
- one root per part: the root-like loop with the largest r_l to the core or the parent part. Every other loop is a contact;
- no root-like loop: 'along' (a pad, a strap, the sash). Never cut;
- two or more root-like loops to the core: several fused parts. Split by multi-source geodesic Voronoi (heapq Dijkstra), snapped to the narrowest closed loop near the border. This splits the LABELS only (two parts, two chains); the geometry stays as modelled;
- hollow sheet (skirt, sleeve; from the structure design): nested loops one thickness apart around the core, with a free rim. Not a contact.

Contacts stay joined in geometry by default; Step 8 splits the skin weights there (U17). 'Separate them' (split_contact) is offered only when the waist verdict is clean and mesh_defects passes after capping.

**Zoo bodies:** tentacles, tentacles_shells, cape, bird_wings, forearm_shield, skirt, ponytail_side, bat_wings

**Acceptance**

- tentacle_4 and tentacle_5 are two parts: the 'merged' points (12) go to 0.
- cape: one part including its hem, rooted at the shoulders; the calf and rump contacts are flagged; 'found in pieces' and 'partly found' go to 0.
- The truth contacts of bird_wings and forearm_shield are flagged. The skirt is a hollow sheet with no contact.
- No contact is flagged on bodies whose truth lists none.
- The root centre is within 1 root radius of the truth root for >= 90% of found parts.
- Geometry is unchanged unless 'Separate them' is chosen.

**Tests**

tests/test_attachments.py on zoo bodies (tentacles, cape, bird_wings, forearm_shield, skirt) and on a no-contact control set.

### U12 - Classes and plain names from descriptors; the ledger's candidates come from the part map

*Effort M; depends on U6, U10, U11; wave W4.*

**Modules**

- `blender_scripts/forge_bpy/appendages.py` (_classify -> descriptor rules; from_object adapts partmap; plain_name, KIND_WORDS)
- `blender_scripts/forge_bpy/ledger.py` (candidates from partmap; rows carry descriptors; step4_cache hook)
- `tests/test_appendages.py`

**Technique**

Kinds come from descriptor rules (ratios only; the rule margin gives 'sure'):
- wing: a sheet on the upper core with >= 2 tube sub-parts along one edge, or a broad sheet pair at the shoulders/back;
- fin: a sheet with a slot root on the centre line;
- cloth: a sheet hanging from a high root, or a hollow sheet around the core;
- ear: a small sheet on the head part (< 25% of its area);
- horn (a cone, taper < 0.45) and antler (branching, >= 2 tips in a tree): both rigid;
- tail / tentacle / trunk: tube chains. Tentacle when >= 3 ground-reaching tubes leave the lower core; trunk at the front of the head;
- spike: a small cone sub-part, rigid;
- armour / plate: a pad with an 'along' or patch root;
- prop: a loose or crossing shell, or a straight one-sided rod at a hand;
- extra arm: a tube pair on the upper core beyond the arm pair.

Names: role + side + host ('left wing', 'third spike on the tail'). Old kind strings stay as aliases where the truth matches, so the existing tests read the same. One partmap part = one row, so fragments merge.

**Zoo bodies:** antlers, shoulder_cannon, loadout, dorsal_fin, dorsal_fin_quadruped, tentacles, tentacles_shells, tail_spikes, chibi, quadruped, quadruped_shells, bat_wings, bird_wings, four_wings, winged_tail, dragon, one_wing_bat, cape, forearm_shield, held_staff, weapon_up, four_arms, hair_spikes, back_spines, back_hair, skirt

**Acceptance**

Zoo, fast, plain + ai:
- rig: 'classified wrong' 43 -> <= 6; 'no class' 16 -> <= 2; phantoms 39 -> <= 5;
- detect 228 -> <= 80: fragments 24 -> <= 4, partly 35.5 -> <= 8, merged 43.5 -> <= 10, not found 125 -> <= 55.
test_appendages stays green through the aliases. Kind assertions change only where the old kind was the bug, each one listed in the PR.

**Tests**

test_appendages.py: new descriptor-rule tests plus the aliases; the class tables in tests/test_partmap.py.

## P3: Skeleton guess and rig (rig-context work packages folded in)

### U13 - Interim skeleton fix: the joint guess ignores wings, capes, skirts, props and loose shells

*Effort S; depends on U2, U10; wave W2.*

**Modules**

- `blender_scripts/forge_bpy/joints.py` (estimate computes partmap.exclusion_mask internally; v1 on the kept vertices)
- `tests/test_joints_mask.py` (new)

**Technique**

- Build the per-vertex mask from U10 (plus U2 islands) and run v1 estimate_points, unchanged, on V[keep].
- The hand tip comes from the hand sub-part, never from a prop tip.
- Fallback to all vertices (logged) when the mask removes > 40% of the vertices, or when the result fails v1's own sanity checks.
- No caller changes. The same mask becomes WP4's pass-1 exclusion.

**Zoo bodies:** bat_wings, bat_wings_shells, bird_wings, four_wings, winged_tail, one_wing, one_wing_bat, forearm_shield, held_staff, weapon_in_hand, loadout, skirt, cape

**Acceptance**

- 'skeleton guess off' 116 -> <= 24 rig points, plain and +ai. Allowed to remain: four_arms, chibi, and at most one more body.
- No new skeleton line on a body that had none.
- Step 4 region words, Step 5 UV and Step 8 tests green; the test_arp_mapping 65-ref human test green.

**Tests**

tests/test_joints_mask.py on the zoo wing, cape, skirt and prop bodies; existing joint-dependent suites unchanged.

### U14 - The ledger travels: low mesh, bake source per region, export manifest

*Effort M; depends on U6, U12; wave W5.*

**Modules**

- `blender_scripts/forge_bpy/ledger.py` (transfer_to_low)
- `blender_scripts/forge_bpy/retopo.py` (calls transfer at the end of the run)
- `blender_scripts/forge_bpy/bake.py` (source per region)
- `blender_scripts/forge_bpy/finalize.py` (manifest rows)
- `tests/test_ledger_transfer.py` (new)

**Technique**

Transfer: forge_ledger_row is copied to the low by nearest surface point, using the Step 4 report's weld loops as hard borders.

Bake source per region:
- the original high everywhere;
- except rows the director let the mirror change (allowed posed pairs, 'make alike'), where the source is the prepared high (fit_target keeps loop data, UVs and material). The texture then matches the new shape.

Export:
- detachable rows export as their own meshes;
- the manifest lists every row: kept / cut / mirrored, detachable parts, sockets.

Step 8 (WP7, WP8) reads rows from the low and never re-detects there.

**Zoo bodies:** tentacles, tentacles_shells, weapon_in_hand, held_staff, loadout, bat_wings, quadruped

**Acceptance**

- On every zoo body, the low's row labels match a transfer of the truth labels on >= 98% of faces.
- Step 8 extra-part rows == ledger rows: no part appears in one step only.
- tentacles with Left: the bake validation miss ratio on the right tentacles <= that on the left.
- A detachable prop exports as its own mesh with a manifest entry.

**Tests**

tests/test_ledger_transfer.py; test_bake source-per-region case; manifest test in the finalize suite.

### WP3 - [rig context] Measurements that fill the card, pre-filled from the Step 4 ledger

*Effort M; depends on WP1, WP2, U6; wave W5.*

**Modules**

- `blender_scripts/forge_bpy/rig_brief.py`
- `blender_scripts/forge_bpy/appendages.py`
- `tests/test_rig_brief.py`

**Technique**

As wps.json WP3. Changes:
- prefill_layers reads forge_ledger rows: kinds from the U12 descriptors arrive as src 'measured' with sure from the rule margins, and Step 4 choices as src 'you';
- ground contacts are imported from limb_guard (one implementation);
- head_top excludes the head's partmap sub-parts (horns, ears, spikes).
This is the lead's choice of height to the top of the head, not counting horns or ears.

**Zoo bodies:** horns_asym, antlers, dragon, chibi, hair_spikes

**Acceptance**

- As wps.json WP3, plus head_top_excludes_horns on the bull and horns_asym.
- The card is pre-filled for every zoo body with no internal names.
- A Step 4 choice appears as src 'you' and is not asked again.

**Tests**

tests/test_rig_brief.py (as specified, plus ledger prefill cases).

### WP4 - [rig context] Joint estimator v2, with pass 1 = the part-map exclusion

*Effort L; depends on WP1, WP2, U13; wave W5.*

**Modules**

- `blender_scripts/forge_bpy/joints.py`
- `blender_addon/forge_send/steps.py`
- `blender_addon/forge_send/stages_late.py`
- `blender_scripts/forge_bpy/uv.py`
- `tests/test_joints_v2.py`
- `tests/test_invariance.py`

**Technique**

As wps.json WP4. Changes:
- pass 1 uses U13's per-vertex exclusion instead of 'appendages.find far components';
- the 'keep vertices within 0.12 H of a hand tip' rule applies to hand vertices only; a one-sided prop beyond the wrist narrowing stays excluded;
- the crotch comes from the split where partmap's two ground-reaching leg tubes leave the core, when available.

**Zoo bodies:** chibi, skirt, cape, weapon_in_hand, loadout, forearm_shield, bat_wings, winged_tail, four_wings

**Acceptance**

- As wps.json WP4 (bull tests, hinges, marks override, v1 compatibility, invariance).
- Zoo 'skeleton guess off' <= 8 rig points: chibi fixed by the head rules; four_arms waits for WP15.

**Tests**

tests/test_joints_v2.py, tests/test_invariance.py (as specified) plus zoo skeleton checks.

### WP5 - [rig context] Steps 1-2: notes, height meaning, facing

*Effort S; depends on WP3; wave W6.*

**Modules**

- `blender_addon/forge_send/stages_ui.py`
- `blender_addon/forge_send/geometry.py`
- `blender_addon/forge_send/steps.py`
- `tests/test_stage_geometry.py`
- `tests/test_blender_addon.py`

**Technique**

As wps.json WP5, scope unchanged. Height means the top of the head, not counting horns or ears; shoulder height for quadrupeds (lead's choice).

**Acceptance**

As wps.json WP5.

**Tests**

As wps.json WP5.

### WP6 - [rig context] Auto-Rig Pro limbs from the plan, hinge check after build, export type

*Effort L; depends on WP0, WP2, WP4; wave W7.*

**Modules**

- `blender_scripts/forge_bpy/arp_rig.py`
- `blender_scripts/forge_bpy/joint_check.py`
- `blender_scripts/forge_bpy/finalize.py`
- `blender_addon/forge_send/steps.py`
- `tests/fake_arp.py`
- `tests/arp_like.py`
- `tests/test_arp_plan.py`

**Technique**

As wps.json WP6, scope unchanged. Upright animals export humanoid-compatible (lead's choice). The top comes from J['_head_top'], which ignores props and horns.

**Acceptance**

As wps.json WP6.

**Tests**

As wps.json WP6.

### WP7 - [rig context] Step 8 card and flow; place_joints reads the ledger rows

*Effort M; depends on WP2, WP3, WP4, WP6, U14; wave W8.*

**Modules**

- `blender_addon/forge_send/stages_ui.py`
- `blender_addon/forge_send/stages_late.py`
- `blender_addon/forge_send/steps.py`
- `tests/test_stage_late.py`
- `tests/test_blender_addon.py`

**Technique**

As wps.json WP7. Change: steps.place_joints builds the appendage list from the ledger rows on the low (U14), through the brief. A fresh detection on the low is only a marked fallback.

**Zoo bodies:** bat_wings, quadruped, tentacles

**Acceptance**

As wps.json WP7, plus: on every zoo body the card's extra parts equal the ledger rows.

**Tests**

As wps.json WP7, plus the ledger-rows case.

### WP8 - [rig context] Extra parts from the brief: every chain-like row rigged, rigid rows stiff

*Effort M; depends on WP0, WP6, WP7, U12; wave W9.*

**Modules**

- `blender_scripts/forge_bpy/arp_rig.py`
- `blender_scripts/forge_bpy/appendages.py`
- `blender_addon/forge_send/stages_late.py`
- `tests/test_arp_plan.py`
- `tests/test_appendages.py`
- `tests/test_rig_chains.py`

**Technique**

As wps.json WP8. Changes:
- appendages.find(expect, seeds, exclude) assigns rows to declared kinds by cost, using U12 descriptors (shape, attachment, root zone, side, size);
- add_extras iterates over all chain-like rows (tails, tentacles, trunks, extra arms, and wings behind the WP0 gate), not 'first tail + ear_l/ear_r';
- rigid rows (horns, antlers, spikes, plates) go through make_rigid;
- cloth and hair move with the body (weights transferred from the host; lead's choice).

**Zoo bodies:** two_tails, tentacles, tentacles_shells, trunk, bat_wings, bird_wings, four_wings, winged_tail, dragon, tail_spikes, antlers, horns_asym, hair_spikes, back_spines, four_arms

**Acceptance**

- As wps.json WP8.
- A new zoo rig-coverage metric with fake_arp: every truth part with rig in {chain, wing, limb} gets a chain whose root is within 1 root radius of the truth root, whose tip is within 10% of its length of the truth tip, and whose parent bone is the truth parent or an ancestor.
- Every rigid truth part goes through make_rigid to its parent.

**Tests**

As wps.json WP8, plus the zoo rig-coverage metric in tests/zoo_baseline.py (fake_arp).

### WP9 - [rig context] Joint checks and the question list (Step 4 questions count inside the 6)

*Effort M; depends on WP4, WP7, WP8; wave W10.*

**Modules**

- `blender_scripts/forge_bpy/joint_check.py`
- `blender_scripts/forge_bpy/marks.py`
- `blender_scripts/forge_bpy/appendages.py`
- `blender_addon/forge_send/rig_pick.py`
- `blender_addon/forge_send/stages_late.py`
- `blender_addon/forge_send/steps.py`
- `tests/test_joint_check.py`
- `tests/test_rig_marks.py`
- `tests/test_stage_late.py`

**Technique**

As wps.json WP9. Changes:
- marks.questions counts the questions Step 4 asked (at most 2) inside the cap of 6;
- PARTS_MATCH and LABEL_MARGIN compare against the ledger rows.

**Acceptance**

As wps.json WP9, plus: Step 4 + Step 8 questions never exceed 6 on any zoo body; 0 questions on all-symmetric humanoids.

**Tests**

As wps.json WP9, plus the cap-sharing case.

### WP10 - [rig context] Point-and-click answering, overlay, memory, Point and tell (also on Step 4 rows)

*Effort L; depends on WP1, WP6, WP9; wave W11.*

**Modules**

- `blender_addon/forge_send/rig_pick.py`
- `blender_scripts/forge_bpy/marks.py`
- `blender_addon/forge_send/steps.py`
- `blender_addon/forge_send/stages_late.py`
- `blender_addon/forge_send/stages_ui.py`
- `tests/test_rig_marks.py`
- `tests/test_blender_addon.py`

**Technique**

As wps.json WP10. Changes:
- the Point and tell menu adds Wing, Fin, Cloth or hair, Armour or attached piece, and Held prop;
- the 'part' and 'tell' modes also work on Step 4 ledger rows and islands;
- '+ Add a part Forge missed' (root and tip clicks) seeds a ledger row.
Point-and-click joints are the fallback for every skeleton the estimators miss: wings, quadrupeds, four arms, chibi.

**Zoo bodies:** four_arms, chibi, quadruped, dragon

**Acceptance**

As wps.json WP10, plus: a Point-and-tell answer on a Step 4 island changes that row's kind (src 'you') and survives a Step 4 re-run.

**Tests**

As wps.json WP10, plus the Step 4 tell case.

### WP11 - [rig context] Props as sockets (grip frames from Step 4 detached props)

*Effort M; depends on WP0, WP6, WP7; wave W12.*

**Modules**

- `blender_scripts/forge_bpy/arp_rig.py`
- `blender_scripts/forge_bpy/finalize.py`
- `blender_scripts/forge_bpy/skin.py`
- `blender_addon/forge_send/steps.py`
- `tests/test_props_sockets.py`

**Technique**

As wps.json WP11. Change: props detached in Step 4 (U15) arrive as their own objects with a stored grip frame, and the socket is placed at that frame. A detachable prop is never welded. Without U15 it works as specified (contact patch, PCA axis).

**Zoo bodies:** weapon_in_hand, weapon_up, held_staff, loadout

**Acceptance**

As wps.json WP11, plus: on weapon_in_hand with U15, the socket is within 1 grip radius of the truth grip and is a child of hand.r.

**Tests**

As wps.json WP11.

### WP12 - [rig context] Test failures point back to a joint

*Effort S; depends on WP10; wave W13.*

**Modules**

- `blender_scripts/forge_bpy/marks.py`
- `blender_addon/forge_send/stages_late.py`
- `blender_addon/forge_send/steps.py`
- `tests/test_stage_late.py`
- `tests/test_rig_marks.py`

**Technique**

As wps.json WP12, scope unchanged.

**Acceptance**

As wps.json WP12.

**Tests**

As wps.json WP12.

### R1 - Structure research line: core ring and exact level-set loops on a proxy (numpy, not wired into the product)

*Effort M; depends on WP1; wave W5.*

**Modules**

- `blender_scripts/forge_bpy/level_sets.py` (new, numpy only)
- `tests/test_level_sets.py` (new)

**Technique**

Kept from the structure design, as research for WP14/WP15:
- proxy by Decimate, accepted when the two-sided distance is < 0.5% H and the shell count is unchanged;
- thickness;
- core ring: the section loop through the geodesic centre, perpendicular to the PCA axis of the thick vertices;
- multi-source Dijkstra f from the ring; exact level loops (crossing edges linked through shared faces);
- Reeb links by slab union-find; creases where girth < 0.55x or thickness < 0.6x the running median;
- the split node of the ground-reaching branches gives the crotch and the leg-pair splits.

**Zoo bodies:** quadruped, quadruped_shells, dorsal_fin_quadruped, dragon, four_arms

**Acceptance**

Decision gate for WP14/WP15:
- crotch within 0.02 H with and without wings or cape on the zoo bodies (numpy check: 0.751-0.756 m);
- quadruped: 4 leg branches, with leg-pair splits within 0.05 H of joints_hint;
- four_arms: 2 arm rows;
- <= 10 s on a 40k proxy.
WP14 uses R1 only if this gate passes.

**Tests**

tests/test_level_sets.py: surface-nets capsule fixtures (from universal/check_mesh.py) and zoo exports as .npz.

### WP13 - [rig context] Four-legged animals, guided mode (template pre-filled from the part map)

*Effort L; depends on WP0, WP6, WP10, U12; wave W14.*

**Modules**

- `blender_scripts/forge_bpy/body_plans.py`
- `blender_scripts/forge_bpy/arp_rig.py`
- `blender_addon/forge_send/steps.py`
- `blender_scripts/forge_bpy/finalize.py`
- `tests/bodies.py`
- `tests/test_arp_plan.py`

**Technique**

As wps.json WP13 (the lead's next body type). Change: the body plan is pre-filled from the WP2 template match on U12 descriptors ('Forge sees four feet on the ground'), so the quadruped template is picked without a question when it is sure. All 12 markers can be clicked, so a four-legged animal never needs 3D bone editing.

**Zoo bodies:** quadruped, quadruped_shells, dorsal_fin_quadruped, dragon

**Acceptance**

As wps.json WP13, plus: zoo quadruped, quadruped_shells and dorsal_fin_quadruped pick the quadruped template with sure >= 0.8.

**Tests**

As wps.json WP13.

### WP14 - [rig context] Four-legged estimator (legs from ground columns and part-map tubes; R1 loops if gated in)

*Effort L; depends on WP4, WP13, U10, R1; wave W15.*

**Modules**

- `blender_scripts/forge_bpy/joints.py`
- `blender_scripts/forge_bpy/sections.py`
- `tests/test_joints_v2.py`
- `tests/bodies.py`

**Technique**

As wps.json WP14. Changes:
- legs from U3 ground-contact columns and U10 ground-reaching tube parts;
- trunk axis and leg-pair splits from R1 loops when R1's gate passed, else sections.trunk_axis;
- the tail from its ledger row.

**Zoo bodies:** quadruped, quadruped_shells, dorsal_fin_quadruped, dragon

**Acceptance**

- As wps.json WP14.
- Zoo 'quadruped skeleton off' (U1 score) -> 0 on quadruped, quadruped_shells, dorsal_fin_quadruped and dragon: < 0.08 H on hips, shoulders, knees and hocks; < 0.1 H on the spine.
- Guided questions 4-6 on the fixture.

**Tests**

As wps.json WP14, plus the zoo quadruped skeleton score.

### WP15 - [rig context] Bird (gated), snake, more arms (rows from the part map)

*Effort M; depends on WP13, U12; wave W16.*

**Modules**

- `blender_scripts/forge_bpy/body_plans.py`
- `blender_scripts/forge_bpy/joints.py`
- `blender_scripts/forge_bpy/arp_rig.py`
- `tests/test_arp_plan.py`

**Technique**

As wps.json WP15. Changes:
- extra-arm rows come from U12 (four_arms 'extra arm', not back_extra);
- the serpent comes from partmap's long core continuation;
- R1's arm rows are used when gated in.

**Zoo bodies:** four_arms, naga, naga_shells, bird_wings

**Acceptance**

As wps.json WP15, plus: four_arms 'skeleton guess off' -> 0; naga plans free + spine; bird falls back when the probe says crash.

**Tests**

As wps.json WP15.

## P4: Steps 6/8/9 universality and the quality options

### U15 - Held props: through-hand cut with a rebuilt grip and a socket frame (new props.py)

*Effort L; depends on WP1, U2, U4, U6, U10; wave W6.*

**Modules**

- `blender_scripts/forge_bpy/props.py` (new)
- `blender_scripts/forge_bpy/ledger.py` (prop rows, disposition 'detach')
- `tests/test_props.py` (new)

**Technique**

Candidate: a significant one-sided add-on island, or a crossing/loose shell, that is elongated (l1/l2 > 6), straight (centroid-polyline bend < 15 degrees) and meets a hand region (U3 terminal or the end of a partmap tube).

Steps:
1. PCA axis, then sections along it (WP1 profile_along).
2. Grip zone = the stretch bounded by section-area jumps above 1.8 (the rig-context crease_along ratio).
3. Cut rings just outside the zone, crease-snapped (U4).
4. Rebuild the hidden grip: loft a tube between the two rings (equal vertex counts, linear in t).
5. Cap the fist's openings (_fan_fill + tidy).
6. Store a socket frame at the grip centre, along the axis, on the prop object for WP11.

Fail safe: no area jumps, or more than one loop at a cut plane, gives 'the held object is too tangled with the hand to take out: it stays in the hand'. The row stays 'keep' (protected).

Default: detach when clean (lead's choice: detachable props with hand sockets). Option: 'leave it in the hand'. Never welded.

**Zoo bodies:** weapon_in_hand, weapon_up, held_staff, loadout

**Acceptance**

- Detach on: prop cut share >= 0.9, arm cut share <= 0.02, hand and prop closed (open_edges 0), socket frame within 1 grip radius of the truth grip.
- Detach off: nothing is cut, the island is protected, arm lost 0.
- Every refusal names its cause.

**Tests**

tests/test_props.py on weapon_in_hand, weapon_up, held_staff, loadout and a two-handed refusal fixture.

### U16 - Wedge plug for slot roots (wings, fins, sails)

*Effort M; depends on U4; wave W5.*

**Modules**

- `blender_scripts/forge_bpy/rescue.py` (_plug: PLUG_SHAPES 'wedge', _hide_plugs)
- `tests/test_wedge_plug.py` (new)

**Technique**

Used only when a sheet must be cut: the director chose 'Cut it off' on a one-sided sheet, or a membrane thinner than one quad edge at this budget (Quad Remesher would merge its faces) has a 'slot' verdict.

Construction:
1. Project the ring into its plane.
2. Take the chord midpoints perpendicular to the major axis; they form a curved medial line, so curved slots work too.
3. Plug rings 1 and 2 descend along -n towards those midpoints (PLUG_STEP, taper).
4. Close with a strip of quads along the medial line.
It cannot fold when the ring is monotone. _plug_faults stays the final check.

**Zoo bodies:** one_wing, one_wing_bat, dorsal_fin, dorsal_fin_quadruped, bat_wings, four_wings, winged_tail

**Acceptance**

- one_wing and one_wing_bat with the cut chosen: wing cut share > 0.9, body cut share < 0.02, joint welded or attached, open_edges 0.
- Bat wings at Unity 8k: the membrane keeps both faces (shape_loss lost < 0.2%).
- Refused cases say why.

**Tests**

tests/test_wedge_plug.py: pure slot loops plus zoo wing and fin roots.

### U17 - Contacts in Step 8: weights split at contacts, motion-check rows, every row gets a rig outcome

*Effort M; depends on U11, U14, WP8; wave W10.*

**Modules**

- `blender_scripts/forge_bpy/arp_rig.py` (store_regions: contact labels from U11, 2-ring blend)
- `blender_scripts/forge_bpy/motion_check.py` (contact rows)
- `tests/test_contacts_rig.py` (new)

**Technique**

- store_regions gives each owner its side of a contact (U11 Voronoi labels), with a 2-ring blend.
- The motion check reports 'touches the left calf: will stretch when they move apart'.
- Completeness: every ledger row gets exactly one Step 8 outcome: chain; stiff with bone X; moves with the body; socket; or 'not rigged on its own because ...'.

**Zoo bodies:** cape, tentacles, tentacles_shells, bird_wings, forearm_shield

**Acceptance**

- cape: the calf-contact vertices follow the calf within a 2-ring blend, and the motion check reports the contact.
- tentacle_4 and tentacle_5 get their own chains.
- With fake_arp, every ledger row on every zoo body has exactly one Step 8 outcome row.

**Tests**

tests/test_contacts_rig.py; test_motion_check contact case.

### U18 - 'Use this side for both' for twins that differ

*Effort M; depends on U6, U16; wave W7.*

**Modules**

- `blender_scripts/forge_bpy/symmetry.py` (exempt island)
- `blender_scripts/forge_bpy/ledger.py` (disposition 'use_side')
- `tests/test_use_side.py` (new)

**Technique**

Offered only when both twins have feasible cut verdicts:
1. Cut both.
2. Drop the non-kept piece.
3. Mirror the kept piece (negative X scale, flip normals).
4. Weld it into the mirrored opening. The core is symmetric, so the openings mirror each other.
Otherwise the option is shown greyed, with the reason ('the horns cannot be cut cleanly at their roots: they stay as they are'). rescue.split_off and weld are reused unchanged.

**Zoo bodies:** horns_asym, two_tails, tentacles

**Acceptance**

- horns_asym with 'use the left for both': horn_r is replaced by the mirrored horn_l, no open edges, weld rows reported.
- Default: unchanged (both horns kept, 0 damage points).

**Tests**

tests/test_use_side.py.

### U19 - Lift-off for pads lying on the body: Quad Remesher symmetry back for pauldron, shield, cannon (optional)

*Effort L; depends on U5, U6, U7; wave W8.*

**Modules**

- `blender_scripts/forge_bpy/rescue.py` (lift_off)
- `blender_scripts/forge_bpy/ledger.py` (disposition 'lift')
- `tests/test_lift_off.py` (new)

**Technique**

Director design D12:
1. Cut the pad along its island loop.
2. Transplant the mirrored bare footprint from the other side into the hole and bridge it (rescue._bridge).
3. Close the pad with an inset copy of that skin, so it becomes a closed shell resting on the body.
4. Remesh the pad alone and attach it as its own shell.
The body is then pad-free and symmetric, so exact mirroring and QR symmetry are allowed (gates still run). The dry run proves feasibility; on failure the row falls back to keep.

**Zoo bodies:** shoulder_pauldron, forearm_shield, shoulder_cannon, loadout

**Acceptance**

shoulder_pauldron, forearm_shield and shoulder_cannon with Left, Right and Auto:
- QR symmetry on;
- the part is its own shell, lost <= 2%, copied 0;
- open edges 0 on the body; attach row; gates pass.
The sash falls back to keep, with its reason.

**Tests**

tests/test_lift_off.py; bake shell-in-shell regression (test_bake hidden faces).

### WP16 - [rig context] Optional local AI read of the concept + Tripo body type (built last)

*Effort M; depends on WP2, WP7; wave W16.*

**Modules**

- `forge/brief.py`
- `forge/cli.py`
- `forge/supervisor/prompt.py`
- `forge/supervisor/llm.py`
- `forge/tripo_stage.py`
- `blender_addon/forge_send/__init__.py`
- `blender_addon/forge_send/stages_ui.py`
- `tests/test_llm_supervisor.py`
- `tests/test_tripo_stage.py`

**Technique**

As wps.json WP16, scope unchanged. It stays optional and is built last (lead's choice); sure is capped at 0.6 and never overrides a measurement with sure >= 0.8.

**Acceptance**

As wps.json WP16.

**Tests**

As wps.json WP16.

### WP17 - [rig context] Acceptance on the director's PC (plus the Step 4 checks)

*Effort S; depends on WP7, WP8, WP9, WP10, WP11, WP12, U9; wave W14.*

**Modules**

- `blender_addon/forge_send/stages_ui.py`
- `blender_addon/forge_send/stages_late.py`
- `blender_scripts/forge_bpy/addon_trial.py`
- `docs/research/step8_acceptance.md`

**Technique**

As wps.json WP17. Added, on the director's real meshes:
- no unplanned change (U1's metric computed on the PC);
- plan rows == run rows;
- U9 timings within target;
- the detached prop and sockets survive the Unreal and Unity export.

**Acceptance**

As wps.json WP17, plus: 0 unplanned-change islands and 0 red deviation rows on two real Tripo meshes, Left and Right.

**Tests**

As wps.json WP17.

## 7. Zoo targets

### Gates (fast = plain + ai, 74 runs; real = 37)

| Gate | When | Fast total | Real total | Must also hold |
|---|---|---|---|---|
| Baseline | today | 782 (step4 340, rig 214, detect 228) | 379 | - |
| A: silent damage gone | U6 + U7 + U8 | <= 385 (step4 <= 6) | <= 185 (step4 <= 4) | 0 damaged / limb / plan != run / QR-with-parts / blocked lines; plan_drift 0; loose shells 0; zoo v2: pouch kept, raised arm mirrored, scar grouped, +ain false protection < 2% |
| B: parts found and classed | U12 + U13 | <= 125 (detect <= 80, skeleton <= 24, class + no class + phantom <= 13) | <= 65 | two_tails, trunk, dragon and quadruped keep their welded cuts |
| C: skeleton | WP4 + WP14 + WP15 | <= 100 (skeleton <= 4) | <= 50 | new 'quadruped skeleton off' score 0 on the 4 quadruped bodies |
| Final | P4 + one frozen calibration pass | <= 80 | <= 40 | rig coverage (fake_arp) >= 95% of truth chain/wing/limb/prop parts; every ledger row has one Step 8 outcome; 0 unplanned change on zoo v2 and on 2 real meshes (WP17) |

### Per body (fast; 'after P1' assumes Step 4 at 0 and island rows counted as found)

| Body | Baseline plain / +ai (step4, rig, detect plain) | After P1 plain / +ai | Final target (each) | Real: baseline (step4) | Fixed by |
|---|---|---|---|---|---|
| bat_wings | 11.5 / 11.5 (0, 6.5, 5) | 11.5 / 11.5 | <= 1 | 11.5 (0) | U10 U12 U13 |
| bird_wings | 5 / 8.25 (0, 5, 0) | 5 / 8.25 | <= 1 | 5 (0) | U11 U12 U13 |
| one_wing | 15.75 / 8.25 (11, 4.75, 0) | 4.75 / 4.75 | <= 1 | 15.75 (11) | U2-U6 U3 U12 U13 (U16 to cut) |
| dorsal_fin | 7 / 7 (6, 1, 0) | 1 / 1 | 0 | 7 (6) | U2 U6 U12 |
| shoulder_cannon | 4.5 / 4.5 (2, 1, 1.5) | 1 / 1 | 0 | 4.5 (2) | U2 U5 U6 U12 (U19) |
| two_tails | 0 / 0 (0, 0, 0) | 0 / 0 | 0 | 0 (0) | guard: U4 U6 keep cuts |
| trunk | 0 / 0 (0, 0, 0) | 0 / 0 | 0 | 0 (0) | guard: U4 U6 keep cuts |
| cape | 6.75 / 11.5 (4, 0.25, 2.5) | 2.75 / 7.5 | <= 1 | 6.75 (4) | U2 U6 U10 U11 U12 U13 |
| tentacles | 9.25 / 8 (2, 3, 4.25) | 7.25 / 6 | <= 1 | 9.25 (2) | U2 U5 U11 U12 U17 |
| horns_asym | 21 / 21 (18, 0, 3) | 0 / 0 | 0 | 21 (18) | U2 U5 U6 (U18) |
| quadruped | 6 / 8 (0, 3, 3) | 6 / 8 | <= 3 | 6 (0) | U3 U10 U12 WP13 WP14 |
| weapon_in_hand | 22 / 22 (15, 4, 3) | 4 / 4 | 0 | 22 (15) | U2 U4 U5 U6 U13 (U15) |
| forearm_shield | 9.75 / 10.75 (2, 5.25, 2.5) | 5.25 / 7.75 | <= 1 | 9.75 (2) | U2 U5 U10 U11 U13 (U19) |
| sash_diagonal | 21 / 21 (18, 0, 3) | 0 / 0 | 0 | 21 (18) | U2 U5 U6 |
| ponytail_side | 21 / 21 (18, 0, 3) | 0 / 0 | 0 | 21 (18) | U2 U5 U6 |
| antlers | 2 / 2 (0, 2, 0) | 2 / 2 | 0 | 2 (0) | U12 |
| hair_spikes | 6 / 6 (0, 0, 6) | 6 / 6 | <= 2 | 6 (0) | U10 U12 |
| back_spines | 5 / 5 (0, 0, 5) | 5 / 5 | <= 1.5 | 5 (0) | U10 U12 |
| skirt | 7 / 7 (0, 4, 3) | 7 / 7 | <= 1 | 7 (0) | U10 U11 U13 |
| four_arms | 5 / 6 (0, 5, 0) | 5 / 6 | <= 1 | 5 (0) | U12 WP15 (WP10 clicks) |
| four_wings | 11.25 / 12.25 (0, 5.75, 5.5) | 11.25 / 12.25 | <= 2 | 11.25 (0) | U10 U12 U13 |
| tail_spikes | 26 / 14 (11, 5, 10) | 15 / 14 | <= 3 | 26 (11) | U0 U6 U10 U12 |
| held_staff | 7.75 / 8.75 (0, 4.75, 3) | 4.75 / 5.75 | <= 1 | 7.75 (0) | U2 U3 U13 (U15) |
| dragon | 7.25 / 8.75 (0, 1.25, 6) | 7.25 / 8.75 | <= 2 | 7.25 (0) | U10 U12 WP14 |
| loadout | 10 / 10 (2, 5, 3) | 5 / 5 | <= 1 | 10 (2) | U2 U5 U12 U13 (U15) |
| winged_tail | 11.75 / 11.75 (0, 6.75, 5) | 11.75 / 11.75 | <= 1 | 11.75 (0) | U10 U12 U13 |
| naga | 5 / 19 (2, 0, 3) | 0 / 0 | 0 | 5 (2) | U2 U5 U6 |
| chibi | 6 / 10.5 (0, 6, 0) | 6 / 10.5 | <= 2 | 6 (0) | U10 U12 WP4 |
| back_hair | 3 / 3 (0, 0, 3) | 3 / 3 | 0 | 3 (0) | U10 U12 |
| one_wing_bat | 18.75 / 10.75 (11, 5.25, 2.5) | 5.25 / 6.25 | <= 1 | 18.75 (11) | U2-U6 U10 U12 U13 |
| dorsal_fin_quadruped | 14.25 / 20.25 (6, 2.25, 6) | 8.25 / 9.25 | <= 2 | 14.25 (6) | U0 U3 U6 U10 U12 WP14 |
| shoulder_pauldron | 26 / 26 (23, 0, 3) | 0 / 0 | 0 | 26 (23) | U2 U5 U6 (U19) |
| weapon_up | 13.25 / 13.25 (13, 0.25, 0) | 0.25 / 0.25 | 0 | 13.25 (13) | U0 U4 U6 U12 |
| bat_wings_shells | 11.5 / 11.5 (0, 6.5, 5) | 11.5 / 11.5 | <= 1 | 11.5 (0) | U2 U5 U10 U12 U13 |
| quadruped_shells | 7.5 / 7.5 (0, 4.5, 3) | 7.5 / 7.5 | <= 3 | 7.5 (0) | U2 U3 U12 WP14 |
| tentacles_shells | 9.25 / 8 (2, 3, 4.25) | 7.25 / 6 | <= 1 | 9.25 (2) | U2 U5 U11 U12 |
| naga_shells | 5 / 19 (2, 0, 3) | 0 / 0 | 0 | 5 (2) | U2 U5 U6 |

Sum of per-body final targets: 69 fast (plain + ai). The committed final gate is <= 80, which leaves room for the calibration pass.

## 8. Existing tests

All existing tests stay green, except these few whose meaning changes by design. U6 rewrites them in the same PR, and each rewrite states the old and the new rule:
- `test_retopo_shape::test_a_part_that_cannot_be_cut_is_never_mirrored`: the part is kept as it is while the rest is mirrored.
- `test_retopo_shape::test_a_part_the_plan_could_not_cut_blocks_the_mirror`: the part is protected and the mirror goes on.
- `test_retopo_shape::test_a_cut_to_one_side_of_the_middle_is_never_mirrored_onto_bare_skin`: the lid region is kept, with no dent (the old veto goes).
- `test_retopo_shape::test_one_sided_detail_turns_mirror_symmetry_off`: the flag now comes from the field.
- `test_appendages::test_a_part_the_one_sided_cut_takes_does_not_block_the_mirror` and the plan-row tests: rows come from the ledger.
- `test_stage_late`: prepare_retopo symmetry flags.

`density.one_sided_parts`, `density.asymmetry`, `density.straddles_middle` and `parts.has_twin` stay as thin wrappers, so the roughly 12 fixture tests that use them keep passing. U12 keeps the old kind strings as aliases, so the roughly 26 kind assertions in `test_appendages` read the same; any assertion that changes because the old kind was the bug is listed in the PR. WP4 keeps `estimate_points` unchanged (rig spec 6.8).

## 9. How the rig-context work packages fold in

The rig-context packages (rig_context/wps.json WP0-WP17) stay as specified, with eight changes, and are folded into one order.

**Order.**
- WP0, WP1 and WP2 run in the first wave, next to U0/U1: they are new files, and rings.py and props.py reuse WP1.
- WP3-WP17 follow Phase 1 and Phase 2. WP16 (local AI read) stays last.

**Changes to the spec.**
1. Section 6.2, pass 1: the exclusion set is U10/U13's per-vertex part-map mask (sheet vertices of parts attached to the core, significant one-sided add-on islands beyond the wrist narrowing, loose shells), not 'appendages.find far components'. The 0.12 H hand-tip keep-rule applies to hand vertices only, so a held prop no longer drags the hand tip to the sword tip.
2. Sections 4.1/5.2: brief parts[] gain 'desc' (shape / attachment / symmetry) and 'step4' (row, disposition). prefill_layers reads forge_ledger: measured kinds carry sure from rule margins, Step 4 choices are src 'you' and are never re-asked.
3. Section 7.3: the question cap of 6 counts Step 4's questions (at most 2). PARTS_MATCH and LABEL_MARGIN compare against ledger rows.
4. Sections 9.5/9.6: add_extras iterates every chain-like ledger row (tails, tentacles, trunks, extra arms, and wings behind the WP0 gate); rigid rows go through make_rigid. Props detached in Step 4 arrive with a grip frame for the socket. place_joints reads rows from the low (U14) and never re-detects.
5. Section 5.4: templates get a descriptor match (two ground-reaching tube twins = legs, etc.), so 'What is it' is pre-filled with a sure value and quadrupeds are chosen without a question when sure.
6. WP10: Point and tell gains Wing, Fin, Cloth or hair, Armour or attached piece, and Held prop, and also works on Step 4 rows ('+ Add a part Forge missed' seeds a ledger row).
7. WP14: legs from the limb guard's ground columns and the part map's ground-reaching tubes; trunk and leg-pair splits from R1's level-set loops only if R1 passes its gate (crotch stable within 0.02 H with wings or cape, quadruped leg splits within 0.05 H), else sections.trunk_axis.
8. WP17 also checks the Step 4 contract on the director's real meshes: 0 unplanned change, plan rows == run rows, U9 timings.

**Overlaps resolved.**
- ground_contacts: one implementation, in limb_guard.py, imported by WP3.
- Loop metrics: one implementation (sections.loop_props) used by rings.py.
- The part map's exclusion mask is the single source for both the interim v1 fix (U13) and WP4.
- Point-and-click joints (WP10, WP13) are the safety net for every skeleton the estimators miss: wings, quadrupeds, four arms, chibi.

## 10. Director flow

**Step 4, before running.** The Symmetry choice (Auto / Left / Right / No mirror) stays as it is. Under it, a 'Left-right check' box appears, filled from the stored plan. It refreshes when the side, the triangle count (only when the set of cut parts changes) or the model changes. A typical body:
- 'Made symmetric from the left side.'
- 'Kept as they are (not mirrored):'
  - 'left shoulder: only on the left' [eye]
  - 'horns: left and right differ' [Use left for both]. Greyed, with the reason, when the horns cannot be cut cleanly.
  - 'across the chest: not symmetric' [eye]
  - 'and 3 smaller differences, kept'
- 'Cut off, remeshed alone, joined back: tail'
- 'Touching: cape and left calf - kept joined' [Separate them]
- 'Held in the right hand: long thin object - taken out, hand socket ready' [Leave in hand]
- 'Quad Remesher mirror: off - 2 things stay one-sided'
- More: 'both legs looked like parts (ignored)'

The Run button says what will happen: 'Run: symmetric from the left, 3 things kept as they are'.

**Other cases.**
- Nothing differs: 'Left and right match: the whole body is mirrored. Quad Remesher mirror: on.'
- No mirror plane: 'Not mirrored: left and right differ too much (38% match). Kept as it is.'
- In Auto only three kinds of row appear: the Quad Remesher mirror on/off row with its reason, the cut rows and the touching rows.

**Seeing it.**
- 'Show differences' colours the original: grey unchanged, green made symmetric, orange kept as it is, blue cut off and joined back, purple touching. Red appears only when the director chose to copy something. A one-line legend sits under the button.
- 'Preview' shows exactly the shape the new mesh will be fitted to (the plan's dry-run result), over the original. Kept regions visibly stay as they were, and nothing appears or disappears. Today's Mirror-modifier preview shows copies and deletions that the run does not do.

**Choosing.**
- At most 3 rows carry buttons. Every row has a safe default, so no row blocks Run.
- Step 4 asks at most 2 real questions, and only these: a held prop at a hand, and a big one-sided part (keep or copy). They count toward Step 8's limit of 6.
- '+ Add a part Forge missed' and Point and tell work on any highlighted region (Wing, Fin, Cloth or hair, Armour or attached piece, Held prop, Part of the body).

**After the run.** The same rows read 'Done: ...' in the plan's order, each with its coverage. A deviation is the only red row, and it always says what was done instead, e.g. 'Planned: cut the tail. It did not cut at run time: kept in place, nothing copied or deleted.' A part that lost more than 2% in remeshing shows a red row with [Show].

**Step 8.** The Rig Brief card opens pre-filled from the same rows: 'one wing on the left', 'prop in the right hand (taken out in Step 4, socket ready)', 'cape: moves with the body', 'horns: stay stiff', 'tail: 6 bones'. Nothing the geometry already settled is asked again, so the six-question cap holds. Joints come from the masked guess, then v2. Where Forge is unsure the director clicks points: wings, four legs, four arms. Every Step 4 row gets exactly one Step 8 outcome (chain, stiff, moves with the body, socket, or 'not rigged on its own because ...'). The motion check names contacts that will stretch.

## 11. Product decisions taken by the lead

1. Default for anything without a faithful twin (one-sided add-ons, differing twins, off-centre parts on the middle, loose pieces): kept exactly as modelled, with the mirror going around it. Copying or deleting happens only on an explicit click, item by item. Why: the owner's rule 'never silently damage the director's model'.
2. Posed pairs: the chosen side wins, as today, when nothing else is kept. When something else is kept, the pose stays as modelled, with a 'make the right like the left anyway' button that lists exactly what would be copied. Why: the displacement mirror cannot re-pose a limb, and a full mirror would copy the kept parts.
3. Quad Remesher's own X symmetry is on only when no significant difference stays on the body. Some bodies lose mirror-identical quads, and a row says why. Why: an honest trade, better than a remesh that copies parts.
4. Differences smaller than the finest export target can show (about half a 30k quad) are listed as one grouped row; they are not mirrored into the shape and do not turn Quad Remesher symmetry off. Protection always uses the 30k resolution, whatever budget is chosen. Why: a sash must not become an X at Unity 8k, and changing Triangles must not force a new cut.
5. In Auto, Forge never cuts a part just to keep Quad Remesher symmetry on; only thin-for-budget parts are cut, as today. Why: fewer seams and fewer welds, and the safer default.
6. No limit on how much of the body may be protected. The naga's coil is kept and the rest is mirrored. Why: the displacement mirror handles it, and refusing to mirror would help no one.
7. If the run would come out different from the plan, Forge continues with the safer outcome (the part stays in place and protected, Quad Remesher symmetry off) and shows one red row. It does not stop the run. This applies only once task 49 (determinism) is closed; until then development builds log both fingerprints. Why: 'Run is never blocked', and fail safe.
8. Contacts (a cape touching a calf, tentacle tips touching) stay joined in the mesh by default. Skin weights are split at the contact in Step 8, and 'Separate them' is an option. Why: cloth moves with the body (an earlier lead choice), and cutting is a visible change.
9. Held props are taken out with a rebuilt grip and a hand socket when the cut is clean; otherwise they stay in the hand with the reason given. Why: an earlier lead choice (detachable props with sockets), applied fail-safe.
10. Sheets (wings, fins, capes) stay with the body by default. They are cut, with the wedge plug, only when the director asks, or when a membrane is thinner than one quad and has a clean slot root. Why: no cut is needed for safety any more, and slot cuts are the riskiest.
11. Step 4 asks at most 2 questions (held prop at a hand; a big one-sided part), counted inside the rig context's limit of 6. Everything else is an inline choice with a safe default. Why: the six-question limit.
12. The Step 4 preview shows the real prepared mesh from the plan's dry run, not a Mirror modifier. Why: 'what you see is what runs'.
13. Show-differences colours: grey unchanged, green made symmetric, orange kept as it is, blue cut off and joined back, purple touching, red only for explicit copies. Why: red is kept for things that change on request.
14. Skeleton order: a cheap interim mask on today's estimator now (U13), v2 next (WP4), then quadrupeds guided by clicks first (WP13) and the quadruped estimator after (WP14), with the structure research (R1) feeding it only if it passes its gate. Why: the quickest credible fix first, and four-legged animals are the next body type.
15. The test zoo gains bodies the current one cannot test: an even-in-x AI noise variant, a raised-arm posed pair, a small fused pouch, a 3 mm scar, plus loose-shell scoring. They are scored in a separate total, so the 782/379 baseline stays comparable. Why: the current warp is odd in x (asymmetry 0.0000), so tolerance numbers cannot be trusted without them.
16. Lift-off for pads (U19) and 'use this side for both' (U18) are optional late packages, built only after Phase 1 holds on the director's real meshes. Why: both are geometry surgery with fallbacks; safety comes first.

## 12. Not solved

- Intent vs accident: geometry cannot tell a designed broken horn from an AI melt. The default keeps both. 'Use this side for both' fixes it in one click, and only where both twins cut cleanly.
- 'Use this side for both' has no option for differences with no clean cut (pads, reliefs, a lopsided sash, differing pauldrons). That would need mesh splicing or SDF blending.
- Bodies that keep a significant difference get a symmetric shape but not mirror-identical quads (Quad Remesher symmetry off). Lift-off (U19) brings it back only for pads with a neck-free footprint, not for a naga coil or a cape hem.
- A posed pair on a body that also keeps something loses its pose fix unless the director presses 'make the right like the left anyway'.
- Asymmetric poses (twisted torso, turned head) have no mirror plane and stay unmirrored. Re-posing is out of scope.
- Parts fused along their whole length (a tail glued to a leg, A-pose arms fused to the hips, a cape glued flat to the back) show no root or contact ring. Step 4 keeps them with the body; Step 8 falls back to the rig context's point-and-click questions.
- Interpenetrating surfaces that are not fused (cloth sunk into a leg) are tolerated by the measurements, not repaired. Layered cloth (a cape over wings) is not modelled for skinning beyond the contact rows.
- Contacts are not separated geometrically by default. Fused tentacle tips stay fused and are split only for weights.
- On very lumpy AI meshes the noise floor rises, so small one-sided details (an earring) are kept in the grouped row rather than as their own rows. Real noise calibration needs the director's meshes (U9).
- Non-standing poses (sitting, lying, flying) weaken the ground terminals and the body-plan match. The limb guard becomes conservative (no big cuts), and the skeleton needs clicks.
- The four_arms and chibi skeletons rely on WP4/WP15 and on clicks. The interim mask does not fix them.
- Semantic identity beyond shape: tail vs tentacle vs trunk all behave as chains but may be named wrong. A thick-rooted feathered wing can read as an arm pair until the Rig Brief confirms.
- Quad Remesher's own output is not deterministic. Plan == run is guaranteed up to the remesher's input; after that, Forge reports plan vs result and does not guarantee it.
- In the baseline's real run, the quadruped's weld after mirroring falls back to 'attached: thin faces'. The faithful fit target may help, but no fix is claimed.
- Colour-only asymmetry (a tattoo on a symmetric surface) in a region the director let the mirror change takes the kept side's colour. U14 bakes those regions from the prepared high, so it is consistent, but it is not flagged separately.
- Runtime of the field, the thickness map and the dry run on 1M-5M meshes on the 4-CPU PC is not measured yet. U9 is the go/no-go gate, with sampling and a cache as the fallbacks.
- Buried internal shells are kept out of the mirror but are still remeshed and still cost triangles.

## 13. Risks and mitigations

- **Real Tripo noise sets more islands than the zoo.** U1 adds the +ain zoo variant and U9 measures on the director's meshes. The noise factor is recalibrated across models, never per model. Small islands are grouped, never shown one by one.
- **The keep-around mirror folds in tight gaps (fingers, between the legs).** The fold gate lowers w and then drops one mode, with the reason. Topology never changes, so nothing tears.
- **Hidden non-determinism in bmesh.** U0 comes first. Any leftover shows up as plan_drift, which fails safe and is logged with both fingerprints.
- **Runtime on 5M meshes.** Sampled field (200k), sampled thickness (100k), and a cache of the dry run keyed by fingerprint. U9 is the go/no-go gate.
- **Calibration of the ring and descriptor thresholds.** One pass on the zoo, then frozen, all as shape ratios. A threshold that fires against what the director accepts is loosened by rule across models (rig spec 15.7).
- **Rig-context spec drift.** The eight spec changes in section 9 are the only deviations. WP0's probe results gate wings as arm duplicates, birds, and the socket export.

## 14. After the rigging work (added on the director's request, 2026-11-28)

Order set by the director: finish the started work (W1, the mouth-dent fix, the fix-tool / detail-paint / face-kit designs) -> build "Fix selected" and the face kit -> fix the tool bugs (detail paint strength, asked vs got, crease handling at the mouth corners, logic errors the designs list) -> the rigging work (WP3-WP17 and the U packages above) -> this section. Lean mode: one builder and one reviewer per job, a second review only for serious findings.

Checks to carry into the rigging work (named so they are verified, not assumed):
- **Ears stretch up to 5x in the current Step 8 check** (director's bull, 1.15.x: left/right ear and ear roots 3.2-5.2x skin stretch, faces turning inside out). WP8's ear chains must bring these rows to green on the bull test.
- **One-eared animals and stray ears**: the director's probe proved arp.disable_limb removes one side's ear and keeps the other (docs/research/arp_3_79_findings.md). Build it in WP8/WP15: add the pair, disable the missing side.
- **HUMANOID export with an extra arm pair**: answered by the director's probe rerun (--only multi_arm,limbs,build); WP6's export type follows the answer.

Roadmap items in no plan yet (docs/FEATURE_ROADMAP.md, A1), scheduled here after the rigging:
- **R2-1 Anatomy flags**: detect and flag anatomy Tripo sometimes generates (udders, genitals), with an option to smooth it over before Step 4. Not in Forge.
- **R2-2 Shoulder girdle for four-legged animals**: scapula slide / chest sling so the front legs do not collapse at the shoulder. Not in Forge; pairs with WP13/WP14.
- **R2-3 Jaw hinge from the face's shape**: the hinge pivot from landmarks and the side silhouette (feeds the face kit's mouth and ARP's jaw). Not in Forge.
- **R2-4 Engine import check**: headless import into Unreal and Unity and the validation that the asset arrives right (scale, facing, skeleton, materials). Not in Forge.
- **R2-5 Finish the partial ones**: breathing bone and idle breath; hooves and foot-roll pivots (heel, ball, toe tip); merging materials into one atlas for mobile; save points with crash-safe resume; real-world scale, facing and origin check; vehicle data (wheel bones, radius, suspension). Partly in Forge today: each needs an audit of what exists before building.
