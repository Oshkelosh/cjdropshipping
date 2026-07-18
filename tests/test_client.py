"""Unit tests for CJDropshipping shipping-quote helpers."""

from app.addons.suppliers.cjdropshipping.client import parse_freight_options, pick_freight_cents
from app.addons.suppliers.shipping_quote import pick_shipping_option


def test_pick_freight_cheapest():
    options = [
        {"logisticName": "CJPacket", "logisticPrice": "8.40"},
        {"logisticName": "PostNL", "logisticPrice": "5.10"},
    ]
    assert pick_freight_cents(options) == 510


def test_pick_freight_unwraps_data_dict():
    payload = {"data": [{"logisticPrice": "3.99"}, {"logisticPrice": "4.50"}]}
    assert pick_freight_cents(payload) == 399


def test_pick_freight_empty_or_malformed_returns_none():
    assert pick_freight_cents([]) is None
    assert pick_freight_cents([{"logisticName": "x"}]) is None
    assert pick_freight_cents(None) is None


def test_parse_freight_options_and_select():
    options = parse_freight_options(
        [
            {"logisticName": "CJPacket", "logisticPrice": "8.40"},
            {"logisticName": "PostNL", "logisticPrice": "5.10"},
        ]
    )
    chosen = pick_shipping_option(options, selected_id="CJPacket", preferred_ids=())
    assert chosen is not None
    assert chosen["cents"] == 840
