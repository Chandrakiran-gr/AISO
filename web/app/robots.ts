import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const base = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";
  return {
    rules: [
      {
        // Default for all crawlers — allow public, block private
        userAgent: "*",
        allow: "/",
        disallow: ["/api/", "/dashboard/", "/settings/", "/_next/"],
      },
      {
        // Explicitly welcome ALL AI crawlers to public content
        userAgent: [
          "GPTBot",           // OpenAI ChatGPT
          "OAI-SearchBot",    // OpenAI Search
          "ChatGPT-User",     // ChatGPT browsing mode
          "ClaudeBot",        // Anthropic Claude
          "Claude-SearchBot", // Anthropic search
          "Claude-User",
          "PerplexityBot",    // Perplexity
          "Google-Extended",  // Gemini / Google AI
          "Applebot",         // Apple Siri
          "Amazonbot",        // Alexa
          "FacebookBot",
          "Twitterbot",
        ],
        allow: "/",
        disallow: ["/api/", "/dashboard/", "/settings/"],
      },
    ],
    sitemap: `${base}/sitemap.xml`,
  };
}
