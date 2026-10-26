import type { Metadata } from "next";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "APAAR Student Data & Verification Platform",
  description:
    "APAAR ID-based student data management and verification for AICTE-approved institutions (SIH26263 prototype). All data is synthetic.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
