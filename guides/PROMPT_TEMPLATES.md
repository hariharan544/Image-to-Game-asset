# Image prompt templates: one concept → parts sheet → multi-view per part

Why: images generated one by one never share a style (the director's first bull set:
every bell, band and rope looked different). Everything must come from **one final
concept image**, which is attached as the reference to every later prompt.

```
A. Final concept      1 image, the whole character wearing every prop
B. Parts sheet        concept attached → every part separated on one sheet
C. Multi-view sheets  concept + parts sheet attached → 4 views of one part (one per part)
```

Rules for every step
- Same chat / same project in the image tool; always attach the **final concept** (A).
- Download at **2K** (2048 px). Square 1:1 for B and C.
- Plain light-grey background, soft even light, no shadows, no text, no labels.
- Reject and regenerate when anything differs from the concept (colour, shape, count).

Fill the `{…}` fields once per character and reuse them in all three prompts.

| Field | Bull example |
|---|---|
| `{CHARACTER}` | friendly cartoon bull |
| `{STYLE}` | stylized 3D animation style, soft rounded shapes, hand-painted look |
| `{BODY}` | round belly, short thick limbs, large eyes, wide pink snout, two short curved horns, ears pointing sideways, short tail with a fluffy tuft, warm brown fur with darker patches |
| `{PROPS}` | a compact tuft of brown fur on top of the head (5-7 large rounded clumps); a thick braided light-tan rope collar around the neck; a large worn-brass cow bell hanging from the front of the collar; one wide brown leather band with stitched edges on each wrist |
| `{PROP_LIST}` | hair tuft, rope collar, bell, wrist band |

---

## A. Final concept (no reference)

```
{CHARACTER}, {STYLE}. Full body, symmetrical T-pose: arms straight out at shoulder
height, fingers slightly spread, thumbs separated; legs straight and slightly apart,
feet flat. {BODY}. Wearing: {PROPS}. Every prop clearly visible and not hiding the
body shape. Orthographic front view, centred, whole character in frame with margin,
soft even studio lighting, no shadows, plain light-grey background, no text.
```
Make 4, pick the best one. **This image is now the style master. Never change it.**

## B. Parts sheet (attach: final concept)

```
Use the attached image as the exact reference for style, colours, materials and
proportions. Create one parts sheet that separates this character into its parts,
laid out in a clean grid with wide empty space between them, nothing touching or
overlapping:
1. The character body alone, same T-pose, front view, with ALL props removed; the
   fur/skin that was under the props is completed naturally.
2. Each prop on its own, isolated, three-quarter view: {PROP_LIST}.
   Paired props (left/right) are shown only once.
Every part keeps exactly the same design, colour and detail as in the reference, at
the same relative scale. Soft even lighting, no shadows, plain light-grey background,
no text, no labels, no arrows.
```

## C. Multi-view sheet, one per part (attach: final concept + parts sheet)

Props:
```
Use the attached images as the exact reference. Show only the {PART} from the
reference character, isolated, exactly the same design, colours and materials.
A 2x2 grid of orthographic views at identical scale and height, centred in each cell:
top-left FRONT, top-right LEFT SIDE, bottom-left BACK, bottom-right RIGHT SIDE.
Camera at the object's mid-height, no perspective. Soft even lighting, no shadows,
plain light-grey background, no text, no labels, no grid lines.
```

Body:
```
Use the attached images as the exact reference. Show only the character body, ALL
props removed, the same T-pose, exactly the same proportions, colours and details.
A 2x2 grid of orthographic views at identical scale, feet on the same line, centred
in each cell: top-left FRONT, top-right LEFT SIDE, bottom-left BACK, bottom-right
RIGHT SIDE. Camera at chest height, no perspective. Soft even lighting, no shadows,
plain light-grey background, no text, no labels, no grid lines.
```

Each 2x2 sheet at 2K gives 1024 px per view, which is enough for Tripo multi-view
(front / left / back / right). Cut the sheets into separate views with:

    forge split-sheet sheets/

(every image in the folder -> sheets/views/<name>_front.png, _left, _back, _right; each
view re-centred, all views of a sheet at the same scale; [!] marks a sheet that is not a
clean 2x2 grid - regenerate it).

## Check before generating 3D
- Same colours and materials as the concept in every view?
- Back view plausible (no invented details)?
- Side views the same height as the front?
- Body sheet really without props, and no holes where they were?
