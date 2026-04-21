"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import styles from "./Sidebar.module.css";

const NAV_GROUPS = [
  {
    label: "Core",
    items: [
      { href: "/dashboard",             icon: "◆", label: "Dashboard" },
      { href: "/dashboard/providers",   icon: "◈", label: "Providers"  },
      { href: "/dashboard/competitors", icon: "◈", label: "Competitors" },
      { href: "/dashboard/taxonomy",    icon: "◈", label: "Taxonomy" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/dashboard/chat",    icon: "◈", label: "AI Copilot" },
      { href: "/dashboard/actions", icon: "◈", label: "Actions" },
      { href: "/dashboard/history", icon: "◈", label: "History" },
    ],
  },
  {
    label: "Manage",
    items: [
      { href: "/dashboard/reports",  icon: "◈", label: "Reports"  },
      { href: "/settings",           icon: "◈", label: "Settings"  },
    ],
  },
];

interface SidebarProps {
  onExpandChange?: (expanded: boolean) => void;
}

export default function Sidebar({ onExpandChange }: SidebarProps) {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);

  function toggle() {
    const next = !expanded;
    setExpanded(next);
    onExpandChange?.(next);
  }

  function isActive(href: string) {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  }

  return (
    <aside
      className={`${styles.sidebar} ${expanded ? styles.expanded : ""}`}
      aria-label="Main navigation"
    >
      {/* Logo */}
      <div className={styles.logo} onClick={toggle} role="button" aria-label="Toggle sidebar">
        <span className={styles.logoMark}>◆</span>
        {expanded && (
          <span className={styles.logoText}>
            <span className="gradient-text">AISO</span>
          </span>
        )}
      </div>

      <div className={styles.glow} />

      {/* Nav groups */}
      <nav className={styles.nav}>
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className={styles.group}>
            {expanded && (
              <span className={styles.groupLabel}>{group.label}</span>
            )}
            {group.items.map((item) => {
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`${styles.navItem} ${active ? styles.active : ""}`}
                  title={!expanded ? item.label : undefined}
                >
                  <span className={styles.navIcon}>{item.icon}</span>
                  {expanded && <span className={styles.navLabel}>{item.label}</span>}
                  {active && <span className={styles.activeDot} />}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Bottom — command palette hint */}
      <div className={styles.bottom}>
        <button className={styles.cmdBtn} aria-label="Open command palette (⌘K)">
          <span className={styles.navIcon}>⌘</span>
          {expanded && <span className={styles.navLabel}>Command</span>}
          {expanded && <kbd className={styles.kbd}>K</kbd>}
        </button>
      </div>
    </aside>
  );
}
