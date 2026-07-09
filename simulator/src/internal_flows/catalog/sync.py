"""Sync the local PIM catalog into PrestaShop — idempotent create/patch.

Reads existing resources through the JSON client and writes via XML. The whole
pass is safe to re-run: anything already present (matched by name) is reused.

Purely additive: it creates and patches to match the PIM, but never deletes.
Removing extraneous data (e.g. PrestaShop's install demo catalogue) is a
platform-specific, setup-time concern handled by provisioning — see the sidecar
PurgeDemoData step — so this sync stays portable across storefront platforms.
"""

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import httpx

from src.internal_flows.catalog import prestashop as ps

log = logging.getLogger("simulator.catalog")

PIM_DIR = Path(__file__).resolve().parents[3] / "data" / "pim"

# PrestaShop's Home category (always id 2). Products also placed here surface in
# the storefront's "featured products" block (HOME_FEATURED_CAT = 2).
HOME_CATEGORY_ID = 2

# Products (by English name) to feature on the home — i.e. also assigned to Home.
# A storefront merchandising choice kept in code so it survives a delete + sync.
FEATURED_PRODUCTS = {"Barrel", "Chest", "Hanging Sign", "Wooden Fence"}

# Flat default catalogue price (tax excl.) given to every product for now.
DEFAULT_PRICE = "10"

# Content languages we publish (the PIM field suffix == the PrestaShop iso_code).
CONTENT_LANGS = ("en", "fr")


def load_pim() -> dict[str, Any]:
    def load(name: str) -> Any:
        with (PIM_DIR / name).open() as f:
            return json.load(f)

    return {
        "categories": load("categories.json"),
        "products": load("products.json"),
        "combinations": load("combinations.json"),
        "attributes": load("attributes.json"),
        "images": {img["item_id"]: img["local_path"] for img in load("images.json")},
    }


def _slugify(text: str) -> str:
    # Transliterate accents (é→e) so French slugs stay clean ASCII.
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


async def _content_lang_ids(json_http: httpx.AsyncClient) -> dict[str, int]:
    """{iso: ps_lang_id} for the installed content languages (en, fr)."""
    by_iso = {
        row["iso_code"]: int(row["id"])
        for row in await ps.get_all(json_http, "languages")
        if row.get("id")
    }
    return {iso: by_iso[iso] for iso in CONTENT_LANGS if iso in by_iso}


def _ml(lang_ids: dict[str, int], item: dict[str, Any], base: str) -> dict[int, str]:
    """{ps_lang_id: item[<base>_<iso>]} with English fallback (name, description, …)."""
    fallback = item.get(f"{base}_en", "")
    return {
        lid: (item.get(f"{base}_{iso}") or fallback) for iso, lid in lang_ids.items()
    }


def _ml_slug(lang_ids: dict[str, int], item: dict[str, Any]) -> dict[int, str]:
    """Per-language link_rewrite, slugified from each language's name."""
    return {lid: _slugify(name) for lid, name in _ml(lang_ids, item, "name").items()}


async def _sync_attribute_groups(
    json_http: httpx.AsyncClient, xml_http: httpx.AsyncClient, pim: dict[str, Any]
) -> dict[str, int]:
    """{group_name: ps_option_id} — create missing ProductOptions."""
    existing = {
        ps.lang_value(g.get("name")).lower(): g["id"]
        for g in await ps.get_all(json_http, "product_options")
        if g.get("id")
    }
    names = {row["attribute"] for row in pim["attributes"]}
    result = {n: existing[n.lower()] for n in names if n.lower() in existing}

    for name in names - set(result):
        label = name.replace("_", " ").title()
        rid = ps.resource_id(
            await ps.post(
                xml_http,
                "product_options",
                ps.wrap(
                    "product_option",
                    ps.field("group_type", "select"),
                    ps.field("is_color_group", "0"),
                    ps.lang("name", label),
                    ps.lang("public_name", label),
                ),
            )
        )
        if rid:
            result[name] = rid
            log.info("attribute group created: %s → %d", name, rid)
    return result


async def _sync_attributes(
    json_http: httpx.AsyncClient,
    xml_http: httpx.AsyncClient,
    pim: dict[str, Any],
    group_map: dict[str, int],
) -> dict[tuple[str, str], int]:
    """{(group_name, value): ps_option_value_id} — create missing ProductOptionValues."""
    existing = await ps.get_all(json_http, "product_option_values")
    by_group: dict[str, list[dict[str, Any]]] = {}
    for row in pim["attributes"]:
        by_group.setdefault(row["attribute"], []).append(row)

    result: dict[tuple[str, str], int] = {}
    for group_name, group_id in group_map.items():
        in_group = {
            ps.lang_value(v.get("name")).lower(): v["id"]
            for v in existing
            if v.get("id_attribute_group") == group_id and v.get("id")
        }
        for row in by_group.get(group_name, []):
            value = row["value"]
            if value.lower() in in_group:
                result[group_name, value] = in_group[value.lower()]
                continue
            rid = ps.resource_id(
                await ps.post(
                    xml_http,
                    "product_option_values",
                    ps.wrap(
                        "product_option_value",
                        ps.field("id_attribute_group", group_id),
                        ps.lang("name", value.replace("_", " ").title()),
                    ),
                )
            )
            if rid:
                result[group_name, value] = rid
    return result


async def _sync_categories(
    json_http: httpx.AsyncClient,
    xml_http: httpx.AsyncClient,
    pim: dict[str, Any],
    lang_ids: dict[str, int],
) -> dict[Any, int]:
    """{pim_category_id: ps_category_id} — create missing categories (en + fr)."""
    existing = {
        ps.lang_value(c.get("name")).lower(): c["id"]
        for c in await ps.get_all(json_http, "categories")
        if c.get("id")
    }
    result: dict[Any, int] = {}
    created = matched = 0
    for cat in pim["categories"]:
        if not cat.get("active"):
            continue
        name = cat["name_en"]
        if name.lower() in existing:
            cid = int(existing[name.lower()])
            result[cat["id"]] = cid
            matched += 1
            # Keep the existing category's en+fr name/slug current.
            await ps.put(
                xml_http,
                "categories",
                cid,
                ps.wrap(
                    "category",
                    ps.field("id", cid),
                    ps.field("active", 1),
                    ps.field("id_parent", 2),
                    ps.lang_multi("name", _ml(lang_ids, cat, "name")),
                    ps.lang_multi("link_rewrite", _ml_slug(lang_ids, cat)),
                ),
            )
            continue
        rid = ps.resource_id(
            await ps.post(
                xml_http,
                "categories",
                ps.wrap(
                    "category",
                    ps.field("active", 1),
                    ps.field("id_parent", 2),
                    ps.lang_multi("name", _ml(lang_ids, cat, "name")),
                    ps.lang_multi("link_rewrite", _ml_slug(lang_ids, cat)),
                ),
            )
        )
        if rid:
            result[cat["id"]] = rid
            created += 1
    log.info("categories: matched=%d created=%d", matched, created)
    return result


async def _create_product(
    xml_http: httpx.AsyncClient,
    product: dict[str, Any],
    lang_ids: dict[str, int],
) -> int | None:
    return ps.resource_id(
        await ps.post(
            xml_http,
            "products",
            ps.wrap(
                "product",
                ps.field("price", DEFAULT_PRICE),
                ps.field("active", 1),
                ps.field("state", 1),
                ps.lang_multi("name", _ml(lang_ids, product, "name")),
                ps.lang_multi("link_rewrite", _ml_slug(lang_ids, product)),
            ),
        )
    )


async def _patch_product(
    xml_http: httpx.AsyncClient,
    pid: int,
    product: dict[str, Any],
    category_id: int | None,
    lang_ids: dict[str, int],
    featured: bool = False,
) -> bool:
    fields = [
        ps.field("id", pid),
        ps.field("price", DEFAULT_PRICE),
        ps.field("active", 1 if product.get("active") else 0),
        ps.field("state", 1),
        ps.field("available_for_order", 1),
        ps.field("show_price", 1),
        ps.field("online_only", 0),
        ps.field("reference", product.get("reference", "")),
        ps.lang_multi("name", _ml(lang_ids, product, "name")),
        ps.lang_multi("link_rewrite", _ml_slug(lang_ids, product)),
        ps.lang_multi("description", _ml(lang_ids, product, "description")),
    ]
    categories: list[int] = []
    if category_id:
        fields.append(ps.field("id_category_default", category_id))
        categories.append(category_id)
    if featured:
        categories.append(HOME_CATEGORY_ID)
    if categories:
        fields.append(ps.associations(ps.id_list("categories", "category", categories)))
    return await ps.put(xml_http, "products", pid, ps.wrap("product", *fields))


async def _product_has_image(json_http: httpx.AsyncClient, pid: int) -> bool:
    r = await json_http.get(f"/images/products/{pid}")
    if r.status_code != 200:
        return False
    data = r.json()
    return bool(data.get("image") or data.get("images"))


async def _sync_combinations(
    xml_http: httpx.AsyncClient,
    pid: int,
    combos: list[dict[str, Any]],
    attr_map: dict[tuple[str, str], int],
) -> int:
    created = 0
    for combo in combos:
        value_ids = [
            attr_map[key[5:], value]
            for key, value in combo.items()
            if key.startswith("attr_") and (key[5:], value) in attr_map
        ]
        if not value_ids:
            continue
        image_id = None
        if combo.get("image_local"):
            image_id = await ps.upload_image(
                xml_http, pid, PIM_DIR / combo["image_local"]
            )
        blocks = [
            ps.id_list("product_option_values", "product_option_value", value_ids)
        ]
        if image_id:
            blocks.append(ps.id_list("images", "image", [image_id]))
        root = await ps.post(
            xml_http,
            "combinations",
            ps.wrap(
                "combination",
                ps.field("id_product", pid),
                ps.field("minimal_quantity", 1),
                ps.associations(*blocks),
            ),
        )
        if root is not None:
            created += 1
    return created


async def sync_catalog(
    json_http: httpx.AsyncClient, xml_http: httpx.AsyncClient
) -> dict[str, Any]:
    """Sync the whole PIM into PrestaShop; return a flat summary of counts."""
    pim = load_pim()
    log.info(
        "sync start: %d products, %d categories, %d attribute rows, %d combinations",
        len(pim["products"]),
        len(pim["categories"]),
        len(pim["attributes"]),
        len(pim["combinations"]),
    )

    lang_ids = await _content_lang_ids(json_http)
    log.info("content languages: %s", lang_ids)

    group_map = await _sync_attribute_groups(json_http, xml_http, pim)
    attr_map = await _sync_attributes(json_http, xml_http, pim, group_map)
    cat_map = await _sync_categories(json_http, xml_http, pim, lang_ids)

    existing = {
        ps.lang_value(p.get("name")).lower(): p["id"]
        for p in await ps.get_all(json_http, "products")
        if p.get("id") and p.get("name")
    }
    combos_by_product: dict[Any, list[dict[str, Any]]] = {}
    for combo in pim["combinations"]:
        combos_by_product.setdefault(combo["product_id"], []).append(combo)

    created = patched = skipped = images = combinations = 0
    errors: list[dict[str, str]] = []

    for product in pim["products"]:
        if not product.get("active"):
            continue
        name = product["name_en"]
        pid = existing.get(name.lower())
        if pid is None:
            pid = await _create_product(xml_http, product, lang_ids)
            if pid is None:
                errors.append({"name": name, "reason": "create failed"})
                continue
            created += 1
        else:
            skipped += 1

        if await _patch_product(
            xml_http,
            pid,
            product,
            cat_map.get(product.get("category_id")),
            lang_ids,
            featured=name in FEATURED_PRODUCTS,
        ):
            patched += 1
        else:
            errors.append({"name": name, "reason": "patch failed"})

        image_local = pim["images"].get(product["id"])
        if image_local and not await _product_has_image(json_http, pid):
            if await ps.upload_image(xml_http, pid, PIM_DIR / image_local) is not None:
                images += 1

        if product["id"] in combos_by_product:
            combinations += await _sync_combinations(
                xml_http, pid, combos_by_product[product["id"]], attr_map
            )

    summary = {
        "attribute_groups": len(group_map),
        "attributes": len(attr_map),
        "categories": len(cat_map),
        "products_created": created,
        "products_patched": patched,
        "products_skipped": skipped,
        "images_uploaded": images,
        "combinations": combinations,
        "errors": errors,
    }
    log.info("sync done: %s", summary)
    return summary
