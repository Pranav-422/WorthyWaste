import type { Metadata } from "next";
import { requireSession } from "@/lib/session";
import { DealerApp } from "./DealerApp";

export const metadata: Metadata = { title: "WorthyWaste · Dealer" };

export default async function Page(props: PageProps<"/dealer">) {
  const id = await requireSession("dealer");
  const sp = await props.searchParams;
  return <DealerApp key={id} dealerId={id} demo={sp.demo !== "0"} />;
}
