import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { sessionId } from "@/lib/session";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Log in · WorthyWaste" };

export default async function Page(props: PageProps<"/login">) {
  const sp = await props.searchParams;
  const role = sp.role === "dealer" ? "dealer" : "collector";
  // Already signed in for this role: go straight to the app.
  if ((await sessionId(role)) !== null) redirect(`/${role}`);
  return <LoginForm initialRole={role} />;
}
