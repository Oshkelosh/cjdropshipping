"""Tests for CJ Dropshipping catalog fetch depth."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.addons.suppliers.cjdropshipping.addon import CJDropshippingAddon


@pytest.mark.asyncio
async def test_fetch_all_products_enriches_rows_without_variants():
    addon = CJDropshippingAddon()
    addon._client = AsyncMock()
    addon._config = {"api_key": "key", "access_token": "tok", "refresh_token": "", "token_expires_at": 0}
    addon._client.list_products.return_value = {
        "list": [{"pid": "p1", "productName": "Gadget"}],
    }
    addon._client.get_product.return_value = {
        "pid": "p1",
        "productName": "Gadget",
        "variants": [
            {"vid": "v1", "variantName": "Red", "variantStock": 5, "variantSellPrice": "9.99"},
            {"vid": "v2", "variantName": "Blue", "variantStock": 3, "variantSellPrice": "10.99"},
        ],
    }

    items = await addon.fetch_catalog_for_import()

    assert addon._client.get_product.await_count == 1
    assert addon._client.get_product.await_args.kwargs["pid"] == "p1"
    importable = [item for item in items if not item.skip_reason]
    assert len(importable) == 2
    assert {item.supplier_variant_id for item in importable} == {"v1", "v2"}
