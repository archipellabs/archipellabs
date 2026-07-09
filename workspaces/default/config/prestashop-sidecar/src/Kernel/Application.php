<?php

declare(strict_types=1);

namespace Archipel\Provisioning\Kernel;

use Archipel\Provisioning\Registry;

/**
 * CLI entrypoint.
 *
 *   provision                 run the whole ordered plan
 *   provision run             run the whole ordered plan
 *   provision run <Step>      run a single step by class name
 *   provision <Step>          run a single step by class name
 *   provision list            print the plan
 */
final class Application
{
    /**
     * @param list<string> $argv arguments after the script name
     */
    public function run(array $argv): int
    {
        $config = new Config();
        $log = new Logger();
        $prestashop = new PrestaShop($config->psRootDir(), $config->installFolder(), $log);
        $console = new Console($config->psRootDir(), $log);
        $ctx = new Context($config, $log, $prestashop, $console);
        $runner = new StepRunner($log);

        $first = $argv[0] ?? null;

        try {
            if ($first === 'list') {
                foreach (Registry::steps() as $step) {
                    $log->info(sprintf('%-22s %s', $step->name(), $step->description()));
                }

                return 0;
            }

            $target = match (true) {
                $first === null, $first === 'run' => $argv[1] ?? null,
                default => $first,
            };

            $prestashop->waitUntilInstalled();

            if ($target === null) {
                $runner->runAll(Registry::steps(), $ctx);
            } else {
                $runner->runOne(Registry::get($target), $ctx);
            }

            $log->success('Provisioning complete');

            return 0;
        } catch (\Throwable $e) {
            $log->error($e->getMessage());

            return 1;
        }
    }
}
