"""Hermetic regression tests for the catalog's reconciliation guarantees."""

import xml.etree.ElementTree as ET

import httpx
import pytest

from src.internal_flows.catalog import doctor
from src.internal_flows.catalog import pool as catalog_pool
from src.internal_flows.catalog import prestashop as ps
from src.internal_flows.catalog import sync as catalog_sync
from src.internal_flows.topics import Topic


def _lang(value: str) -> list[dict[str, object]]:
    # PrestaShop's legacy Webservice serialises multilingual ids as strings.
    return [{"id": str(ps.LANG_ID), "value": value}]


def _langs(values: dict[int, str]) -> list[dict[str, object]]:
    return [
        {"id": str(language_id), "value": value}
        for language_id, value in values.items()
    ]


def test_lang_value_accepts_webservice_string_ids_and_single_language_values():
    assert ps.lang_value(_lang("Wood Type")) == "Wood Type"
    assert ps.lang_value("Wood Type") == "Wood Type"


async def test_get_all_uses_offset_pagination():
    requested_limits: list[str] = []

    def paginated(request: httpx.Request) -> httpx.Response:
        assert "page" not in request.url.params
        assert request.url.params["sort"] == "[id_ASC]"
        limit = request.url.params["limit"]
        requested_limits.append(limit)
        if limit == "0,100":
            rows = [{"id": str(i)} for i in range(100)]
        elif limit == "100,100":
            rows = [{"id": str(i)} for i in range(100, 102)]
        else:
            raise AssertionError(f"unexpected pagination request: {limit}")
        return httpx.Response(200, request=request, json={"combinations": rows})

    transport = httpx.MockTransport(paginated)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://shop.test/api"
    ) as http:
        rows = await ps.get_all(http, "combinations")

    assert len(rows) == 102
    assert requested_limits == ["0,100", "100,100"]


async def test_get_all_raises_instead_of_treating_read_failure_as_empty():
    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request, text="temporarily unavailable")

    transport = httpx.MockTransport(unavailable)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://shop.test/api"
    ) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await ps.get_all(http, "products")


async def test_attribute_group_reuses_human_label_for_pim_identifier(monkeypatch):
    async def fake_get_all(http, resource):
        assert resource == "product_options"
        # Include a duplicate left by the old bug: reconciliation adopts the oldest.
        return [
            {"id": "9", "name": _lang("Wood Type")},
            {"id": "3", "name": _lang("Wood Type")},
        ]

    async def unexpected_post(*args, **kwargs):
        raise AssertionError("an existing normalized group must not be recreated")

    monkeypatch.setattr(ps, "get_all", fake_get_all)
    monkeypatch.setattr(ps, "post", unexpected_post)

    result = await catalog_sync._sync_attribute_groups(
        object(),
        object(),
        {"attributes": [{"attribute": "wood_type", "value": "oak"}]},
    )

    assert result == {"wood_type": 3}


async def test_attribute_value_matches_normalized_name_and_string_group_id(monkeypatch):
    async def fake_get_all(http, resource):
        assert resource == "product_option_values"
        return [
            {
                "id": "11",
                "id_attribute_group": "3",
                "name": _lang("Dark Oak"),
            }
        ]

    async def unexpected_post(*args, **kwargs):
        raise AssertionError("an existing normalized value must not be recreated")

    monkeypatch.setattr(ps, "get_all", fake_get_all)
    monkeypatch.setattr(ps, "post", unexpected_post)

    result = await catalog_sync._sync_attributes(
        object(),
        object(),
        {"attributes": [{"attribute": "wood_type", "value": "dark_oak"}]},
        {"wood_type": 3},
    )

    assert result == {("wood_type", "dark_oak"): 11}


async def test_converged_category_is_not_written(monkeypatch):
    async def fake_get_all(http, resource):
        assert resource == "categories"
        return [
            {
                "id": "7",
                "active": "1",
                "id_parent": "2",
                "name": _lang("Raw Wood"),
                "link_rewrite": _lang("raw-wood"),
            }
        ]

    async def unexpected_mutation(*args, **kwargs):
        raise AssertionError("a converged category must not be mutated")

    monkeypatch.setattr(ps, "get_all", fake_get_all)
    monkeypatch.setattr(ps, "post", unexpected_mutation)
    monkeypatch.setattr(ps, "put", unexpected_mutation)

    result = await catalog_sync._sync_categories(
        object(),
        object(),
        {
            "categories": [
                {
                    "id": "CAT_RAW_WOOD",
                    "name_en": "Raw Wood",
                    "active": 1,
                }
            ]
        },
        {"en": ps.LANG_ID},
    )

    assert result == {"CAT_RAW_WOOD": 7}


def test_converged_product_does_not_need_patch():
    lang_ids = {"en": 1, "fr": 2}
    product = {
        "active": 1,
        "reference": "oak_log",
        "name_en": "Oak Log",
        "name_fr": "Bûche",
        "description_en": "English description",
        "description_fr": "Description française",
    }
    current = {
        "active": "1",
        "state": "1",
        "available_for_order": "1",
        "show_price": "1",
        "online_only": "0",
        "price": "10.000000",
        "reference": "oak_log",
        "id_category_default": "7",
        "name": _langs({1: "Oak Log", 2: "Bûche"}),
        "link_rewrite": _langs({1: "oak-log", 2: "buche"}),
        "description": _langs({1: "English description", 2: "Description française"}),
        "associations": {"categories": {"category": [{"id": "7"}]}},
    }

    assert not catalog_sync._product_needs_patch(
        current, product, 7, lang_ids, featured=False
    )

    current["show_price"] = "0"
    assert catalog_sync._product_needs_patch(
        current, product, 7, lang_ids, featured=False
    )


def test_product_image_presence_uses_product_associations():
    assert catalog_sync._product_has_image({"associations": {"images": [{"id": 24}]}})
    assert catalog_sync._product_has_image(
        {"associations": {"images": {"image": [{"id": "24"}]}}}
    )
    assert not catalog_sync._product_has_image({"associations": {"images": []}})
    assert not catalog_sync._product_has_image(None)


async def test_legacy_combination_is_adopted_without_recreation_or_image_upload(
    monkeypatch,
):
    updates: list[str] = []

    async def unexpected_create(*args, **kwargs):
        raise AssertionError("an existing combination must not be recreated")

    async def fake_put(http, resource, rid, body):
        assert resource == "combinations"
        assert rid == 70
        updates.append(body)
        return True

    monkeypatch.setattr(ps, "post", unexpected_create)
    monkeypatch.setattr(ps, "put", fake_put)
    monkeypatch.setattr(ps, "upload_image", unexpected_create)

    created, updated, skipped = await catalog_sync._sync_combinations(
        object(),
        42,
        [
            {
                "id": "oak_stairs",
                "reference": "oak_stairs",
                "attr_wood_type": "oak",
                "image_local": "images/Oak_Stairs.png",
            }
        ],
        {("wood_type", "oak"): 11},
        [
            {
                "id": "70",
                "id_product": "42",
                "reference": "",
                "associations": {
                    "product_option_values": {"product_option_value": [{"id": "11"}]},
                    "images": {"image": [{"id": "99"}]},
                },
            }
        ],
    )

    assert (created, updated, skipped) == (0, 1, 0)
    assert "<reference>oak_stairs</reference>" in updates[0]
    assert "<id>99</id>" in updates[0]


async def test_new_combination_persists_its_stable_reference(monkeypatch):
    bodies: list[str] = []

    async def fake_post(http, resource, body):
        assert resource == "combinations"
        bodies.append(body)
        return ET.fromstring(
            "<prestashop><combination><id>77</id></combination></prestashop>"
        )

    monkeypatch.setattr(ps, "post", fake_post)

    created, updated, skipped = await catalog_sync._sync_combinations(
        object(),
        42,
        [
            {
                "id": "oak_stairs",
                "reference": "oak_stairs",
                "attr_wood_type": "oak",
            }
        ],
        {("wood_type", "oak"): 11},
        [],
    )

    assert (created, updated, skipped) == (1, 0, 0)
    assert "<reference>oak_stairs</reference>" in bodies[0]


async def test_matching_combination_is_a_true_noop(monkeypatch):
    async def unexpected_mutation(*args, **kwargs):
        raise AssertionError("a converged combination must not be mutated")

    monkeypatch.setattr(ps, "post", unexpected_mutation)
    monkeypatch.setattr(ps, "put", unexpected_mutation)
    monkeypatch.setattr(ps, "upload_image", unexpected_mutation)

    result = await catalog_sync._sync_combinations(
        object(),
        42,
        [
            {
                "id": "oak_stairs",
                "reference": "oak_stairs",
                "attr_wood_type": "oak",
                "image_local": "images/Oak_Stairs.png",
            }
        ],
        {("wood_type", "oak"): 11},
        [
            {
                "id": "70",
                "id_product": "42",
                "reference": "oak_stairs",
                "associations": {
                    "product_option_values": {"product_option_value": [{"id": "11"}]},
                    "images": {"image": [{"id": "99"}]},
                },
            }
        ],
    )

    assert result == (0, 0, 1)


class _CatalogContext:
    def __init__(self) -> None:
        self.resources = {"json_http": object(), "xml_http": object()}


async def test_catalog_handler_raises_when_summary_is_incomplete(monkeypatch):
    async def incomplete(*args, **kwargs):
        return {"errors": [{"name": "Chest", "reason": "patch failed"}]}

    monkeypatch.setattr(catalog_sync, "sync_catalog", incomplete)

    with pytest.raises(RuntimeError, match="catalog sync incomplete"):
        await catalog_pool.sync(_CatalogContext(), {})


class _JsonClientContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return None


class _DoctorContext:
    def __init__(self) -> None:
        self.emitted: list[str] = []

    async def emit(self, topic: str, **payload):
        self.emitted.append(topic)


async def test_doctor_emits_full_reconciliation_even_when_existence_check_is_clean(
    monkeypatch,
):
    async def clean(http):
        return None

    monkeypatch.setattr(doctor, "json_client", _JsonClientContext)
    monkeypatch.setattr(doctor, "_detect_drift", clean)
    ctx = _DoctorContext()

    await doctor.tick(ctx)

    assert ctx.emitted == [Topic.CATALOG_SYNC]
