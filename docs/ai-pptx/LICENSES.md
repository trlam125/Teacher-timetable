# Dependencies and teaching resources

All JavaScript package versions and transitive packages are pinned by web/ai-slides/package-lock.json.

| Dependency | License |
|---|---|
| PptxGenJS | MIT |
| Office Kit core | MIT, with bundled THIRD_PARTY_NOTICES |
| JSZip | MIT or GPL-3.0-or-later |
| Mammoth | BSD-2-Clause |
| PDF.js | Apache-2.0 |
| Vite | MIT |

Dependencies are bundled for browser use. Build tooling remains a development dependency. Their complete license notices are distributed alongside the generated bundle.

The Vietnam geographic illustration uses Natural Earth 1:110m Admin 0 Countries, public domain. Asset metadata records its upstream source and verification date. The image is a coarse land outline and carries no current administrative claim.

Water-cycle video links point to NASA Precipitation Education, Water, Water, Everywhere. The file contains an outbound link to the original educational page. Video bytes and thumbnails are not redistributed.

Physics simulation code uses the basic Ohm law and small-angle pendulum equation. The UI states the model assumptions.

The resource registry links to three Vietnamese HTML5 simulations hosted by PhET Interactive Simulations, University of Colorado Boulder: [Ohm's Law](https://phet.colorado.edu/en/simulations/ohms-law), [Fractions: Intro](https://phet.colorado.edu/en/simulations/fractions-intro), and [States of Matter: Basics](https://phet.colorado.edu/en/simulations/states-of-matter-basics). Studio does not redistribute PhET code, screenshots, thumbnails or media. The original provider and outbound URL are included in slide notes. Links need Internet and remain subject to the source website's terms; this catalog is not a claim of affiliation or permanent availability.

User-uploaded books and excerpts remain subject to the user's permission and consent. Source files are never added to the repository by Studio.
OCR uses tesseract.js 7.0.0 and tesseract.js-core 7.0.0 (Apache-2.0), with @tesseract.js-data/vie 1.0.0 (package metadata MIT). The Vietnamese 4.0.0_best_int traineddata is derived from naptha/tessdata / Tessdata Best under Apache-2.0. The upstream license is retained in web/ai-slides/licenses/TESSDATA_LICENSE.txt and emitted in THIRD_PARTY_NOTICES.txt. Worker, non-SIMD LSTM core/WASM and Vietnamese language data are served locally; images are not sent to an OCR service. Sources: https://github.com/naptha/tesseract.js/tree/v7.0.0 and https://github.com/naptha/tessdata.
