# Native motion compatibility

Checked 2026-11-22.

| Component | Version |
|---|---|
| PptxGenJS | 4.0.1 |
| Office Kit | 0.30.0 |
| Node in codex-skill-env | 22.23.5 |
| Vite | 8.3.8 |

The image-size dependency is overridden to 2.1.0. npm audit reported zero vulnerabilities after dependency updates.

## Automated evidence

scripts/motion-spike.js generates a five-slide deck containing Vietnamese text, editable named objects, a chart, teacher notes, an internal slide link and an HTTPS link.

The adapter maps semantic objectName values to Office Kit getShapeName values. It writes Appear/FadeIn with click starts and Fade slide transitions, then saves the package.

Round-trip assertions passed for slide count, shape names, text and notes. Office Kit validatePresentation returned an empty issue list. Separate ZIP/XML checks parsed every XML part and compared all relationship targets before and after. The animated fixture has five timing trees, five transitions and fifteen object effects.

Exporter tests also cover quiz relationships, notes, reduced motion mode and URI allowlisting.

The live-provider Ohm lesson was also exported by headless Chromium. Its basic export has 15 lesson slides plus 4 quiz feedback pages. Both gentle and minimal QA exports have 14 timing trees and 19 slide transitions. All package XML parts parsed. These are structural checks, not evidence of Desktop playback. QA files and the reviewed sample manifest are under tmp/ai-studio-qa.

## Release gate

The agent has not controlled or observed PowerPoint Desktop. On 2026-11-23, after receiving the three QA files below and a checklist covering incremental objects, Fade transitions, quiz/Notes and absence of repair warnings, the user reported: “Cả 3 tệp chạy đúng”. This is user-reported manual Desktop verification, separate from automated structural checks. The Office version and screenshots/video were not supplied; no particular Office release or universal compatibility is claimed.

Native motion is controlled per environment by AI_SLIDES_NATIVE_MOTION_ENABLED, false by default. After that manual result, the preview may enable Appear/FadeIn and Fade transitions using the pinned PptxGenJS 4.0.1 / Office Kit 0.30.0 combination. Recheck the fixture packs before enabling it after dependency or exporter changes. The interface offers an explicit basic download, honors reduced-motion preferences, and explains an engine failure instead of silently delivering a basic file as animated.

Morph, complex timing, imported PPTX content and arbitrary effect presets remain outside the active capability set.

## Three Desktop QA packs — 2026-11-23

Generated in headless Chromium from the browser exporter with native motion explicitly enabled for QA. At generation time the public UI capability was false; it is now configurable after the user-reported result.

| File under tmp/ai-studio-qa/native-desktop | Slides, including quiz feedback | Timing trees | Fade transitions | Shape targets |
|---|---:|---:|---:|---:|
| 01-vat-li-om.pptx | 19 | 14 | 19 | 64 |
| 02-khoa-hoc-nuoc.pptx | 10 | 5 | 10 | 21 |
| 03-dia-li-viet-nam.pptx | 10 | 5 | 10 | 16 |

All XML parts parsed and every animation target refers to an existing shape ID. The Ohm sample was previously reviewed; the water/geography samples are synthetic structural fixtures, not provider benchmark results. Geographic fixture explicitly describes the coarse land outline and incomplete island/administrative coverage.

README.txt in that directory gives the manual steps: open each file with PowerPoint Desktop without repair warnings; use Slide Show and clicks to verify incremental objects within a slide and Fade between slides; test quiz return links and Notes; report PowerPoint version and any faults. The user confirmed all three files run correctly. The version remains unreported.

## Actual UI download regression checks

Four headless cases pass: enabled QA flag writes timing/transition XML through the real download button; the explicit basic button writes neither; reduced-motion downloads have neither; deliberately blocking the motion-engine bundle shows an error and still permits an explicit basic download. These checks validate exporter wiring and failure handling, not additional Desktop versions.
