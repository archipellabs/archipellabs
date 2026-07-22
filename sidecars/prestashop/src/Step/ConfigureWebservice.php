<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Enables the PrestaShop Webservice and creates a full-access API key using PS
 * native classes (WebserviceKey, Configuration). Fully idempotent: re-running
 * reuses the existing key and re-applies permissions.
 */
final class ConfigureWebservice extends BaseStep
{
    /**
     * Every Webservice resource, granted all HTTP methods.
     *
     * @var list<string>
     */
    private const RESOURCES = [
        'addresses', 'attachments', 'carriers', 'cart_rules', 'carts', 'categories',
        'combinations', 'configurations', 'contacts', 'content_management_system',
        'countries', 'currencies', 'customer_messages', 'customer_threads', 'customers',
        'customizations', 'deliveries', 'employees', 'groups', 'guests', 'image_types',
        'images', 'languages', 'manufacturers', 'messages', 'order_carriers',
        'order_cart_rules', 'order_details', 'order_histories', 'order_invoices',
        'order_payments', 'order_slip', 'order_states', 'orders', 'price_ranges',
        'product_customization_fields', 'product_feature_values', 'product_features',
        'product_option_values', 'product_options', 'product_suppliers', 'products',
        'search', 'shop_groups', 'shop_urls', 'shops', 'specific_price_rules',
        'specific_prices', 'states', 'stock_availables', 'stock_movement_reasons',
        'stock_movements', 'stocks', 'stores', 'suppliers', 'supply_order_details',
        'supply_order_histories', 'supply_order_receipt_histories', 'supply_order_states',
        'supply_orders', 'tags', 'tax_rule_groups', 'tax_rules', 'taxes',
        'translated_configurations', 'warehouse_product_locations', 'warehouses',
        'weight_ranges', 'zones',
    ];

    public function description(): string
    {
        return 'Enable the Webservice API and create a full-access key.';
    }

    public function apply(Context $ctx): void
    {
        $ctx->prestashop->boot();
        $apiKey = $ctx->config->webserviceApiKey();

        \Configuration::updateValue('PS_WEBSERVICE', 1);
        $ctx->log->info('Webservice enabled');

        $accountId = $this->ensureKey($ctx, $apiKey);
        $this->grantPermissions($accountId);

        $ctx->log->info('Granted permissions on ' . \count(self::RESOURCES) . ' resources');
    }

    private function ensureKey(Context $ctx, string $apiKey): int
    {
        $existingId = \WebserviceKey::getIdFromKey($apiKey);

        if ($existingId) {
            $ctx->log->info("Webservice key already exists (id={$existingId})");

            return (int) $existingId;
        }

        $account = new \WebserviceKey();
        $account->key = $apiKey;
        $account->description = 'Archipellabs API key';
        $account->active = 1;

        // ObjectModel::add() raises a PS-internal null-property notice here.
        $saved = $ctx->quietly(fn () => $account->save());

        if (!$saved) {
            throw new \RuntimeException('Failed to save the webservice key');
        }

        $ctx->log->info("Webservice key created (id={$account->id})");

        return (int) $account->id;
    }

    private function grantPermissions(int $accountId): void
    {
        $methods = ['GET' => 1, 'POST' => 1, 'PUT' => 1, 'PATCH' => 1, 'DELETE' => 1, 'HEAD' => 1];

        $permissions = [];
        foreach (self::RESOURCES as $resource) {
            $permissions[$resource] = $methods;
        }

        \WebserviceKey::setPermissionForAccount($accountId, $permissions);
    }
}
