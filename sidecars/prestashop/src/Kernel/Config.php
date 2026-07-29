<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

/**
 * Reads provisioning parameters from the environment. Secrets and ids are passed
 * in by the compose service so the same image works against any environment.
 */
final class Config
{
    public function psRootDir(): string
    {
        return getenv('PS_ROOT_DIR') ?: '/var/www/html';
    }

    public function installFolder(): string
    {
        return getenv('PS_FOLDER_INSTALL') ?: 'install-dev';
    }

    public function webserviceApiKey(): string
    {
        return $this->required('WEBSERVICE_API_KEY');
    }

    /** Where the shop answers on the shared network — same var Camel uses. */
    public function shopInternalHost(): string
    {
        return getenv('SHOP_INTERNAL_HOST') ?: 'prestashop';
    }

    /** Read-only key for the investigating agent; empty disables the step. */
    public function agentApiKey(): string
    {
        return getenv('AGENT_API_KEY') ?: '';
    }

    public function adminApiClientId(): string
    {
        return getenv('API_CLIENT_ID') ?: 'root_admin_integration';
    }

    public function adminApiClientSecret(): string
    {
        return $this->required('API_CLIENT_SECRET');
    }

    public function adminApiClientName(): string
    {
        return getenv('API_CLIENT_NAME') ?: 'My integration';
    }

    public function matomoUrl(): string
    {
        return getenv('MATOMO_URL') ?: 'https://tracking.archipellabs.test/';
    }

    public function matomoSiteId(): string
    {
        return getenv('MATOMO_SITE_ID') ?: '1';
    }

    public function matomoToken(): string
    {
        return getenv('MATOMO_TOKEN') ?: '';
    }

    private function required(string $name): string
    {
        $value = getenv($name);
        if ($value === false || $value === '') {
            throw new \RuntimeException("Missing required environment variable: {$name}");
        }

        return $value;
    }
}
