import type { Metadata } from "next";
import { AboutExperience } from "@/components/public/AboutExperience";
import "../home/home.css";
import "../public-pages.css";

export const metadata: Metadata = {
  title: "About",
  description: "FPL Copilot is an AI assistant for Fantasy Premier League: captains, transfers, fitness, predictions and your own team.",
};

/** /about (Prompt W5): public -- no sign-in needed; the header switches on the browser's Clerk session. */
export default function AboutPage() {
  return <AboutExperience />;
}
