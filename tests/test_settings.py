from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from futures_intel.settings import normalize_product, save_products, validate_products


class SettingsTest(unittest.TestCase):
    def test_auto_product_removes_contract_override(self) -> None:
        product = normalize_product(
            {"code": "sh", "name": "烧碱", "exchange": "czce", "mode": "auto", "contract": "SH2701"}
        )
        self.assertEqual("SH", product["code"])
        self.assertNotIn("contract_override", product)

    def test_fixed_product_requires_matching_contract(self) -> None:
        product = normalize_product(
            {"code": "SH", "name": "烧碱", "exchange": "CZCE", "mode": "fixed", "contract": "SH2701"}
        )
        self.assertEqual("SH2701", product["contract_override"])
        with self.assertRaises(ValueError):
            normalize_product(
                {"code": "SH", "name": "烧碱", "mode": "fixed", "contract": "SH701"}
            )
        with self.assertRaises(ValueError):
            normalize_product(
                {"code": "SH", "name": "烧碱", "mode": "fixed", "contract": "V2701"}
            )

    def test_validate_and_save_products(self) -> None:
        products = validate_products(
            [
                {"code": "SH", "name": "烧碱", "exchange": "CZCE", "mode": "fixed", "contract": "SH2701"},
                {"code": "V", "name": "PVC", "exchange": "DCE", "mode": "auto"},
            ]
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "default.json"
            path.write_text('{"timezone": "Asia/Shanghai"}\n', encoding="utf-8")
            saved = save_products(path, products)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(2, len(saved))
            self.assertEqual("SH2701", payload["products"][0]["contract_override"])
            self.assertNotIn("contract_override", payload["products"][1])


if __name__ == "__main__":
    unittest.main()
