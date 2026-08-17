Funder logo files for funding.html.

Present (each downloaded from the organization's own site):
  nih-nia.svg                 nia.nih.gov
  alzheimers-association.svg  alz.org
  bbrf.png                    bbrfoundation.org (143x64; shown at native size,
                              never upscaled, so it stays sharp)
  vcu-provost.svg             branding.vcu.edu (VCU academic logo; no Office of
                              the Provost lockup is published)

Not a file:
  The Whitehall Foundation publishes no logo image. Its mark is rendered in CSS
  on its own site, so funding.html rebuilds it the same way, using the values
  from whitehall.org/css/style.css:
      .logo-title  background #d9d9f0, text #5f7ca0, 700 weight, uppercase
      .logo-since  background #5f7ca0, text #ffffff, 300 weight, 0.15em tracking
      typeface     Roboto Condensed
  See .wh-mark / .wh-title / .wh-since in funding.html. If the Foundation ever
  releases an image, drop it here and swap the markup back to an <img>.

Cards with an <img> fall back to a typographic wordmark if the file is missing,
then swap to the image automatically once it exists. The logo band is 120 px
tall and uses object-fit: contain.
