<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

/**
 * A single provisioning unit. Steps must be idempotent and individually
 * invokable: the runner replays the whole ordered set at boot, and later the
 * simulator may trigger one on demand.
 */
interface Step
{
    public function name(): string;

    public function description(): string;

    /**
     * True when the desired state already holds, so the runner can skip apply().
     * apply() must itself stay safe to re-run regardless.
     */
    public function isApplied(Context $ctx): bool;

    public function apply(Context $ctx): void;
}
