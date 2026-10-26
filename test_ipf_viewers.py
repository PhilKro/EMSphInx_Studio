from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import h5py
import numpy as np

import utils
from ipf_maps import IPFMapCache
from tab_viewer_edax import TabViewerEdax
from tab_viewer_oxford import TabViewerOxford
from test_detector_tilt_workflow import Value


class EventLoop:
    def __init__(self):
        self.pending = []

    def after(self, delay, callback, *args):
        self.pending.append((callback, args))

    def flush(self):
        while self.pending:
            callback, args = self.pending.pop(0)
            callback(*args)


class IPFViewerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.jobs = []
        self.source_count = 0
        self.loop = EventLoop()
        self.errors = self.patch("tkinter.messagebox.showerror")
        self.patch("ipf_maps.threading.Thread", side_effect=self.make_thread)
        self.flat = np.array(
            [[255, 0, 0], [0, 255, 0], [0, 0, 255], [200, 100, 0], [0, 100, 200], [100, 0, 200]],
            dtype=np.uint8,
        )
        self.maps = {
            "IPF X": self.flat,
            "IPF Y": np.roll(self.flat, 1, axis=0),
            "IPF Z": np.roll(self.flat, 2, axis=0),
        }

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def make_thread(self, *args, **kwargs):
        target = kwargs.get("target", args[0] if args else None)
        job = mock.Mock()
        job.start.side_effect = lambda: self.jobs.append(lambda: target(*kwargs.get("args", ())))
        return job

    def finish_jobs(self):
        while self.jobs:
            self.jobs.pop(0)()
        self.loop.flush()

    def make_source(self, vendor, indexed=True):
        self.source_count += 1
        path = self.directory / (vendor + str(self.source_count) + (".edaxh5" if vendor == "EDAX" else ".h5oina"))
        with h5py.File(path, "w") as handle:
            for scan_name in ("Scan0", "Scan1"):
                scan = handle.create_group(scan_name)
                if vendor == "EDAX":
                    scan["Sample/Number Of Columns"] = [3]
                    scan["Sample/Number Of Rows"] = [2]
                    scan["Sample/Step X"] = [0.1]
                    for key in ("X-Star", "Y-Star", "Z-Star"):
                        scan[f"EBSD/ANG/HEADER/Pattern Center Calibration/{key}"] = [0.5]
                    fields = [("IQ", "f4"), ("Phase", "i4")]
                    if indexed:
                        fields += [("Orientations", "f8", (9,)), ("Valid", "i4")]
                    data = np.zeros(6, dtype=fields)
                    data["IQ"] = np.arange(6) * 20
                    if indexed:
                        data["Orientations"] = np.eye(3).reshape(9)
                        data["Valid"] = 1
                        scan["EBSD/ANG/HEADER/Phase/1/Symmetry"] = [43]
                    scan["EBSD/ANG/DATA/DATA"] = data
                else:
                    header = scan.create_group("EBSD/Header")
                    for name, value in (("X Cells", 3), ("Y Cells", 2), ("X Step", 0.1), ("Beam Voltage", 20.0)):
                        header[name] = [value]
                    data = scan.create_group("EBSD/Data")
                    for name in ("Pattern Center X", "Pattern Center Y", "Detector Distance"):
                        data[name] = np.full(6, 0.5)
                    data["Band Contrast"] = np.arange(6) * 20
                    data["Processed Patterns"] = np.zeros((6, 4, 4), dtype=np.uint8)
                    if indexed:
                        data["Euler"] = np.zeros((6, 3))
                        data["Phase"] = np.ones(6, dtype=np.uint8)
                        header["Phases/1/Space Group"] = [225]
        return path

    def viewer(self, vendor, indexed=True):
        path = self.make_source(vendor, indexed)
        state = utils.SharedState()
        state.h5_path = str(path)
        state.scan_name = "Scan0" + ("/EBSD" if vendor == "OXFORD" else "")
        state.nx, state.ny = 3, 2
        app = SimpleNamespace(root=self.loop, shared_state=state, tab_nml_edax=mock.Mock(), tab_nml_oxford=mock.Mock())
        viewer = SimpleNamespace(
            app=app,
            state=state,
            ipf_cache=IPFMapCache(self.loop),
            var_map_field=Value("IPF X"),
            var_map_row_major=Value(True),
            var_nx=Value(),
            var_ny=Value(),
            combo_scan=Value(),
            combo_map_field=Value(),
            combo_pat_type=Value(),
            var_pat_type=Value("Processed Patterns"),
            lbl_pat_dims=mock.Mock(),
            init_viewer=mock.Mock(),
            update_pattern_image=mock.Mock(),
            draw_roi_from_state=mock.Mock(),
            map_canvas=mock.Mock(),
            mmap=None,
            map_data_2d=None,
            current_map_image=None,
            tk_img_map=None,
            map_canvas_img_item=None,
            scans_cache={},
            h5_file=None,
        )
        viewer.draw_map_image = lambda image: setattr(viewer, "current_map_image", image.copy())
        cls = TabViewerEdax if vendor == "EDAX" else TabViewerOxford
        viewer._ipf_key = lambda: cls._ipf_key(viewer)
        viewer._clear_map_image = lambda: cls._clear_map_image(viewer)
        viewer._ipf_ready = lambda *args: cls._ipf_ready(viewer, *args)
        viewer.recalc_map = lambda: cls.recalc_map(viewer)
        viewer.on_scan_select = lambda event: cls.on_scan_select(viewer, event)
        if vendor == "OXFORD":
            viewer.h5_file = h5py.File(path, "r")
            self.addCleanup(lambda: viewer.h5_file.close() if viewer.h5_file else None)
        loader = self.patch(
            ("tab_viewer_edax" if vendor == "EDAX" else "tab_viewer_oxford") + ".load_ipf_maps",
            return_value=self.maps,
        )
        return viewer, loader, cls

    def test_ipf_directions_use_rgb_and_cache_without_recomputing(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer, loader, _ = self.viewer(vendor)
                viewer.recalc_map()
                self.assertEqual(len(self.jobs), 1)
                self.finish_jobs()
                self.assertEqual(viewer.current_map_image.mode, "RGB")
                np.testing.assert_array_equal(viewer.map_data_2d, self.flat.reshape(2, 3, 3))
                viewer.var_map_field.set("IPF Y")
                viewer.recalc_map()
                np.testing.assert_array_equal(viewer.map_data_2d, self.maps["IPF Y"].reshape(2, 3, 3))
                viewer.var_map_field.set("IPF Z")
                viewer.recalc_map()
                np.testing.assert_array_equal(viewer.map_data_2d, self.maps["IPF Z"].reshape(2, 3, 3))
                self.assertEqual(loader.call_count, 1)
        self.errors.assert_not_called()

    def test_rgb_grid_order_matches_pattern_indices(self):
        for vendor in ("EDAX", "OXFORD"):
            viewer, _, cls = self.viewer(vendor)
            viewer.recalc_map()
            self.finish_jobs()
            for row_major in (True, False):
                with self.subTest(vendor=vendor, row_major=row_major):
                    viewer.var_map_row_major.set(row_major)
                    viewer.recalc_map()
                    for y in range(2):
                        for x in range(3):
                            index = cls.get_1d_index(viewer, x, y)
                            np.testing.assert_array_equal(viewer.map_data_2d[y, x], self.flat[index])

    def test_late_ipf_result_cannot_replace_selected_scalar_map(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer, _, _ = self.viewer(vendor)
                viewer.recalc_map()
                viewer.var_map_field.set("IQ" if vendor == "EDAX" else "Band Contrast")
                viewer.recalc_map()
                expected = viewer.map_data_2d.copy()
                self.assertEqual(viewer.current_map_image.mode, "L")
                self.finish_jobs()
                self.assertEqual(viewer.current_map_image.mode, "L")
                np.testing.assert_array_equal(viewer.map_data_2d, expected)
        self.errors.assert_not_called()

    def test_map_options_only_offer_ipf_when_orientation_data_exists(self):
        for vendor in ("EDAX", "OXFORD"):
            for indexed in (True, False):
                with self.subTest(vendor=vendor, indexed=indexed):
                    viewer, _, cls = self.viewer(vendor, indexed)
                    with mock.patch("tkinter.filedialog.askopenfilename", return_value=viewer.state.h5_path):
                        if vendor == "EDAX":
                            cls.load_h5(viewer)
                        else:
                            cls.load_h5oina(viewer)
                    options = viewer.combo_map_field.options["values"]
                    for name in self.maps:
                        self.assertEqual(name in options, indexed)
        self.errors.assert_not_called()

    def test_switching_scans_cannot_paint_the_previous_scan_result(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer, loader, _ = self.viewer(vendor)
                new_maps = {name: np.roll(colors, 3, axis=0) for name, colors in self.maps.items()}
                loader.side_effect = [self.maps, new_maps]
                rendered = []
                viewer.draw_map_image = lambda image: rendered.append(np.asarray(image).copy())
                viewer.recalc_map()
                viewer.state.scan_name = "Scan1" + ("/EBSD" if vendor == "OXFORD" else "")
                viewer.recalc_map()
                self.assertEqual(len(self.jobs), 2)
                self.finish_jobs()
                self.assertEqual(len(rendered), 1)
                np.testing.assert_array_equal(rendered[0], new_maps["IPF X"].reshape(2, 3, 3))
        self.errors.assert_not_called()

    def test_reloading_same_file_discards_inflight_results_and_cached_colours(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer, loader, cls = self.viewer(vendor)
                new_maps = {name: np.roll(colors, 4, axis=0) for name, colors in self.maps.items()}
                loader.side_effect = [self.maps, new_maps]
                viewer.recalc_map()
                with mock.patch("tkinter.filedialog.askopenfilename", return_value=viewer.state.h5_path):
                    if vendor == "EDAX":
                        cls.load_h5(viewer)
                    else:
                        cls.load_h5oina(viewer)
                viewer.var_map_field.set("IPF X")
                viewer.recalc_map()
                self.finish_jobs()
                np.testing.assert_array_equal(viewer.map_data_2d, new_maps["IPF X"].reshape(2, 3, 3))
                self.assertEqual(loader.call_count, 2)
        self.errors.assert_not_called()

    def test_late_ipf_error_does_not_interrupt_scalar_view(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer, loader, _ = self.viewer(vendor)
                loader.side_effect = ValueError("Unsupported phase metadata")
                viewer.recalc_map()
                viewer.var_map_field.set("IQ" if vendor == "EDAX" else "Band Contrast")
                viewer.recalc_map()
                expected = viewer.map_data_2d.copy()
                self.finish_jobs()
                np.testing.assert_array_equal(viewer.map_data_2d, expected)
        self.errors.assert_not_called()

    def test_scalar_column_order_also_agrees_with_pattern_indices(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer, _, cls = self.viewer(vendor)
                viewer.var_map_field.set("IQ" if vendor == "EDAX" else "Band Contrast")
                viewer.var_map_row_major.set(False)
                viewer.recalc_map()
                for y in range(2):
                    for x in range(3):
                        self.assertEqual(viewer.map_data_2d[y, x], cls.get_1d_index(viewer, x, y) * 20)
        self.errors.assert_not_called()


if __name__ == "__main__":
    unittest.main()
