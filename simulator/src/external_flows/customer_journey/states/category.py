"""Landing → category: pick a category from the home "shop by category" tiles."""

import re

from src.external_flows.customer_journey.session import JourneySession

# Categories now live as tiles in the home "shop by category" section (the
# ps_mainmenu top-menu is no longer the catalogue entry point). Each tile is an
# <a.tw-cat> wrapping a <.tw-cat__name> label; we disambiguate on the label so
# "Wood" doesn't accidentally match "Raw Wood".
CATEGORY_LINK = "a.tw-cat"
CATEGORY_NAME = ".tw-cat__name"


class CategoryState:
    name = "category"

    def __init__(
        self,
        category_name: str,
        next_state: str = "catalog",
    ) -> None:
        self._category_name = category_name
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page

        # The category tiles live only on the home, so navigate there first. This
        # state runs both right after landing AND again mid-journey (e.g. the 2nd
        # category of a multi-item run), where the page is elsewhere and the tiles
        # would be absent.
        await page.goto(
            session.base_url,
            wait_until="domcontentloaded",
            timeout=session.default_timeout_ms,
        )

        # Exact-match on the tile label so "Wood" doesn't accidentally pick
        # "Raw Wood" or "Processed Wood".
        exact = re.compile(rf"^\s*{re.escape(self._category_name)}\s*$")
        link = page.locator(
            CATEGORY_LINK, has=page.locator(CATEGORY_NAME, has_text=exact)
        ).first
        await link.wait_for(state="visible", timeout=session.default_timeout_ms)
        href = await link.get_attribute("href")

        session.data["selected_category"] = {"name": self._category_name, "url": href}
        session.log.emit("category_clicked", category=self._category_name, url=href)

        await link.click()
        await page.wait_for_load_state(
            "domcontentloaded", timeout=session.default_timeout_ms
        )
        return self._next
