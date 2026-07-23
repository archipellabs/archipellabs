"""Sync the local PIM catalog into PrestaShop — idempotent create/patch.

Reads existing resources through the JSON client and writes via XML. The whole
pass is safe to re-run: products/combinations use stable references, while
human-labelled resources use canonical comparison keys.

Purely additive: it creates and patches to match the PIM, but never deletes.
Removing extraneous data (e.g. PrestaShop's install demo catalogue) is a
platform-specific, setup-time concern handled by provisioning — see the sidecar
PurgeDemoData step — so this sync stays portable across storefront platforms.
"""

import json
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
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


def _canonical_key(text: str) -> str:
    """A stable comparison key for PIM identifiers and storefront labels.

    The PIM calls its option group ``wood_type`` while PrestaShop exposes the
    human label ``Wood Type``. Treating those as different created a fresh group
    on every sync. This key deliberately normalizes both representations.
    """
    return _slugify(text).replace("-", "_")


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


def _multilang_matches(current: Any, desired: dict[int, str]) -> bool:
    """Whether every managed language already has its desired value."""
    values = ps.lang_values(current)
    return all(
        values.get(language_id) == value for language_id, value in desired.items()
    )


def _integer_matches(current: Any, desired: int) -> bool:
    try:
        return int(current) == desired
    except TypeError, ValueError:
        return False


def _decimal_matches(current: Any, desired: str) -> bool:
    try:
        return Decimal(str(current)) == Decimal(desired)
    except InvalidOperation, TypeError, ValueError:
        return False


async def _sync_attribute_groups(
    json_http: httpx.AsyncClient, xml_http: httpx.AsyncClient, pim: dict[str, Any]
) -> dict[str, int]:
    """{group_name: ps_option_id} — create missing ProductOptions."""
    existing: dict[str, int] = {}
    for group in await ps.get_all(json_http, "product_options"):
        if not group.get("id"):
            continue
        key = _canonical_key(ps.lang_value(group.get("name")))
        if key:
            # If an older buggy run already created duplicates, consistently reuse
            # the oldest one. The additive reconciler does not delete user data.
            existing[key] = min(existing.get(key, int(group["id"])), int(group["id"]))
    names = {row["attribute"] for row in pim["attributes"]}
    result = {
        name: existing[_canonical_key(name)]
        for name in names
        if _canonical_key(name) in existing
    }

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
        if rid is None:
            raise RuntimeError(f"attribute group {name!r} was created without an id")
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
            _canonical_key(ps.lang_value(v.get("name"))): int(v["id"])
            for v in existing
            if str(v.get("id_attribute_group")) == str(group_id) and v.get("id")
        }
        for row in by_group.get(group_name, []):
            value = row["value"]
            key = _canonical_key(value)
            if key in in_group:
                result[group_name, value] = in_group[key]
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
            if rid is None:
                raise RuntimeError(
                    f"attribute value {group_name}={value!r} was created without an id"
                )
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
        _canonical_key(ps.lang_value(c.get("name"))): c
        for c in await ps.get_all(json_http, "categories")
        if c.get("id") and ps.lang_value(c.get("name"))
    }
    result: dict[Any, int] = {}
    created = patched = unchanged = 0
    for cat in pim["categories"]:
        if not cat.get("active"):
            continue
        name = cat["name_en"]
        key = _canonical_key(name)
        if key in existing:
            current = existing[key]
            cid = int(current["id"])
            result[cat["id"]] = cid
            names = _ml(lang_ids, cat, "name")
            slugs = _ml_slug(lang_ids, cat)
            needs_patch = (
                not _integer_matches(current.get("active"), 1)
                or not _integer_matches(current.get("id_parent"), HOME_CATEGORY_ID)
                or not _multilang_matches(current.get("name"), names)
                or not _multilang_matches(current.get("link_rewrite"), slugs)
            )
            if needs_patch:
                await ps.put(
                    xml_http,
                    "categories",
                    cid,
                    ps.wrap(
                        "category",
                        ps.field("id", cid),
                        ps.field("active", 1),
                        ps.field("id_parent", HOME_CATEGORY_ID),
                        ps.lang_multi("name", names),
                        ps.lang_multi("link_rewrite", slugs),
                    ),
                )
                patched += 1
            else:
                unchanged += 1
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
        if rid is None:
            raise RuntimeError(f"category {name!r} was created without an id")
        result[cat["id"]] = rid
        created += 1
    log.info(
        "categories: created=%d patched=%d unchanged=%d",
        created,
        patched,
        unchanged,
    )
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


def _association_ids(value: Any) -> set[int]:
    """Extract ids from PrestaShop's variably nested association JSON."""
    if isinstance(value, list):
        result: set[int] = set()
        for item in value:
            result.update(_association_ids(item))
        return result
    if isinstance(value, dict):
        result = set()
        if value.get("id") not in (None, ""):
            result.add(int(value["id"]))
        for key, nested in value.items():
            if key != "id":
                result.update(_association_ids(nested))
        return result
    return set()


def _product_has_image(product: dict[str, Any] | None) -> bool:
    """Read image presence from the product returned by ``display=full``.

    PrestaShop exposes image ids under the product's associations.  A GET on
    ``/images/products/{id}`` is not a reliable collection probe: this shop
    returns 404 before the first upload and 500 once an image exists.
    """
    if product is None:
        return False
    associations = product.get("associations")
    if not isinstance(associations, dict):
        return False
    return bool(_association_ids(associations.get("images", [])))


def _product_needs_patch(
    current: dict[str, Any],
    product: dict[str, Any],
    category_id: int | None,
    lang_ids: dict[str, int],
    *,
    featured: bool,
) -> bool:
    """Compare the managed product fields before issuing an expensive PUT."""
    integer_fields = {
        "active": 1 if product.get("active") else 0,
        "state": 1,
        "available_for_order": 1,
        "show_price": 1,
        "online_only": 0,
    }
    if any(
        not _integer_matches(current.get(field), desired)
        for field, desired in integer_fields.items()
    ):
        return True
    if not _decimal_matches(current.get("price"), DEFAULT_PRICE):
        return True
    if str(current.get("reference", "")) != str(product.get("reference", "")):
        return True
    if not _multilang_matches(current.get("name"), _ml(lang_ids, product, "name")):
        return True
    if not _multilang_matches(current.get("link_rewrite"), _ml_slug(lang_ids, product)):
        return True
    if not _multilang_matches(
        current.get("description"), _ml(lang_ids, product, "description")
    ):
        return True

    desired_categories: set[int] = set()
    if category_id is not None:
        desired_categories.add(category_id)
        if not _integer_matches(current.get("id_category_default"), category_id):
            return True
    if featured:
        desired_categories.add(HOME_CATEGORY_ID)

    associations = current.get("associations", {})
    if not isinstance(associations, dict):
        return bool(desired_categories)
    current_categories = _association_ids(associations.get("categories", []))
    return current_categories != desired_categories


def _combination_signature(row: dict[str, Any]) -> frozenset[int]:
    associations = row.get("associations", {})
    if not isinstance(associations, dict):
        return frozenset()
    return frozenset(_association_ids(associations.get("product_option_values", [])))


def _combination_image_ids(row: dict[str, Any]) -> list[int]:
    associations = row.get("associations", {})
    if not isinstance(associations, dict):
        return []
    return sorted(_association_ids(associations.get("images", [])))


async def _sync_combinations(
    xml_http: httpx.AsyncClient,
    pid: int,
    combos: list[dict[str, Any]],
    attr_map: dict[tuple[str, str], int],
    existing: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """Create missing variants and repair existing references/associations."""
    by_reference = {
        str(row.get("reference", "")).strip().lower(): row
        for row in existing
        if str(row.get("reference", "")).strip()
    }
    by_signature = {
        signature: row for row in existing if (signature := _combination_signature(row))
    }
    created = updated = skipped = 0
    for combo in combos:
        value_ids = [
            attr_map[key[5:], value]
            for key, value in combo.items()
            if key.startswith("attr_") and (key[5:], value) in attr_map
        ]
        if not value_ids:
            continue
        reference = str(combo.get("reference") or combo.get("id") or "").strip()
        if not reference:
            raise ValueError(f"combination for product {pid} has no stable reference")
        signature = frozenset(value_ids)
        reference_key = reference.lower()
        reference_match = by_reference.get(reference_key)
        signature_match = by_signature.get(signature)
        if (
            reference_match is not None
            and signature_match is not None
            and reference_match.get("id") != signature_match.get("id")
        ):
            raise RuntimeError(
                f"combination {reference!r} conflicts with an existing option set"
            )
        current = reference_match or signature_match
        current_signature = (
            _combination_signature(current) if current is not None else frozenset()
        )
        image_ids = _combination_image_ids(current) if current is not None else []
        image_added = False
        if combo.get("image_local") and not image_ids:
            image_id = await ps.upload_image(
                xml_http, pid, PIM_DIR / combo["image_local"]
            )
            if image_id is None:
                raise RuntimeError(
                    f"image upload for combination {reference!r} returned no id"
                )
            image_ids.append(image_id)
            image_added = True

        reference_changed = (
            current is not None
            and str(current.get("reference", "")).strip().lower() != reference_key
        )
        association_changed = current is not None and current_signature != signature
        if current is not None and not (
            reference_changed or association_changed or image_added
        ):
            skipped += 1
            continue

        blocks = [
            ps.id_list("product_option_values", "product_option_value", value_ids)
        ]
        if image_ids:
            blocks.append(ps.id_list("images", "image", image_ids))
        fields = [
            ps.field("id_product", pid),
            ps.field("reference", reference),
            ps.field("minimal_quantity", 1),
            ps.associations(*blocks),
        ]
        if current is not None:
            rid = int(current["id"])
            await ps.put(
                xml_http,
                "combinations",
                rid,
                ps.wrap("combination", ps.field("id", rid), *fields),
            )
            updated += 1
            if current_signature:
                by_signature.pop(current_signature, None)
            old_reference = str(current.get("reference", "")).strip().lower()
            if old_reference:
                by_reference.pop(old_reference, None)
            current = {**current, "reference": reference}
        else:
            root = await ps.post(
                xml_http, "combinations", ps.wrap("combination", *fields)
            )
            new_id = ps.resource_id(root)
            if new_id is None:
                raise RuntimeError(
                    f"combination {reference!r} was created without an id"
                )
            created += 1
            current = {"id": new_id, "id_product": pid, "reference": reference}
        by_reference[reference_key] = current
        by_signature[signature] = current
    return created, updated, skipped


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

    existing_products = await ps.get_all(json_http, "products")
    existing_products_by_id = {
        int(product["id"]): product
        for product in existing_products
        if product.get("id")
    }
    products_by_reference = {
        str(product.get("reference", "")).strip().lower(): int(product["id"])
        for product in existing_products
        if product.get("id") and str(product.get("reference", "")).strip()
    }
    # Name fallback adopts products created by older versions before their stable
    # PIM reference was patched in. Reference remains the primary identity.
    products_by_name = {
        _canonical_key(ps.lang_value(product.get("name"))): int(product["id"])
        for product in existing_products
        if product.get("id") and ps.lang_value(product.get("name"))
    }
    existing_combinations: dict[int, list[dict[str, Any]]] = {}
    for combination in await ps.get_all(json_http, "combinations"):
        if combination.get("id_product") is None:
            continue
        existing_combinations.setdefault(int(combination["id_product"]), []).append(
            combination
        )
    combos_by_product: dict[Any, list[dict[str, Any]]] = {}
    for combo in pim["combinations"]:
        combos_by_product.setdefault(combo["product_id"], []).append(combo)

    created = patched = skipped = images = combinations = 0
    combinations_updated = combinations_skipped = 0
    errors: list[dict[str, str]] = []

    for product in pim["products"]:
        if not product.get("active"):
            continue
        name = product["name_en"]
        reference = str(product.get("reference", "")).strip().lower()
        pid = products_by_reference.get(reference) or products_by_name.get(
            _canonical_key(name)
        )
        current_product = existing_products_by_id.get(pid) if pid is not None else None
        if pid is None:
            pid = await _create_product(xml_http, product, lang_ids)
            if pid is None:
                errors.append({"name": name, "reason": "create failed"})
                continue
            created += 1
            if reference:
                products_by_reference[reference] = pid
            products_by_name[_canonical_key(name)] = pid

        category_id = cat_map.get(product.get("category_id"))
        featured = name in FEATURED_PRODUCTS
        if current_product is not None and not _product_needs_patch(
            current_product,
            product,
            category_id,
            lang_ids,
            featured=featured,
        ):
            skipped += 1
        else:
            if await _patch_product(
                xml_http,
                pid,
                product,
                category_id,
                lang_ids,
                featured=featured,
            ):
                patched += 1
            else:
                errors.append({"name": name, "reason": "patch failed"})

        image_local = pim["images"].get(product["id"])
        if image_local and not _product_has_image(current_product):
            if await ps.upload_image(xml_http, pid, PIM_DIR / image_local) is None:
                errors.append({"name": name, "reason": "image upload returned no id"})
            else:
                images += 1

        if product["id"] in combos_by_product:
            combo_created, combo_updated, combo_skipped = await _sync_combinations(
                xml_http,
                pid,
                combos_by_product[product["id"]],
                attr_map,
                existing_combinations.get(pid, []),
            )
            combinations += combo_created
            combinations_updated += combo_updated
            combinations_skipped += combo_skipped

    summary = {
        "attribute_groups": len(group_map),
        "attributes": len(attr_map),
        "categories": len(cat_map),
        "products_created": created,
        "products_patched": patched,
        "products_skipped": skipped,
        "images_uploaded": images,
        # Kept as `combinations` for compatibility; it is the number created by
        # this pass, not the total number present in PrestaShop.
        "combinations": combinations,
        "combinations_updated": combinations_updated,
        "combinations_skipped": combinations_skipped,
        "errors": errors,
    }
    log.info("sync done: %s", summary)
    return summary
