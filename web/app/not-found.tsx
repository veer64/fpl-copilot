import type { Metadata } from "next";
import { Oops } from "@/components/public/Oops";
import "./home/home.css";
import "./public-pages.css";

export const metadata: Metadata = { title: "Page not found", robots: { index: false, follow: false } };

/** Prompt W7b (F4): the branded 404 -- an unknown URL gets the site's page with Home / Sign in, never Next's default. */
export default function NotFound() {
  return <Oops kind="404" />;
}
