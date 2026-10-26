import math
import os
import tempfile
import unittest

import h5py
import numpy as np

from detector_tilt import (
    oxford_elevation_only,
    read_ang_detector_tilt,
    read_edax_detector_tilt,
    read_oxford_detector_orientation,
    read_oxford_detector_tilt,
    resolve_detector_tilt,
)


class DetectorTiltMetadataTests(unittest.TestCase):
    def setUp(self):
        self.h5 = h5py.File("detector-tilt-test.h5", "w", driver="core", backing_store=False)
        self.addCleanup(self.h5.close)

    def test_edax_acquisition_camera_elevation_preserves_degrees_and_sign(self):
        for index, angle in enumerate((-12.5, 0.0, 10.0)):
            with self.subTest(angle=angle):
                scan = self.h5.create_group(str(index))
                scan["Camera/Elevation Angle"] = [angle]
                scan["Camera/Azimuthal Angle"] = [0.0]
                self.assertEqual(read_edax_detector_tilt(scan), angle)

    def test_edax_header_export_schemas_and_scalar_storage(self):
        for index, path in enumerate((
            "EBSD/ANG/HEADER/Camera Elevation Angle",
            "EBSD/Header/Camera Elevation Angle",
        )):
            with self.subTest(path=path):
                scan = self.h5.create_group(str(index))
                scan[path] = -7.25
                self.assertEqual(read_edax_detector_tilt(scan), -7.25)

    def test_edax_acquisition_zero_precedes_export_header(self):
        self.h5["Camera/Elevation Angle"] = [0.0]
        self.h5["Camera/Azimuthal Angle"] = [0.0]
        self.h5["EBSD/ANG/HEADER/Camera Elevation Angle"] = [10.0]
        self.h5["EBSD/ANG/HEADER/Camera Azimuthal Angle"] = [15.0]
        self.assertEqual(read_edax_detector_tilt(self.h5), 0.0)

    def test_edax_acquisition_calibration_ignores_conflicting_export_azimuth(self):
        self.h5["Camera/Elevation Angle"] = [8.0]
        self.h5["Camera/Azimuthal Angle"] = [0.0]
        self.h5["EBSD/ANG/HEADER/Camera Elevation Angle"] = [10.0]
        self.h5["EBSD/ANG/HEADER/Camera Azimuthal Angle"] = [15.0]
        self.assertEqual(read_edax_detector_tilt(self.h5), 8.0)

    def test_edax_does_not_mix_azimuth_from_an_incomplete_schema(self):
        self.h5["Camera/Azimuthal Angle"] = [15.0]
        self.h5["EBSD/Header/Camera Elevation Angle"] = [5.0]
        self.h5["EBSD/Header/Camera Azimuthal Angle"] = [0.0]
        self.assertEqual(read_edax_detector_tilt(self.h5), 5.0)

    def test_edax_azimuth_without_any_elevation_leaves_tilt_missing(self):
        self.h5["Camera/Azimuthal Angle"] = [15.0]
        self.assertIsNone(read_edax_detector_tilt(self.h5))

    def test_sample_tilt_does_not_substitute_for_detector_tilt(self):
        self.h5["Tilt Angle"] = [math.radians(70.0)]
        self.h5["EBSD/Header/Sample Tilt"] = [70.0]
        self.assertIsNone(read_oxford_detector_tilt(self.h5))
        self.assertEqual(read_oxford_detector_orientation(self.h5), (None, None))
        self.assertIsNone(read_edax_detector_tilt(self.h5))

    def test_oxford_euler_radians_convert_to_signed_elevation(self):
        for index, angle in enumerate((-10.0, 0.0, 8.0)):
            with self.subTest(angle=angle):
                header = self.h5.create_group(str(index))
                header["Detector Orientation Euler"] = [0.0, math.radians(90.0 + angle), 0.0]
                self.assertAlmostEqual(read_oxford_detector_tilt(header), angle)

    def test_oxford_row_and_column_vectors_are_supported(self):
        for index, shape in enumerate(((1, 3), (3, 1))):
            with self.subTest(shape=shape):
                header = self.h5.create_group(str(index))
                header["Detector Orientation Euler"] = np.array(
                    [0.0, math.radians(98), 0.0]
                ).reshape(shape)
                self.assertAlmostEqual(read_oxford_detector_tilt(header), 8.0)

    def test_oxford_outer_full_turns_are_equivalent_to_zero(self):
        self.h5["Detector Orientation Euler"] = [2 * math.pi, math.pi / 2, -2 * math.pi]
        self.assertAlmostEqual(read_oxford_detector_tilt(self.h5), 0.0)
        _tilt, euler = read_oxford_detector_orientation(self.h5)
        self.assertFalse(oxford_elevation_only(euler))

    def test_oxford_outer_rotations_are_preserved_and_reported(self):
        for index, angles in enumerate(((0.01, math.pi / 2, 0), (0, math.pi / 2, 0.01))):
            with self.subTest(angles=angles):
                header = self.h5.create_group(str(index))
                header["Detector Orientation Euler"] = angles
                tilt, original_euler = read_oxford_detector_orientation(header)
                self.assertAlmostEqual(tilt, 0.0)
                self.assertEqual(original_euler, angles)
                self.assertTrue(oxford_elevation_only(original_euler))

    def test_real_oxford_orientation_retains_raw_euler_and_uses_elevation(self):
        original = (0.001705034519545734, 1.5550974607467651, 6.281116008758545)
        self.h5["Detector Orientation Euler"] = original
        tilt, euler = read_oxford_detector_orientation(self.h5)
        self.assertEqual(euler, original)
        self.assertAlmostEqual(tilt, -0.8994787671, places=7)
        self.assertAlmostEqual(read_oxford_detector_tilt(self.h5), tilt)
        self.assertTrue(oxford_elevation_only(euler))

    def test_invalid_oxford_metadata_is_rejected(self):
        invalid = (
            [0, 90, 0],  # Degrees stored where the format requires radians.
            [0, math.nan, 0],
            [0, math.inf, 0],
            [math.nan, math.pi / 2, 0],
            [0, math.pi / 2, math.inf],
            [0, math.radians(151), 0],
            [0, math.radians(29), 0],
            [0, math.pi / 2],
            [[0, math.pi / 2, 0], [0, math.pi / 2, 0]],
            [b"not", b"an", b"angle"],
        )
        for index, angles in enumerate(invalid):
            with self.subTest(angles=angles):
                header = self.h5.create_group(str(index))
                header["Detector Orientation Euler"] = angles
                with self.assertRaises(ValueError):
                    read_oxford_detector_tilt(header)

    def test_invalid_edax_metadata_does_not_fall_back_to_header(self):
        for index, angle in enumerate(([math.nan], [math.inf], [61], [-61], [1, 2], [b"invalid"])):
            with self.subTest(angle=angle):
                scan = self.h5.create_group(str(index))
                scan["Camera/Elevation Angle"] = angle
                scan["EBSD/ANG/HEADER/Camera Elevation Angle"] = [10]
                with self.assertRaises(ValueError):
                    read_edax_detector_tilt(scan)

    def test_edax_nonzero_azimuth_is_rejected_and_full_turn_is_accepted(self):
        self.h5["Camera/Elevation Angle"] = [8.0]
        self.h5["Camera/Azimuthal Angle"] = [1.0]
        with self.assertRaisesRegex(ValueError, "azimuth"):
            read_edax_detector_tilt(self.h5)
        self.h5["Camera/Azimuthal Angle"][...] = [360.0]
        self.assertEqual(read_edax_detector_tilt(self.h5), 8.0)


class DetectorTiltAngTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.up1 = os.path.join(directory.name, "sample.up1")
        self.ang = os.path.join(directory.name, "sample.ang")

    def write_header(self, content):
        with open(self.ang, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_ang_header_preserves_signed_degrees(self):
        self.write_header(
            "# SampleTiltAngle 70.0\n# CameraElevationAngle -8.25\n"
            "# CameraAzimuthalAngle 0.0\n0 0 0 0 0 0\n"
        )
        self.assertEqual(read_ang_detector_tilt(self.ang), -8.25)
        self.assertEqual(resolve_detector_tilt(None, self.up1), -8.25)

    def test_missing_ang_or_missing_header_keeps_legacy_zero(self):
        self.assertIsNone(read_ang_detector_tilt(self.ang))
        self.assertEqual(resolve_detector_tilt(None, self.up1), 0.0)
        self.write_header("# SampleTiltAngle 70.0\n0 0 0 0\n# CameraElevationAngle 9\n")
        self.assertIsNone(read_ang_detector_tilt(self.ang))
        self.assertEqual(resolve_detector_tilt(None, self.up1), 0.0)
        self.assertEqual(resolve_detector_tilt(None), 0.0)

    def test_h5_zero_takes_precedence_over_invalid_ang(self):
        self.write_header("# CameraElevationAngle invalid\n# CameraAzimuthalAngle 45\n")
        self.assertEqual(resolve_detector_tilt(0.0, self.up1), 0.0)

    def test_invalid_ang_elevation_and_unsupported_azimuth_are_rejected(self):
        for header in (
            "# CameraElevationAngle\n",
            "# CameraElevationAngle invalid\n",
            "# CameraElevationAngle nan\n",
            "# CameraElevationAngle 61\n",
            "# CameraElevationAngle -61\n",
            "# CameraElevationAngle 8\n# CameraAzimuthalAngle 5\n",
        ):
            with self.subTest(header=header):
                self.write_header(header)
                with self.assertRaises(ValueError):
                    resolve_detector_tilt(None, self.up1)


if __name__ == "__main__":
    unittest.main()
