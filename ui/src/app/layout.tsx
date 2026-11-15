import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import AuthProvider from "@/components/AuthProvider";
import { currentUser } from "@/lib/auth";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Riverview Admissions Workspace",
  description: "Human-led applicant processing, dossier review, and final decisions",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Public Home and login remain available when the data service is offline.
  const user = await currentUser().catch(() => null);
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col"><AuthProvider user={user}>{children}</AuthProvider></body>
    </html>
  );
}
