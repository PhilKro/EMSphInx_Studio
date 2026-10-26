"""Read vendor detector calibration as the SphInx camera tilt in degrees."""

import math
import os

import numpy as np


def validate_detector_tilt(value):
    """Apply the same camera-tilt limits as SphInx's namelist reader."""
    try:
        angle = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Detector tilt must be a finite angle in degrees.") from exc
    if not math.isfinite(angle) or not -60.0 <= angle <= 60.0:
        raise ValueError("Detector tilt must be finite and between -60 and 60 degrees.")
    return angle


def _scalar_tilt(dataset):
    values = np.asarray(dataset[()])
    if values.size != 1:
        raise ValueError(f"{dataset.name}: expected one detector tilt angle.")
    try:
        return validate_detector_tilt(values.reshape(-1)[0])
    except ValueError as exc:
        raise ValueError(f"{dataset.name}: {exc}") from exc


def _validate_azimuth(value, source):
    try:
        angle = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{source}: expected a finite detector azimuth in degrees.") from exc
    if not math.isfinite(angle) or abs(math.remainder(angle, 360.0)) > 1e-6:
        raise ValueError(
            f"{source}: detector azimuth cannot be represented by SphInx's camera tilt."
        )


def read_edax_detector_tilt(scan_group):
    """Read EDAX camera elevation, already expressed in degrees.

    Current .edaxh5 maps store calibration under Camera; older OIM exports
    place it in the EBSD header. Prefer the acquisition camera calibration.
    """
    for elevation_path, azimuth_path in (
        ("Camera/Elevation Angle", "Camera/Azimuthal Angle"),
        ("EBSD/ANG/HEADER/Camera Elevation Angle", "EBSD/ANG/HEADER/Camera Azimuthal Angle"),
        ("EBSD/Header/Camera Elevation Angle", "EBSD/Header/Camera Azimuthal Angle"),
    ):
        if elevation_path not in scan_group:
            continue
        # A schema supplies one calibration. Never combine its elevation with
        # azimuth from another (possibly stale) export of the same scan.
        angle = _scalar_tilt(scan_group[elevation_path])
        if azimuth_path in scan_group:
            dataset = scan_group[azimuth_path]
            values = np.asarray(dataset[()])
            if values.size != 1:
                raise ValueError(f"{dataset.name}: expected one detector azimuth angle.")
            _validate_azimuth(values.reshape(-1)[0], dataset.name)
        return angle
    return None


def read_oxford_detector_orientation(header_group):
    """Return H5OINA detector elevation (degrees) and original Euler radians.

    Oxford defines all angles in radians. SphInx's scalar elevation is
    Phi - pi/2. The outer Euler rotations are preserved for reporting;
    they cannot be applied through its single camera-tilt parameter.
    Reference: oinanoanalysis/h5oina, H5OINAFile.md, EBSD Header.
    """
    key = "Detector Orientation Euler"
    if key not in header_group:
        return None, None
    dataset = header_group[key]
    try:
        euler = np.asarray(dataset[()], dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{dataset.name}: expected three finite Euler angles in radians.") from exc
    if euler.shape not in ((3,), (1, 3), (3, 1)) or not np.all(np.isfinite(euler)):
        raise ValueError(f"{dataset.name}: expected three finite Euler angles in radians.")
    euler = euler.reshape(3)
    try:
        tilt = validate_detector_tilt(math.degrees(euler[1]) - 90.0)
    except ValueError as exc:
        raise ValueError(f"{dataset.name}: {exc}") from exc
    return tilt, tuple(float(angle) for angle in euler)


def read_oxford_detector_tilt(header_group):
    """Return the scalar Oxford detector elevation in SphInx degrees."""
    return read_oxford_detector_orientation(header_group)[0]


def oxford_elevation_only(euler):
    """Whether Oxford's preserved outer rotations need a limitation note."""
    if euler is None:
        return False
    return any(
        abs(math.remainder(float(euler[index]), 2.0 * math.pi)) > 1e-6
        for index in (0, 2)
    )


def read_ang_detector_tilt(path):
    """Read CameraElevationAngle in degrees from an EDAX ANG header."""
    try:
        handle = open(path, "r", encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        return None
    angle = None
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if not line.startswith("#"):
                break
            fields = line[1:].split()
            if fields and fields[0] == "CameraElevationAngle":
                if len(fields) < 2:
                    raise ValueError(f"{path}: CameraElevationAngle has no value.")
                try:
                    angle = validate_detector_tilt(fields[1])
                except ValueError as exc:
                    raise ValueError(f"{path}: CameraElevationAngle: {exc}") from exc
            elif fields and fields[0] == "CameraAzimuthalAngle":
                if len(fields) < 2:
                    raise ValueError(f"{path}: CameraAzimuthalAngle has no value.")
                _validate_azimuth(fields[1], f"{path}: CameraAzimuthalAngle")
    return angle


def resolve_detector_tilt(tilt_degrees, up1_path=None):
    """Prefer H5 tilt, then the selected EDAX UP1's ANG, then legacy zero."""
    if tilt_degrees is not None:
        return validate_detector_tilt(tilt_degrees)
    if up1_path:
        sidecar = os.path.splitext(os.fspath(up1_path))[0] + ".ang"
        angle = read_ang_detector_tilt(sidecar)
        if angle is not None:
            return angle
    return 0.0
