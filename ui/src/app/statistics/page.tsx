import type { Metadata } from "next";
import StatisticsDashboard from "@/components/statistics/StatisticsDashboard";
import { EMPTY_FILTERS, parseStatisticsFilters } from "@/lib/statistics";

export const metadata: Metadata = { title: "Summary statistics | Riverview Admissions" };

export default async function StatisticsPage({ searchParams }: PageProps<"/statistics">) {
  const values = await searchParams, params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (typeof value === "string") params.set(key, value);
  let filters = EMPTY_FILTERS;
  try { filters = parseStatisticsFilters(params); } catch { /* Invalid bookmarks open the unfiltered dashboard. */ }
  return <StatisticsDashboard initialFilters={filters} />;
}
