import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "APAAR Student Data & Verification Platform",
  description:
    "APAAR ID-based student data management and verification for AICTE-approved institutions (SIH26263 prototype).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="bg-amber-100 px-4 py-1.5 text-center text-xs font-medium text-amber-900">
          Prototype — all data is synthetic.
        </div>
        {children}
      </body>
    </html>
  );
}
