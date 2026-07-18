"""CJDropshipping API client."""

from __future__ import annotations

import time
from typing import Any

import httpx

CJ_BASE = "https://developers.cjdropshipping.com/api2.0/v1"


class CJDropshippingAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class CJDropshippingClient:
    def __init__(
        self,
        api_key: str,
        *,
        access_token: str = "",
        refresh_token: str = "",
        token_expires_at: float = 0,
        timeout: float = 60.0,
    ):
        self._api_key = api_key
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expires_at = token_expires_at
        self._timeout = timeout

    @property
    def tokens(self) -> dict[str, Any]:
        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "token_expires_at": self._token_expires_at,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "CJ-Access-Token": self._access_token,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        url = f"{CJ_BASE}{path}"
        headers = self._headers() if auth else {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method, url, headers=headers, params=params, json=json
            )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            message = resp.text
            if isinstance(data, dict):
                message = str(data.get("message") or resp.text)
            raise CJDropshippingAPIError(message, status_code=resp.status_code, body=data)
        if isinstance(data, dict) and data.get("result") is False:
            raise CJDropshippingAPIError(str(data.get("message") or "CJ API error"), body=data)
        return data.get("data") if isinstance(data, dict) and "data" in data else data

    async def authenticate(self) -> None:
        payload = await self._request(
            "POST",
            "/authentication/getAccessToken",
            json={"apiKey": self._api_key},
            auth=False,
        )
        if not isinstance(payload, dict):
            raise CJDropshippingAPIError("Invalid CJ auth response")
        self._access_token = str(payload.get("accessToken") or "")
        self._refresh_token = str(payload.get("refreshToken") or "")
        expires_in = payload.get("accessTokenExpiryDate") or payload.get("expiresIn")
        if isinstance(expires_in, (int, float)):
            self._token_expires_at = time.time() + float(expires_in)
        else:
            self._token_expires_at = time.time() + 15 * 24 * 3600

    async def refresh_access_token(self) -> None:
        if not self._refresh_token:
            await self.authenticate()
            return
        payload = await self._request(
            "POST",
            "/authentication/refreshAccessToken",
            json={"refreshToken": self._refresh_token},
            auth=False,
        )
        if not isinstance(payload, dict):
            raise CJDropshippingAPIError("Invalid CJ refresh response")
        self._access_token = str(payload.get("accessToken") or self._access_token)
        self._refresh_token = str(payload.get("refreshToken") or self._refresh_token)
        self._token_expires_at = time.time() + 15 * 24 * 3600

    async def ensure_token(self) -> None:
        if not self._access_token or time.time() >= (self._token_expires_at - 300):
            if self._refresh_token:
                await self.refresh_access_token()
            else:
                await self.authenticate()

    async def list_products(self, *, page_num: int = 1, page_size: int = 50) -> Any:
        await self.ensure_token()
        return await self._request(
            "GET",
            "/product/list",
            params={"pageNum": page_num, "pageSize": page_size},
        )

    async def get_product(
        self,
        *,
        pid: str | None = None,
        product_sku: str | None = None,
        variant_sku: str | None = None,
    ) -> Any:
        """Fetch product detail including variants (GET /product/query)."""
        await self.ensure_token()
        params: dict[str, str] = {}
        if pid:
            params["pid"] = pid
        elif product_sku:
            params["productSku"] = product_sku
        elif variant_sku:
            params["variantSku"] = variant_sku
        else:
            raise CJDropshippingAPIError("pid, product_sku, or variant_sku is required")
        return await self._request("GET", "/product/query", params=params)

    async def calculate_freight(
        self,
        products: list[dict[str, Any]],
        start_country: str,
        end_country: str,
    ) -> Any:
        """POST /logistic/freightCalculate — shipping options for a cart."""
        await self.ensure_token()
        body = {
            "startCountryCode": start_country,
            "endCountryCode": end_country,
            "products": products,
        }
        return await self._request("POST", "/logistic/freightCalculate", json=body)

    async def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_token()
        data = await self._request("POST", "/shopping/order/createOrder", json=payload)
        return data if isinstance(data, dict) else {"result": data}

    async def get_order(self, order_id: str) -> dict[str, Any]:
        await self.ensure_token()
        data = await self._request("GET", f"/shopping/order/getOrderDetail", params={"orderId": order_id})
        return data if isinstance(data, dict) else {"result": data}


def _freight_option_list(options: Any) -> list[dict[str, Any]]:
    if isinstance(options, dict):
        for key in ("data", "list"):
            val = options.get(key)
            if isinstance(val, list):
                options = val
                break
    if not isinstance(options, list):
        return []
    return [row for row in options if isinstance(row, dict)]


def parse_freight_options(options: Any) -> list[dict[str, Any]]:
    """Normalize CJ freightCalculate rows into checkout options."""
    from app.addons.suppliers.shipping_quote import to_cents

    parsed: list[dict[str, Any]] = []
    for option in _freight_option_list(options):
        cents = to_cents(option.get("logisticPrice"))
        if cents is None:
            continue
        name = str(
            option.get("logisticName") or option.get("logisticAgeName") or ""
        ).strip()
        code = str(option.get("logisticCode") or "").strip()
        option_id = name or code or f"option-{len(parsed) + 1}"
        parsed.append(
            {
                "id": option_id,
                "name": name or option_id,
                "cents": cents,
            }
        )
    return parsed


def pick_freight_cents(options: Any) -> int | None:
    """CJ returns a list of logistics options; pick the cheapest ``logisticPrice``.

    Amounts are USD decimal strings. Returns ``None`` when nothing can be priced.
    """
    from app.addons.suppliers.shipping_quote import pick_shipping_option

    chosen = pick_shipping_option(parse_freight_options(options), preferred_ids=())
    return int(chosen["cents"]) if chosen else None
