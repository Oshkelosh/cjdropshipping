"""CJDropshipping catalog normalization."""

from __future__ import annotations

from typing import Any

from app.addons.suppliers.catalog_utils import (
    decimal_price_to_cents,
    variant_attributes_from_row,
    variant_title_from_attributes,
)
from schemas.supplier import (
    SupplierCatalogItem,
    SupplierCatalogProduct,
    SupplierCatalogVariant,
)


def normalize_cj_catalog(raw: Any) -> list[SupplierCatalogItem]:
    items: list[SupplierCatalogItem] = []
    products: list[dict[str, Any]] = []
    if isinstance(raw, list):
        products = [p for p in raw if isinstance(p, dict)]
    elif isinstance(raw, dict):
        for key in ("list", "products", "data", "content"):
            val = raw.get(key)
            if isinstance(val, list):
                products = [p for p in val if isinstance(p, dict)]
                break

    for product in products:
        pid = str(product.get("pid") or product.get("productId") or product.get("id") or "").strip()
        if not pid:
            continue
        name = str(product.get("productName") or product.get("nameEn") or product.get("name") or pid)
        variants = product.get("variants") or product.get("variantList") or []
        image = product.get("productImage") or product.get("bigImage")
        if isinstance(variants, list) and variants:
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                vid = str(variant.get("vid") or variant.get("variantId") or variant.get("id") or "").strip()
                if not vid:
                    continue
                variant_name = str(variant.get("variantName") or variant.get("name") or name)
                price = variant.get("variantSellPrice") or variant.get("sellPrice") or product.get("sellPrice")
                stock = variant.get("variantStock") or variant.get("stock") or 0
                try:
                    inventory = max(int(stock), 0)
                except (TypeError, ValueError):
                    inventory = 0
                if inventory <= 0:
                    items.append(
                        SupplierCatalogItem(
                            external_key=f"cjdropshipping:{pid}:{vid}",
                            name=variant_name,
                            description=product.get("description"),
                            price_cents=0,
                            sku=None,
                            image_url=image,
                            supplier_value="cjdropshipping",
                            supplier_product_id=pid,
                            supplier_variant_id=vid,
                            inventory_quantity=0,
                            skip_reason="CJ variant out of stock",
                        )
                    )
                    continue
                items.append(
                    SupplierCatalogItem(
                        external_key=f"cjdropshipping:{pid}:{vid}",
                        name=variant_name,
                        description=product.get("description"),
                        price_cents=decimal_price_to_cents(price),
                        sku=str(variant.get("variantSku") or f"cj-{pid}-{vid}"),
                        image_url=variant.get("variantImage") or image,
                        supplier_value="cjdropshipping",
                        supplier_product_id=pid,
                        supplier_variant_id=vid,
                        inventory_quantity=inventory,
                    )
                )
            continue
        price = product.get("sellPrice")
        items.append(
            SupplierCatalogItem(
                external_key=f"cjdropshipping:{pid}",
                name=name,
                description=product.get("description"),
                price_cents=decimal_price_to_cents(price),
                sku=str(product.get("productSku") or f"cj-{pid}"),
                image_url=image,
                supplier_value="cjdropshipping",
                supplier_product_id=pid,
                supplier_variant_id="",
                inventory_quantity=0,
                skip_reason="CJ product has no variants",
            )
        )
    return items


def normalize_cj_catalog_products(raw: Any) -> list[SupplierCatalogProduct]:
    """Map CJ list_products() rows to grouped catalog products."""
    products: list[SupplierCatalogProduct] = []
    source: list[dict[str, Any]] = []
    if isinstance(raw, list):
        source = [p for p in raw if isinstance(p, dict)]
    elif isinstance(raw, dict):
        for key in ("list", "products", "data", "content"):
            val = raw.get(key)
            if isinstance(val, list):
                source = [p for p in val if isinstance(p, dict)]
                break

    for product in source:
        pid = str(product.get("pid") or product.get("productId") or product.get("id") or "").strip()
        if not pid:
            continue
        name = str(product.get("productName") or product.get("nameEn") or product.get("name") or pid)
        description = product.get("description")
        image = product.get("productImage") or product.get("bigImage")
        product_image = str(image).strip() if image else None
        product_images = [product_image] if product_image else []
        variants_raw = product.get("variants") or product.get("variantList") or []
        variants: list[SupplierCatalogVariant] = []

        if isinstance(variants_raw, list) and variants_raw:
            for variant in variants_raw:
                if not isinstance(variant, dict):
                    continue
                vid = str(variant.get("vid") or variant.get("variantId") or variant.get("id") or "").strip()
                if not vid:
                    continue
                attributes = variant_attributes_from_row(variant, "variantName")
                variant_name = variant_title_from_attributes(
                    name,
                    attributes,
                    fallback=str(variant.get("variantName") or variant.get("name") or name),
                )
                price = variant.get("variantSellPrice") or variant.get("sellPrice") or product.get("sellPrice")
                stock = variant.get("variantStock") or variant.get("stock") or 0
                try:
                    inventory = max(int(stock), 0)
                except (TypeError, ValueError):
                    inventory = 0
                variant_image = variant.get("variantImage") or image
                variant_image_url = str(variant_image).strip() if variant_image else None
                variant_images = [variant_image_url] if variant_image_url else list(product_images)
                if inventory <= 0:
                    variants.append(
                        SupplierCatalogVariant(
                            external_key=f"cjdropshipping:{pid}:{vid}",
                            title=variant_name,
                            attributes=attributes,
                            price_cents=0,
                            sku=None,
                            inventory_quantity=0,
                            supplier_product_id=pid,
                            supplier_variant_id=vid,
                            image_urls=variant_images,
                            skip_reason="CJ variant out of stock",
                        )
                    )
                    continue
                variants.append(
                    SupplierCatalogVariant(
                        external_key=f"cjdropshipping:{pid}:{vid}",
                        title=variant_name,
                        attributes=attributes,
                        price_cents=decimal_price_to_cents(price),
                        sku=str(variant.get("variantSku") or f"cj-{pid}-{vid}"),
                        inventory_quantity=inventory,
                        supplier_product_id=pid,
                        supplier_variant_id=vid,
                        image_urls=variant_images,
                    )
                )
        else:
            price = product.get("sellPrice")
            variants.append(
                SupplierCatalogVariant(
                    external_key=f"cjdropshipping:{pid}",
                    title=name,
                    attributes={},
                    price_cents=decimal_price_to_cents(price),
                    sku=str(product.get("productSku") or f"cj-{pid}"),
                    inventory_quantity=0,
                    supplier_product_id=pid,
                    supplier_variant_id="",
                    image_urls=product_images,
                    skip_reason="CJ product has no variants",
                )
            )

        products.append(
            SupplierCatalogProduct(
                external_product_key=f"cjdropshipping:{pid}",
                name=name,
                description=description if isinstance(description, str) else None,
                product_type=None,
                image_urls=product_images,
                image_alt_texts=[],
                variants=variants,
                supplier_value="cjdropshipping",
            )
        )
    return products
