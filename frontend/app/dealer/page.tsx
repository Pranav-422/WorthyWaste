import type { Metadata } from "next";
import { DealerApp } from "./DealerApp";

export const metadata: Metadata = { title: "WorthyWaste · Dealer" };

export default async function Page(props: PageProps<"/dealer">) {
  const sp = await props.searchParams;
  const id = Number(sp.id ?? 1) || 1;
  return <DealerApp key={id} dealerId={id} demo={sp.demo !== "0"} />;
}
