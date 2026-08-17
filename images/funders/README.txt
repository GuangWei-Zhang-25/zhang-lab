Funder logo files for funding.html.

Present:
  nih-nia.svg                 official, from nia.nih.gov
  alzheimers-association.svg  official, from alz.org
  bbrf.png                    official, from bbrfoundation.org (143x64, shown at native size)
  vcu-provost.svg             VCU academic logo, from branding.vcu.edu
                              (no Office of the Provost lockup is published)

Missing:
  whitehall-foundation.png    the Foundation publishes no logo image file; its own
                              site sets the name as CSS text, so the card falls back
                              to a typographic wordmark. Drop a PNG/SVG here with
                              this name to replace it.

Each card shows a typographic wordmark until its file exists, then swaps to the
image automatically. To use a different extension, update the src in funding.html.
The logo band is 120 px tall and uses object-fit: contain, so images never upscale.
