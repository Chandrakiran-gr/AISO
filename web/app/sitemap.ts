import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";
  const now = new Date();

  return [
    { url: `${base}`,              lastModified: now, changeFrequency: "weekly",  priority: 1.0 },
    { url: `${base}/platform`,     lastModified: now, changeFrequency: "weekly",  priority: 0.9 },
    { url: `${base}/free-report`,  lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${base}/pricing`,      lastModified: now, changeFrequency: "monthly", priority: 0.8 },
    { url: `${base}/blog`,         lastModified: now, changeFrequency: "weekly",  priority: 0.8 },
    { url: `${base}/faq`,          lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${base}/about`,        lastModified: now, changeFrequency: "monthly", priority: 0.6 },
  ];
}
