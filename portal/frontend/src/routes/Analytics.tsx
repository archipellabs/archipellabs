import { useEffect, useState } from "react";
import { Stack, Text } from "../ui";
import { getAnalytics, type Analytics as AnalyticsData } from "../api";
import {
  BarList,
  ColumnChart,
  DataTable,
  Panel,
  ProportionBar,
  StatCard,
  type Segment,
} from "../components/charts";

const REFRESH_MS = 15_000;

const OUTCOME_META: {
  key: keyof AnalyticsData["outcome"];
  label: string;
  color: string;
}[] = [
  { key: "completed", label: "Completed", color: "var(--chart-completed)" },
  { key: "abandoned", label: "Abandoned", color: "var(--chart-abandoned)" },
  { key: "errored", label: "Errored", color: "var(--chart-errored)" },
  { key: "other", label: "Other", color: "var(--chart-other)" },
];

export function Analytics() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll the aggregate API so the charts move as new journeys land in the DB.
  useEffect(() => {
    let alive = true;
    const load = () =>
      getAnalytics()
        .then((d) => {
          if (alive) {
            setData(d);
            setError(null);
          }
        })
        .catch((e: unknown) => {
          if (alive) setError(String(e));
        });
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const outcome = data?.outcome;
  const total = outcome
    ? outcome.completed + outcome.abandoned + outcome.errored + outcome.other
    : 0;
  const completionRate =
    outcome && total ? Math.round((outcome.completed / total) * 100) : 0;

  return (
    <Stack direction="column" gap="lg">
      <Stack direction="row" justify="between" align="end" wrap gap="sm">
        <Stack direction="column" gap="2xs">
          <Text variant="overline" color="brand">
            ANALYTICS
          </Text>
          <Text variant="h2" as="h1">
            Journey outcomes
          </Text>
          <Text variant="body" color="muted">
            What the synthetic journeys actually did, read from the activity database.
          </Text>
        </Stack>
        <span className="live-tag">
          <span className="live-dot" />
          Live · refreshes every {REFRESH_MS / 1000}s
        </span>
      </Stack>

      {error && !data ? (
        <Text color="danger">
          Couldn’t load analytics. Is the backend up? ({error})
        </Text>
      ) : !data ? (
        <Text color="muted">Loading…</Text>
      ) : (
        <>
          <div className="portal-stats">
            <StatCard label="Journeys · last 24h" value={data.window.last_24h} />
            <StatCard label="Journeys · last 1h" value={data.window.last_1h} />
            <StatCard label="Completion rate" value={`${completionRate}%`} />
            <StatCard label="Runs · all time" value={total} />
          </div>

          <Panel eyebrow="OUTCOME · ALL RUNS" title="Completed vs. abandoned vs. errored">
            <ProportionBar
              segments={OUTCOME_META.map<Segment>((m) => ({
                key: m.key,
                label: m.label,
                value: data.outcome[m.key],
                color: m.color,
              }))}
            />
            <DataTable
              columns={["Outcome", "Runs"]}
              rows={OUTCOME_META.map((m) => [m.label, data.outcome[m.key]])}
            />
          </Panel>

          <div className="chart-grid-2">
            <Panel eyebrow="BY JOURNEY" title="Runs per journey">
              <BarList
                items={data.by_journey.map((b) => ({
                  key: b.key,
                  label: b.key,
                  value: b.count,
                }))}
              />
              <DataTable
                columns={["Journey", "Runs"]}
                rows={data.by_journey.map((b) => [b.key, b.count])}
              />
            </Panel>
            <Panel eyebrow="BY DEVICE" title="Runs per device">
              <BarList
                items={data.by_device.map((b) => ({
                  key: b.key,
                  label: b.key,
                  value: b.count,
                }))}
              />
              <DataTable
                columns={["Device", "Runs"]}
                rows={data.by_device.map((b) => [b.key, b.count])}
              />
            </Panel>
          </div>

          <Panel eyebrow="THROUGHPUT · LAST 24H · UTC" title="Runs over time">
            <ColumnChart
              data={data.by_hour.map((h) => ({
                label: h.hour,
                value: h.count,
                // Label only the clock quarters (00/06/12/18) so 24 columns stay legible.
                tick: parseInt(h.hour, 10) % 6 === 0 ? h.hour : undefined,
              }))}
            />
            <DataTable
              columns={["Hour", "Runs"]}
              rows={data.by_hour.map((h) => [h.hour, h.count])}
            />
          </Panel>
        </>
      )}
    </Stack>
  );
}
