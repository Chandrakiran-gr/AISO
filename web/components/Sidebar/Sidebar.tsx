"use client";

import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import { usePathname } from "next/navigation";
import styles from "./Sidebar.module.css";

type NavItem = {
  badge?: string;
  href: string;
  icon: string;
  label: string;
};

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Core",
    items: [
      { href: "/dashboard", icon: "🏠", label: "Dashboard" },
      { href: "/dashboard/providers", icon: "🤖", label: "Providers" },
      { href: "/dashboard/competitors", icon: "🏁", label: "Competitors" },
      { href: "/dashboard/taxonomy", icon: "🧭", label: "Taxonomy" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/dashboard/responses", icon: "🔎", label: "Responses" },
      { href: "/dashboard/actions", icon: "✅", label: "Actions", badge: "12" },
      { href: "/dashboard/chat", icon: "💬", label: "Copilot" },
      { href: "/dashboard/scans", icon: "🕘", label: "History" },
    ],
  },
  {
    label: "Manage",
    items: [
      { href: "/dashboard/reports", icon: "📊", label: "Reports" },
      { href: "/dashboard/settings", icon: "⚙", label: "Settings" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const accountLabel =
    session?.user?.name?.split(" ")[0] ?? session?.user?.email?.split("@")[0] ?? "Chandrakiran";

  function isActive(href: string) {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  }

  return (
    <aside className={styles.sidebar} aria-label="Main navigation">
      <div className={styles.sidebarGlow} aria-hidden="true" />

      <Link href="/dashboard" className={styles.logo} aria-label="AISO dashboard">
        <span className={styles.logoMark} aria-hidden="true" />
        <span className={styles.logoCopy}>
          <span className={styles.logoTitle}>AISO</span>
          <span className={styles.logoSubtitle}>AI Visibility OS</span>
        </span>
      </Link>

      <nav className={styles.nav}>
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className={styles.group}>
            <span className={styles.groupLabel}>{group.label}</span>
            {group.items.map((item) => {
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`${styles.navItem} ${active ? styles.active : ""}`}
                >
                  <span className={styles.iconTile} aria-hidden="true">
                    {item.icon}
                  </span>
                  <span className={styles.navLabel}>{item.label}</span>
                  {item.badge && <span className={styles.badge}>{item.badge}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className={styles.brandCard} aria-label="Current brand summary">
        <span className={styles.brandMeta}>Current brand</span>
        <div className={styles.brandRow}>
          <span className={styles.brandName}>Boston Brew</span>
          <span className={styles.brandScore}>67</span>
        </div>
        <span className={styles.brandTrack}>
          <span className={styles.brandTrackValue} />
        </span>
        <span className={styles.brandDate}>Last scan Apr 25</span>
      </div>

      <div className={styles.account}>
        <span className={styles.accountDot} aria-hidden="true" />
        <span className={styles.accountName}>{accountLabel}</span>
        <button
          type="button"
          className={styles.signOutBtn}
          onClick={() => signOut({ callbackUrl: "/" })}
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
