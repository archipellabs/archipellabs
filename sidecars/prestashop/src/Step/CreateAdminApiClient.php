<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Step;

use Archipel\Provisioning\Kernel\BaseStep;
use Archipel\Provisioning\Kernel\Context;

/**
 * Creates the OAuth2 Admin API client via the PrestaShop console (the only path
 * that exists for it). Idempotent: skipped when a client with the same id is
 * already registered.
 */
final class CreateAdminApiClient extends BaseStep
{
    public function description(): string
    {
        return 'Create the OAuth2 Admin API client (all scopes).';
    }

    public function isApplied(Context $ctx): bool
    {
        $clientId = $ctx->config->adminApiClientId();
        $db = $ctx->db();

        $existing = $db->getValue(
            'SELECT id_api_client FROM ' . _DB_PREFIX_
            . 'api_client WHERE client_id = "' . pSQL($clientId) . '"'
        );

        return (bool) $existing;
    }

    public function apply(Context $ctx): void
    {
        $config = $ctx->config;

        $ctx->console->run([
            'prestashop:api-client', 'create', $config->adminApiClientId(),
            '--name=' . $config->adminApiClientName(),
            '--all-scopes',
            '--secret=' . $config->adminApiClientSecret(),
        ]);

        $ctx->log->info('Admin API client created: ' . $config->adminApiClientId());
    }
}
