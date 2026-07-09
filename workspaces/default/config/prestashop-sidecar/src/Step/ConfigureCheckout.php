<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Checkout policy. Keeps a single, properly named carrier — the only demo
 * carrier that already covers the North-America zone (id_reference 2, shipped as
 * "My carrier") — renamed and set as default, with every other carrier
 * disabled. Restricts payment to bank wire only (disables the other payment
 * modules) and fills in its placeholder bank-account details so they show on the
 * payment step and order-confirmation page. Idempotent: re-running re-applies the
 * same name/state and is a no-op once everything is already in place.
 */
final class ConfigureCheckout extends BaseStep
{
    private const CARRIER_REFERENCE = 2;
    private const CARRIER_NAME = 'TimberWorks Delivery';
    /** Multilang "delivery time" text, keyed by language iso. */
    private const CARRIER_DELAY = [
        'en' => 'Delivered in 3-5 business days',
        'fr' => 'Livraison en 3 à 5 jours ouvrés',
    ];
    private const KEEP_PAYMENT_MODULE = 'ps_wirepayment';
    private const DISABLE_PAYMENT_MODULES = ['ps_checkpayment', 'ps_cashondelivery', 'ps_checkout'];

    // Placeholder North-America bank details (USD/CAD scope, not a French RIB).
    // They render on the payment step AND the order-confirmation page, which is
    // how a customer gets them while there's no transactional email yet.
    private const BANK_WIRE_OWNER = 'TimberWorks Inc.';
    /** Free-text blocks; the module runs them through nl2br, so \n becomes <br>. */
    private const BANK_WIRE_DETAILS = "Account #: 0123456789\nRouting (ABA): 021000021\nSWIFT/BIC: EVRGUS33";
    private const BANK_WIRE_ADDRESS = "Evergreen National Bank\n500 Cedar Avenue, Portland, OR 97201, USA";
    /** Per-language note shown with the details (BANK_WIRE_CUSTOM_TEXT is multilang). */
    private const BANK_WIRE_CUSTOM_TEXT = [
        'en' => 'Orders ship once we receive your transfer (typically 1-3 business days). Please use your order reference as the payment reference.',
        'fr' => 'Les commandes sont expédiées dès réception de votre virement (généralement 1 à 3 jours ouvrés). Merci d’indiquer votre numéro de commande en référence du paiement.',
    ];
    /** Informational only — adds a "goods reserved N days" line; nothing enforces it. */
    private const BANK_WIRE_RESERVATION_DAYS = 7;

    public function description(): string
    {
        return 'Checkout: single named carrier + bank-wire-only payment.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        $this->configureCarrier($ctx);
        $this->restrictToBankWire($ctx);
        $this->configureBankWire($ctx);
    }

    private function configureBankWire(Context $ctx): void
    {
        \Configuration::updateValue('BANK_WIRE_OWNER', self::BANK_WIRE_OWNER);
        \Configuration::updateValue('BANK_WIRE_DETAILS', self::BANK_WIRE_DETAILS);
        \Configuration::updateValue('BANK_WIRE_ADDRESS', self::BANK_WIRE_ADDRESS);

        \Configuration::updateValue('BANK_WIRE_CUSTOM_TEXT', $ctx->localized(self::BANK_WIRE_CUSTOM_TEXT));
        \Configuration::updateValue('BANK_WIRE_RESERVATION_DAYS', self::BANK_WIRE_RESERVATION_DAYS);

        // Ensure the details block is shown to the customer.
        \Configuration::updateValue('BANK_WIRE_PAYMENT_INVITE', true);

        $ctx->log->info('Bank wire details configured (owner: ' . self::BANK_WIRE_OWNER . ')');
    }

    private function configureCarrier(Context $ctx): void
    {
        $carrier = \Carrier::getCarrierByReference(self::CARRIER_REFERENCE);
        if (!\Validate::isLoadedObject($carrier)) {
            $ctx->log->info('Carrier reference ' . self::CARRIER_REFERENCE . ' not found — skipping carrier setup');

            return;
        }

        $carrier->name = self::CARRIER_NAME;
        $carrier->delay = $ctx->localized(self::CARRIER_DELAY);
        $carrier->active = true;
        $carrier->save();
        \Configuration::updateValue('PS_CARRIER_DEFAULT', (int) $carrier->id);
        $ctx->log->info('Carrier "' . self::CARRIER_NAME . '" (id=' . (int) $carrier->id . ') set + default');

        // Disable every other carrier so checkout offers this one only.
        $disabled = 0;
        $langId = (int) \Configuration::get('PS_LANG_DEFAULT');
        foreach (\Carrier::getCarriers($langId) as $row) {
            if ((int) $row['id_carrier'] === (int) $carrier->id) {
                continue;
            }
            $other = new \Carrier((int) $row['id_carrier']);
            if ($other->active) {
                $other->active = false;
                $other->save();
                $disabled++;
            }
        }
        $ctx->log->info("Disabled {$disabled} other carrier(s)");
    }

    private function restrictToBankWire(Context $ctx): void
    {
        foreach (self::DISABLE_PAYMENT_MODULES as $name) {
            if (\Module::isInstalled($name) && \Module::isEnabled($name)) {
                \Module::disableByName($name);
                $ctx->log->info("Disabled payment module {$name}");
            }
        }

        // Make sure the one method we keep is actually available.
        if (\Module::isInstalled(self::KEEP_PAYMENT_MODULE) && !\Module::isEnabled(self::KEEP_PAYMENT_MODULE)) {
            $wire = \Module::getInstanceByName(self::KEEP_PAYMENT_MODULE);
            if ($wire) {
                $wire->enable();
                $ctx->log->info('Enabled payment module ' . self::KEEP_PAYMENT_MODULE);
            }
        }
        $ctx->log->info('Payment restricted to bank wire (' . self::KEEP_PAYMENT_MODULE . ')');
    }
}
