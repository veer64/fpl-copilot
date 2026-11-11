import { Suspense } from "react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { AdminExperience } from "@/components/admin/AdminExperience";
import "../home/home.css";
import "../public-pages.css";
import "./admin.css";

export const metadata: Metadata = { title: "Admin", robots: { index: false, follow: false } };

/** /admin (Prompt W6): the owner's page. A signed-out visitor is sent to /login before anything renders (as /home); a
 *  signed-in visitor who is not the admin is sent to /home by the page when GET /admin/summary answers 403 -- the backend's
 *  check is the real guard; this page only reads. */
export default function AdminPage() {
  return (
    <Suspense fallback={<div className="pp" aria-busy="true" />}>
      <Protected />
    </Suspense>
  );
}

async function Protected() {
  const { userId } = await auth();
  if (!userId) redirect("/login");
  return <AdminExperience />;
}
