import type { Metadata } from "next";
import { CollectorApp } from "./CollectorApp";

export const metadata: Metadata = { title: "WorthyWaste · Collector" };

export default async function Page(props: PageProps<"/collector">) {
  const sp = await props.searchParams;
  const id = Number(sp.id ?? 1) || 1;
  return <CollectorApp key={id} collectorId={id} demo={sp.demo !== "0"} />;
}
