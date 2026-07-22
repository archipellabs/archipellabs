<?php

declare(strict_types=1);

namespace Archipel\Provisioning;

use Archipel\Provisioning\Kernel\Step;
use Archipel\Provisioning\Step\ApplyTimberworksTheme;
use Archipel\Provisioning\Step\CleanupHomeModules;
use Archipel\Provisioning\Step\ConfigureCatalogDisplay;
use Archipel\Provisioning\Step\ConfigureCheckout;
use Archipel\Provisioning\Step\ConfigureLanguages;
use Archipel\Provisioning\Step\ConfigureNorthAmerica;
use Archipel\Provisioning\Step\ConfigureReassurance;
use Archipel\Provisioning\Step\ConfigureWebservice;
use Archipel\Provisioning\Step\CreateAdminApiClient;
use Archipel\Provisioning\Step\InstallCustomModules;
use Archipel\Provisioning\Step\InstallMatomo;
use Archipel\Provisioning\Step\PlaceReverseProxyEnv;
use Archipel\Provisioning\Step\PurgeDemoData;
use Archipel\Provisioning\Step\SetShopLogo;

/**
 * The ordered provisioning plan. Order is explicit (not filename-based); each
 * entry is idempotent and standalone-invokable by name.
 */
final class Registry
{
    /**
     * @return list<Step>
     */
    public static function steps(): array
    {
        return [
            new PlaceReverseProxyEnv(),
            new ConfigureWebservice(),
            new CreateAdminApiClient(),
            new ConfigureLanguages(),
            new ConfigureNorthAmerica(),
            new ConfigureCheckout(),
            new InstallCustomModules(),
            new InstallMatomo(),
            new ApplyTimberworksTheme(),
            new SetShopLogo(),
            new CleanupHomeModules(),
            new ConfigureCatalogDisplay(),
            new ConfigureReassurance(),
            new PurgeDemoData(),
        ];
    }

    public static function get(string $name): Step
    {
        foreach (self::steps() as $step) {
            if ($step->name() === $name) {
                return $step;
            }
        }

        throw new \RuntimeException("Unknown step: {$name}");
    }
}
