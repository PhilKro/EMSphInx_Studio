import os
import tempfile
import unittest

from oxford_filenames import next_nml_name, output_name_parts


class OxfordFilenameTests(unittest.TestCase):
    def test_new_names_omit_map_label(self):
        names = output_name_parts(
            "/data/Cu_Al_NSs Cu Ref AD Site 1 Map Data 1.h5oina",
            "Map_Data_1",
            123,
        )
        self.assertEqual(names[0], "Cu_Al_NSs Cu Ref AD Site 1 Map Data 1.up1")
        self.assertEqual(names[2], "Cu_Al_NSs Cu Ref AD Site 1 Map Data 1_BW123")
        self.assertEqual(names[1], "Cu_Al_NSs Cu Ref AD Site 1 Map Data 1_Map_Data_1.up1")

    def test_legacy_nml_names_are_included_when_incrementing(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = os.path.join(directory, "sample_Map_Data_1_BW123_3.nml")
            with open(legacy, "w"):
                pass
            result = next_nml_name(
                directory, "sample_BW123", "sample_Map_Data_1_BW123"
            )
        self.assertEqual(result, "sample_BW123_4.nml")

    def test_first_nml_uses_clean_unsuffixed_name(self):
        with tempfile.TemporaryDirectory() as directory:
            result = next_nml_name(
                directory, "sample_BW123", "sample_Map_Data_1_BW123"
            )
        self.assertEqual(result, "sample_BW123.nml")


if __name__ == "__main__":
    unittest.main()
