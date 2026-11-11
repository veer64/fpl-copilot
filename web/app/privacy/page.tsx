import type { Metadata } from "next";
import { PrivacyExperience } from "@/components/public/PrivacyExperience";
import "../home/home.css";
import "../public-pages.css";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What FPL Copilot keeps, who handles it, and how to delete it.",
};

/** /privacy (Prompt W5): public -- no sign-in needed; the header switches on the browser's Clerk session. */
export default function PrivacyPage() {
  return <PrivacyExperience />;
}
