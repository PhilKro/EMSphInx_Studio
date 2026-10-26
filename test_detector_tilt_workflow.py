import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import h5py
import numpy as np

import utils
from tab_nml_edax import TabNMLBuilderEdax
from tab_nml_oxford import TabNMLOxford
from tab_viewer_edax import TabViewerEdax
from tab_viewer_oxford import TabViewerOxford


class Value:
    """Small widget substitute so the real workflow can run without a display."""

    def __init__(self, value=""):
        self.value = value
        self.options = {}

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def __setitem__(self, key, value):
        self.options[key] = value

    def current(self, index):
        self.value = self.options["values"][index]


class DetectorTiltWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = utils.SharedState()
        self.app = SimpleNamespace(
            shared_state=self.state,
            config={},
            params={},
            tab_queue=mock.Mock(),
            tab_nml_edax=mock.Mock(),
            tab_nml_oxford=mock.Mock(),
            notebook=mock.Mock(),
        )
        self.master = self.root / "master.sht"
        self.master.touch()
        self.patch("utils.save_json")
        self.patch("utils.uses_wsl", return_value=False)
        self.patch("utils.get_available_memory", return_value=16 * 1024**3)
        self.patch("tab_nml_oxford.threading.Thread")
        self.errors = self.patch("tkinter.messagebox.showerror")

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def write_h5(self, vendor, angles, name="input"):
        suffix = ".edaxh5" if vendor == "EDAX" else ".h5oina"
        path = self.root / (name + suffix)
        with h5py.File(path, "w") as handle:
            for index, angle in enumerate(angles):
                scan = handle.create_group(f"Scan{index}")
                if vendor == "EDAX":
                    scan["Sample/Number Of Columns"] = [1]
                    scan["Sample/Number Of Rows"] = [1]
                    scan["Sample/Step X"] = [0.1]
                    scan["Electron Beam/SEMkV"] = [20.0]
                    for key in ("X-Star", "Y-Star", "Z-Star"):
                        scan[f"EBSD/ANG/HEADER/Pattern Center Calibration/{key}"] = [0.5]
                    if angle is not None:
                        scan["Camera/Elevation Angle"] = [angle]
                else:
                    header = scan.create_group("EBSD/Header")
                    header["X Cells"] = [1]
                    header["Y Cells"] = [1]
                    header["X Step"] = [0.1]
                    header["Beam Voltage"] = [20.0]
                    # A sample tilt must never be mistaken for camera elevation.
                    header["Tilt Angle"] = [math.radians(70)]
                    if angle is not None:
                        header["Detector Orientation Euler"] = [
                            0.0, math.radians(90 + angle), 0.0
                        ]
                    data = scan.create_group("EBSD/Data")
                    for key in ("Pattern Center X", "Pattern Center Y", "Detector Distance"):
                        data[key] = [0.5]
                    data["Processed Patterns"] = np.zeros((1, 4, 4), dtype=np.uint8)
        return path

    def viewer(self, vendor):
        viewer = SimpleNamespace(
            state=self.state,
            app=self.app,
            scans_cache={},
            combo_scan=Value(),
            var_nx=Value(),
            var_ny=Value(),
            combo_map_field=Value(),
            var_map_field=Value(),
            init_viewer=mock.Mock(),
            recalc_map=mock.Mock(),
            _clear_map_image=mock.Mock(),
            ipf_cache=mock.Mock(),
        )
        if vendor == "EDAX":
            viewer.lbl_up1_file = mock.Mock()
            viewer.lbl_pat_dims = mock.Mock()
            viewer.on_scan_select = lambda event: TabViewerEdax.on_scan_select(viewer, event)
        else:
            viewer.h5_file = None
            viewer.combo_pat_type = Value()
            viewer.var_pat_type = Value("Processed Patterns")
            viewer.lbl_pat_dims = mock.Mock()
            viewer.on_scan_select = lambda event: TabViewerOxford.on_scan_select(viewer, event)
            self.app.tab_viewer_oxford = viewer
            self.addCleanup(lambda: viewer.h5_file.close() if viewer.h5_file else None)
        return viewer

    def load(self, vendor, viewer, path):
        with mock.patch("tkinter.filedialog.askopenfilename", return_value=str(path)):
            if vendor == "EDAX":
                TabViewerEdax.load_h5(viewer)
                self.state.pat_w = self.state.pat_h = 4
                self.state.up1_path = str(self.root / "patterns.up1")
            else:
                TabViewerOxford.load_h5oina(viewer)

    def builder(self, vendor, name, binning=1):
        builder = SimpleNamespace(
            state=self.state,
            app=self.app,
            sht_listbox=mock.Mock(),
            var_nml_name=Value(name + ".nml"),
            var_bw=Value("123"),
            var_delta=Value("20"),
            var_detector_tilt=Value(),
            var_work_dir=Value(),
            var_kv=Value(),
            var_gausbckg=Value(False),
            var_nregions=Value("0"),
            var_nthread=Value("0"),
            var_batchsize=Value("0"),
            var_refine=Value(True),
            var_normed=Value(False),
            var_use_roi=Value(False),
            var_circmask=Value("-1 (Disabled)"),
            var_binning=Value(str(binning)),
            var_up1_name=Value(name + ".up1"),
            lbl_progress=mock.Mock(),
            lbl_binning=mock.Mock(),
            lbl_roi_max=mock.Mock(),
            _worker_generate_up1=mock.Mock(),
        )
        builder.sht_listbox.get.return_value = (str(self.master),)
        cls = TabNMLBuilderEdax if vendor == "EDAX" else TabNMLOxford
        builder.reset_detector_tilt = lambda: cls.reset_detector_tilt(builder)
        builder.update_h5_data = lambda **kwargs: cls.update_h5_data(builder, **kwargs)
        if vendor == "OXFORD":
            builder._update_binning_display = lambda **kwargs: TabNMLOxford._update_binning_display(builder, **kwargs)
            builder._update_output_names = lambda *args: TabNMLOxford._update_output_names(builder, *args)
        builder.reset_detector_tilt()
        return builder

    def generate(self, vendor, name, binning=1, tilt_text=None):
        builder = self.builder(vendor, name, binning)
        if tilt_text is not None:
            builder.var_detector_tilt.set(tilt_text)
        self.generate_builder(vendor, builder)
        return self.root / (name + ".nml")

    def generate_builder(self, vendor, builder):
        if vendor == "EDAX":
            TabNMLBuilderEdax.generate_and_queue(builder)
        else:
            TabNMLOxford.generate_and_queue(builder)

    def test_each_vendor_scan_angle_reaches_nml_and_missing_scan_resets_it(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0, -5.0, 0.0, None], vendor))
                for index, expected in enumerate((8.0, -5.0, 0.0, None)):
                    viewer.combo_scan.set(f"Scan{index}" + ("/EBSD" if vendor == "OXFORD" else ""))
                    viewer.on_scan_select(None)
                    if expected is None:
                        self.assertIsNone(self.state.detector_tilt)
                    else:
                        self.assertAlmostEqual(self.state.detector_tilt, expected)
                    path = self.generate(vendor, f"{vendor}_{index}", binning=2)
                    self.assertTrue(path.exists())
                    tilt_line = next(line for line in path.read_text().splitlines() if "thetac" in line)
                    actual = float(tilt_line.split("=")[1].strip().rstrip(","))
                    self.assertAlmostEqual(actual, expected or 0.0)
                self.errors.assert_not_called()

    def test_edax_matching_ang_fallback_and_explicit_h5_zero_precedence(self):
        viewer = self.viewer("EDAX")
        self.load("EDAX", viewer, self.write_h5("EDAX", [None, 0.0]))
        (self.root / "patterns.ang").write_text(
            "# SampleTiltAngle 70\n# CameraElevationAngle -7.5\n0 0 0\n"
        )
        fallback = self.generate("EDAX", "fallback").read_text()
        self.assertIn("thetac", fallback)
        self.assertIn("-7.5", fallback)
        viewer.combo_scan.set("Scan1")
        viewer.on_scan_select(None)
        # An unused sidecar must not invalidate known H5 metadata.
        (self.root / "patterns.ang").write_text("# CameraElevationAngle nan\n")
        h5_zero = self.generate("EDAX", "h5_zero").read_text()
        tilt_line = next(line for line in h5_zero.splitlines() if "thetac" in line)
        self.assertEqual(float(tilt_line.split("=")[1].strip().rstrip(",")), 0.0)
        self.errors.assert_not_called()

    def test_missing_angle_in_new_file_does_not_keep_previous_angle(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0], vendor + "_first"))
                self.assertAlmostEqual(self.state.detector_tilt, 8.0)
                self.load(vendor, viewer, self.write_h5(vendor, [None], vendor + "_second"))
                self.assertIsNone(self.state.detector_tilt)
        self.errors.assert_not_called()

    def test_invalid_present_metadata_blocks_reusing_previous_selection(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0], vendor + "_valid"))
                self.load(vendor, viewer, self.write_h5(vendor, [float("nan")], vendor + "_invalid"))
                self.assertEqual(self.state.scan_name, "")
                self.app.tab_queue.reset_mock()
                path = self.generate(vendor, vendor + "_invalid_output")
                self.assertFalse(path.exists())
                self.app.tab_queue.add_job.assert_not_called()
                self.assertTrue(self.errors.called)

    def test_oxford_calibrated_outer_rotations_keep_elevation_and_record_limitation(self):
        euler = (0.001705034519545734, 1.5550974607467651, 6.281116008758545)
        path = self.write_h5("OXFORD", [0.0, None])
        with h5py.File(path, "r+") as handle:
            handle["Scan0/EBSD/Header/Detector Orientation Euler"][...] = euler
        viewer = self.viewer("OXFORD")
        self.load("OXFORD", viewer, path)
        self.assertAlmostEqual(self.state.detector_tilt, math.degrees(euler[1]) - 90)
        self.assertEqual(self.state.detector_euler, euler)
        output = self.generate("OXFORD", "calibrated").read_text()
        tilt_line = next(line for line in output.splitlines() if line.lstrip().startswith("thetac"))
        actual = float(tilt_line.split("=")[1].strip().rstrip(","))
        self.assertAlmostEqual(actual, -0.89948, places=4)
        self.assertIn("detector azimuth/twist not applied", output)
        self.app.tab_queue.append_console.assert_called_once()
        self.assertIn("detector azimuth/twist not applied", self.app.tab_queue.append_console.call_args.args[0])

        viewer.combo_scan.set("Scan1/EBSD")
        viewer.on_scan_select(None)
        self.assertIsNone(self.state.detector_euler)
        self.app.tab_queue.append_console.reset_mock()
        plain = self.generate("OXFORD", "missing_angle").read_text()
        self.assertNotIn("detector azimuth/twist not applied", plain)
        self.app.tab_queue.append_console.assert_not_called()
        self.errors.assert_not_called()

    def test_imported_tilt_is_displayed_and_manual_edits_reach_nml(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0], vendor + "_editable"))
                builder = self.builder(vendor, vendor + "_manual")
                self.assertAlmostEqual(float(builder.var_detector_tilt.get()), 8.0)
                builder.var_detector_tilt.set("-3.75")
                self.generate_builder(vendor, builder)
                output = (self.root / (vendor + "_manual.nml")).read_text()
                tilt_line = next(line for line in output.splitlines() if line.lstrip().startswith("thetac"))
                self.assertEqual(float(tilt_line.split("=")[1].strip().rstrip(",")), -3.75)
                self.assertAlmostEqual(self.state.detector_tilt, 8.0)
                self.assertNotIn("detector_tilt", self.app.params[vendor])
        self.errors.assert_not_called()

    def test_explicit_manual_zero_replaces_imported_nonzero(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0], vendor + "_zero"))
                output = self.generate(vendor, vendor + "_zero_edit", tilt_text="0").read_text()
                tilt_line = next(line for line in output.splitlines() if line.lstrip().startswith("thetac"))
                self.assertEqual(float(tilt_line.split("=")[1].strip().rstrip(",")), 0.0)
        self.errors.assert_not_called()

    def test_manual_tilt_survives_refresh_and_resets_on_scan_selection(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0, -5.0, None], vendor + "_refresh"))
                builder = self.builder(vendor, vendor + "_refresh")
                if vendor == "EDAX":
                    self.app.tab_nml_edax = builder
                else:
                    self.app.tab_nml_oxford = builder
                builder.var_detector_tilt.set("4.25")
                builder.update_h5_data()
                if vendor == "OXFORD":
                    builder.var_binning.set("2")
                    TabNMLOxford.on_binning_change(builder)
                self.assertEqual(builder.var_detector_tilt.get(), "4.25")
                viewer.combo_scan.set("Scan1" + ("/EBSD" if vendor == "OXFORD" else ""))
                viewer.on_scan_select(None)
                self.assertAlmostEqual(float(builder.var_detector_tilt.get()), -5.0)
                viewer.combo_scan.set("Scan2" + ("/EBSD" if vendor == "OXFORD" else ""))
                viewer.on_scan_select(None)
                self.assertEqual(float(builder.var_detector_tilt.get()), 0.0)
        self.errors.assert_not_called()

    def test_edited_invalid_tilt_blocks_nml_and_queue(self):
        for vendor in ("EDAX", "OXFORD"):
            viewer = self.viewer(vendor)
            self.load(vendor, viewer, self.write_h5(vendor, [8.0], vendor + "_bad_edit"))
            for index, text in enumerate(("", "invalid", "nan", "inf", "61", "-61")):
                with self.subTest(vendor=vendor, text=text):
                    self.app.tab_queue.reset_mock()
                    path = self.generate(vendor, vendor + "_bad_edit_" + str(index), tilt_text=text)
                    self.assertFalse(path.exists())
                    self.app.tab_queue.add_job.assert_not_called()
                    self.errors.assert_called_with("Invalid Detector Tilt", mock.ANY)

    def test_edax_ang_prefill_and_user_override_do_not_reread_sidecar(self):
        viewer = self.viewer("EDAX")
        self.load("EDAX", viewer, self.write_h5("EDAX", [None]))
        sidecar = self.root / "patterns.ang"
        sidecar.write_text("# CameraElevationAngle -7.5\n")
        builder = self.builder("EDAX", "manual_ang")
        self.assertEqual(float(builder.var_detector_tilt.get()), -7.5)
        builder.var_detector_tilt.set("2.5")
        sidecar.write_text("# CameraElevationAngle invalid\n")
        self.generate_builder("EDAX", builder)
        output = (self.root / "manual_ang.nml").read_text()
        tilt_line = next(line for line in output.splitlines() if line.lstrip().startswith("thetac"))
        self.assertEqual(float(tilt_line.split("=")[1].strip().rstrip(",")), 2.5)
        self.errors.assert_not_called()

    def test_reset_defaults_restores_loaded_calibration(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0], vendor + "_defaults"))
                builder = self.builder(vendor, vendor + "_defaults")
                builder.var_detector_tilt.set("-4")
                cls = TabNMLBuilderEdax if vendor == "EDAX" else TabNMLOxford
                cls.reset_defaults(builder)
                self.assertAlmostEqual(float(builder.var_detector_tilt.get()), 8.0)
        self.errors.assert_not_called()

    def test_edax_up1_selection_refreshes_angle_once_and_clears_failed_prefill(self):
        viewer = self.viewer("EDAX")
        self.load("EDAX", viewer, self.write_h5("EDAX", [None]))
        builder = self.builder("EDAX", "up1_refresh")
        self.app.tab_nml_edax = builder
        for stem, header in (("first", "-7.5"), ("second", "4.25"), ("broken", "invalid")):
            builder.var_detector_tilt.set("12")
            path = self.root / (stem + ".up1")
            path.write_bytes(struct.pack("<4I", 1, 4, 4, 16) + bytes(16))
            path.with_suffix(".ang").write_text("# CameraElevationAngle " + header + "\n")
            self.errors.reset_mock()
            with mock.patch("tkinter.filedialog.askopenfilename", return_value=str(path)):
                TabViewerEdax.load_up1(viewer)
            if header == "invalid":
                self.assertEqual(builder.var_detector_tilt.get(), "")
                self.errors.assert_called_once_with("Invalid Detector Tilt", mock.ANY)
                self.app.tab_queue.reset_mock()
                self.generate_builder("EDAX", builder)
                self.app.tab_queue.add_job.assert_not_called()
            else:
                self.assertEqual(float(builder.var_detector_tilt.get()), float(header))
                self.errors.assert_not_called()

    def test_failed_file_load_clears_displayed_angle(self):
        for vendor in ("EDAX", "OXFORD"):
            with self.subTest(vendor=vendor):
                viewer = self.viewer(vendor)
                self.load(vendor, viewer, self.write_h5(vendor, [8.0], vendor + "_display_valid"))
                builder = self.builder(vendor, vendor + "_clear_display")
                if vendor == "EDAX":
                    self.app.tab_nml_edax = builder
                else:
                    self.app.tab_nml_oxford = builder
                builder.var_detector_tilt.set("12")
                self.load(vendor, viewer, self.write_h5(vendor, [float("nan")], vendor + "_display_invalid"))
                self.assertEqual(builder.var_detector_tilt.get(), "")


if __name__ == "__main__":
    unittest.main()
