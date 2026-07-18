"""CJDropshipping supplier integration."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field, SecretStr

from app.addons.suppliers.base import SupplierAddon
from app.addons.suppliers.catalog_utils import row_lacks_variant_list, variant_dicts_from_row
from app.addons.suppliers.cjdropshipping.catalog import normalize_cj_catalog_products
from app.addons.suppliers.cjdropshipping.client import (
    CJDropshippingAPIError,
    CJDropshippingClient,
    parse_freight_options,
)
from schemas.supplier import SupplierCatalogProduct
from app.addons.log import exception, info, warning
from app.addons.config_serialization import dump_addon_config


class CJDropshippingConfig(BaseModel):
    api_key: SecretStr = Field(default=..., description="CJ API key")
    is_active: bool = Field(default=False)
    warehouse_country: str = Field(
        default="CN",
        description="Origin country code used for shipping-rate quotes (ISO alpha-2)",
    )
    access_token: str = Field(default="", description="Managed by addon after auth")
    refresh_token: str = Field(default="", description="Managed by addon after auth")
    token_expires_at: float = Field(default=0, description="Unix timestamp for access token expiry")

    @classmethod
    def config_model(cls):
        return cls


def _map_shipping(address: Dict[str, Any]) -> Dict[str, Any]:
    from app.addons.suppliers.address import canonical_address

    addr = canonical_address(address)
    return {
        "shippingCountryCode": addr["country_code"],
        "shippingProvince": addr["state"],
        "shippingCity": addr["city"],
        "shippingAddress": addr["line1"],
        "shippingAddress2": addr["line2"],
        "shippingZip": addr["zip"],
        "shippingCustomerName": addr["name"],
        "shippingPhone": addr["phone"],
        "shippingCustomerEmail": addr["email"],
    }


class CJDropshippingAddon(SupplierAddon):
    requires_variant_id = True

    addon_id: str = "cjdropshipping"
    addon_name: str = "CJDropshipping"
    addon_description: str = "Dropshipping catalog and fulfillment via CJ API 2.0."
    addon_category: str = "supplier"
    version: str = "1.0.0"

    _config: Dict[str, Any] | None = None
    _client: CJDropshippingClient | None = None

    @classmethod
    def config_schema(cls):
        return CJDropshippingConfig

    def _build_client(self, cfg: dict[str, Any]) -> CJDropshippingClient:
        return CJDropshippingClient(
            cfg.get("api_key", ""),
            access_token=str(cfg.get("access_token") or ""),
            refresh_token=str(cfg.get("refresh_token") or ""),
            token_expires_at=float(cfg.get("token_expires_at") or 0),
        )

    def _sync_tokens_to_config(self) -> None:
        if self._client is None or self._config is None:
            return
        tokens = self._client.tokens
        self._config["access_token"] = tokens["access_token"]
        self._config["refresh_token"] = tokens["refresh_token"]
        self._config["token_expires_at"] = tokens["token_expires_at"]

    async def initialize(self, config: dict) -> None:
        validated = CJDropshippingConfig(**config)
        dumped = dump_addon_config(validated)
        dumped["api_key"] = validated.api_key.get_secret_value()
        self._config = dumped
        self._client = self._build_client(dumped)
        self.is_enabled = validated.is_active
        info("CJDropshipping", "Initialized")

    async def validate_config(self, config: dict) -> None:
        from app.core.exceptions import ValidationError

        validated = CJDropshippingConfig(**config)
        api_key = validated.api_key.get_secret_value()
        if not api_key:
            return
        client = CJDropshippingClient(api_key)
        try:
            await client.authenticate()
            await client.list_products(page_size=1)
        except CJDropshippingAPIError as exc:
            if exc.status_code == 401:
                raise ValidationError(message="Invalid API key — check your credentials") from exc
            if exc.status_code == 403:
                raise ValidationError(
                    message="API key is valid but missing required permissions: catalog:read"
                ) from exc
            raise ValidationError(message=f"CJDropshipping API error: {exc}") from exc

    async def shutdown(self) -> None:
        self._client = None
        self._config = None
        self.is_enabled = False

    def export_config_updates(self) -> dict[str, Any]:
        """Return token fields to persist after API calls."""
        self._sync_tokens_to_config()
        if not self._config:
            return {}
        return {
            "access_token": self._config.get("access_token", ""),
            "refresh_token": self._config.get("refresh_token", ""),
            "token_expires_at": self._config.get("token_expires_at", 0),
        }

    def _require_client(self) -> CJDropshippingClient:
        if self._client is None:
            raise CJDropshippingAPIError("CJDropshipping addon is not initialized")
        return self._client

    async def _enrich_list_row(self, client: CJDropshippingClient, row: dict[str, Any]) -> dict[str, Any]:
        if not row_lacks_variant_list(row, "variants", "variantList"):
            return row
        pid = str(row.get("pid") or row.get("productId") or row.get("id") or "").strip()
        if not pid:
            return row
        try:
            detail = await client.get_product(pid=pid)
            self._sync_tokens_to_config()
            if not isinstance(detail, dict):
                return row
            variants = variant_dicts_from_row(detail, "variants", "variantList")
            if not variants:
                return row
            merged = dict(row)
            merged["variants"] = variants
            return merged
        except CJDropshippingAPIError as exc:
            warning("CJDropshipping", "catalog sync: product/query({}) failed: {}", pid, exc)
            return row

    async def _fetch_all_products(self) -> list[dict[str, Any]]:
        client = self._require_client()
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await client.list_products(page_num=page, page_size=50)
            self._sync_tokens_to_config()
            batch: list[dict[str, Any]] = []
            if isinstance(data, list):
                batch = [r for r in data if isinstance(r, dict)]
            elif isinstance(data, dict):
                for key in ("list", "products", "content"):
                    val = data.get(key)
                    if isinstance(val, list):
                        batch = [r for r in val if isinstance(r, dict)]
                        break
            if batch:
                enriched = []
                for row in batch:
                    enriched.append(await self._enrich_list_row(client, row))
                rows.extend(enriched)
            else:
                rows.extend(batch)
            if len(batch) < 50:
                break
            page += 1
            if page > 200:
                break
        return rows

    async def list_products(self, **kwargs: Any) -> List[Dict[str, Any]]:
        return await self._fetch_all_products()

    async def fetch_catalog_for_import(self, **kwargs: Any) -> List[SupplierCatalogProduct]:
        data = await self._fetch_all_products()
        return normalize_cj_catalog_products(data)

    async def get_product(self, product_id: str) -> Dict[str, Any]:
        for row in await self.list_products():
            pid = str(row.get("pid") or row.get("productId") or row.get("id") or "")
            if pid == product_id:
                return row
        return {"error": f"CJ product '{product_id}' not found"}

    def supports_shipping_quotes(self) -> bool:
        return True

    async def quote_shipping(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        currency: str | None = None,
    ) -> int | None:
        """Live CJ freight; cheapest option. None → Site Settings.

        CJ freight requires an origin warehouse country (``warehouse_country``
        config, default CN). CJ stocks the same variant across warehouses, so
        this is a per-account default rather than per-product truth.
        """
        details = await self.quote_shipping_details(items, shipping_address, currency=currency)
        if details is None:
            return None
        return int(details["cents"])

    async def quote_shipping_details(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        selected_id: str | None = None,
        currency: str | None = None,
    ) -> Dict[str, Any] | None:
        """Live CJ logistics options; selected_id overrides the cheapest default."""
        if currency and str(currency).upper() != "USD":
            # CJ freightCalculate prices are USD only; don't present them as
            # another shop currency. Fall back to Site Settings shipping.
            return None
        from app.services.countries import normalize_country_code
        from app.addons.suppliers.shipping_quote import pick_shipping_option

        client = self._require_client()
        cfg = self._config or {}
        try:
            country_raw = (shipping_address or {}).get("country") or (
                shipping_address or {}
            ).get("country_code")
            end_country = normalize_country_code(str(country_raw) if country_raw else None)
            if not end_country:
                return None
            start_country = str(cfg.get("warehouse_country") or "CN").strip().upper() or "CN"
            products = []
            for item in items:
                vid = str(item.get("supplier_variant_id") or "").strip()
                if not vid:
                    continue
                products.append({"vid": vid, "quantity": int(item.get("quantity") or 1)})
            if not products:
                return None
            data = await client.calculate_freight(products, start_country, end_country)
            self._sync_tokens_to_config()
            options = parse_freight_options(data)
            chosen = pick_shipping_option(
                options,
                selected_id=selected_id,
                preferred_ids=(),
            )
            if chosen is None:
                return None
            return {
                "cents": int(chosen["cents"]),
                "selected_id": str(chosen["id"]),
                "options": options,
            }
        except CJDropshippingAPIError as exc:
            warning("CJDropshipping", "quote_shipping error: {}", exc)
            return None
        except Exception:
            exception("CJDropshipping", "quote_shipping unexpected error")
            return None

    async def create_order(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        external_id: str | None = None,
        supplier_ref: str | None = None,
        shipping_method: str | None = None,
        currency: str | None = None,
    ) -> Dict[str, Any]:
        del supplier_ref, currency
        client = self._require_client()
        try:
            products = []
            for item in items:
                pid = str(item.get("supplier_product_id") or "").strip()
                vid = str(item.get("supplier_variant_id") or "").strip()
                if not pid or not vid:
                    continue
                products.append(
                    {
                        "pid": pid,
                        "vid": vid,
                        "quantity": int(item.get("quantity") or 1),
                    }
                )
            if not products:
                return {"success": False, "error": "No valid CJ line items (need pid + vid)"}

            payload: Dict[str, Any] = {
                "products": products,
                **_map_shipping(shipping_address),
            }
            if external_id:
                payload["orderNumber"] = external_id
            logistic = (shipping_method or "").strip()
            if logistic:
                payload["logisticName"] = logistic

            data = await client.create_order(payload)
            self._sync_tokens_to_config()
            order_id = str(data.get("orderId") or data.get("id") or "")
            return {
                "success": True,
                "order_id": order_id,
                "status": data.get("orderStatus", "submitted"),
                "cj_order_id": order_id,
                "config_updates": self.export_config_updates(),
            }
        except CJDropshippingAPIError as exc:
            warning("CJDropshipping", "create_order error: {}", exc)
            return {"success": False, "error": str(exc)}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            data = await self._require_client().get_order(order_id)
            self._sync_tokens_to_config()
            return {"order_id": order_id, "status": data.get("orderStatus", "unknown")}
        except CJDropshippingAPIError as exc:
            return {"order_id": order_id, "status": "error", "detail": str(exc)}

    async def sync_inventory(self) -> None:
        products = await self.list_products()
        info("CJDropshipping", "Catalog has {} products", len(products))

    def get_routers(self) -> List[APIRouter]:
        from app.addons.suppliers.cjdropshipping.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.suppliers.cjdropshipping.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")
