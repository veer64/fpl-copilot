"use client";

import { useEffect } from "react";
import { Oops } from "@/components/public/Oops";
import "./home/home.css";
import "./public-pages.css";

/** Prompt W7b (F4): a client-side crash inside a page shows the branded "Something went wrong." with Try again (Next's
 *  reset) and Home -- not Next's default "Application error" screen. The error itself goes to the console only. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("[page error]", error);
  }, [error]);
  return <Oops kind="error" onRetry={reset} />;
}
