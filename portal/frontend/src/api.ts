export interface OutcomeCounts {
  completed: number;
  abandoned: number;
  errored: number;
  other: number;
}

export interface Bucket {
  key: string;
  count: number;
}

export interface HourCount {
  hour: string;
  count: number;
}

export interface TimeWindow {
  last_24h: number;
  last_1h: number;
}

export interface Analytics {
  window: TimeWindow;
  outcome: OutcomeCounts;
  by_journey: Bucket[];
  by_device: Bucket[];
  by_hour: HourCount[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return (await res.json()) as T;
}

export type Tier = "public" | "enterprise" | "roadmap";
export type Status = "up" | "down" | "planned";

export interface CartoApp {
  id: string;
  name: string;
  sub?: string;
  tier: Tier;
  url?: string;
  thumb?: string;
  login?: { user: string; password: string };
  blurb?: string;
  status: Status;
}

export interface CartoFlow {
  from: string;
  to: string;
  label: string;
  kind: "live" | "planned";
  bidir?: boolean;
}

export interface Cartography {
  apps: CartoApp[];
  flows: CartoFlow[];
}

export const getAnalytics = () => get<Analytics>("/api/analytics");
export const getCartography = () => get<Cartography>("/api/cartography");
