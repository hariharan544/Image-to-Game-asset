# "Best AI add-ons for Blender" (NewCgi, youtube.com/watch?v=x1qwuKq9c4Y): what's in it for Forge

Pages checked 27 Nov 2026. Every fact comes from the seller's own Superhive page, docs, changelog or reviews, or from the model makers' own pages. Nothing was installed or run.

**Short answer:** none of the 12 tools should be bought and built into Forge today. There are four reasons:

- **No script commands.** None of the 12 publishes commands Forge could call from a script.
- **No Blender 5.3 claim from the useful ones.** Only Nitro Retopo formally supports 5.3. Smart Remesh, Image to 3D, Auto Unwrap and Smart Segmentation all stop at 5.2. MotionGen's range also stops at 5.2, although its latest notes fix one 5.3 bug.
- **"AI" is mostly a label.** Four of the tools contain no AI at all.
- **Two sellers make most of the list.** At least 4 tools come from Milad Kambari and probably 5 from Blender Procedural. Treat the video as a tour of two catalogues, not an independent comparison.

**What's worth having:**

- One free action using a tool we already own.
- Two very cheap tests.
- Several ideas we can build into Forge ourselves.

Nothing here changes the top 5 from our earlier plugin hunt (Voxel Heat Diffuse Skinning first).

**How sure we are which product the video means:** we could not open the video page (captcha and "too many requests" errors), and its links are cut off. Each tool was therefore matched by name and seller. That is 85-95% sure for each one, but not proven.

---

## 1. The table

| Add-on (seller, price) | What it is, in one line | Forge step | Verdict | Reason |
|---|---|---|---|---|
| Nitro Retopo (Adriflex, $25) | Hand retopology: you draw the patch borders and it fills them with quads | 4 | **Idea-only** | Someone has to draw every patch, and it has no script commands. There is no AI inside; "AI" only describes the meshes it is meant for. |
| Smart Remesh 3 (Milad Kambari, **owned**) | Two remeshers. "Organic" is Instant Meshes, a free research tool from 2015. "Hardsurface" turns flat areas into single big faces. | 4 (rigid props only) | **Trial: gated, low priority** | Worse than Quad Remesher on characters. It might save faces on props, but only if it can be scripted and turns on in 5.3. |
| Auto Unwrap 2 (Milad Kambari, $18) | One-click seams and unwrap, built on OptCuts, the same engine UVgami uses | 5 | **Skip** | UVgami 2.5.0, which we own and which is now free, already does the same. Auto Unwrap has no script commands and no "keep seams off the face" painting. |
| Smart Segmentation (Milad Kambari, $12) | Splits a mesh into parts at thin spots and inward folds | 2-3 | **Idea-only** | The parts have no names, and corrections are hand tools. Forge already measures thickness, but its crease idea is worth copying. |
| Image to 3D (Milad Kambari, $12-18) | Runs open image-to-3D models (TRELLIS.2, Pixal3D, Hunyuan) locally on your graphics card | 1 | **Trial, for evaluation only** | It is the only possible offline backup to Tripo. But no engine is clearly licensed for shipping, it outputs one sealed mesh with no parts, and it has no script commands. |
| AI Material Factory (Blender Procedural, $4.50) | Makes a tiling material from a text prompt using Stable Diffusion | 7 at most | **Skip** | Wrong job: it ignores our asset and its UVs. It has an unnamed cloud service and a 2/5 rating with 72% one-star. |
| Auto Painter AI (Blender Procedural, $19) | Paints a colour texture onto a mesh using an old image model (SD 1.5) | 7 | **Skip** | Colour only, with no roughness, metal or normal maps. Needs administrator rights, has an unnamed cloud service, and is rated 3/5 with half one-star. |
| Blender AI Library Pro (Blender Procedural, $12) | Cloud front end for older open models (InstantMesh, Shap-E, Stable Diffusion) | 1 | **Skip** | Sends concept art to unnamed providers, and the results are weaker than Tripo. |
| AutoDepth AI (Blender Procedural, $9) | Estimates depth from one photo and turns it into a raised surface (a relief), not a full 3D object | none | **Idea-only** | The only useful part is the free depth model inside (Depth Anything V2 Small, commercial use allowed). Forge can run it without the add-on. |
| TrueDepth (Lewis Martin, $25) | Well-made depth-map toolkit: reliefs, 3D-print files, HDRI scenes | none | **Idea-only** | The best depth tool in the video, but nothing Forge needs. Its larger models are non-commercial. |
| Video Depth AI (Blender Procedural, $14) | Depth from video, used to move a raised surface over time | none | **Skip** | This is not motion capture. Its default cloud mode is broken by its own page's admission, and it is rated 2/5. |
| MotionGen (TAngraFX, $1-250) | Turns a video of one person into an animated skeleton (motion capture without markers) | 8 (optional external clip) | **Trial: manual, humans only** | A way to film our own humanoid attack, hit and death clips. It has no script commands, and the AI model underneath and its licence are not disclosed. |
| *(look-alike)* Motion Gen (Haseeb Ahmed, $20) | Makes humanoid motion from a text prompt | 8 | **Skip** | Probably not the one in the video. Its licence does not cover the EU, UK or South Korea, its body model is non-commercial, and it needs 24-26 GB of graphics memory against our 16 GB. |

---

## 2. What's actually useful, ranked

### 1. Switch on what UVgami already does (free, owned)
- **What to do.** UVgami 2.5.0 came out 21 Nov 2026 and is now free. It adds automatic splitting of organic parts into regions, a GPU engine called PartUV, per-part symmetry and an "Auto" organic/hard-surface choice. Checked against the 2.5.0 source: the engines are OptCuts, PartUV and xatlas (`props.engine`), region splitting is `split_regions` (on by default), and there is a new `material_seams` option (cut seams where the material changes). Forge's UV step sets neither the engine nor these options, so it runs whatever the director last picked in UVgami's panel. Make them explicit. Then compare the current OptCuts engine with PartUV, with region splitting on, on 2-3 real characters.
- **Replaces or adds.** Nothing new to buy. It might give better seams and faster unwraps on dense meshes. It is also the reason Auto Unwrap is a skip.
- **Cost.** Testing time. PartUV downloads about 200 MB.
- **Risk.** Low. Keep UVgami's symmetry and "stack similar" switched off: the bake needs every island unique, which is why Forge already turns them off. The island repair tools are dated 23-24 Nov, after 2.5.0, so they may need an update.
- **How Forge calls it.** The same way it already does: set the scene's UVgami settings, run `bpy.ops.uvgami.start`, then poll the job.

### 2. Smart Remesh "Hardsurface" for rigid props (owned, so time only)
- **What to do.** Run it through gates in order, and drop it at the first failure:
  1. Run `forge setup-blender`. This confirms it is really installed (Forge has never detected it), that it turns on in Blender 5.3 (its listing stops at 5.2), and that it has a command Forge can call without the mouse. The probe entry for this already exists.
  2. Update to 3.0.5. Check that its always-running overlay, which a buyer says stopped Auto Save working in 3.0.0, does not start inside Forge's sessions or interfere with Quad Remesher polling.
  3. On 2-3 real Tripo props, compare it with Quad Remesher (with hard-edge detection on) and with the home-built "rigid part path" in section 3. Measure how much the shape changed.
- **Replaces or adds.** A separate route for props and mechanical parts. Today Forge sends everything through Quad Remesher's organic remesh. **Never use it on characters.** Its organic mode applies one even density everywhere, and a competitor's test plus two buyers report it shrinking or distorting shapes.
- **Cost.** Time only. If the copy came from the seller's own shop rather than Superhive, its licence covers one person, and a team install needs the "extended" licence.
- **Risk.** It went from version 1 to version 3 in about 3 months, and a buyer reports v3 is worse than v2, so its commands may change between versions. The seller's claims ("2 million to 20,000 faces in seconds", "shape unmoved") have not been measured by anyone independent.
- **How Forge calls it.** Unknown until the probe runs. It probably works like Quad Remesher: start a job and poll until it finishes.

### 3. MotionGen Lite, $1, as a technical test for humanoid custom clips
- **What to do.** Buy the $1 Lite tier on the RTX 4080 Super PC itself; the licence is locked to one machine. Film a 3-second action. Retarget it to one Forge Auto-Rig Pro character in Blender 5.3 two ways: MotionGen's own Auto-Rig Pro retarget, and MotionGen's Mixamo rig fed into ARP Remap's documented Mixamo preset. Run Forge's foot-slide and self-intersection checks on the result. Read its open-source add-on code for command names.
- **Replaces or adds.** It adds a source for the optional "external clip" slot: our own attack, hit, death and emote clips. Formulas do these badly, and raw Mixamo files cannot be shipped. It replaces none of Forge's procedural clips (motion-range test, loops, quadrupeds, tails).
- **Cost.** $1 to test. Shipping clips needs Pro ($29, 1 seat, 30-second limit) or Gold ($57). **Studio or team use needs Ultimate ($250).**
- **Risk.** It does not disclose which AI body model it uses or under what licence. The SMPL family of body models, which is common for this, is non-commercial. **Ship no clip until the seller confirms in writing** which model it uses and its licence. Other points:
  - It captures one human body only: no hands, face or animals.
  - It is Windows-only, and needs a separate engine window kept open.
  - Activation sends your email, order number and a fingerprint of the PC's hardware to the seller.
  - 27 of its 78 reviews are marked "received for free".
  - The seller says "production-ready in seconds", but one user reports a 13-second video took 2 hours.
- **How Forge calls it.** It can't for now. Treat it as a guided manual step, like ARP Remap is today.

### 4. Image to 3D, as a $12 evaluation only (seller's shop price until 2 Dec, 7-day refund)
- **What to do.** Only if you want to know whether an offline, no-credit backup to Tripo is worth pursuing:
  - Run TRELLIS.2 and Pixal3D on 3 Forge test images and compare them with Tripo on silhouette, texture and how well the parts separate.
  - Read the licence file inside the download and the code that runs the engines.
  - Test it in Blender 5.3.
  - Leave Hunyuan off.
- **Replaces or adds.** At best, a fallback for Step 1. It does not match Tripo on what Forge relies on: it gives one sealed mesh instead of separate parts, has no documented delighting (removing baked-in lighting), does not document which texture maps come out, and has no script commands.
- **Cost.** $12-18, plus about 132 GB of model downloads (TRELLIS alone is 16.8 GB).
- **Risk: adoption is blocked by licences.** The step that exports textured models in both TRELLIS.2 and Pixal3D uses an NVIDIA component (nvdiffrast) licensed for "research or evaluation" only. Hunyuan3D 2.1 is not licensed in the EU, UK or South Korea. Reviews are mixed: weak on hard-edged objects and stylised art. Its viewport panel reportedly steals mouse control from other add-ons.
- **How Forge calls it.** No published commands. Forge would have to drive the engine runner directly after reading its code, or run the open models itself.

**Not worth money:** the other 8. Their useful parts (free depth and material-splitting models, a seamless-tiling trick) are free to use without buying anything; see section 3.

---

## 3. Ideas to build into Forge ourselves

### Tail and appendage roots at Step 4
- **Cut in the crease, not just at the thin spot.** Forge's part finder (parts.py) only looks at thickness; it has no "inward fold" signal, which we checked. Score each candidate cut ring by its jump in thickness plus how concave the surface is along it. Then let the ring slide up to a few face rings toward the nearest crease, with a stiffness setting (Smart Segmentation uses 0.6 by default). Work it out on a reduced copy, then refine on the full Tripo mesh. The tail root then lands in the fold where tail meets body. That gives Quad Remesher a clean border and hides the join.
- **Force an edge loop exactly at the root.** Nitro Retopo's core idea is that a drawn border always becomes an edge loop. Forge can do this without anyone drawing: paint a material band at the computed root and joint rings, and turn on Quad Remesher's "use materials" option (already planned in detail-editing.md). Do not remesh the tail separately, because the loops where pieces meet must match exactly.
- **Score, then keep the best result.** Run 2-3 Quad Remesher variants. Measure each one's volume change and its average and worst distance from the source, and check the root area specifically. Keep the winner automatically. This is the method a competitor used to test Smart Remesh, and the reason we know it shrinks shapes.
- **Pre-check before Step 4.** Count separate pieces and triangles, and warn above set limits (Nitro warns above 20 pieces or 100,000 triangles).
- **Do not add Instant Meshes as a fallback remesher.** Our earlier mouth-crease investigation already rejected it, and nothing here changes that.

### Bake stains at part joins in Step 6
- **Cutting in the crease (above) also hides the join in a shadowed fold**, where any leftover stain is far less visible.
- **Part ID check.** Tag every face of the dense source with its part, giving one colour per part (Smart Segmentation's "Bake To Materials" preview). Bake that ID map alongside the colour map. Any texel whose ray hit a different part's surface is a stain. Refill it from its own part, the same way Forge's existing second pass fills texels the cage missed. This is our own idea and untested, but it also shows exactly where each stain comes from.
- **Exploded bake.** If rays still reach neighbouring parts, move the parts apart before baking and put them back afterwards. This is the standard game-bake trick, and the reason pro bakers have "bake groups".
- **Fix only the failing islands.** Measure each UV island for stretching or stains. Re-unwrap or re-bake only those, then let UVPackmaster repack (Auto Unwrap's "Redo Selected Island" principle).

### Part splitting
- **Work out all candidate cuts once, then choose instantly.** Store the candidate cuts once, so the roadmap's "cut height slider" and "3 candidate cuts as thumbnails" respond instantly instead of re-running the planner.
- **Remember the director's choices by position on the model, not by part number**, so they survive a re-run with different settings.
- **Preview before cutting.** Show the proposed parts as colours on the uncut mesh, drop tiny crumbs below a minimum size, and allow "re-split just this region" (for example, only the head for horns and ears).
- **A separate path for rigid parts** (Smart Remesh's Hardsurface idea, built ourselves):
  1. Merge flat areas.
  2. Try removing each edge loop, and keep the removal only if the shape stays within a small tolerance (for example 0.2% of the part's size).
  3. Split the large faces into triangles before export and mark sharp edges for the bake.
- **Generate tricky parts separately, before Tripo** (Image to 3D's "Find Parts" idea). An image-edit model draws the cape, held item or helmet on its own, and each goes to Tripo separately; this matches the roadmap's Tripo pre-flight. These models allow commercial use: FLUX.2 klein 4B (Apache 2.0, about 13 GB of graphics memory), Qwen-Image-Edit (Apache 2.0) and SAM 3 (Meta's SAM licence).
- **Concept-versus-mesh check.** Estimate depth from the concept image with Depth Anything V2 Small or DA3MONO-LARGE (both Apache, commercial OK). Compare it with a front render of the Tripo mesh to catch an arm Tripo fused into the body, or a missing horn. Use it as a warning only: depth from a single stylised drawing is unreliable.

### Step 8 motion quality on quadrupeds
- **Nothing in the video makes four-legged motion.** MotionGen is humans only, and Motion Gen explicitly excludes animals. Forge's formula-based gaits remain the answer, as animation-workflow.md already concluded.
- **Automatic foot lock (borrowed from MotionGen).** Mark a foot as planted when it is low enough and slow enough, then pin its IK control in place for those frames and blend in and out. Run it after spine bend and follow-through on Quad_Walk and Quad_Trot, and on any imported clip. It turns Forge's foot-slide *check* into a foot-slide *fix*.
- **Clean-up on intake** for any clip:
  - Put the feet on the ground at frame 1.
  - Remove slow up-and-down drift.
  - Optionally make an in-place copy for game engines.
  - Apply light smoothing to captured clips only.
- **Script one Remap click.** Key the rest pose at frame 0 before retargeting, so ARP Remap's "redefine rest pose" click is done automatically.
- **Licence rule for any AI motion source.** "The output is yours" is not enough. Record which body model sits underneath and any territory limits, and keep such clips out of the Forge repository, as we already do for Mixamo.

### Other quick wins
- **Delighting licence settled.** Marigold-IID-Appearance v1.1 splits an image into albedo, roughness and metallic. Its weights are OpenRAIL++, which allows commercial use with some use restrictions. That closes the "unverified licence" item in texture-definition.md section 10.
- **Run AI vision models outside Blender's own Python**, as a separate process that passes image files back and forth. Several of these add-ons broke because they installed PyTorch into Blender.
- **Load fewer add-ons in Forge's sessions.** Forge's add-on stages currently load *every* enabled add-on. Load only the ones each stage needs, so overlays like Smart Remesh's or Image to 3D's cannot interfere.
- **Detail-tile library.** TrueDepth's free handbook documents its "Make Seamless" edge blend, and it recommends keeping height maps at 16-bit.

---

## 4. Where the video over-sells, and the traps

### Marketing versus evidence
- **"AI" that isn't.**
  - Nitro Retopo: hand tools; "AI" only describes the meshes it is meant for.
  - Smart Remesh: a 2015 research remesher plus Python.
  - Smart Segmentation: plain geometry.
  - Auto Unwrap: a classic unwrap engine (OptCuts), plus a "learned" seam step whose type and data are unpublished.
- **"3D from an image" that is really a relief.** AutoDepth's "3D Model Generation" and Video Depth AI's "3D animated scenes" are raised surfaces seen from one side, not game assets.
- **Unbacked speed and quality claims.**
  - Smart Remesh "shape unmoved": a competitor measured an average 1.9% volume loss, and 6.2% at worst.
  - MotionGen "production-ready in seconds": a user reports 13 seconds of video took 2 hours.
  - Auto Unwrap "AI seams": backed only by the seller's training counts.
- **Weak ratings behind the hype.** Blender Procedural's five tools are rated 2-3 out of 5, with 46-72% one-star. Video Depth AI's own page says its cloud mode is broken. TrueDepth's live page still contains draft placeholder text.
- **Scripting and Blender 5.3.** Not one of the 12 publishes script commands. Most of the useful ones only claim support up to Blender 5.2.

### Privacy traps: don't send unreleased art here
- **Uploads to unnamed cloud services with no terms:**
  - Video Depth AI: by default.
  - Blender AI Library Pro: always.
  - AI Material Factory and Auto Painter AI: in cloud mode. Auto Painter's cloud mode sends renders of your mesh.
  - AutoDepth's Mac/old version: reviewers say it uses a public online demo.
- **Administrator rights at install:** Auto Painter AI, Blender AI Library Pro, and AutoDepth's old installer.
- **MotionGen:** sends a fingerprint of the PC's hardware to the seller's server, and offers remote-desktop installs (AnyDesk) that a studio may not allow.

### Licence traps for a commercial game
- **Non-commercial depth models:**
  - Depth Anything V2: Base, Large and Giant.
  - Video-Depth-Anything: Base and Large.
  - Depth Anything 3: Large, Giant and Nested.
  - TrueDepth offers some of these, and its own FAQ links to the non-commercial Large model. Its "commercial use: yes" answer covers your renders, not the model licences.
- **TRELLIS.2 and Pixal3D:** the models themselves are MIT (open, commercial OK). But their textured export uses NVIDIA's nvdiffrast, licensed for research or evaluation only. Pixal3D's model page is also blocked for EU users.
- **Tencent models:** Hunyuan3D 2.1 and HY-Motion are not licensed in the EU, UK or South Korea, and need a separate Tencent licence above 1 million monthly users.
- **Human body models:** SMPL, SMPL-X and SMPL-H are non-commercial (commercial licences come through Meshcapade). They sit under Motion Gen, under the FlowHMR model, and possibly under MotionGen.
- **Hi3D**, mentioned as the detail engine inside Image to 3D: game assets made with it are fine. But a branding and size clause applies if Forge itself is ever sold with Hi3D inside. It also officially needs Linux and a 96 GB server card, so it is not runnable on our PC.
- **Seat limits:**
  - Smart Remesh from the seller's own shop: one person only.
  - MotionGen: locked to one PC; studio use needs the $250 tier.
  - Auto Unwrap: studio licence $85.
- **GPL code:** don't paste Smart Segmentation's code into Forge, because of GPL obligations. Rebuild the ideas instead.
