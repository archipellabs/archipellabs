<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Scopes the shop to North America: enables US + Canada (disables every other
 * country), ensures USD + CAD currencies with USD as default, and disables the
 * stray GBP that ships with the install. Idempotent.
 *
 * It also owns the shop's shipping geography end to end, because the install
 * leaves a lot behind: eight enabled zones covering countries the shop does not
 * sell to, carriers still serving Europe from the original GB/GBP install, and
 * three demo carriers with full price tables. All of it is inert — and all of it
 * is noise for anyone (or anything) later asking "who can we actually ship to?".
 *
 * So the shipping setup is DECLARED here rather than inherited:
 *
 *  - one zone per country, so coverage can differ between markets — out of the
 *    box both sit in a single "North America" zone, and one country cannot then
 *    lose its carrier without the other losing it too;
 *  - a zone is enabled if and only if it holds an active country;
 *  - exactly the carriers in CARRIERS exist, serving exactly the zones named
 *    there at a flat rate; every other carrier is removed.
 */
final class ConfigureNorthAmerica extends BaseStep
{
    private const ENABLED_COUNTRIES = ['US', 'CA'];
    /** US military postal regions — codes, not states, and unserviceable. */
    private const NON_CIVILIAN_STATES = ['AA', 'AE', 'AP'];
    private const DEFAULT_COUNTRY = 'US';
    private const DEFAULT_CURRENCY = 'USD';
    private const DISABLE_CURRENCIES = ['GBP'];
    /** One shipping zone per country, so coverage can differ between them. */
    private const COUNTRY_ZONES = ['US' => 'United States', 'CA' => 'Canada'];
    /** Flat shipping price, per zone, for every carrier. */
    private const SHIPPING_FLAT_RATE = 5.00;
    /** Widest sensible price range; one range per carrier keeps pricing flat. */
    private const PRICE_RANGE_MAX = 10000.0;
    /**
     * The shop's carriers, and the only ones that survive this step. The
     * domestic carrier deliberately does NOT serve Canada: a market that loses
     * cross-border shipping then still has a working option at home, which is
     * how a real shop degrades and what makes the two markets independently
     * observable.
     *
     * name => [zones (from COUNTRY_ZONES), delay per language iso]
     */
    private const CARRIERS = [
        'TimberWorks Ground' => [
            'zones' => ['United States'],
            'delay' => [
                'en' => 'Delivered in 3-5 business days',
                'fr' => 'Livraison en 3 à 5 jours ouvrés',
            ],
        ],
        'TimberWorks Cross-Border' => [
            'zones' => ['United States', 'Canada'],
            'delay' => [
                'en' => 'Delivered in 5-8 business days',
                'fr' => 'Livraison en 5 à 8 jours ouvrés',
            ],
        ],
    ];
    /** iso => fields (rate vs USD, ISO-4217 numeric, symbol, per-language names). */
    private const CURRENCY_DATA = [
        'USD' => [
            'rate' => 1.0, 'numeric' => 840, 'symbol' => '$',
            'name' => ['en' => 'US Dollar', 'fr' => 'Dollar des États-Unis'],
        ],
        'CAD' => [
            'rate' => 1.35, 'numeric' => 124, 'symbol' => 'CA$',
            'name' => ['en' => 'Canadian Dollar', 'fr' => 'Dollar canadien'],
        ],
    ];

    public function description(): string
    {
        return 'Scope to North America: US + Canada, USD + CAD, zones and carriers.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        $this->configureCurrencies($ctx);
        $this->configureCountries($ctx);
        $this->configureZones($ctx);
        $this->configureCarriers($ctx);
        $this->configurePaymentRestrictions($ctx);
    }

    private function configureCurrencies(Context $ctx): void
    {
        foreach (self::CURRENCY_DATA as $iso => $data) {
            $this->ensureCurrency($ctx, $iso, $data);
        }

        $defaultId = (int) \Currency::getIdByIsoCode(self::DEFAULT_CURRENCY);
        if ($defaultId) {
            \Configuration::updateValue('PS_CURRENCY_DEFAULT', $defaultId);
            $ctx->log->info('Default currency = ' . self::DEFAULT_CURRENCY . " (id={$defaultId})");
        }

        // Disable stray currencies only after the new default is set.
        foreach (self::DISABLE_CURRENCIES as $iso) {
            $id = (int) \Currency::getIdByIsoCode($iso);
            if (!$id) {
                continue;
            }
            $currency = new \Currency($id);
            if ($currency->active) {
                $currency->active = false;
                $currency->save();
                $ctx->log->info("Disabled currency {$iso}");
            }
        }
    }

    /** @param array{rate: float, numeric: int, symbol: string, name: array<string, string>} $data */
    private function ensureCurrency(Context $ctx, string $iso, array $data): void
    {
        $id = (int) \Currency::getIdByIsoCode($iso);
        if ($id) {
            $currency = new \Currency($id);
            if (!$currency->active) {
                $currency->active = true;
                $currency->save();
                $ctx->log->info("Enabled currency {$iso}");
            }
            return;
        }

        // Fill the localized fields by hand — CLDR's LocaleRepository isn't wired
        // in this CLI bootstrap (no Symfony container), so we don't call
        // refreshLocalizedCurrencyData. Keyed per active language.
        $name = $symbol = $pattern = [];
        foreach (\Language::getLanguages(false) as $lang) {
            $lid = (int) $lang['id_lang'];
            $name[$lid] = $data['name'][$lang['iso_code']] ?? $data['name']['en'];
            $symbol[$lid] = $data['symbol'];
            $pattern[$lid] = $lang['iso_code'] === 'fr' ? '#,##0.00 ¤' : '¤#,##0.00';
        }

        $currency = new \Currency();
        $currency->iso_code = $iso;
        $currency->numeric_iso_code = (string) $data['numeric'];
        $currency->precision = 2;
        $currency->conversion_rate = $data['rate'];
        $currency->active = true;
        $currency->name = $name;
        $currency->symbol = $symbol;
        $currency->pattern = $pattern;
        if (!$currency->add()) {
            throw new \RuntimeException("Failed to create currency {$iso}");
        }
        $ctx->log->info("Created currency {$iso} (id={$currency->id})");
    }

    /**
     * Bulk activation stays raw SQL on purpose: the alternative is loading and
     * saving ~250 multilang Country objects to switch one flag, which is slower
     * and drags in the container-backed paths this CLI bootstrap cannot build.
     */
    private function configureCountries(Context $ctx): void
    {
        $db = $ctx->db();
        $enabled = implode(
            ',',
            array_map(static fn (string $iso) => '"' . pSQL($iso) . '"', self::ENABLED_COUNTRIES)
        );
        $db->execute('UPDATE ' . _DB_PREFIX_ . 'country SET active = 0');
        $db->execute(
            'UPDATE ' . _DB_PREFIX_ . 'country SET active = 1 WHERE iso_code IN (' . $enabled . ')'
        );
        $ctx->log->info('Enabled countries: ' . implode(', ', self::ENABLED_COUNTRIES));

        $defaultCountry = (int) \Country::getByIso(self::DEFAULT_COUNTRY);
        if ($defaultCountry) {
            \Configuration::updateValue('PS_COUNTRY_DEFAULT', $defaultCountry);
            $ctx->log->info('Default country = ' . self::DEFAULT_COUNTRY . " (id={$defaultCountry})");
        }

        $this->disableNonCivilianStates($ctx);
    }

    /**
     * The US state list ships with three military postal regions whose name is
     * just their code — "AA", "AE", "AP" (Armed Forces Americas / Europe /
     * Pacific). They sit in the dropdown between Alabama and Alaska, so the
     * list reads as a mix of two-letter codes and real state names, and no
     * carrier covers them anyway.
     */
    private function disableNonCivilianStates(Context $ctx): void
    {
        $disabled = 0;
        foreach (self::NON_CIVILIAN_STATES as $iso) {
            $id = (int) \State::getIdByIso($iso, (int) \Country::getByIso('US'));
            if (!$id) {
                continue;
            }
            $state = new \State($id);
            if (!$state->active) {
                continue;
            }
            $state->active = false;
            $state->save();
            $disabled++;
        }
        if ($disabled) {
            $ctx->log->info("Disabled {$disabled} military postal region(s): " . implode(', ', self::NON_CIVILIAN_STATES));
        }
    }

    /**
     * One zone per served country, and nothing else enabled.
     *
     * The rule is declarative — a zone is active if and only if it holds an
     * active country — so the eight zones the install ships with switch
     * themselves off here, and would come back on by themselves if a country in
     * one were ever enabled again.
     */
    private function configureZones(Context $ctx): void
    {
        foreach (self::COUNTRY_ZONES as $iso => $zoneName) {
            $this->moveCountryToZone($ctx, $iso, $this->ensureZone($ctx, $zoneName));
        }

        $langId = (int) \Configuration::get('PS_LANG_DEFAULT');
        $served = [];
        foreach (\Country::getCountries($langId, true) as $country) {
            $served[(int) $country['id_zone']] = true;
        }

        $off = [];
        foreach (\Zone::getZones(false) as $row) {
            $zone = new \Zone((int) $row['id_zone']);
            $wanted = isset($served[(int) $zone->id]);
            if (!$wanted) {
                $off[] = $zone->name;
            }
            if ((bool) $zone->active !== $wanted) {
                $zone->active = $wanted;
                $zone->update();
            }
        }

        $ctx->log->info(
            'Zones enabled: ' . implode(', ', self::COUNTRY_ZONES)
            . ' — disabled (no active country): ' . (implode(', ', $off) ?: 'none')
        );
    }

    private function ensureZone(Context $ctx, string $name): int
    {
        $id = (int) \Zone::getIdByName($name);
        if ($id) {
            return $id;
        }

        $zone = new \Zone();
        $zone->name = $name;
        $zone->active = true;
        if (!$zone->add()) {
            throw new \RuntimeException("Failed to create zone {$name}");
        }
        $ctx->log->info("Created zone {$name} (id={$zone->id})");

        return (int) $zone->id;
    }

    /**
     * Move a country AND every one of its states into the zone.
     *
     * The states are not a detail. Address::getZoneById() prefers the state's
     * zone over the country's whenever the address has one, so for a country
     * with states — which both of ours have — the state rows are what actually
     * decide which carriers a customer is offered. Move only the country and
     * checkout silently offers no delivery method at all, because every US and
     * Canadian state still points at the zone the install shipped them in.
     */
    private function moveCountryToZone(Context $ctx, string $iso, int $zoneId): void
    {
        $countryId = (int) \Country::getByIso($iso);
        if (!$countryId) {
            throw new \RuntimeException("Unknown country {$iso}");
        }

        $country = new \Country($countryId);
        if ((int) $country->id_zone !== $zoneId) {
            $country->id_zone = $zoneId;
            if (!$country->save()) {
                throw new \RuntimeException("Failed to move {$iso} to zone {$zoneId}");
            }
            $ctx->log->info("Country {$iso} now in zone id={$zoneId}");
        }

        $moved = 0;
        foreach (\State::getStatesByIdCountry($countryId) as $row) {
            $state = new \State((int) $row['id_state']);
            if ((int) $state->id_zone === $zoneId) {
                continue;
            }
            $state->id_zone = $zoneId;
            $state->save();
            $moved++;
        }
        if ($moved) {
            $ctx->log->info("Country {$iso}: moved {$moved} state(s) into zone id={$zoneId}");
        }
    }

    /**
     * Exactly the declared carriers, serving exactly their declared zones at the
     * flat rate — and nothing else.
     *
     * Pricing is declared here rather than copied from whatever the install
     * seeded, so no zone has to survive as a pricing template and the shop's
     * whole shipping table is readable from this file.
     */
    private function configureCarriers(Context $ctx): void
    {
        $keep = [];
        foreach (self::CARRIERS as $name => $spec) {
            $carrier = $this->ensureCarrier($ctx, $name, $spec['delay']);
            $keep[] = (int) $carrier->id;
            $this->applyCoverage($ctx, $carrier, $spec['zones']);
        }

        $this->removeCarriersExcept($ctx, $keep);
        $this->forgetCarrierList();

        \Configuration::updateValue('PS_CARRIER_DEFAULT', $keep[0]);
        $ctx->log->info('Default carrier = ' . array_key_first(self::CARRIERS));
    }

    /**
     * Drop PrestaShop's memoised carrier list.
     *
     * Carrier::getCarriers() caches per SQL hash in a static that lives for the
     * whole process, and it does not invalidate when carriers change. Anything
     * that reads the list after this step has rewritten it would otherwise get
     * the carriers the install shipped with — including PrestaShop's own
     * addCheckboxCarrierRestrictionsForModule(), which then grants the payment
     * module to carriers that no longer exist and leaves checkout with no
     * payment method. Only a from-scratch run shows this: on a re-run the
     * carriers already exist when the list is first cached.
     */
    private function forgetCarrierList(): void
    {
        \Cache::clean('Carrier::getCarriers_*');
    }

    /**
     * Live carriers, keyed by id. ALL_CARRIERS because "everything else goes"
     * has to mean module carriers too.
     *
     * @return array<int, string> id => name
     */
    private function liveCarriers(): array
    {
        // Read through the cache, not from it: this step creates and removes
        // carriers between calls, so a memoised list is wrong by construction.
        $this->forgetCarrierList();

        $langId = (int) \Configuration::get('PS_LANG_DEFAULT');
        $rows = \Carrier::getCarriers($langId, false, false, false, null, \Carrier::ALL_CARRIERS);

        $byId = [];
        foreach ($rows as $row) {
            $byId[(int) $row['id_carrier']] = (string) $row['name'];
        }

        return $byId;
    }

    /** @param array<string, string> $delay */
    private function ensureCarrier(Context $ctx, string $name, array $delay): \Carrier
    {
        $found = array_search($name, $this->liveCarriers(), true);
        $id = false === $found ? 0 : (int) $found;

        $carrier = $id ? new \Carrier($id) : new \Carrier();
        $carrier->name = $name;
        $carrier->active = true;
        $carrier->is_free = false;
        // Off, so the price a customer pays is exactly the declared flat rate —
        // handling would silently add the shop-wide fee on top of it.
        $carrier->shipping_handling = false;
        $carrier->shipping_method = \Carrier::SHIPPING_METHOD_PRICE;
        $carrier->range_behavior = 0; // out of range: charge the highest range
        $carrier->need_range = true;
        $carrier->is_module = false;
        $carrier->shipping_external = false;
        $carrier->url = '';
        $carrier->grade = 0;
        $carrier->max_width = 0;
        $carrier->max_height = 0;
        $carrier->max_depth = 0;
        $carrier->max_weight = 0;
        $carrier->delay = $ctx->localized($delay);

        if (!($id ? $carrier->update() : $carrier->add())) {
            throw new \RuntimeException("Failed to save carrier {$name}");
        }
        if (!$id) {
            $ctx->log->info("Created carrier {$name} (id={$carrier->id})");
        }

        // Every customer group, or the carrier never appears at checkout.
        $groups = \Group::getGroups((int) \Configuration::get('PS_LANG_DEFAULT'));
        $carrier->setGroups(array_column($groups, 'id_group'));

        return $carrier;
    }

    /**
     * A carrier_zone row alone is not enough: without a matching ps_delivery row
     * the carrier is linked to the zone but quotes no price, and the storefront
     * silently offers no shipping method at all — the same symptom as having no
     * carrier, from a different cause.
     *
     * addZone() seeds those rows at price 0 with a NULL id_shop, while
     * addDeliveryPrice() writes — and deletes — rows scoped to the current shop.
     * Its delete-then-insert therefore never matches the zero rows, and the two
     * sets accumulate side by side. Clearing the carrier's rows outright is what
     * makes this converge, whatever an earlier version of this step left behind.
     *
     * @param list<string> $zoneNames
     */
    private function applyCoverage(Context $ctx, \Carrier $carrier, array $zoneNames): void
    {
        $db = $ctx->db();

        $wanted = [];
        foreach ($zoneNames as $zoneName) {
            $zoneId = (int) \Zone::getIdByName($zoneName);
            if (!$zoneId) {
                throw new \RuntimeException("Missing zone: {$zoneName}");
            }
            $wanted[] = $zoneId;
        }

        $linked = array_map(
            static fn (array $row): int => (int) $row['id_zone'],
            $carrier->getZones() ?: []
        );
        foreach (array_diff($linked, $wanted) as $stale) {
            $carrier->deleteZone($stale);
        }
        foreach (array_diff($wanted, $linked) as $missing) {
            $carrier->addZone($missing);
        }

        $rangeId = $this->ensurePriceRange($ctx, $carrier);

        // The one place raw SQL beats the API here: deleteDeliveryPrice() scopes
        // its DELETE to the current shop, so it cannot reach rows addZone() wrote
        // with a NULL id_shop. Using it would leave exactly the zero-price
        // duplicates described above.
        $db->execute(
            'DELETE FROM ' . _DB_PREFIX_ . 'delivery WHERE id_carrier = ' . (int) $carrier->id
        );

        $priceList = [];
        foreach ($wanted as $zoneId) {
            $priceList[] = [
                'id_carrier' => (int) $carrier->id,
                'id_range_price' => $rangeId,
                'id_range_weight' => 0,
                'id_zone' => $zoneId,
                'price' => self::SHIPPING_FLAT_RATE,
            ];
        }
        $carrier->addDeliveryPrice($priceList);

        $ctx->log->info(
            "Carrier {$carrier->name}: serves " . implode(' + ', $zoneNames)
            . ' at ' . number_format(self::SHIPPING_FLAT_RATE, 2)
        );
    }

    /** Exactly one range wide enough for any cart, so the rate is truly flat. */
    private function ensurePriceRange(Context $ctx, \Carrier $carrier): int
    {
        $rows = \RangePrice::getRanges((int) $carrier->id) ?: [];

        foreach (array_slice($rows, 1) as $extra) {
            (new \RangePrice((int) $extra['id_range_price']))->delete();
            $ctx->log->info("Carrier {$carrier->name}: dropped an extra price range");
        }

        $range = $rows ? new \RangePrice((int) $rows[0]['id_range_price']) : new \RangePrice();
        $range->id_carrier = (int) $carrier->id;
        $range->delimiter1 = 0;
        $range->delimiter2 = self::PRICE_RANGE_MAX;

        if (!($rows ? $range->update() : $range->add())) {
            throw new \RuntimeException("Failed to save price range for {$carrier->name}");
        }

        return (int) $range->id;
    }

    /**
     * Everything else goes: the install's demo carriers, and anything left over
     * from an earlier shape of this step.
     *
     * @param list<int> $keep
     */
    private function removeCarriersExcept(Context $ctx, array $keep): void
    {
        $removed = 0;
        foreach ($this->liveCarriers() as $id => $name) {
            if (in_array($id, $keep, true)) {
                continue;
            }

            // softDelete(), not delete(): the full cascade resolves services
            // through the Symfony container, which this CLI bootstrap never
            // builds. It is also what the back office does — flagging the row
            // keeps past orders able to name the carrier that shipped them,
            // which a hard delete would take away.
            $carrier = new \Carrier($id);
            if ($ctx->quietly(static fn (): bool => (bool) $carrier->softDelete())) {
                $ctx->log->info("Removed carrier {$name} (id={$id})");
                $removed++;
            }
        }

        if ($removed) {
            \Carrier::cleanPositions();
        }
    }

    /**
     * The install scoped the payment modules to the old GBP/GB pair, so no
     * payment method matches a USD/CAD cart shipped to the US/CA. Re-run the
     * same logic the BO "Payment > Preferences" screen applies: clear each
     * module's restrictions, then let PrestaShop re-grant the shop's currencies,
     * its *active* countries (US + CA) and its carriers. The DELETEs keep this
     * idempotent — the helpers use plain INSERTs that would collide on re-run.
     *
     * Carriers matter here because this step replaces them. Carrier::add() does
     * seed ps_module_carrier itself, but it does so by iterating
     * Module::getPaymentModules(), which needs a customer context this CLI
     * bootstrap has not got — so it silently inserts nothing, the payment module
     * stays bound to the carriers it was installed with, and checkout offers no
     * payment method at all once those carriers are gone. Hence: run this AFTER
     * the carriers exist.
     */
    private function configurePaymentRestrictions(Context $ctx): void
    {
        $db = $ctx->db();
        $count = 0;
        foreach (\PaymentModule::getInstalledPaymentModules() as $row) {
            $module = \Module::getInstanceByName($row['name']);
            if (!$module instanceof \PaymentModule) {
                continue;
            }
            $id = (int) $module->id;
            $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'module_currency WHERE id_module = ' . $id);
            $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'module_country WHERE id_module = ' . $id);
            $db->execute('DELETE FROM ' . _DB_PREFIX_ . 'module_carrier WHERE id_module = ' . $id);
            $module->addCheckboxCurrencyRestrictionsForModule();
            $module->addCheckboxCountryRestrictionsForModule();
            $module->addCheckboxCarrierRestrictionsForModule();
            $ctx->log->info("Payment {$row['name']}: granted currencies + active countries + carriers");
            $count++;
        }
        $ctx->log->info("Configured {$count} payment module(s) for North America");
    }
}
