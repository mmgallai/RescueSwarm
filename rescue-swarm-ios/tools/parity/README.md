# Corrected-validation detector comparison

This is an inference-only implementation comparison, not training or threshold
selection. Run the **Corrected validation parity** workflow on the integration branch.

## Frozen inputs

- 32 of the existing 247 corrected HERIDAL validation images: 53 annotations,
  seven empty images, all nine manually corrected images, and four site groups.
- The remaining images were selected deterministically across site and
  zero/one/multiple-person strata, before inference. See `manifest.json`.
- Original image bytes are downloaded from the public HERIDAL archive and must
  match the original corrected-label manifest's SHA256. Corrected boxes come from
  that manifest; publisher boxes are not substituted.
- The exact existing app `YOLO26n.mlpackage`, checked by file hashes. JSON metadata
  is hashed with LF line endings; binary model and weights are hashed unchanged.
- Input 1280, confidence 0.25, NMS IoU 0.7, Core ML compute units ALL in both languages.

The public archive is [HERIDAL in keras-retinanet PASCAL VOC format](https://zenodo.org/records/5662351),
Pasi Pyrrö, version 0.0.1, CC BY 3.0, based on the original HERIDAL dataset.
Image files and preprocessed pixel buffers are temporary CI data, not committed.

## Comparisons

1. Actual Swift app preprocessing, inference and output decoding.
2. Evi's Python/OpenCV preprocessing, the same Core ML package, and Python decoding.
3. Diagnostic: Python runs the exact RGB pixels exported by Swift. This isolates
   image decoding/resizing from inference and output decoding.

`reference.py` copies Evi's `coreml_reference.py` from commit
`8fba4cc9baa9a8676c2523091a5dd6348a221179`, with only its Detection dataclass and
person-class constant made standalone. No PyTorch import, export or training runs.
This does **not** prove equivalence with Evi's separate PyTorch worker.

One-to-one matching maximizes the number of box pairs at IoU >= 0.5, then total
IoU. The shared-pixel check requires no unmatched detections, minimum matched IoU
>= 0.999 and maximum confidence difference <= 0.0001, with at least one detection.
Native-preprocessing differences are reported descriptively, not hidden behind a
relaxed pass threshold. Ground-truth counts use the corrected boxes and the same
one-to-one matching rule. This reused, deliberately stratified sample is not a new
independent accuracy benchmark.

The workflow uploads original predictions and a JSON comparison report. No weights,
confidence thresholds, image sizes or training splits are changed by these scripts.

## Results — 21 November 2026

[Mac CI run 44953504716](https://github.com/mmgallai/RescueSwarm/actions/runs/44953504716)
passed on code `90aaaaa`. Downloaded reports also passed an independent local
augmenting-path matching audit, separate from the SciPy assignment implementation.

| Pipeline | Correct detections | False positives | Missed annotations | Recall | Precision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Swift, native preprocessing | 8 | 0 | 45 | 15.09% | 100% |
| Python/CoreML, native preprocessing | 8 | 0 | 45 | 15.09% | 100% |
| Python/CoreML, exact Swift pixels | 8 | 0 | 45 | 15.09% | 100% |

All three find the same eight annotation instances. Native Python versus Swift
matches 8/8 output boxes, mean IoU 0.950865 (minimum 0.830922), mean confidence
difference 0.008240 (maximum 0.022949). With shared input pixels, the complete
detection lists are exactly equal: IoU 1.0 and confidence difference zero.
Thus the small native box/score differences are isolated to preprocessing. No
inference or coordinate-decoding defect was demonstrated on this sample.

The only repaired issue was the test's model-metadata hash comparison: Windows
CRLF versus Git LF. The model definition and weights matched throughout. No
detector implementation, model weights or inference settings were changed.

The current bundled model's low recall remains a limitation, not a solved issue.
100% precision here means only eight detections with no observed false positives;
it does not imply rescue readiness. This is full-image 1280 inference, not the
fine-tuned/tiled research pipeline. See `results/20261121` for complete metrics and
paired predictions. Timings in those predictions are single-pass diagnostics,
not a controlled speed comparison or phone benchmark.

## Retained fine-tuned checkpoint — 21 November 2026

[Fine-tuned comparison run 44972619050](https://github.com/mmgallai/RescueSwarm/actions/runs/44972619050)
passed on `0d2f99c`. This exports a **copy** of D85's retained
`yolo26n-wisard-full-20261022/mixed640/weights/best.pt`, SHA256
`321b3164ad4c94005345bfd716997e2e5741d6dfb6687dabd156080e1cec47ae`.
The checkpoint in `checkpoints/d85-best.pt` is for testing only and is not part of
the app bundle. The original app package and detector implementation remain unchanged.
No retraining, threshold tuning or new checkpoint selection was performed.

Same 32 photos, corrected labels, 1280 input, confidence 0.25 and NMS IoU 0.7:

| Fine-tuned pipeline | Correct detections | False positives | Missed annotations | Recall | Precision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original PyTorch checkpoint, CPU FP32 | 15 | 14 | 38 | 28.30% | 51.72% |
| Python/CoreML, native OpenCV preprocessing | 16 | 15 | 37 | 30.19% | 51.61% |
| Swift/CoreML, native app preprocessing | 18 | 10 | 35 | 33.96% | 64.29% |
| Python/CoreML, exact Swift pixels | 18 | 10 | 35 | 33.96% | 64.29% |

- Native Python/CoreML and Swift match 26 boxes, with five Python-only and two
  Swift-only boxes. Mean matched IoU 0.925381; mean score difference 0.041091.
- With identical pixels, all 28 Swift and Python/CoreML detections are exactly
  equal, including scores and box coordinates. No language-level inference or
  coordinate-decoding mismatch was demonstrated.
- Python/CoreML retains all 29 PyTorch detections at IoU >= 0.5 and adds two in
  `train_MED_3028`. Export is not bit-identical to PyTorch; predictions are preserved
  in the reports rather than declaring perfect export equivalence.
- Swift retains all 15 annotation instances found by PyTorch and matches three
  additional instances. This is a small, reused validation sample, not a guarantee
  of person retention on other images.

Compared with the previous app-model result on these same images, Swift finds
18 rather than 8 people, with 10 rather than 0 false positives. It still misses
35/53 annotations. These are full-frame 1280 settings; historical stronger results
used larger resolutions or overlapping crops and separately calibrated thresholds.
This result does not justify immediate app replacement or claim field readiness.

Export dependencies are pinned: Ultralytics 8.4.171, Torch 2.7.0, torchvision 0.22.0,
CoreMLTools 9.0 and NumPy 1.26.4. The initial NumPy 2.2.6 dependency conflict was
resolved before export; no model change was required. Source and candidate hashes,
paired predictions, and an independent local matching audit are saved in
`results/finetuned-20261121`. The Core ML package is retained as a workflow artifact
and in the local project handover folder, outside the app.

## Retained D85 with overlapping crops — 21 November 2026

[Mac comparison run 44980831481](https://github.com/mmgallai/RescueSwarm/actions/runs/44980831481)
passed on `cdb3d42`. The source checkpoint is unchanged. A separate 640-pixel
Core ML export was tested outside the app. No retraining, threshold selection,
production detector edit or app model replacement occurred.

Frozen historical tiled recipe: 4x4 integer grid, 10% tile-width/height margin on
each side (rounded to nearest even and clipped to image edges), 640 input,
per-crop NMS IoU 0.5, global stable greedy NMS suppressing IoU > 0.5, inclusive
confidence cutoff **0.2193603515625**. Prediction uses 0.21923828125 before the
inclusive filter, preserving the historical FP16 boundary convention.

Same 32 corrected validation images, 53 annotated people, 512 lossless crops:

| Pipeline | People found | False positives | Missed | Recall | Precision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Python/PyTorch, CPU FP32 | 30 | 26 | 23 | 56.60% | 53.57% |
| Python/Core ML, native preprocessing | 30 | 26 | 23 | 56.60% | 53.57% |
| Swift/Core ML | 30 | 26 | 23 | 56.60% | 53.57% |
| Python/Core ML, exact Swift pixels | 30 | 26 | 23 | 56.60% | 53.57% |
| Archived GB10 FP16, same 32-image subset | 30 | 26 | 23 | 56.60% | 53.57% |

All pipelines find the same 30 annotation instances, including the archived
GB10 reference. Historical confidence-ordered matching and the independent
maximum-cardinality audit agree on all counts. The previously reported 74.24%
recall / 70.29% precision used all 247 validation images, not this selected subset.
The current result therefore reproduces the historical same-image outcome.

Relative to the preceding full-frame Swift run, the tiled recipe finds 30 rather
than 18 people, but false positives rise from 10 to 26. This comparison changes
crop handling, input size, confidence and NMS to reproduce the historical recipe;
it does not isolate the causal contribution of tiling alone.

With identical input pixels, all 56 merged Python/Core ML and Swift detections
match exactly (IoU 1, confidence difference 0). Swift independently restores crop
coordinates and performs global NMS; its output matches Python's merge exactly.
Native Python/Core ML versus Swift matches 54/56 boxes, and PyTorch versus Swift
55/56. No annotated person is lost across these variants.
Native resizing and export numerical differences remain; identical counts do not
mean every raw output is identical.

The comparison supplies identical lossless crop fixtures generated with the
historical PIL decoder and exact grid. Swift uses the production preprocessing
and decoding helpers with test-only model invocation and historical NMS settings.
This does not add tiling to the shipping app. Original research ran FP16 batches
of 16 on GB10; this PyTorch reference runs CPU FP32 sequentially. No phone timing,
battery, fresh generalization or field-readiness claim is made.

Reports, crop predictions, merged predictions, manifests, historical subset and
independent audit are in `results/tiled-20261121`. The tested Core ML package is a
workflow artifact and local handover artifact, outside the app bundle. The
initial test-only async call compile error was fixed before this passing run.
Regular Swift app checks and the original bundled-model parity also pass on
`cdb3d42`. Physical-device testing remains separate.
