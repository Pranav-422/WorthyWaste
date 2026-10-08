import type { Metadata } from "next";
import { demoEnabled } from "@/lib/demo";
import { requireSession } from "@/lib/session";
import { HouseholdApp } from "./HouseholdApp";

export const metadata: Metadata = { title: "WorthyWaste · Green Wallet" };

export default async function Page(props: PageProps<"/household">) {
  const id = await requireSession("household");
  const sp = await props.searchParams;
  return <HouseholdApp key={id} demo={demoEnabled(sp)} />;
}
