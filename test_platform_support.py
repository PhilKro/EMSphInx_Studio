import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

# The platform helpers live in utils.py alongside a Tk widget. Allow their unit tests
# to run with Python installations that do not include the optional Tk binding.
try:
    import tkinter  # noqa: F401
except ModuleNotFoundError:
    tkinter_stub = types.ModuleType("tkinter")
    ttk_stub = types.ModuleType("tkinter.ttk")
    ttk_stub.Frame = object
    tkinter_stub.ttk = ttk_stub
    sys.modules["tkinter"] = tkinter_stub
    sys.modules["tkinter.ttk"] = ttk_stub

import utils


class ImageSizingTests(unittest.TestCase):
    def test_rectangular_image_fits_without_changing_aspect_ratio(self):
        self.assertEqual(utils.fit_dimensions(640, 480, 400, 400), (400, 300))
        self.assertEqual(utils.fit_dimensions(480, 640, 400, 400), (300, 400))

    def test_image_is_limited_by_both_canvas_dimensions(self):
        self.assertEqual(utils.fit_dimensions(640, 480, 300, 500), (300, 225))

    def test_fitted_image_is_centered_in_unused_canvas_space(self):
        self.assertEqual(
            utils.centered_fit_geometry(200, 100, 500, 500),
            (500, 250, 0, 125),
        )

    def test_canvas_selection_accounts_for_centering_offsets(self):
        geometry = (115, 55, 100, 50, 10, 10, 2, 1)
        self.assertEqual(utils.canvas_to_grid_point(*geometry), (1, 0))
        self.assertIsNone(
            utils.canvas_to_grid_point(50, 50, 100, 50, 10, 10, 2, 1)
        )

    def test_roi_points_are_clamped_to_displayed_map(self):
        self.assertEqual(
            utils.clamp_canvas_point(50, 400, 100, 125, 500, 250),
            (100, 375),
        )

    def test_canvas_roi_accounts_for_offsets_and_reverse_dragging(self):
        forward = utils.canvas_roi_to_grid(
            115, 65, 145, 85, 100, 50, 10, 10, 20, 10
        )
        reverse = utils.canvas_roi_to_grid(
            145, 85, 115, 65, 100, 50, 10, 10, 20, 10
        )
        self.assertEqual(forward, (1, 1, 3, 2))
        self.assertEqual(reverse, forward)


class NativeExecutionTests(unittest.TestCase):
    def test_native_paths_are_absolute_and_unchanged(self):
        with mock.patch("utils.uses_wsl", return_value=False):
            result = utils.to_execution_path("data/job.nml", {})
            self.assertEqual(result, os.path.abspath("data/job.nml"))
            self.assertEqual(utils.to_host_path(result, {}), result)

    def test_native_command_and_validation(self):
        with tempfile.TemporaryDirectory() as executable_dir:
            executable = os.path.join(executable_dir, "IndexEBSD")
            with open(executable, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(executable, 0o755)
            config = {"native_executable_dir": executable_dir}

            with mock.patch("utils.uses_wsl", return_value=False):
                self.assertIsNone(utils.validate_execution_config(config))
                command = utils.build_native_index_command(config, "job.nml")

            self.assertEqual(command[0], executable)
            self.assertEqual(command[1], os.path.abspath("job.nml"))
            completed = subprocess.run(command, cwd=executable_dir, capture_output=True)
            self.assertEqual(completed.returncode, 0)

    def test_missing_native_executable_is_reported(self):
        with tempfile.TemporaryDirectory() as executable_dir:
            with mock.patch("utils.uses_wsl", return_value=False):
                error = utils.validate_execution_config(
                    {"native_executable_dir": executable_dir}
                )
        self.assertIn("IndexEBSD was not found", error)

    def test_nml_paths_escape_apostrophes(self):
        path = "/Users/O'Neil/Data/job.nml"
        literal = utils.nml_string(path)
        self.assertEqual(literal, "'/Users/O''Neil/Data/job.nml'")
        self.assertEqual(utils.parse_nml_string(literal[1:-1]), path)


class WslCompatibilityTests(unittest.TestCase):
    def test_existing_drive_mapping_is_preserved(self):
        with mock.patch("utils.os.path.splitdrive", return_value=("C:", r"\Data Set\job.nml")):
            result = utils.to_wsl_path(
                r"C:\Data Set\job.nml", {"C:": "/mnt/c"}
            )
        self.assertEqual(result, "/mnt/c/Data Set/job.nml")

    def test_existing_unc_mapping_is_preserved(self):
        result = utils.to_wsl_path(
            r"\\server\share\Data\job.nml",
            {},
            {"/mnt/n": r"\\server\share"},
        )
        self.assertEqual(result, "/mnt/n/Data/job.nml")

    def test_wsl_configuration_keys_are_still_accepted(self):
        config = {
            "wsl_distro": "Debian",
            "wsl_executable_dir": "/opt/EMSphInx",
        }
        with mock.patch("utils.uses_wsl", return_value=True):
            self.assertIsNone(utils.validate_execution_config(config))


if __name__ == "__main__":
    unittest.main()
