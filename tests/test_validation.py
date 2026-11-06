"""Validation tests."""

import unittest

from mira.exceptions import ValidationError
from mira.utils.validation import validate_manifest, validate_mirrors_file, validate_countries_config


class TestValidation(unittest.TestCase):
    def test_manifest_ok(self):
        data = {
            "schema_version": 1,
            "database_version": "1.0.0",
            "countries": ["ir", "us"],
            "providers": ["pypi"],
        }
        out = validate_manifest(data)
        self.assertEqual(out["database_version"], "1.0.0")

    def test_manifest_bad_schema(self):
        with self.assertRaises(ValidationError):
            validate_manifest({"schema_version": 99, "database_version": "1", "countries": [], "providers": []})

    def test_mirrors_ok(self):
        data = {
            "schema_version": 1,
            "country": "ir",
            "provider": "pypi",
            "mirrors": [
                {"id": "m1", "name": "M1", "url": "https://example.com/simple/", "enabled": True, "priority": 10}
            ],
        }
        out = validate_mirrors_file(data, expected_country="ir", expected_provider="pypi")
        self.assertEqual(len(out["mirrors"]), 1)

    def test_mirrors_http_rejected(self):
        data = {
            "schema_version": 1,
            "country": "ir",
            "provider": "pypi",
            "mirrors": [{"id": "m1", "url": "http://insecure.example/"}],
        }
        with self.assertRaises(ValidationError):
            validate_mirrors_file(data)

    def test_countries(self):
        self.assertEqual(validate_countries_config("*"), ["*"])
        self.assertEqual(validate_countries_config("ir,de"), ["ir", "de"])
        with self.assertRaises(ValidationError):
            validate_countries_config("iran")


if __name__ == "__main__":
    unittest.main()