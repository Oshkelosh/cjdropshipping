# CJDropshipping (`cjdropshipping`)

Dropshipping catalog and fulfillment via CJ API 2.0.

## Overview

| | |
|---|---|
| Addon ID | `cjdropshipping` |
| Category | supplier |
| Version | 1.0.0 |
| Category guide | [../README.md](../README.md) |
| Fulfillment key | `cjdropshipping` |

Multiple suppliers can be enabled at the same time. Fulfillment runs when an order becomes **paid**.

## Enable and configure

1. Install this package under `app/addons/suppliers/cjdropshipping/`
2. Open **Admin → Suppliers → CJDropshipping** at `/admin/suppliers/cjdropshipping`
3. Enter API credentials and enable the addon

## Configuration schema

| Field | Type | Description |
|-------|------|-------------|
| `api_key` | secret | CJ API key |
| `is_active` | bool | Whether the addon is active |
| `access_token` | string | Managed by addon after OAuth (do not edit manually) |
| `refresh_token` | string | Managed by addon after OAuth |
| `token_expires_at` | float | Access token expiry (Unix timestamp) |

## Routes

### Public API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/suppliers/cjdropshipping/products` | List catalog products |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/suppliers/cjdropshipping` | Config form |
| POST | `/admin/suppliers/cjdropshipping/save` | Save config |
| POST | `/admin/suppliers/cjdropshipping/sync` | Trigger catalog sync |

## Core integration

- **Variant supplier fields:** paid-order fulfillment reads CJ product/variant IDs from each **ProductVariant** row
- **Fulfillment:** places CJ order via API 2.0; OAuth tokens refreshed automatically via `export_config_updates()`
- **Grouping:** line items grouped by fulfillment key `cjdropshipping`

## Variant supplier fields

| Field | Description |
|-------|-------------|
| `supplier_addon_id` | `cjdropshipping` |
| `supplier_product_id` | CJ product id (`pid`) |
| `supplier_variant_id` | CJ variant id (`vid`) |

Both IDs are required.

## Catalog sync

Supported. Admin sync at `/admin/suppliers/cjdropshipping` or `POST /api/v1/admin/suppliers/cjdropshipping/sync`.

**Import model:** one Oshkelosh Product per CJ product; one ProductVariant per CJ variant.

| Key | Format |
|-----|--------|
| Variant dedup key | `cjdropshipping:{pid}:{vid}` |

**Prerequisites:**

- Paginated product list with variant stock checks.

## Provider setup

- Obtain CJ API key; tokens are managed after first auth.

## Package layout

```
cjdropshipping/
├── README.md
├── addon.py
├── catalog.py
├── client.py
├── routes.py
└── templates/
```

## See also

- [Supplier addon development](../README.md)
- [Oshkelosh addon guide](../../README.md)
