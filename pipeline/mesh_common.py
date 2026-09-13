"""Shared mesh-generation helpers: heightfield -> watertight solid.

Conventions (used by P1.5 and intended for P3/P5):
  - Heightfields are (H, W) arrays of TOP surface z in mm, row 0 = north.
  - A boolean `mask` selects the cells that exist; each cell is a square
    pixel of side `px` mm.
  - Output solids sit on z=0 (flat bottom), with vertical walls from z=0
    up to the local top around every mask boundary (outer coastline and
    any interior holes alike).
  - Mesh coordinates: x east (col * px), y north ((H - row) * px), z up.
    Origin = the SW corner of the pixel grid.

Watertightness contract: `heightfield_to_mesh` produces a closed 2-manifold
PROVIDED the mask has no diagonal-only pinches (two cells touching only at
a corner); run `remove_diagonal_pinches` first. Shared grid nodes are
emitted exactly once, so no vertex merging is needed afterwards.
"""

import numpy as np
import trimesh
from scipy import ndimage


def largest_component(mask, connectivity=1):
    """Largest connected component of a boolean mask.

    connectivity=1 (4-connectivity) is what the mesher's wall topology
    assumes; diagonal-only bridges would not get walls anyway.
    """
    st = ndimage.generate_binary_structure(2, connectivity)
    lab, n = ndimage.label(mask, structure=st)
    if n <= 1:
        return mask.copy()
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return lab == sizes.argmax()


def fill_interior_holes(mask):
    """Fill regions of ~mask fully enclosed by mask (no path to the array
    border). Returns (filled_mask, holes_mask)."""
    filled = ndimage.binary_fill_holes(mask)
    return filled, filled & ~mask


def remove_diagonal_pinches(mask):
    """Fill cells so the mask has no 2x2 block where two cells touch only
    diagonally. Such pinches put four wall quads on one vertical edge,
    breaking watertightness. Filling (never deleting) preserves
    connectivity; iterates until no pattern remains.

    Returns (new_mask, n_cells_added)."""
    m = mask.copy()
    while True:
        a, b = m[:-1, :-1], m[:-1, 1:]
        c, d = m[1:, :-1], m[1:, 1:]
        p1 = a & d & ~b & ~c  # X.  -> fill NE
        p2 = b & c & ~a & ~d  # .X  -> fill NW
        if not (p1.any() or p2.any()):
            break
        m[:-1, 1:] |= p1
        m[:-1, :-1] |= p2
    return m, int(m.sum() - mask.sum())


def fill_nearest(values, valid):
    """Replace values outside `valid` with the value of the nearest valid
    cell (Euclidean). Used to extend elevation/region rasters into filled
    holes before resampling/meshing."""
    if valid.all():
        return values.copy()
    idx = ndimage.distance_transform_edt(
        ~valid, return_distances=False, return_indices=True)
    return values[tuple(idx)]


def node_heights(top, mask, mode="mean"):
    """Heights on the (H+1, W+1) grid of pixel CORNERS from per-cell tops.

    mode='mean': average of the adjacent masked cells (smooth terrain).
    mode='min':  minimum of the adjacent masked cells (used for engraved
                 grooves, so a 2-px groove keeps its full width and depth
                 instead of being averaged into a shallow V).
    Nodes with no adjacent masked cell get 0 (they are never referenced).
    """
    h, w = mask.shape
    mp = np.zeros((h + 2, w + 2), bool)
    mp[1:-1, 1:-1] = mask
    quad = [mp[:-1, :-1], mp[:-1, 1:], mp[1:, :-1], mp[1:, 1:]]
    if mode == "mean":
        zp = np.zeros((h + 2, w + 2), top.dtype)
        zp[1:-1, 1:-1] = np.where(mask, top, 0)
        zq = [zp[:-1, :-1], zp[:-1, 1:], zp[1:, :-1], zp[1:, 1:]]
        cnt = sum(q.astype(np.int32) for q in quad)
        tot = sum(z for z in zq)
        return np.where(cnt > 0, tot / np.maximum(cnt, 1), 0.0)
    if mode == "min":
        zp = np.full((h + 2, w + 2), np.inf)
        zp[1:-1, 1:-1] = np.where(mask, top, np.inf)
        zq = [zp[:-1, :-1], zp[:-1, 1:], zp[1:, :-1], zp[1:, 1:]]
        out = np.minimum(np.minimum(zq[0], zq[1]), np.minimum(zq[2], zq[3]))
        return np.where(np.isfinite(out), out, 0.0)
    raise ValueError(mode)


def node_counts(mask):
    """Number of masked cells adjacent to each grid node ((H+1, W+1))."""
    h, w = mask.shape
    mp = np.zeros((h + 2, w + 2), np.int32)
    mp[1:-1, 1:-1] = mask
    return mp[:-1, :-1] + mp[:-1, 1:] + mp[1:, :-1] + mp[1:, 1:]


def heightfield_to_mesh(top, mask, px, node_z=None, bottom="grid"):
    """Extrude a masked heightfield into a watertight solid trimesh.

    top     (H, W) float, cell top z in mm (only read where mask).
    mask    (H, W) bool; MUST be free of diagonal pinches
            (see remove_diagonal_pinches).
    px      pixel size in mm.
    node_z  optional (H+1, W+1) precomputed corner heights; defaults to
            node_heights(top, mask, 'mean').
    bottom  'grid' = one quad per cell (any mask shape);
            'fan'  = single fan from a center vertex (requires mask.all(),
            i.e. a full rectangular slab) — cuts the triangle count of a
            flat bottom from 2*H*W to ~2*(H+W).

    Returns a trimesh.Trimesh: heightfield top + vertical boundary walls
    + flat bottom at z=0, shared vertices, consistent outward winding.
    """
    H, W = mask.shape
    if node_z is None:
        node_z = node_heights(top, mask, "mean")

    used = node_counts(mask) > 0
    node_id = np.full((H + 1, W + 1), -1, np.int64)
    n_used = int(used.sum())
    node_id[used] = np.arange(n_used)

    rr, cc = np.nonzero(used)
    xs = cc * px
    ys = (H - rr) * px
    verts = np.empty((2 * n_used, 3))
    verts[:n_used, 0] = xs
    verts[:n_used, 1] = ys
    verts[:n_used, 2] = node_z[rr, cc]
    verts[n_used:, 0] = xs
    verts[n_used:, 1] = ys
    verts[n_used:, 2] = 0.0
    o = n_used  # bottom-vertex offset

    faces = []
    r, c = np.nonzero(mask)
    A = node_id[r, c]          # NW corner
    B = node_id[r, c + 1]      # NE
    C = node_id[r + 1, c + 1]  # SE
    D = node_id[r + 1, c]      # SW
    # top, CCW seen from +z
    faces.append(np.stack([A, D, C], 1))
    faces.append(np.stack([A, C, B], 1))
    if bottom == "grid":
        # bottom, CCW seen from -z
        faces.append(np.stack([A + o, C + o, D + o], 1))
        faces.append(np.stack([A + o, B + o, C + o], 1))
    elif bottom == "fan":
        if not mask.all():
            raise ValueError("bottom='fan' requires a full rectangular mask")
        # perimeter node ids, CCW seen from +z, starting at the SW corner
        perim = np.concatenate([
            node_id[H, 0:W + 1],            # south edge, west -> east
            node_id[H - 1::-1, W],          # east edge, south -> north
            node_id[0, W - 1::-1],          # north edge, east -> west
            node_id[H - 1:0:-1, 0],         # west edge, north -> south
        ]) + o
        center = np.array([[W * px / 2.0, H * px / 2.0, 0.0]])
        verts = np.vstack([verts, center])
        cid = 2 * n_used
        nxt = np.roll(perim, -1)
        faces.append(np.stack([np.full(perim.shape, cid), nxt, perim], 1))
    else:
        raise ValueError(bottom)

    def walls(exposed, p_node, q_node, flip):
        """Wall quads for boundary edges. p/q map cell (r,c) -> node
        (row, col); winding validated per-direction (see below)."""
        er, ec = np.nonzero(exposed)
        if er.size == 0:
            return
        P = node_id[p_node[0](er), p_node[1](ec)]
        Q = node_id[q_node[0](er), q_node[1](ec)]
        if flip:
            P, Q = Q, P
        faces.append(np.stack([P, Q, Q + o], 1))
        faces.append(np.stack([P, Q + o, P + o], 1))

    ident = lambda v: v
    plus1 = lambda v: v + 1
    nb = np.zeros_like(mask)
    # north neighbor absent -> wall facing +y: (P,Q) = (r,c),(r,c+1)
    nb[:] = False; nb[1:] = mask[:-1]
    walls(mask & ~nb, (ident, ident), (ident, plus1), flip=False)
    # south neighbor absent -> wall facing -y: reversed
    nb[:] = False; nb[:-1] = mask[1:]
    walls(mask & ~nb, (plus1, ident), (plus1, plus1), flip=True)
    # east neighbor absent -> wall facing +x: (P,Q) = (r,c+1),(r+1,c+1)
    nb[:] = False; nb[:, :-1] = mask[:, 1:]
    walls(mask & ~nb, (ident, plus1), (plus1, plus1), flip=False)
    # west neighbor absent -> wall facing -x: reversed
    nb[:] = False; nb[:, 1:] = mask[:, :-1]
    walls(mask & ~nb, (ident, ident), (plus1, ident), flip=True)

    mesh = trimesh.Trimesh(vertices=verts, faces=np.concatenate(faces),
                           process=False)
    if bottom == "fan":
        mesh.remove_unreferenced_vertices()  # interior bottom nodes
    if mesh.volume < 0:
        mesh.invert()
    return mesh
