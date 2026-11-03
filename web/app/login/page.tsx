import type { Metadata } from "next";
import { LoginExperience } from "@/components/login/LoginExperience";
import "./login.css";

export const metadata: Metadata = { title: "Sign in" };

/** /login: gate -> intro (6.2 s) -> the sign-in state, all on the client; this file only sets the title and the styles. */
export default function LoginPage() {
  return <LoginExperience />;
}
