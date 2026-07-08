"""Unit tests for CJ Dropshipping catalog normalization."""

from app.addons.suppliers.cjdropshipping.catalog import normalize_cj_catalog
from schemas.supplier import POD_INVENTORY_PLACEHOLDER


def test_cj_uses_real_inventory():
    items = normalize_cj_catalog(
        [
            {
                "pid": "p1",
                "productName": "Gadget",
                "variants": [{"vid": "v1", "variantName": "Red", "variantStock": 42}],
            }
        ]
    )
    assert items[0].inventory_quantity == 42
    assert items[0].inventory_quantity != POD_INVENTORY_PLACEHOLDER
