import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "ABSOLUTE-ZERO Workbench",
  description: "Operating console for the ABSOLUTE-ZERO Agentic OS",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <div className="flex h-screen gap-3 p-3">
            <Nav />
            <main className="min-w-0 flex-1 overflow-auto">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
