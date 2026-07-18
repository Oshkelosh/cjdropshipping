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
    importable = [
        variant
        for product in items
        for variant in product.variants
        if not variant.skip_reason
    ]
    assert len(importable) == 2
    assert {variant.supplier_variant_id for variant in importable} == {"v1", "v2"}


def test_supports_shipping_quotes():
    assert CJDropshippingAddon().supports_shipping_quotes() is True


@pytest.mark.asyncio
async def test_quote_shipping_returns_cheapest_cents():
    addon = CJDropshippingAddon()
    addon._config = {"api_key": "key", "warehouse_country": "CN"}
    addon._client = AsyncMock()
    addon._client.calculate_freight = AsyncMock(
        return_value=[
            {"logisticName": "CJPacket", "logisticPrice": "8.40"},
            {"logisticName": "PostNL", "logisticPrice": "5.10"},
        ]
    )
    cents = await addon.quote_shipping(
        [{"supplier_product_id": "p1", "supplier_variant_id": "v1", "quantity": 2}],
        {"country": "US"},
    )
    assert cents == 510
    call = addon._client.calculate_freight.await_args
    assert call.args[1] == "CN"
    assert call.args[2] == "US"


@pytest.mark.asyncio
async def test_quote_shipping_none_without_destination():
    addon = CJDropshippingAddon()
    addon._config = {"api_key": "key", "warehouse_country": "CN"}
    addon._client = AsyncMock()
    cents = await addon.quote_shipping(
        [{"supplier_product_id": "p1", "supplier_variant_id": "v1", "quantity": 1}],
        {},
    )
    assert cents is None
    addon._client.calculate_freight.assert_not_awaited()


@pytest.mark.asyncio
async def test_quote_shipping_returns_none_on_api_error():
    from app.addons.suppliers.cjdropshipping.client import CJDropshippingAPIError

    addon = CJDropshippingAddon()
    addon._config = {"api_key": "key", "warehouse_country": "CN"}
    addon._client = AsyncMock()
    addon._client.calculate_freight = AsyncMock(
        side_effect=CJDropshippingAPIError("bad request", status_code=400)
    )
    cents = await addon.quote_shipping(
        [{"supplier_product_id": "p1", "supplier_variant_id": "v1", "quantity": 1}],
        {"country": "US"},
    )
    assert cents is None


@pytest.mark.asyncio
async def test_quote_shipping_details_honors_selected_method():
    addon = CJDropshippingAddon()
    addon._config = {"api_key": "key", "warehouse_country": "CN"}
    addon._client = AsyncMock()
    addon._client.calculate_freight = AsyncMock(
        return_value=[
            {"logisticName": "CJPacket", "logisticPrice": "8.40"},
            {"logisticName": "PostNL", "logisticPrice": "5.10"},
        ]
    )
    details = await addon.quote_shipping_details(
        [{"supplier_product_id": "p1", "supplier_variant_id": "v1", "quantity": 1}],
        {"country": "US"},
        selected_id="CJPacket",
    )
    assert details is not None
    assert details["cents"] == 840
    assert details["selected_id"] == "CJPacket"


@pytest.mark.asyncio
async def test_create_order_sends_logistic_name():
    addon = CJDropshippingAddon()
    addon._config = {"api_key": "key"}
    addon._client = AsyncMock()
    addon._client.create_order = AsyncMock(return_value={"orderId": "ord-1"})
    result = await addon.create_order(
        [{"supplier_product_id": "p1", "supplier_variant_id": "v1", "quantity": 1}],
        {"line1": "1 Main", "city": "Austin", "postal_code": "78701", "country": "US"},
        shipping_method="CJPacket",
    )
    assert result["success"] is True
    payload = addon._client.create_order.await_args.args[0]
    assert payload["logisticName"] == "CJPacket"
