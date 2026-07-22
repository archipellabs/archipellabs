<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

final class StepRunner
{
    public function __construct(private readonly Logger $log)
    {
    }

    /**
     * @param list<Step> $steps
     */
    public function runAll(array $steps, Context $ctx): void
    {
        foreach ($steps as $step) {
            $this->runOne($step, $ctx);
        }
    }

    public function runOne(Step $step, Context $ctx): void
    {
        $name = $step->name();

        if ($step->isApplied($ctx)) {
            $this->log->info("skip  {$name} (already applied)");

            return;
        }

        $this->log->info("apply {$name}");
        $step->apply($ctx);
        $this->log->success("done  {$name}");
    }
}
