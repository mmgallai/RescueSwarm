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
