"""IPF colours from public pyMTEX APIs, preserving the file's pixel order."""

import os
import threading

import h5py
import numpy as np


IPF_FIELDS = ("IPF X", "IPF Y", "IPF Z")
_EDAX_SYMMETRY_CODES = {1, 2, 20, 22, 4, 42, 3, 32, 6, 62, 23, 43}


def ipf_available(scan_group, vendor):
    """Inspect field names without loading orientations or importing pyMTEX."""
    if vendor == "EDAX":
        path = "ANG/DATA/DATA"
        if path not in scan_group:
            return False
        fields = scan_group[path].dtype.names or ()
        return "Orientations" in fields and "Phase" in fields
    return "Data/Euler" in scan_group and "Data/Phase" in scan_group


def reshape_map(values, nx, ny, row_major=True):
    """Lay out scalar or RGB file rows consistently with the probing index."""
    values = np.asarray(values)
    if values.ndim not in (1, 2) or (values.ndim == 2 and values.shape[1] != 3):
        raise ValueError("A map must contain scalar values or three RGB channels per pixel.")
    if nx <= 0 or ny <= 0 or len(values) != nx * ny:
        raise ValueError("Map data length does not match the selected scan dimensions.")
    channels = values.shape[1:]
    if row_major:
        return values.reshape((ny, nx) + channels)
    grid = values.reshape((nx, ny) + channels)
    return grid.transpose((1, 0, 2)) if channels else grid.T


def _scalar_number(group, key):
    if key not in group:
        raise ValueError(f"{group.name}: IPF maps require explicit {key} metadata.")
    values = np.asarray(group[key][()])
    if values.size != 1:
        raise ValueError(f"{group.name}/{key}: expected one symmetry identifier.")
    try:
        value = float(values.reshape(-1)[0])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{group.name}/{key}: unsupported symmetry identifier.") from exc
    if not np.isfinite(value) or value != int(value):
        raise ValueError(f"{group.name}/{key}: unsupported symmetry identifier.")
    return int(value)


def _validate_phase(phase, vendor, frame):
    if vendor == "EDAX":
        code = _scalar_number(phase, "Symmetry")
        if code not in _EDAX_SYMMETRY_CODES:
            raise ValueError(f"{phase.name}: unsupported EDAX symmetry code {code}.")
        dimension_keys = [f"Lattice Constant {axis}" for axis in ("A", "B", "C")]
        angle_keys = [f"Lattice Constant {angle}" for angle in ("Alpha", "Beta", "Gamma")]
    else:
        number = _scalar_number(phase, "Space Group")
        if not 1 <= number <= 230:
            raise ValueError(f"{phase.name}: unsupported space group {number}.")
        dimension_keys, angle_keys = ["Lattice Dimensions"], ["Lattice Angles"]
    for keys, dimensions in ((dimension_keys, True), (angle_keys, False)):
        if any(key not in phase for key in keys):
            raise ValueError(f"{phase.name}: indexed phase has incomplete lattice metadata.")
        try:
            values = np.concatenate([np.asarray(phase[key][()], dtype=float).reshape(-1) for key in keys])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{phase.name}: indexed phase has invalid lattice metadata.") from exc
        upper = np.inf if dimensions else (180.0 if vendor == "EDAX" else np.pi)
        if values.size != 3 or not np.all(np.isfinite(values)) or np.any(values <= 0) or np.any(values >= upper):
            raise ValueError(f"{phase.name}: indexed phase has invalid lattice metadata.")
    if not frame.isIndexed:
        raise ValueError(f"{phase.name}: pyMTEX could not construct a usable indexed phase frame.")


def _authoritative_phase_ids(scan, vendor, raw_phase, valid, rows, ebsd):
    """Bind vendor phase numbers to the imported frames by header group ID.

    mtex 1.0 guesses the phase offset from the phases occurring in the data.
    That guess fails when a declared phase is unused. Its CSList follows the
    HDF5 header traversal order, which is lexical rather than numeric.
    """
    root = "ANG/HEADER/Phase" if vendor == "EDAX" else "Header/Phases"
    names = [] if root not in scan else [name for name in sorted(scan[root]) if isinstance(scan[root][name], h5py.Group)]
    if len(ebsd.CSList) != len(names) + 1:
        raise ValueError("Imported phase frames do not match the selected scan's phase headers.")
    indices = {}
    for index, name in enumerate(names, 1):
        try:
            number = int(name)
        except ValueError as exc:
            raise ValueError(f"Phase header {name!r} is not a numeric phase identifier.") from exc
        if number <= 0 or number in indices:
            raise ValueError("Phase headers contain invalid or duplicate numeric identifiers.")
        indices[number] = (index, name)
    used = np.zeros(len(valid), dtype=bool)
    used[rows] = True
    used &= valid
    indexed = raw_phase >= 0 if vendor == "EDAX" else raw_phase > 0
    ids = np.zeros(len(valid), dtype=np.int64)
    for raw_id in np.unique(raw_phase[used & indexed]):
        number = int(raw_id) + (1 if vendor == "EDAX" else 0)
        if number not in indices:
            raise ValueError(f"Indexed phase {int(raw_id)} has no matching phase symmetry metadata.")
        phase_id, name = indices[number]
        _validate_phase(scan[root][name], vendor, ebsd.CSList[phase_id])
        ids[used & (raw_phase == raw_id)] = phase_id
    return ids


def _raw_scan_data(scan, vendor):
    if vendor == "EDAX":
        table = scan["ANG/DATA/DATA"]
        orientation = np.asarray(table["Orientations"], dtype=float)
        if orientation.ndim != 2 or orientation.shape[1] != 9:
            raise ValueError("EDAX orientations must contain nine matrix components per pixel.")
        raw_phase = np.asarray(table["Phase"], dtype=float).reshape(-1)
        valid = np.isfinite(orientation).reshape(len(orientation), -1).all(axis=1)
        valid &= np.any(orientation != 0, axis=1)
        if "Valid" in table.dtype.names:
            valid &= np.asarray(table["Valid"]).reshape(-1) != 0
        if "CI" in table.dtype.names:
            valid &= np.asarray(table["CI"]).reshape(-1) >= 0
    else:
        orientation = np.asarray(scan["Data/Euler"], dtype=float)
        if orientation.ndim != 2 or orientation.shape[1] != 3:
            raise ValueError("Oxford orientations must contain three Euler angles per pixel.")
        raw_phase = np.asarray(scan["Data/Phase"], dtype=float).reshape(-1)
        valid = np.isfinite(orientation).reshape(len(orientation), -1).all(axis=1)
        # H5OINA phase zero is unindexed, even in an entirely unindexed scan
        # where the importer's phase-numbering heuristic cannot disambiguate it.
        valid &= raw_phase != 0
        if "Header/Specimen Orientation Euler" in scan:
            surface = np.asarray(scan["Header/Specimen Orientation Euler"][()], dtype=float)
            if surface.size != 3 or not np.all(np.isfinite(surface)) or np.any(surface != 0):
                raise ValueError(
                    "IPF maps cannot yet display a nonzero Oxford Specimen Orientation Euler: "
                    "the installed pyMTEX importer interprets this radian metadata as degrees."
                )
    if len(raw_phase) != len(orientation):
        raise ValueError("Orientation and phase counts differ in the selected scan.")
    valid &= np.isfinite(raw_phase) & (raw_phase == np.floor(raw_phase))
    return orientation, raw_phase, valid


def _original_rows(ebsd, count):
    record = ebsd.meta.get("h5", {})
    if record.get("fileLength") != count:
        raise ValueError("pyMTEX orientation rows do not match the original scan.")
    rows = record.get("rows")
    if rows is None:
        rows = np.arange(count)
    else:
        rows = np.asarray(rows)
        if rows.ndim != 1 or rows.dtype.kind not in "iu" or len(np.unique(rows)) != len(rows):
            raise ValueError("pyMTEX returned an invalid original-row mapping.")
        if np.any(rows < 0) or np.any(rows >= count):
            raise ValueError("pyMTEX returned an out-of-range original-row mapping.")
    if len(rows) != len(ebsd):
        raise ValueError("pyMTEX positions do not match the original-row mapping.")
    return rows


def load_ipf_maps(path, dataset_path, nx, ny, vendor):
    """Colour the selected scan in X/Y/Z with its own phase-aware HSV keys."""
    try:
        from mtex import EBSD, ipfColors, loadEBSD, rotation, xvector, yvector, zvector
    except ImportError as exc:
        raise ValueError("IPF maps require pyMTEX. Install the project requirements.") from exc
    expected = "/" + str(dataset_path).strip("/")
    with h5py.File(path, "r") as handle:
        scan = handle[expected]
        if not ipf_available(scan, vendor):
            raise ValueError("The selected scan has no indexed orientations and phase fields.")
        orientation, raw_phase, valid = _raw_scan_data(scan, vendor)
        if len(valid) != nx * ny:
            raise ValueError("Indexed orientation count does not match the selected scan dimensions.")
        ebsd = loadEBSD(os.fspath(path), dataSet=expected, grid=False, verbose=False)
        actual = "/" + str(ebsd.meta.get("dataSet", "")).strip("/")
        if actual != expected:
            raise ValueError("pyMTEX loaded a different scan from the selected map.")
        rows = _original_rows(ebsd, len(valid))
        ids = _authoritative_phase_ids(scan, vendor, raw_phase, valid, rows, ebsd)
    # Rebuild from raw orientations: the importer may already have replaced
    # valid zero-based EDAX rotations with NaNs after guessing the wrong phase.
    # MTEX performs both conversions and the vendor correction; no Euler or
    # quaternion operations are duplicated here.
    orientation = orientation.copy()
    if vendor == "EDAX":
        orientation[~valid] = np.eye(3).reshape(9)
        raw_rotations = rotation.byMatrix(orientation.reshape(-1, 3, 3).transpose(0, 2, 1))
    else:
        orientation[~valid] = 0.0
        raw_rotations = rotation.byEuler(orientation[:, 0], orientation[:, 1], orientation[:, 2])
    correction = ebsd.meta["h5"]["correction"]
    meta = dict(ebsd.meta)
    meta["sourcePhaseId"] = raw_phase[rows].copy()
    ebsd = EBSD(
        ebsd.pos, (correction * raw_rotations)[rows], ids[rows], ebsd.CSList,
        frame=ebsd.frame, lattice=ebsd.lattice, scanUnit=ebsd.scanUnit, meta=meta,
    )
    maps = {}
    for field, direction in zip(IPF_FIELDS, (xvector, yvector, zvector)):
        colours = np.asarray(
            ipfColors(ebsd, ipfDirection=direction, unindexed=(0, 0, 0), exact=True),
            dtype=float,
        ).reshape(-1, 3)
        if len(colours) != len(rows):
            raise ValueError("pyMTEX colour count does not match the original-row mapping.")
        full = np.zeros((len(valid), 3), dtype=np.uint8)
        colours = np.nan_to_num(colours, nan=0.0, posinf=0.0, neginf=0.0)
        full[rows] = np.rint(np.clip(colours, 0, 1) * 255).astype(np.uint8)
        full[~valid] = 0
        maps[field] = full
    return maps


class IPFMapCache:
    """Compute colours off the UI thread; publish only the current generation."""

    def __init__(self, root):
        self.root = root
        self.maps = {}
        self.pending = set()
        self.generation = 0

    def invalidate(self):
        self.generation += 1
        self.maps.clear()
        self.pending.clear()

    def get_or_request(self, key, loader, callback):
        if key in self.maps:
            return self.maps[key]
        if key in self.pending:
            return None
        self.pending.add(key)
        generation = self.generation

        def work():
            result, error = None, None
            try:
                result = loader()
            except Exception as exc:
                error = exc
            try:
                self.root.after(0, self._complete, generation, key, result, error, callback)
            except Exception:
                # A closing Tk application no longer accepts queued callbacks.
                return

        threading.Thread(target=work, daemon=True).start()
        return None

    def _complete(self, generation, key, maps, error, callback):
        if generation != self.generation:
            return
        self.pending.discard(key)
        if error is None:
            self.maps[key] = maps
        callback(key, maps, error)
