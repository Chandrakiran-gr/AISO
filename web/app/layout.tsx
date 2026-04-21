import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"
  ),
  title: {
    default: "AISO by Sapienic — AI Search Optimization Platform",
    template: "%s | AISO by Sapienic",
  },
  description:
    "Measure and improve how AI recommends your business across ChatGPT, Claude, Perplexity, and Gemini. Track your AI visibility score, benchmark competitors, and get actionable steps to get recommended more.",
  keywords: [
    "AI search optimization",
    "AI visibility",
    "generative engine optimization",
    "GEO",
    "AEO",
    "answer engine optimization",
    "ChatGPT visibility",
    "Perplexity optimization",
    "brand visibility AI",
    "AI SEO",
  ],
  authors: [{ name: "Sapienic" }],
  creator: "Sapienic",
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "/",
    siteName: "AISO by Sapienic",
    title: "AISO by Sapienic — AI Search Optimization Platform",
    description:
      "Is AI recommending your competitors instead of you? Measure and optimize your brand's visibility across ChatGPT, Claude, Perplexity, and Gemini.",
    images: [{ url: "/og-image.png", width: 1200, height: 630, alt: "AISO — AI Search Optimization" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "AISO by Sapienic — AI Search Optimization Platform",
    description:
      "Is AI recommending your competitors instead of you? Measure and optimize your brand's visibility across ChatGPT, Claude, Perplexity, and Gemini.",
    images: ["/og-image.png"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-video-preview": -1, "max-image-preview": "large", "max-snippet": -1 },
  },
};

// JSON-LD structured data — Organization entity
const organizationSchema = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "Sapienic",
  url: process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000",
  logo: `${process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"}/logo.png`,
  description:
    "AI Search Optimization platform that measures and improves business visibility across ChatGPT, Claude, Perplexity, and Gemini.",
  knowsAbout: [
    "AI Search Optimization",
    "Generative Engine Optimization",
    "Answer Engine Optimization",
    "AI Visibility",
    "Brand Recommendation Optimization",
  ],
  sameAs: ["https://linkedin.com/company/sapienic"],
};

const softwareSchema = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "AISO by Sapienic",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  description:
    "Measure and improve how AI recommends your business across ChatGPT, Claude, Perplexity, and Gemini.",
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
    description: "Free AI visibility report",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* JSON-LD structured data for AI crawlers */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationSchema) }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareSchema) }}
        />
        {/* Preconnect to Google Fonts */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
