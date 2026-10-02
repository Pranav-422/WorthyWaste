import type { Metadata } from "next";
import { requireSession } from "@/lib/session";
import { CollectorApp } from "./CollectorApp";

export const metadata: Metadata = { title: "WorthyWaste · Collector" };

export default async function Page(props: PageProps<"/collector">) {
  const id = await requireSession("collector");
  const sp = await props.searchParams;
  return <CollectorApp key={id} collectorId={id} demo={sp.demo !== "0"} />;
}
