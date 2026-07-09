<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Scopes the shop to North America: enables US + Canada (disables every other
 * country), ensures USD + CAD currencies with USD as default, and disables the
 * stray GBP that ships with the install. Idempotent.
 */
final class ConfigureNorthAmerica extends BaseStep
{
    private const ENABLED_COUNTRIES = ['US', 'CA'];
    private const DEFAULT_COUNTRY = 'US';
    private const DEFAULT_CURRENCY = 'USD';
    private const DISABLE_CURRENCIES = ['GBP'];
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
        return 'Scope to North America: US + Canada, USD + CAD (USD default).';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        $this->configureCurrencies($ctx);
        $this->configureCountries($ctx);
        $this->configurePaymentRestrictions($ctx);
    }

    /**
     * The install scoped the payment modules to the old GBP/GB pair, so no
     * payment method matches a USD/CAD cart shipped to the US/CA. Re-run the
     * same logic the BO "Payment > Preferences" screen applies: clear each
     * module's restrictions, then let PrestaShop re-grant the shop's currencies
     * and its *active* countries (US + CA). The DELETE keeps this idempotent —
     * the currency helper uses a plain INSERT that would collide on re-run.
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
            $module->addCheckboxCurrencyRestrictionsForModule();
            $module->addCheckboxCountryRestrictionsForModule();
            $ctx->log->info("Payment {$row['name']}: granted currencies + active countries");
            $count++;
        }
        $ctx->log->info("Configured {$count} payment module(s) for North America");
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
    }
}
