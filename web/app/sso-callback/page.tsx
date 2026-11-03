"use client";

import { HandleSSOCallback } from "@clerk/nextjs";
import { useRouter } from "next/navigation";

/** Google sends the browser back here (signIn.sso's redirectCallbackUrl). Clerk finishes the OAuth exchange -- a
 *  sign-in, or a transfer to a sign-up for a new Google account -- and we land on /teams. Anything that still needs
 *  a step goes back to /login with a reason the card can show. */
export default function SsoCallbackPage() {
  const router = useRouter();
  return (
    <main className="flex flex-1 items-center justify-center p-6" aria-busy="true">
      <HandleSSOCallback
        navigateToApp={({ decorateUrl }) => {
          const url = decorateUrl("/teams");
          if (url.startsWith("http")) window.location.href = url;
          else router.push(url);
        }}
        navigateToSignIn={() => router.push("/login?sso=incomplete")}
        navigateToSignUp={() => router.push("/login?sso=incomplete")}
      />
      <p className="font-mono text-[12px] uppercase tracking-[0.18em] text-fpl-accent-text">› Connecting to Google</p>
    </main>
  );
}
