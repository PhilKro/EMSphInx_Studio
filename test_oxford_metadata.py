import unittest

from oxford_metadata import (
    beam_voltage_lookup_labels,
    format_beam_voltage_kv,
    format_step_size_um,
    normalize_beam_voltage_kv,
    normalize_step_size_um,
)


class OxfordMetadataTests(unittest.TestCase):
    def test_step_size_removes_binary_float_noise(self):
        self.assertEqual(normalize_step_size_um(0.050000000134), 0.05)
        self.assertEqual(format_step_size_um(0.050000000134), "0.0500")

    def test_step_size_rounds_to_four_decimal_places(self):
        self.assertEqual(normalize_step_size_um(0.05006), 0.0501)
        self.assertEqual(format_step_size_um(0.05006), "0.0501")

    def test_beam_voltage_rounds_to_one_decimal_place(self):
        self.assertEqual(format_beam_voltage_kv(29.99934255), "30.0")
        self.assertEqual(normalize_beam_voltage_kv(29.94), 29.9)
        self.assertEqual(format_beam_voltage_kv(20.000001), "20.0")

    def test_whole_voltage_keeps_legacy_sht_lookup_label(self):
        self.assertEqual(beam_voltage_lookup_labels(29.99934255), ("30.0", "30"))


if __name__ == "__main__":
    unittest.main()
