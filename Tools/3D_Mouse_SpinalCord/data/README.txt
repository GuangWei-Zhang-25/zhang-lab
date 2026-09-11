Allen P56 mouse spinal cord, label volume
=========================================
Extracted from the 3D Mouse Spinal Cord Atlas at
https://guangweizhang.com/Tools/3D_Mouse_SpinalCord/spinal_cord_index.html

Atlas id : allen-p56-anatomical-completion-v3
Source label checksum (SHA-256):
  0e4f8ce928cc229361a432f2e4d3d130f5c3df5a33869e7b1b1c37bf508dce01

FILES
  allen-p56-spinal-cord-labels.nii.gz   NIfTI-1, uint8, gzip   (3D volumetric data)
  allen-p56-spinal-cord-labels.tif      multi-page TIFF, uint8, deflate (stacked)
  allen-p56-spinal-cord-labels.csv      colour code table, 91 regions:
                                          voxel_value, allen_id, acronym, name,
                                          anatomy_group, kind, hex_color, r, g, b,
                                          present_in_volume, voxel_count
  allen-p56-spinal-cord-colour-table.html same table, rendered with colour swatches
                                          and grouped by anatomical class (printable)

GEOMETRY
  Shape (Z, Y, X)      (795, 373, 493)   = 795 slices of 373 x 493
  In-plane spacing     0.00594 x 0.00594 mm  (5.94 um)
  In-plane origin      [-1.46124, -1.10484] mm
  Axes                 X = medio-lateral, Y = dorso-ventral, Z = rostro-caudal
  TIFF page order      page 0 = most rostral, page 794 = most caudal

  IMPORTANT: slice spacing along Z is NOT uniform. It ranges from 0.020 to
  0.040 mm (median 0.03933). The NIfTI header stores the median as pixdim[3],
  because NIfTI cannot represent variable slice spacing. For measurements
  along the rostro-caudal axis use the true per-slice positions in
  z_coordinates_mm.json rather than the header value.

VOXEL VALUES
  Voxel values are palette indices, not Allen structure IDs. Map them with the
  CSV: the voxel_value column gives the value stored in the volume, atlas_id
  gives the corresponding Allen id. 0 is outside the source envelope.
  73 of the 91 catalogued labels occur in the volume.

  Exact verified grid

PROVENANCE
  This is the full-resolution part of the atlas, not the display preview.
  Both the NIfTI and TIFF were verified voxel-for-voxel against the volume
  embedded in the viewer after extraction.
