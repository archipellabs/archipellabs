"""Checkout step 2: fill the delivery address.

Phone is intentionally NOT filled: the field is optional in PrestaShop and
Faker's US phone format (with "xNNN" extensions) can fail validation silently,
which prevents the shipping section from ever rendering.
"""

from src.external_flows.customer_journey.session import JourneySession

FIELD_ADDRESS1 = "#field-address1"
FIELD_CITY = "#field-city"
FIELD_POSTCODE = "#field-postcode"
FIELD_STATE_SELECT = "#field-id_state"
FIELD_COUNTRY_SELECT = "#field-id_country"
SUBMIT = "button[data-link-action='save-address'], button[name='confirm-addresses']"

# PrestaShop country dropdown ids observed in the address form. These are the
# install's fixed `ps_country.id_country` values, not per-shop settings. Only the
# markets the shop actually sells to (see envelope.LOCATIONS) belong here.
PRESTASHOP_COUNTRY_IDS = {
    "US": "21",
    "CA": "4",
}


class CheckoutAddressState:
    name = "checkout_address"

    def __init__(self, next_state: str = "checkout_shipping") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page

        await page.locator(FIELD_ADDRESS1).wait_for(
            state="visible", timeout=session.default_timeout_ms
        )

        guest = session.guest

        # The country may already be set to the desired one; only change if needed.
        desired_country_id = PRESTASHOP_COUNTRY_IDS.get(guest.country)
        country_select = page.locator(FIELD_COUNTRY_SELECT)
        if desired_country_id and await country_select.count() > 0:
            current = await country_select.first.input_value()
            if current != desired_country_id:
                await country_select.first.select_option(value=desired_country_id)
                # Country change triggers an ajax refresh of the form.
                await page.wait_for_load_state(
                    "networkidle", timeout=session.default_timeout_ms
                )

        await page.fill(FIELD_ADDRESS1, guest.address1)
        await page.fill(FIELD_CITY, guest.city)
        await page.fill(FIELD_POSTCODE, guest.postcode)

        # Some countries (US, CA…) require a state. The dropdown is rendered
        # asynchronously after the country select loads — wait for it explicitly.
        # If it never appears, the country has no state field and we skip.
        state_select = page.locator(FIELD_STATE_SELECT)
        state_visible = False
        try:
            await state_select.first.wait_for(state="visible", timeout=3_000)
            state_visible = True
        except Exception:
            pass

        if state_visible:
            options = [
                (
                    await option.get_attribute("value"),
                    (await option.inner_text()).strip(),
                )
                for option in await state_select.locator(
                    "option[value]:not([value=''])"
                ).all()
            ]

            # The customer's own region, matched on the label the shop renders.
            # Falling back to the first option would put every customer in one
            # region, so a miss is worth a signal rather than a silent guess.
            chosen = next((opt for opt in options if opt[1] == guest.state), None)
            if chosen is None:
                chosen = options[0] if options else None
                session.log.emit("checkout_state_fallback", wanted=guest.state)

            if chosen is not None:
                await state_select.first.select_option(value=chosen[0])
                session.log.emit("checkout_state_selected", state=chosen[1])
            else:
                session.log.emit("checkout_state_unavailable")

        session.log.emit(
            "checkout_step_completed",
            step="address",
            country=guest.country,
            city=guest.city,
            postcode=guest.postcode,
        )

        await page.locator(SUBMIT).first.click()
        return self._next
