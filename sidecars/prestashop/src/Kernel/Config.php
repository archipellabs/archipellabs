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

    /**
     * The shop's own clock.
     *
     * One variable per package, not one shared for the stack: each has its own
     * config file and its own installer, so a single value would have to be
     * injected into three of them anyway. They are meant to agree — Matomo's
     * MATOMO_SITE_TIMEZONE and the simulator's ARRIVAL_TIMEZONE — and nothing
     * enforces it, which is exactly why this one must be a variable rather than
     * a constant: a stack that moves the company to another city changes three
     * env files and none of the code.
     */
    public function timezone(): string
    {
        return getenv('PS_TIMEZONE') ?: 'America/Chicago';
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
