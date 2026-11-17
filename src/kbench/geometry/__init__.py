"""Exact geometry of the test models: meshes, primitives, STL files, plane sections, rasters."""


class GeometryError(ValueError):
    """Geometry that the suite cannot use as ground truth (open, inverted, degenerate, …)."""
