<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Payment policy. Restricts payment to bank wire only (disables the other
 * payment modules) and fills in its placeholder bank-account details so they
 * show on the payment step and order-confirmation page. Idempotent: re-running
 * re-applies the same state and is a no-op once everything is in place.
 *
 * Carriers are NOT configured here. They used to be — this step renamed demo
 * carrier id_reference 2 and disabled every other one — but shipping geography
 * and carriers now belong to ConfigureNorthAmerica, which owns zones, coverage
 * and pricing together. Two steps configuring carriers meant the later one
 * disabling what the earlier one had just created.
 */
final class ConfigureCheckout extends BaseStep
{
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
        return 'Checkout: bank-wire-only payment, with its details filled in.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
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
