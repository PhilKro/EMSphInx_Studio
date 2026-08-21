from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BinningGeometry:
    """Geometry of a centered crop followed by square detector binning."""

    factor: int
    input_width: int
    input_height: int
    output_width: int
    output_height: int
    crop_left: int
    crop_right: int
    crop_top: int
    crop_bottom: int

    @property
    def cropped_width(self):
        return self.output_width * self.factor

    @property
    def cropped_height(self):
        return self.output_height * self.factor


def binning_geometry(pattern_width, pattern_height, factor):
    """Return a centered crop which makes both dimensions divisible by factor.

    When an odd number of pixels must be discarded, the extra pixel is removed
    from the trailing (right or bottom) edge. This gives deterministic slices
    and keeps the retained detector area as centered as the pixel grid permits.
    """
    pattern_width = int(pattern_width)
    pattern_height = int(pattern_height)
    factor = int(factor)

    if pattern_width <= 0 or pattern_height <= 0:
        raise ValueError("Pattern dimensions must be positive.")
    if factor < 1:
        raise ValueError("Binning must be a positive integer.")
    if factor > pattern_width or factor > pattern_height:
        raise ValueError("Binning cannot exceed either pattern dimension.")

    discarded_width = pattern_width % factor
    discarded_height = pattern_height % factor
    crop_left = discarded_width // 2
    crop_top = discarded_height // 2

    return BinningGeometry(
        factor=factor,
        input_width=pattern_width,
        input_height=pattern_height,
        output_width=pattern_width // factor,
        output_height=pattern_height // factor,
        crop_left=crop_left,
        crop_right=discarded_width - crop_left,
        crop_top=crop_top,
        crop_bottom=discarded_height - crop_top,
    )


def bin_patterns(patterns, geometry):
    """Crop and block-average one chunk of uint8 patterns.

    Integer accumulation and rounding preserve the uint8 intensity scale and
    avoid allocating a floating-point copy of the input chunk.
    """
    patterns = np.asarray(patterns)
    if patterns.ndim < 2 or patterns.shape[-2:] != (
        geometry.input_height,
        geometry.input_width,
    ):
        raise ValueError("Pattern chunk dimensions do not match binning geometry.")

    if geometry.factor == 1:
        return np.ascontiguousarray(patterns, dtype=np.uint8)

    y_stop = geometry.input_height - geometry.crop_bottom
    x_stop = geometry.input_width - geometry.crop_right
    cropped = patterns[
        ...,
        geometry.crop_top:y_stop,
        geometry.crop_left:x_stop,
    ]
    leading_shape = cropped.shape[:-2]
    blocks = cropped.reshape(
        *leading_shape,
        geometry.output_height,
        geometry.factor,
        geometry.output_width,
        geometry.factor,
    )
    block_sums = blocks.sum(axis=(-3, -1), dtype=np.uint32)
    block_area = geometry.factor * geometry.factor
    binned = (block_sums + block_area // 2) // block_area
    return np.ascontiguousarray(binned, dtype=np.uint8)


def emsoft_calibration(pc, native_delta, geometry):
    """Convert Oxford H5OINA calibration after crop/binning to EMsoft units.

    Oxford PC X and detector distance are normalized by the original detector
    width in the H5OINA data used by the Studio. The returned X/Y values are in
    output pixels relative to the retained pattern center; Z is in microns.
    """
    pcx, pcy, detector_distance = (float(value) for value in pc)
    native_delta = float(native_delta)
    if native_delta <= 0:
        raise ValueError("Native delta must be positive.")

    x_native = geometry.input_width * (pcx - 0.5)
    y_native = geometry.input_width * pcy - 0.5 * geometry.input_height

    # A centered even crop has no offset. If an odd crop is needed, the extra
    # trailing-edge pixel moves the retained center by half a native pixel.
    x_crop_correction = 0.5 * (geometry.crop_right - geometry.crop_left)
    y_crop_correction = 0.5 * (geometry.crop_top - geometry.crop_bottom)

    pc_x = (x_native + x_crop_correction) / geometry.factor
    pc_y = (y_native + y_crop_correction) / geometry.factor
    detector_distance_microns = (
        geometry.input_width * detector_distance * native_delta
    )
    effective_delta = native_delta * geometry.factor
    return pc_x, pc_y, detector_distance_microns, effective_delta
