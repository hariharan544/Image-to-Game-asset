# Forge plugin hunt: what to add, what to test, what to skip

Research date: 27 November 2026. Target: Blender 5.3 on Windows, driven by Forge from Python.

## How to read this

- **Nothing was installed or run.** Every fact comes from the vendor's own page, documentation, changelog or published source code. Speed and quality figures are the vendors' own claims.
- **Blender 5.3 is new.** Most vendors only claim support up to 5.2. Every tool below needs a load test in your Blender 5.3 before Forge depends on it.
- **"Scriptable" means Forge can press the button for you.** "Confirmed" means the command name was read in vendor documentation or in the add-on's source code. "Unproven" means the vendor publishes no command names, so Forge can only find out after the add-on is installed.
- Many paid items are 10 days to 2 months old with few or no ratings. They are marked "unproven product".

## Executive recommendation: top 5, in order

| # | Tool | Cost | Why now |
|---|---|---|---|
| 1 | **Voxel Heat Diffuse Skinning 5.1.1** | $30 (1 seat) | The only paid tool here that has all four: a Blender 5.3 listing, Windows support, an October 2026 update, and a vendor-documented script recipe. It fixes Step 8's main failure: Blender's automatic weights fail or leak on Tripo characters made of separate, non-watertight parts. |
| 2 | **3D Print Toolbox** | Free | A maintained "Make Manifold" call and geometry checks to use as a gate before Quad Remesher. Command names confirmed in source. |
| 3 | **Texel Density Checker** | Free | Gives Forge a measured texture-sharpness number per asset and a one-call rescale before UVPackmaster packs. Fills the gap between UVgami and UVPackmaster. Command names confirmed in source. |
| 4 | **UniV** | Free | Island tidy-up Forge lacks: straighten islands and stack identical ones so mirrored props share texture space. Use it for orient and stack only, and Texel Density Checker for density. |
| 5 | **AI Mesh Fixer** | $14 | Purpose-built Tripo clean-up with a Tripo preset and a before/after report. Buy as a trial: its command name is unpublished and it is tested on 5.2, not 5.3. Compare against Forge's current Step 3 on two or three real Tripo meshes before adopting. |

**Total spend: $44.** Three of the five are free.

**Test next, after the top 5:**
- **SimpleBake ($20)**: the best feature fit for Steps 6 and 9, but its script commands are undocumented.
- **Wiggle Bones or Jiggle Physics (both free)**: tail and ear follow-through for the animation check.
- **EasyWeight (free)**: weight clean-up after binding.

**Two warnings for whoever wires these in:**
1. Both Step 3 tools fill holes by default. 3D Print Toolbox fills every hole unless its `sides` setting is changed. AI Mesh Fixer's Game preset fills holes up to 64 edges. Either can close eye and mouth openings or the neck cuts made in Step 2, so Forge must set these values explicitly.
2. 3D Print Toolbox's Make Manifold works on the active object only. Forge must loop over the parts.

**One lead not yet researched:** Auto-Rig Pro's changelog mentions "Support for the new Adaptive Auto Skinning addon as new bind engine". Its price, vendor page and 5.3 support are unknown. It is worth a follow-up, because anything exposed as an ARP bind engine is reachable through Forge's existing ARP bind call.

---

## Step 3: geometry repair

| Name | What it adds to Forge | Scriptable? | Blender 5.x | Price | Link | Verdict |
|---|---|---|---|---|---|---|
| AI Mesh Fixer (Sonneblom Digitaal) 1.3.0, 25 Nov 2026 | One-call Tripo clean-up: weld triangle soup, remove floaters, fill small holes, fix normals, decimate to a triangle budget keeping UVs and vertex colours. Before/after report Forge can show. Tripo preset. | Unproven. Vendor says "Every setting is on the Fix operator: F9 shows them all", which is good indirect evidence, but no command name is published. | Listing 4.2 - 5.2; "Tested on Blender 4.2 LTS and 5.2 LTS". 5.3 not claimed. Windows not named (pure Python). | $14 | https://superhivemarket.com/products/ai-mesh-fixer | **Trial.** Unproven product (about 1 month old, no ratings). Leave its QuadriFlow remesh, Symmetrize and Flat base options off. Set "Max hole edges" to 1 to keep openings. |
| 3D Print Toolbox 1.5.0, 19 Oct 2026 | Free manifold gate before Quad Remesher, plus checks (solid, intersections, shells, degenerate faces). | **Confirmed in source.** `mesh.print3d_clean_non_manifold` (settings: threshold, sides). Checks: `mesh.print3d_check_solid`, `_check_intersect`, `_check_shells`, `_check_degenerate`, `_check_all`. | "Blender 4.2 LTS and newer", no upper limit. 5.3 not named. | Free (GPL) | https://extensions.blender.org/add-ons/print3d-toolbox/ | **Install.** Community-maintained on Blender's extensions site. Removes loose geometry and interior faces, but not fully separate hidden shells. Active object only. |
| MeshRepair (ssh4net) 2.8.0 | Fills large holes (neck cuts, split-off props) with triangles that match the surrounding density. Built for million-polygon meshes. | **Confirmed two ways.** Command line (`meshrepair input.obj output.obj`) and add-on commands read in source (`meshrepair.repair_all`, `meshrepair.fill_holes`, `meshrepair.detect_holes`, `meshrepair.preprocess`). | Docs say "Blender: 3.3+", source says 4.2. No 5.x statement. | Free (the licence texts disagree between GPL and LGPL versions) | https://ssh4net.github.io/MeshRepair | **Maybe, low priority.** The engine must be obtained separately ("Download from Patreon or build from source"). Last update date not verifiable. Its clean-up removes small disconnected pieces, which could delete props on a joined mesh. Use before texturing only. |

## Step 4: retopology

Nothing found replaces Quad Remesher for the main character. No tool gives automatic eye and mouth loops without someone clicking landmarks.

| Name | What it adds to Forge | Scriptable? | Blender 5.x | Price | Link | Verdict |
|---|---|---|---|---|---|---|
| QuadMend 0.10.9 (MendWorks) | Fallback remesher for parts where Quad Remesher tears or refuses. Repairs first, runs two remeshers, keeps the better result, re-bakes textures. Has symmetry and a "Keep Separate" mode for parts. No density map. | Unproven. Runs "in a background process", so Forge would have to wait and poll. | "tested on 4.2, 5.0 and 5.2". 5.3 not claimed. Windows 10/11 full support. | $15 (the $49 on the page is a separate 5-product bundle) | https://superhivemarket.com/products/quadmend | **Maybe.** Pre-1.0, about 2 months old, 2 ratings. Vendor warns that thin clothing and hair pieces can merge into the body. |
| NexTopo 1.0.0 | Symmetric quad remesh with input repair and part-by-part baking, which matches the body-plus-props problem. | Unproven. Separate engine program with an undocumented command line. | "developed and tested on Blender 5.2 LTS". Windows x64 only. 5.3 not claimed. | $12.99; free edition capped at 5,000 quads and 10,000 vertices | https://superhivemarket.com/products/nextopo-auto-quad-remesh-lods--baking-for-blender | **Maybe.** 17 days old, no ratings. Unsigned engine triggers a Windows SmartScreen prompt. Vendor says "Plan to re-unwrap or re-bake textures for production". Updates included for 12 months. The free edition is a no-cost test for the 8k mobile target. |
| B-Skin (alternatives: TopoFit, BWrap, Wrap for Blender) | The only route to real deformation loops around eyes and mouth: fit one hand-made base mesh, with its UVs and weights, onto each character. | **No hands-free path.** All four need matching landmarks clicked by hand. Landmark sets can be saved as JSON and reused. | B-Skin listing 4.2 - 5.3. TopoFit "4.5, 5.0, 5.1, 5.2 and 5.3". BWrap 4.5 - 5.2. Wrap for Blender 5.0 - 5.2, Windows only. | B-Skin $19. TopoFit $16 (sale). BWrap free tier or $29.99. Wrap for Blender $39. | https://superhivemarket.com/products/b-skin | **Maybe, as a guided manual step only.** B-Skin and TopoFit are 10 - 11 days old. Needs a studio base mesh per body type. TopoFit is "Made for humanoid characters". |

## Step 5: UVs

| Name | What it adds to Forge | Scriptable? | Blender 5.x | Price | Link | Verdict |
|---|---|---|---|---|---|---|
| Texel Density Checker 2026.1.1, 6 Jul 2026 | A measured texel-density figure per asset, and a rescale to a target before packing. Gives the panel a pass/fail number and matching density across body and props. | **Confirmed in source.** `object.texel_density_check` and `object.texel_density_set`. They take no arguments: Forge sets values on `scene.td` first (for example `density_set` as text "10.24") and reads the result from `scene.td.density`. Needs an active object and a normal window. | "Blender 4.2 LTS and newer"; README "even 5.0+". 5.3 not named. | Free (optional $10 support copy) | https://extensions.blender.org/add-ons/texel-density-checker/ | **Install.** The extensions-site build is Python only, so slower on big meshes; the GitHub zip has the faster backend. |
| UniV 4.0.0, 8 Jul 2026 | Orient islands to axes, stack similar islands, normalise density, straighten after Quad Remesher. | **Partly confirmed in source.** Density commands read: `mesh.univ_texel_density_set`, `mesh.univ_texel_density_get`, `mesh.univ_normalize`, `mesh.univ_adjust_td`, `mesh.univ_calc_uv_coverage`. Orient and Stack command names not yet read. | "Blender 4.2 LTS and newer"; fixes named for 5.0, 5.1, 5.2. 5.3 not named. | Free | https://extensions.blender.org/add-ons/univ/ | **Install, for orient and stack.** Vendor warns many commands depend on selection mode and modifier keys, so each call needs testing with explicit settings. |
| Zen UV 5.4.0 | Relax for organic islands, stack system, density presets, a pack front-end that drives UVPackmaster. | Unproven. No public command list. Docs warn the Pack command may open a dialog when called from a script. | Listing 4.2 - 5.2. Shows an "untested Blender version" warning on newer builds. | $39 single user | https://superhivemarket.com/products/zen-uv | **Maybe, leaning skip.** Mostly overlaps tools already owned. A 2026 update could not be confirmed. |

## Step 6: detail bake

| Name | What it adds to Forge | Scriptable? | Blender 5.x | Price | Link | Verdict |
|---|---|---|---|---|---|---|
| SimpleBake | Could replace Forge's hand-built bake: auto pairing by "_high / _low" names, auto cage, AO, curvature, thickness and colour ID in one pass, body and props to one atlas, ORM packing and DirectX normals for Unreal. | **Unproven.** No Python or command documentation anywhere on the vendor page. Has "Background baking". | Listing 5.0 - 5.2. "Compatibility is guaranteed with Blender 5 and above - official releases only". 5.3 not yet listed. | $20 single user (studio tiers $60 and $80) | https://superhivemarket.com/products/simplebake---simple-pbr-and-other-baking-in-blender-2 | **Maybe: first thing to test after the top 5.** Latest build date not public. |
| Ultibake 2.0.112, 24 Aug 2026 | Low-cost baker that lists Blender 5.3. | Unproven. A claimed script command could not be confirmed (the docs pages return 404). | Listing 4.2 - 5.3 | $15 | https://superhivemarket.com/products/ultibake | **Maybe, test only.** Empty product description, small user base. Do not plan around it. |
| Marmoset Toolbag 5.03 (separate application) | Industry-standard baker with bake groups, so body and props do not bleed into each other. | Partly. Vendor has a Python section but says more documentation is "coming soon"; the reference manual could not be read. Would run as a separate program, not inside Blender. | Independent of Blender | Individual: $15.19/month or $319.20 one-time on current sale (list $18.99 and $399). Studio: $39.99/seat/month or $1,039.20 one-time on sale. The Individual licence is described as "hobbyist, freelancer, student", so a studio needs the Studio licence. | https://marmoset.co/shop/ | **Maybe, only if in-Blender bakes show artefacts Forge cannot fix.** |

## Step 7: colour texture

| Name | What it adds to Forge | Scriptable? | Blender 5.x | Price | Link | Verdict |
|---|---|---|---|---|---|---|
| Ucupaint 3.0.2, 16 Nov 2026 | A layer stack over the baked Tripo colour for hand touch-up (paint out baked-in lighting, AO layer, masks), then bake down and pack ORM. | Unproven. Mainly an interactive painting tool. | "Blender 4.2 LTS and newer"; the 3.0.2 notes include a Blender 5.3 fix, so the author tests on 5.3. | Free | https://extensions.blender.org/add-ons/ucupaint/ | **Maybe, as your manual touch-up tool.** Not for automation. |
| StableGen | AI repaint or masked repair of a bad Tripo texture. | Batch feature exists but takes only .dae/.glb, makes a new UV map and exports .glb, so it would not keep Forge's UVs or part split. No command documentation. Needs a ComfyUI server (about 5 GB). | "Blender 4.2 to 4.5, or 5.1 and later. Blender 5.0 is not supported." | Free. Three bundled models are non-commercial only; "Qwen Image Edit and SDXL are not affected". | https://github.com/sakalond/StableGen | **Maybe, optional repair branch only.** Close to skip for the automated path. Release date unverified. |
| Curve-BStrands 1.0.0, 19 Nov 2026 | Bakes a reusable hair/fur strand atlas and builds UV-ready cards. Forge has no hair-card path today. | Unproven, and the workflow is hand-directed. Placing cards on a character depends on a companion add-on still "in development". | "tested on 5.1, 5.2 and 5.3" | $19 (updates included for 12 months) | https://superhivemarket.com/products/curve-bstrands | **Maybe, low priority.** Does not fit a scripted pipeline today. |

## Step 8: rig, skinning, pose test

| Name | What it adds to Forge | Scriptable? | Blender 5.x | Price | Link | Verdict |
|---|---|---|---|---|---|---|
| Voxel Heat Diffuse Skinning 5.1.1, 29 Oct 2026 | Skinning that treats assembled parts as one solid. Auto Fusion mode uses one method for face, fingers and toes and another for body and clothes, with an Auto-Rig Pro preset. Iterative Bone Heat "always generates a result, it never fails", a reliable fallback. | **Confirmed in vendor docs.** `bpy.ops.wm.afu_populate_mask_bones(preset_type="ARP")` then `bpy.ops.wm.auto_fusion()`; also `wm.iterative_bone_heat()` and `wm.voxel_heat_diffuse_adaptive()`. Jobs run in the background; Forge polls `scene.fusion_job_finished` (and the two sibling flags) from a timer. | Listing 3.6 - 5.3. Windows 7 - 11. | $30 (10 seats $180) | https://superhivemarket.com/products/voxel-heat-diffuse-skinning | **Buy.** To check on arrival: whether the ARP preset covers tail and ear chain bones, and whether ARP 3.79 offers Auto Fusion as a bind engine (ARP's changelog confirms VHDS as a bind engine but does not name Auto Fusion). The solver is a bundled program, so antivirus blocking it breaks it silently. Version 5.1 removed older modes, so older tutorials will not match. |
| EasyWeight 1.1.3, 1 Sep 2026 (Blender Studio) | Clean-up after binding: remove unused groups, and symmetrise weights even when the mesh is not perfectly symmetrical. | **Confirmed in source** (not a promised API): `object.symmetrize_vertex_weights`, `object.delete_unused_vgroups`, `object.delete_empty_deform_vgroups`. Symmetrise probably needs bones selected in weight-paint mode; untested. | "Blender 4.2 LTS" up to 6.0; 1.1.3 is a fix specifically for 5.3. | Free | https://extensions.blender.org/add-ons/easyweight/ | **Maybe.** Small gain, no cost. |
| Wiggle Bones 1.1.2, 7 Sep 2026 | Physical follow-through on tail and ear chains, baked to plain keyframes so it exports. | **Confirmed in source.** `wiggle.bake` is an ordinary blocking command (not modal); settings live on `scene.wiggle`. | "Blender 4.5 LTS and newer"; "fully fixed for Blender 5.0". 5.3 not stated. | Free | https://extensions.blender.org/add-ons/wiggle-bones/ | **Worth a trial.** |
| Jiggle Physics 4.5.3, 16 Aug 2026 | Same job as Wiggle Bones, with a solver described as "incredibly resilient to exploding". Highest download count of the three (about 96,000). | **Confirmed in source.** `armature.jiggle_bake` is an ordinary blocking command. | "Blender 4.2 LTS and newer"; Blender 5.0 support added December 2025. 5.3 not stated. | Free | https://extensions.blender.org/add-ons/jiggle-physics/ | **Maybe, equal standing with Wiggle Bones.** Try both on one tailed character and keep one. |
| Retarget 5.2.0, 23 Aug 2026 | Free fallback retargeter if Auto-Rig Pro Remap misbehaves on 5.3. Presets include Mixamo, Unreal and Auto Rig Pro. | Unproven. The public repository has no source code. | "Blender 5.0 and newer" | Free | https://extensions.blender.org/add-ons/retarget/ | **Maybe, fallback only.** |
| Animation Layers (2.4.1 or later) | Additive fix layers for hand-cleaning motion capture. Auto-Rig Pro's docs call it "highly recommended if you process a lot of mocap". | Not documented, and not needed for automation. | Listing 3.2 - 5.2 | $30 | https://superhivemarket.com/products/animation-layers | **Maybe, only if you edit mocap by hand.** |
| Auto-Rig Pro Remap and game export (owned; 3.79.24, 26 Nov 2026) | Retargets external clips and exports to engines. See the Animation workflow document. | Export: confirmed in vendor docs. Remap: no script documentation. | Listing says up to 5.2, but November 2026 release notes include Blender 5.3 fixes. | Owned | https://superhivemarket.com/products/auto-rig-pro | **Keep using.** |

## Step 9: export, LODs, collision

| Name | What it adds to Forge | Scriptable? | Blender 5.x | Price | Link | Verdict |
|---|---|---|---|---|---|---|
| Blender for Unreal Engine (xavier150) 4.4.8, 22 Jul 2026 | Exports meshes, collisions and sockets, and writes the Unreal-side import script so assets arrive with correct settings. | **Confirmed in project wiki.** Set scene values (for example `scene.bfu_use_static_export = True`) then `bpy.ops.object.exportforunreal()`. Author says "For the moment I don't have a true API". | 4.4.7 added Blender 5.2. 5.3 not named anywhere. | Free (GPL) | https://github.com/xavier150/Blender-For-UnrealEngine-Addons | **Maybe.** Useful for props, collisions and sockets. Custom LODs are "only for Static Meshes", so not for the rigged character. Test on 5.3 first. |
| Send to Unreal 2.6.7 (community fork) | One call pushes assets into an open Unreal project. | Confirmed in repository docs: `bpy.ops.wm.send2ue()`. | Maintainers test on Blender 3.6 and 4.2 only. | Free (MIT) | https://github.com/poly-hammer/BlenderTools/releases | **Maybe, leaning skip.** No release since November 2025, and it needs Unreal running with remote execution on. |
| Simple Collider 1.2.2, 12 Nov 2026 | Automatic multi-piece collision shapes with Unreal and Unity naming. Forge has no collision step today. | Probable but undocumented. Command names read in public source (`collision.vhacd`, `collision.coacd`, `mesh.add_bounding_convex_hull`). The auto-convex job runs in the background with no documented "finished" flag. | Version history: "tested against Blender 5.3" (the listing field, 4.2 - 5.1, is stale). | $30 | https://superhivemarket.com/products/simple-collider | **Maybe.** Only if multi-piece collision for complex props is wanted; a single convex hull is easy for Forge to make itself. |
| LOD Architect / Quick LOD Decimator | LODs that protect UV seams so baked textures do not tear. Quick LOD Decimator also carries shape keys and vertex groups, which matters for rigged characters. | Unproven for both. | LOD Architect "Tested ... 5.2 LTS / 5.3". Quick LOD Decimator listing 4.0 - 5.3. | $14 / $8.99 | https://superhivemarket.com/products/lod-architect and https://superhivemarket.com/products/quick-lod-decimator | **Maybe.** The seam-protection trick is simple enough for Forge to build in. Buy only if current LODs show seam tearing; for characters, Quick LOD Decimator is the more relevant. LOD Architect is aimed at props. |

**Unity:** no maintained, scriptable Unity-specific exporter confirmed on Blender 5.3 was found. Auto-Rig Pro's own export and Blender's built-in FBX/glTF remain the route for the URP target.

---

## Skip list

**Checked on the vendor page:**
- **Ministry of Flat**: automatic UV command-line tool, but the download is a frozen April 2024 file. Fails the "maintained in 2026" rule. Emergency fallback at most; UVgami is already owned.
- **TexTools (franMarz fork)**: no Blender 5.x statement; nothing that maintained tools do not already cover.
- **BakeMaster**: listing stops at Blender 4.5; docs last updated July 2024.
- **Unreal LOD Maker ($12.99)**: actively updated and tested on 5.3, but Forge already builds LODs. Its only new item is a screen-size number that needs the vendor's second product to reach Unreal.
- **Export Checker ($10.99)**: vendor verified it only on 4.3 and 4.5; does not check skin weights; Forge can do these checks itself.
- **Faceit ($78 - $99)**: manual landmark placement, needs separate eyes, teeth and tongue, no 5.3 claim, no dated update.
- **Wiggle 2: RTX Edition**: same job as Wiggle Bones, with a larger, fast-changing code base and modal bakes that are awkward to script.
- **AnimToolbox ($40)**: animator comfort tools, nothing to automate.
- **Bulletproof Retarget**: one week old, humanoids only. Watch it.
- **Rokoko Studio Live**: adds nothing over Auto-Rig Pro Remap; conflicting licence statements.
- **Cascadeur Bridge**: no update since September 2024; needs a second paid application.

**Rejected by the first researcher, not re-checked:**
- **QRemeshify**: no 5.x statement, low rating.
- **Mesh Repair Tools (SineWave)**: last updated 2024.
- **Quadify Ultra ($75)**: expensive, contradictory version information.
- **QuadAnneal**: overlaps QuadMend and Quad Remesher.
- **LOD Forge**: listing stops at 5.1.
- **SoftWrap**: about 7 years old, manual.
- **Hair Tool 4, RT Fur Cards, Fur Tool For Game Engines**: no Blender 5 confirmation or old listings.
- **WeightForge Pro ($45)**: its page calls its voxel engine "experimental" and says "Auto-Rig Pro is detected but not auto-fixed".
- **LODGen**: last updated August 2025.
- **Ubisoft CHORD**: research-only licence, not usable for a commercial game.
- **Other hair-card tools** (Simple Hair Cards, FiberBake, Tuftwork, StrandKit, RapidHair Cards): all manual grooming tools.

---

## What could not be verified

- **Blender 5.3 for most tools.** Named for 5.3: Voxel Heat Diffuse Skinning, Simple Collider, LOD Architect, Quick LOD Decimator (listing only), B-Skin (listing only), TopoFit, Curve-BStrands, Ultibake (listing only), Unreal LOD Maker, and 5.3-specific fixes in EasyWeight, Ucupaint and Auto-Rig Pro.
- **Script commands** for AI Mesh Fixer, QuadMend, NexTopo, SimpleBake, Zen UV, Ucupaint, StableGen, Ultibake, the LOD tools and Retarget.
- **Release dates** for SimpleBake's and Zen UV's latest builds, QuadMend, LOD Architect, MeshRepair and StableGen 0.4.0.
- **Marmoset's Python baker reference** (blocked by a bot check).
- **GitHub web pages** were blocked in the research session; facts were read from raw files and git instead.

## Suggested order of work

1. Install the three free tools (3D Print Toolbox, Texel Density Checker, UniV) and load-test them in Blender 5.3.
2. Buy Voxel Heat Diffuse Skinning ($30). Test on one Tripo character with a tail and ears.
3. Buy AI Mesh Fixer ($14). Read its command name and compare it against Forge's current Step 3 on real Tripo meshes.
4. Decide on SimpleBake ($20) once someone has listed its commands inside Blender.
5. Trial Wiggle Bones and Jiggle Physics for the animation check (see the Animation workflow document).
6. Leave template wrapping (B-Skin) and hair atlases (Curve-BStrands) as documented manual options.
