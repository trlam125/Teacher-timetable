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

PowerPoint Desktop Slide Show has not been exercised. The user requested testing without controlling the computer. Automated structural results establish package content and preservation, while actual presentation playback remains unverified.

The public capabilities response therefore returns native_motion=false. The UI labels current downloads as basic interaction. Office Kit's motion adapter is available for fixtures and subsequent compatibility qualification.

Morph, complex timing, imported PPTX content and arbitrary effect presets remain outside the active capability set.
