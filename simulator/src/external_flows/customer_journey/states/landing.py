"""Landing → catalog: open the shop, dismissing the activation page if shown."""

from src.external_flows.customer_journey.session import JourneySession

# The maintenance/landing page is dismissed by clicking the store logo.
ACTIVATION_LOGO_LINK = "h1 a:has(img[src*='logo.png'])"


class LandingState:
    name = "landing"

    def __init__(self, next_state: str = "catalog") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page
        await page.goto(
            session.base_url,
            wait_until="domcontentloaded",
            timeout=session.default_timeout_ms,
        )
        session.log.emit("page_viewed", page="landing", url=page.url)

        # The activation page may or may not be present — check briefly
        # without failing if absent.
        logo = page.locator(ACTIVATION_LOGO_LINK).first
        try:
            await logo.wait_for(state="visible", timeout=2_000)
            await logo.click()
            await page.wait_for_load_state(
                "domcontentloaded", timeout=session.default_timeout_ms
            )
            session.log.emit("activation_dismissed", url=page.url)
        except Exception:
            session.log.emit("activation_skipped")

        return self._next
