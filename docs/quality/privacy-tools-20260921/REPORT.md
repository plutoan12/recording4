# Privacy model download and smoke validation (2026-09-21)

The three candidate projects were reviewed in a private evaluation directory. No
model weight, source video, audit report, or credential is committed to Git.

## Models

| Backend | Model | License/source | SHA-256 | Status |
| --- | --- | --- | --- | --- |
| deface 1.5.0 | bundled CenterFace ONNX | MIT, ORB-HD/deface | recorded in the private manifest | passed |
| OpenScrub | CenterFace ONNX | MIT, Star-Clouds/CenterFace | `77e394b51108381b4c4f7b4baf1c64ca9f4aba73e5e803b2636419578913b5fe` | passed |
| EgoBlur Gen1 | `ego_blur_face.jit` | Apache-2.0, Project Aria/EgoBlur | recorded in the private manifest | passed one-frame image smoke |
| EgoBlur Gen1 | `ego_blur_lp.jit` | Apache-2.0, Project Aria/EgoBlur | recorded in the private manifest | downloaded; not connected to face-only UI |

The EgoBlur archives are the public Gen1 weights from the Project Aria model
release. They are not evidence that arbitrary YouTube footage has Gen1-domain
quality. Gen2 weights are distributed through the Project Aria access page and
were not silently substituted with a different generation.

## Smoke checks

- OpenScrub CenterFace + mosaic on the bundled face-video sample: 14 input and
  14 output frames, 2560×1920, 10 fps, AAC audio retained, non-empty MP4 and
  hash-verified audit report.
- deface 1.5.0 is present in the worker image and its mosaic command is covered
  by the worker tests and an FFmpeg testsrc/audio smoke run.
- EgoBlur Gen1 face model loaded and produced a non-empty transformed PNG from a
  640×480 sample frame. A full video run was intentionally not promoted to a
  quality result: the CPU-only container was still processing the 14-frame
  2560×1920 sample after roughly two minutes. The adapter command path is
  covered, but video throughput and temporal tracking need a Linux/CUDA run.
- The worker privacy adapter now has fail-closed command paths for `deface`,
  `openscrub`, and `egoblur`. Missing executables/models, non-zero exits, empty
  output, and the one-hour limit are errors.

These are transform/output-integrity checks, not face recall or privacy recall
measurements. A human review set with annotated faces is still needed before
changing the default backend or claiming production privacy quality.
