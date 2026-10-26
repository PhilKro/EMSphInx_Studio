import os
import tempfile
import unittest
from unittest import mock

import h5py
import numpy as np

from ipf_maps import IPF_FIELDS, ipf_available, load_ipf_maps, reshape_map

try:
    from mtex import ipfColors, loadEBSD, rotation, vector3d, xvector, yvector, zvector
except ImportError:
    HAS_MTEX = False
else:
    HAS_MTEX = True


class MapReshapingTests(unittest.TestCase):
    def test_nonsquare_rgb_channels_and_probe_indices_match_both_orders(self):
        values = np.arange(18, dtype=np.uint8).reshape(6, 3)
        for row_major in (True, False):
            with self.subTest(row_major=row_major):
                grid = reshape_map(values, 3, 2, row_major)
                self.assertEqual(grid.shape, (2, 3, 3))
                scalar = reshape_map(np.arange(6), 3, 2, row_major)
                for y in range(2):
                    for x in range(3):
                        index = y * 3 + x if row_major else x * 2 + y
                        np.testing.assert_array_equal(grid[y, x], values[index])
                        self.assertEqual(scalar[y, x], index)

    def test_wrong_grid_length_and_non_rgb_arrays_are_rejected(self):
        for values in (np.zeros((5, 3)), np.zeros((6, 4)), np.zeros((2, 3, 3))):
            with self.subTest(shape=values.shape), self.assertRaises(ValueError):
                reshape_map(values, 3, 2)

    def test_availability_requires_orientation_and_phase_fields(self):
        with h5py.File("ipf-fields.h5", "w", driver="core", backing_store=False) as handle:
            self.assertFalse(ipf_available(handle, "OXFORD"))
            handle["Data/Euler"] = np.zeros((4, 3))
            self.assertFalse(ipf_available(handle, "OXFORD"))
            handle["Data/Phase"] = np.ones(4)
            self.assertTrue(ipf_available(handle, "OXFORD"))
            self.assertFalse(ipf_available(handle, "EDAX"))
            handle.create_dataset("ANG/DATA/DATA", shape=(4,), dtype=[("Orientations", "f8", (9,)), ("Phase", "i4")])
            self.assertTrue(ipf_available(handle, "EDAX"))


@unittest.skipUnless(HAS_MTEX, "pyMTEX is not installed")
class IpfColourTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = directory.name

    def oxford(self, euler, phases=None, groups=None):
        euler = np.asarray(euler, dtype=float)
        phases = np.ones(len(euler), dtype=np.uint8) if phases is None else np.asarray(phases, dtype=np.uint8)
        groups = [225] if groups is None else groups
        path = os.path.join(self.directory, "scan.h5oina")
        with h5py.File(path, "w") as handle:
            handle["Manufacturer"] = np.bytes_("Oxford Instruments")
            scan = handle.create_group("1/EBSD")
            scan["Data/Euler"] = euler
            scan["Data/Phase"] = phases
            scan["Header/X Cells"] = [len(euler)]
            scan["Header/Y Cells"] = [1]
            scan["Header/X Step"] = [1.0]
            scan["Header/Y Step"] = [1.0]
            scan["Header/Scanning Rotation Angle"] = [0.0]
            scan["Header/Specimen Orientation Euler"] = [[0.0, 0.0, 0.0]]
            for index, group in enumerate(groups, 1):
                phase = scan.create_group(f"Header/Phases/{index}")
                phase["Space Group"] = [group]
                phase["Phase Name"] = np.bytes_(f"Phase {index}")
                phase["Lattice Dimensions"] = [[1.0, 1.0, 1.6 if group == 194 else 1.0]]
                phase["Lattice Angles"] = [[np.pi / 2, np.pi / 2, 2 * np.pi / 3 if group == 194 else np.pi / 2]]
        return path

    def edax(self, matrices, phases=None, valid=None, ci=None, groups=None):
        matrices = np.asarray(matrices, dtype=float)
        count = len(matrices)
        path = os.path.join(self.directory, "scan.edaxh5")
        table = np.zeros(count, dtype=[("Orientations", "f8", (9,)), ("Phase", "i4"), ("Valid", "i4"), ("CI", "f4")])
        table["Orientations"] = matrices.transpose(0, 2, 1).reshape(count, 9)
        table["Phase"] = 0 if phases is None else phases
        table["Valid"] = 1 if valid is None else valid
        table["CI"] = 1 if ci is None else ci
        with h5py.File(path, "w") as handle:
            scan = handle.create_group("Map")
            scan["Sample/Step X"] = [1.0]
            scan["Sample/Step Y"] = [1.0]
            scan["Sample/Number Of Columns"] = [count]
            scan["Sample/Number Of Rows"] = [1]
            scan["EBSD/ANG/DATA/DATA"] = table
            for index, symmetry in enumerate([43] if groups is None else groups, 1):
                phase = scan.create_group(f"EBSD/ANG/HEADER/Phase/{index}")
                phase["Symmetry"] = [symmetry]
                phase["Material Name"] = np.bytes_(f"Phase {index}")
                for axis in ("A", "B", "C"):
                    phase[f"Lattice Constant {axis}"] = [1.6 if symmetry == 62 and axis == "C" else 1.0]
                for angle in ("Alpha", "Beta", "Gamma"):
                    phase[f"Lattice Constant {angle}"] = [120.0 if symmetry == 62 and angle == "Gamma" else 90.0]
        return path

    def test_cubic_001_110_111_have_hsv_key_anchor_colours(self):
        axes = ([0, 0, 1], [1, 1, 0], [1, 1, 1])
        euler = [rotation.map(vector3d(axis), zvector).Euler() for axis in axes]
        maps = load_ipf_maps(self.oxford(euler), "/1/EBSD", 3, 1, "OXFORD")
        self.assertEqual(set(maps), set(IPF_FIELDS))
        np.testing.assert_allclose(maps["IPF Z"], np.eye(3, dtype=np.uint8) * 255, atol=3)
        self.assertTrue(np.any(maps["IPF X"] != maps["IPF Z"]))

    def test_multiphase_hexagonal_colour_uses_its_own_symmetry(self):
        euler = [rotation.map(vector3d([1, 1, 1]), zvector).Euler()] * 2
        maps = load_ipf_maps(self.oxford(euler, phases=[1, 2], groups=[225, 194]), "/1/EBSD", 2, 1, "OXFORD")
        self.assertEqual(maps["IPF Z"].shape, (2, 3))
        self.assertFalse(np.array_equal(maps["IPF Z"][0], maps["IPF Z"][1]))
        self.assertGreater(maps["IPF Z"][0, 2], 250)

    def test_oxford_phase_zero_is_black_in_mixed_and_all_unindexed_scans(self):
        for phases in ([0, 1], [0, 0]):
            with self.subTest(phases=phases):
                maps = load_ipf_maps(self.oxford(np.zeros((2, 3)), phases=phases), "/1/EBSD", 2, 1, "OXFORD")
                for colours in maps.values():
                    self.assertTrue(np.all(colours[np.asarray(phases) == 0] == 0))

    def test_oxford_unused_highest_phase_does_not_change_phase_one_colour(self):
        euler = [rotation.map(vector3d([1, 1, 1]), zvector).Euler()] * 2
        path = self.oxford(euler, phases=[0, 1], groups=[225, 194])
        maps = load_ipf_maps(path, "/1/EBSD", 2, 1, "OXFORD")
        np.testing.assert_array_equal(maps["IPF Z"][0], 0)
        np.testing.assert_allclose(maps["IPF Z"][1], [0, 0, 255], atol=3)

    def test_edax_unused_highest_declared_phase_keeps_phase_zero_indexed(self):
        path = self.edax([np.eye(3)], phases=[0], groups=[43, 62])
        maps = load_ipf_maps(path, "/Map/EBSD", 1, 1, "EDAX")
        np.testing.assert_allclose(maps["IPF Z"][0], [255, 0, 0], atol=3)

    def test_numeric_phase_group_id_is_not_lexical_group_position(self):
        groups = [194] * 11
        groups[9] = 225
        euler = [rotation.map(vector3d([1, 1, 1]), zvector).Euler()]
        path = self.oxford(euler, phases=[10], groups=groups)
        maps = load_ipf_maps(path, "/1/EBSD", 1, 1, "OXFORD")
        np.testing.assert_allclose(maps["IPF Z"][0], [0, 0, 255], atol=3)

    def test_edax_phase_zero_stays_indexed_but_valid_and_confidence_masks_are_black(self):
        path = self.edax(np.tile(np.eye(3), (4, 1, 1)), valid=[1, 0, 1, 1], ci=[1, 1, -1, 1])
        maps = load_ipf_maps(path, "/Map/EBSD", 4, 1, "EDAX")
        for colours in maps.values():
            self.assertTrue(np.any(colours[0]))
            np.testing.assert_array_equal(colours[[1, 2]], 0)
            self.assertTrue(np.any(colours[3]))

    def test_edax_zero_orientation_matrix_is_black_even_with_valid_confidence(self):
        path = self.edax([np.eye(3), np.zeros((3, 3))], valid=[1, 1], ci=[1, 1])
        maps = load_ipf_maps(path, "/Map/EBSD", 2, 1, "EDAX")
        for colours in maps.values():
            self.assertTrue(np.any(colours[0]))
            np.testing.assert_array_equal(colours[1], 0)

    def test_raw_reconstruction_matches_public_vendor_corrections_in_all_directions(self):
        euler = np.deg2rad([[17.0, 42.0, 93.0], [133.0, 26.0, 215.0]])
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                if vendor == "EDAX":
                    matrices = rotation.byEuler(euler[:, 0], euler[:, 1], euler[:, 2]).matrix()
                    path, dataset = self.edax(matrices, groups=[62]), "/Map/EBSD"
                else:
                    path, dataset = self.oxford(euler, groups=[194]), "/1/EBSD"
                    with h5py.File(path, "r+") as handle:
                        handle["1/EBSD/Header/Scanning Rotation Angle"][...] = [np.deg2rad(31.0)]
                imported = loadEBSD(path, dataSet=dataset, grid=False, verbose=False)
                self.assertGreater(float(imported.meta["h5"]["correction"].angle()), 0.01)
                maps = load_ipf_maps(path, dataset, 2, 1, vendor)
                for field, direction in zip(IPF_FIELDS, (xvector, yvector, zvector)):
                    expected = np.rint(ipfColors(imported, ipfDirection=direction, unindexed=(0, 0, 0), exact=True) * 255).astype(np.uint8)
                    np.testing.assert_array_equal(maps[field], expected)

    def test_nonfinite_orientations_are_black(self):
        for vendor in ("OXFORD", "EDAX"):
            with self.subTest(vendor=vendor):
                if vendor == "OXFORD":
                    path, dataset = self.oxford([[0, 0, 0], [np.nan, 0, 0]]), "/1/EBSD"
                else:
                    matrices = np.tile(np.eye(3), (2, 1, 1))
                    matrices[1, 0, 0] = np.nan
                    path, dataset = self.edax(matrices), "/Map/EBSD"
                maps = load_ipf_maps(path, dataset, 2, 1, vendor)
                for colours in maps.values():
                    self.assertTrue(np.any(colours[0]))
                    np.testing.assert_array_equal(colours[1], 0)

    def test_unsupported_or_missing_symmetry_does_not_silently_become_triclinic(self):
        for vendor in ("OXFORD", "EDAX"):
            with self.subTest(vendor=vendor):
                path = self.oxford([[0, 0, 0]], groups=[999]) if vendor == "OXFORD" else self.edax([np.eye(3)])
                dataset = "/1/EBSD" if vendor == "OXFORD" else "/Map/EBSD"
                if vendor == "EDAX":
                    with h5py.File(path, "r+") as handle:
                        del handle["Map/EBSD/ANG/HEADER/Phase/1/Symmetry"]
                with self.assertRaisesRegex(ValueError, "symmetry|space group|Symmetry"):
                    load_ipf_maps(path, dataset, 1, 1, vendor)

    def test_indexed_phase_with_missing_lattice_metadata_is_an_error(self):
        path = self.oxford([[0, 0, 0]])
        with h5py.File(path, "r+") as handle:
            del handle["1/EBSD/Header/Phases/1/Lattice Dimensions"]
        with self.assertRaisesRegex(ValueError, "phase|lattice"):
            load_ipf_maps(path, "/1/EBSD", 1, 1, "OXFORD")

    def test_nonzero_oxford_specimen_orientation_has_specific_error(self):
        path = self.oxford([[0, 0, 0]])
        with h5py.File(path, "r+") as handle:
            handle["1/EBSD/Header/Specimen Orientation Euler"][...] = [[0, 0.1, 0]]
        with self.assertRaisesRegex(ValueError, "Specimen Orientation Euler"):
            load_ipf_maps(path, "/1/EBSD", 1, 1, "OXFORD")

    def test_mismatched_grid_is_rejected_without_resizing(self):
        with self.assertRaisesRegex(ValueError, "count"):
            load_ipf_maps(self.oxford(np.zeros((2, 3))), "/1/EBSD", 3, 1, "OXFORD")

    def test_different_imported_dataset_is_rejected(self):
        path = self.oxford(np.zeros((2, 3)))
        ebsd = loadEBSD(path, dataSet="/1/EBSD", grid=False, verbose=False)
        ebsd.meta["dataSet"] = "/1/Data Processing"
        with mock.patch("mtex.loadEBSD", return_value=ebsd):
            with self.assertRaisesRegex(ValueError, "different scan"):
                load_ipf_maps(path, "/1/EBSD", 2, 1, "OXFORD")

    def test_retained_rows_are_restored_in_original_order_with_missing_rows_black(self):
        path = self.oxford(np.zeros((3, 3)))
        ebsd = loadEBSD(path, dataSet="/1/EBSD", grid=False, verbose=False)[[0, 2]]
        ebsd.meta["h5"]["rows"] = np.array([0, 2])
        ebsd.meta["h5"]["fileLength"] = 3
        with mock.patch("mtex.loadEBSD", return_value=ebsd):
            maps = load_ipf_maps(path, "/1/EBSD", 3, 1, "OXFORD")
        for colours in maps.values():
            self.assertTrue(np.any(colours[0]))
            np.testing.assert_array_equal(colours[1], 0)
            np.testing.assert_array_equal(colours[0], colours[2])


if __name__ == "__main__":
    unittest.main()
