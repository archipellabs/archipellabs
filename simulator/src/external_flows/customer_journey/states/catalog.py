"""Catalog → product: pick the first in-stock product."""

from src.external_flows.customer_journey.session import JourneySession

# Product miniatures on the home/catalog page. Out-of-stock products carry an
# extra `.product-flags .out_of_stock` badge (rendered only when out of stock) we
# use to filter them out. The title is the miniature's own `<a>` link.
PRODUCT_MINIATURE = ".products .product-miniature"
PRODUCT_OUT_OF_STOCK_FLAG = ".product-flags .out_of_stock"
PRODUCT_TITLE_LINK = "a.product-miniature__title"


class CatalogState:
    name = "catalog"

    def __init__(self, next_state: str = "product") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page
        miniatures = page.locator(PRODUCT_MINIATURE)
        await miniatures.first.wait_for(
            state="visible", timeout=session.default_timeout_ms
        )

        count = await miniatures.count()
        session.log.emit("product_list_viewed", visible_products=count)

        target = None
        for i in range(count):
            tile = miniatures.nth(i)
            if await tile.locator(PRODUCT_OUT_OF_STOCK_FLAG).count() > 0:
                continue
            target = tile
            break

        if target is None:
            raise RuntimeError("No in-stock products on the catalog page")

        link = target.locator(PRODUCT_TITLE_LINK).first
        name = (await link.inner_text()).strip()
        href = await link.get_attribute("href")

        session.data["selected_product"] = {"name": name, "url": href}
        session.log.emit("product_clicked", product_name=name, product_url=href)

        await link.click()
        await page.wait_for_load_state(
            "domcontentloaded", timeout=session.default_timeout_ms
        )
        return self._next
