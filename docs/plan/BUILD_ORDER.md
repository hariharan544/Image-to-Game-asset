# Build order from the three designs (lead's call, lean mode)

Designs: DESIGN_fix_tools.md (F0-F10), DESIGN_detail_paint.md (D0-D13), DESIGN_face_kit.md (FK0-FK12).
Rule: one builder + one reviewer per job, fixes only for real findings, nothing new until running jobs merge.

## Stage 2a - Fix selected (first usable set)
- FX1 = F0 + F1a (+ the undo part of F1b): fit-source record and crease record written by Step 4,
  fixkit core (patches, per-vertex target, diagnose incl. 'crease cut across' / 'bend in the wrong
  place', verify, transactions), BVHTree.FromObject source tree (also speeds every Step 4 run).
- FX2 = F2 + F3: Snap, Smooth, Auto fix ladder L0-L3, panel (Select the area, Find problems top 10
  in the background with Stop, Next/Previous, Keep as is, Undo, Show before, Both sides).
- FX3 = F4: Follow crease (two-click trace) + the director's mouth-corner notch (L4a slide, L4b
  denser + straight cut). This is the tool for the defect in 85/87/88.
- Later (after rigging unless asked): F5 Denser/Coarser/Rebuild here, F6 Match other side,
  F7 re-runs with grafts, F8 carry through Steps 4b-8, F9 Step 4 tidy-up, F10 sweep.

## Stage 2b - Face kit, geometry first
- FK-A = FK1 + FK2: face marks (mouth line, corners, eye fits, hinge/chin) and the Step 4b panel.
  Uses a local copy of the crease tracer until D7a exists.
- FK-B = FK3: mouth cut open with a measured gap, inside of the mouth to a throat point.
- FK-C = FK4 + FK5 + FK5b: eyes with lids and sunk eyeballs, teeth/tongue/eyeball meshes, Step 5
  keeps kit objects out of UVgami/packer.
- Waits for the director's ARP rerun: FK0 probe, FK8 rig, FK9 checks (go with the rigging stage).
- Later: FK6, FK7, FK10, FK11 full body set, FK12 edit the face.

## Stage 3 - Tool bug fixes (detail paint, logic)
- DP1 = D0 + D1b: record QR settings/timing/raw snapshot; density-aware fake QR; 'unpainted =
  today' byte-identical test.
- DP2 = D1 + D2 + D3: Forge_Paint layer at half strength with presets, field (mirror about the
  measured middle, per-area cap, seeded grading), cost rows. No Quad Remesher setting changes
  here: whether hard-edge detection comes back on is settled by the PC probe (D6).
- DP3 = D4: asked vs got on the raw snapshot, 'Show Quad Remesher's result'.
- PC probe D6 (about 10 min on the director's PC) before D7c/D12/D13. D9 GPU-only bake trial.

## Carried from the mouth-dent fix (1.15.5)
- region_labels puts the neck at mouth height on a neckless cartoon head, so about half of the
  mouth line is labelled body and carve never sees it (goes with the part map work).
- Zoo dragon at 3000 triangles: worst bump 8.6 -> 23.9 tol after the final tidy on thin wings
  (island counts went down 86 -> 14). Trace in Stage 3.
- Narrow notches (about one quad wide) come back only part of the way by design: going all the
  way digs the skin beside them. Follow crease (FX3) is the tool for those.
