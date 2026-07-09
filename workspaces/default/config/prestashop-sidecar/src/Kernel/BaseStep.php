<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

abstract class BaseStep implements Step
{
    public function name(): string
    {
        $parts = explode('\\', static::class);

        return end($parts);
    }

    public function description(): string
    {
        return '';
    }

    public function isApplied(Context $ctx): bool
    {
        return false;
    }
}
