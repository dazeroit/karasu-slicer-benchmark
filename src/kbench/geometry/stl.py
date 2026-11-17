"""Binary STL files.

Writing is deterministic: the same mesh and header give the same bytes. Normals are computed from
the ``float32`` corners and written for completeness; the suite never reads them back.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from kbench.geometry import GeometryError
from kbench.geometry.mesh import FloatArray, Mesh

_HEADER_BYTES = 80
_RECORD = np.dtype([("normal", "<f4", (3,)), ("corners", "<f4", (3, 3)), ("attribute", "<u2")])


def write_binary_stl(path: Path, mesh: Mesh, header: str) -> None:
    """Write ``mesh`` as binary STL; ``header`` is ASCII text of at most 80 bytes."""
    encoded = header.encode("ascii")
    if len(encoded) > _HEADER_BYTES:
        raise GeometryError("the STL header exceeds 80 bytes")
    corners = mesh.triangle_vertices
    if not np.array_equal(corners.astype(np.float32).astype(np.float64), corners):
        raise GeometryError("vertices are not float32 values; quantise the mesh first")

    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 0.0)

    records = np.zeros(len(corners), dtype=_RECORD)
    records["normal"] = normals
    records["corners"] = corners
    with path.open("wb") as stream:
        stream.write(encoded.ljust(_HEADER_BYTES, b"\0"))
        stream.write(np.uint32(len(corners)).tobytes())
        stream.write(records.tobytes())


def read_binary_stl(path: Path) -> FloatArray:
    """The triangle corners ``(m, 3, 3)`` of a binary STL file, as ``float64``.

    The size must match the declared triangle count exactly; ASCII STL is refused.
    """
    data = path.read_bytes()
    if len(data) < _HEADER_BYTES + 4:
        raise GeometryError(f"{path.name}: too short for binary STL")
    count = int(np.frombuffer(data, dtype="<u4", count=1, offset=_HEADER_BYTES)[0])
    expected = _HEADER_BYTES + 4 + count * _RECORD.itemsize
    if len(data) != expected:
        hint = " (ASCII STL is not supported)" if data[:5].lower() == b"solid" else ""
        raise GeometryError(
            f"{path.name}: {len(data)} bytes, but {count} triangles need {expected}{hint}"
        )
    records = np.frombuffer(data, dtype=_RECORD, count=count, offset=_HEADER_BYTES + 4)
    return records["corners"].astype(np.float64)
