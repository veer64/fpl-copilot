import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { MusicProvider } from "@/components/music/MusicProvider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: { default: "FPL Copilot", template: "%s · FPL Copilot" },
  description: "AI assistant for FPL managers: injury flags, points predictions, fixtures and cited club news.",
  icons: { icon: "/logo.svg" },
};

export const viewport: Viewport = {
  themeColor: "#04070C",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        {/* Core 3: the provider sits inside <body>; our own sign-in page is /login (no stock <SignIn/>). */}
        <ClerkProvider signInUrl="/login" signUpUrl="/login" signInFallbackRedirectUrl="/home" signUpFallbackRedirectUrl="/home">
          {/* Prompt W5b: the one audio element for the whole site lives here, so the music survives every client navigation */}
          <MusicProvider>
            {children}
            <Toaster position="top-center" richColors={false} closeButton={false} />
          </MusicProvider>
        </ClerkProvider>
      </body>
    </html>
  );
}
