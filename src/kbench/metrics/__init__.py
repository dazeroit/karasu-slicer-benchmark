"""Measurements of decoded layer stacks against the reference (docs/METRICS.md)."""

# Coverage at or above this value makes a pixel material in binary metrics. For 8-bit images
# grey/255 ≥ 0.5 is grey ≥ 128, the usual material threshold of resin slicers' masks.
MATERIAL_THRESHOLD = 0.5
