import unittest

import numpy as np

from oxford_binning import bin_patterns, binning_geometry, emsoft_calibration


class OxfordBinningTests(unittest.TestCase):
    def test_divisible_pattern_dimensions(self):
        geometry = binning_geometry(624, 512, 2)
        self.assertEqual((geometry.output_width, geometry.output_height), (312, 256))
        self.assertEqual(
            (geometry.crop_left, geometry.crop_right, geometry.crop_top, geometry.crop_bottom),
            (0, 0, 0, 0),
        )

    def test_center_crop_for_non_divisible_dimensions(self):
        geometry = binning_geometry(624, 512, 3)
        self.assertEqual((geometry.output_width, geometry.output_height), (208, 170))
        self.assertEqual(
            (geometry.crop_left, geometry.crop_right, geometry.crop_top, geometry.crop_bottom),
            (0, 0, 1, 1),
        )

    def test_block_average_uses_center_crop_and_rounding(self):
        patterns = np.arange(2 * 5 * 7, dtype=np.uint8).reshape(2, 5, 7)
        geometry = binning_geometry(7, 5, 2)
        result = bin_patterns(patterns, geometry)

        expected = np.empty((2, 2, 3), dtype=np.uint8)
        for i, pattern in enumerate(patterns):
            cropped = pattern[0:4, 0:6]
            for y in range(2):
                for x in range(3):
                    block = cropped[y * 2 : y * 2 + 2, x * 2 : x * 2 + 2]
                    expected[i, y, x] = (int(block.sum()) + 2) // 4

        np.testing.assert_array_equal(result, expected)
        self.assertTrue(result.flags.c_contiguous)

    def test_pc_delta_and_distance_for_divisible_binning(self):
        geometry = binning_geometry(624, 512, 2)
        pc_x, pc_y, distance, delta = emsoft_calibration(
            (0.55, 0.45, 0.6), 20.0, geometry
        )
        self.assertAlmostEqual(pc_x, 15.6)
        self.assertAlmostEqual(pc_y, 12.4)
        self.assertAlmostEqual(distance, 7488.0)
        self.assertAlmostEqual(delta, 40.0)

    def test_asymmetric_center_crop_corrects_pc(self):
        geometry = binning_geometry(7, 7, 2)
        pc_x, pc_y, distance, delta = emsoft_calibration(
            (0.5, 0.5, 0.5), 10.0, geometry
        )
        self.assertAlmostEqual(pc_x, 0.25)
        self.assertAlmostEqual(pc_y, -0.25)
        self.assertAlmostEqual(distance, 35.0)
        self.assertAlmostEqual(delta, 20.0)

    def test_invalid_binning_is_rejected(self):
        for factor in (0, -1, 513):
            with self.subTest(factor=factor), self.assertRaises(ValueError):
                binning_geometry(624, 512, factor)


if __name__ == "__main__":
    unittest.main()
