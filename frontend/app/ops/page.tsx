import type { Metadata } from "next";
import { demoEnabled } from "@/lib/demo";
import { requireSession } from "@/lib/session";
import { OpsApp } from "./OpsApp";

export const metadata: Metadata = { title: "WorthyWaste · Team" };

export default async function Page(props: PageProps<"/ops">) {
  const id = await requireSession("ops");
  const sp = await props.searchParams;
  // Forced billing is a demo shortcut; the API refuses it unless WW_DEMO_MODE=1 as well.
  return <OpsApp key={id} demo={demoEnabled(sp)} />;
}
