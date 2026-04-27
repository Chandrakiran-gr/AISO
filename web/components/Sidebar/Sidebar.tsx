"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getSession, signOut, useSession } from "next-auth/react";
import styles from "./Sidebar.module.css";

const NAV_ITEMS = [
  { href: "/dashboard",             icon: "overview", label: "Overview" },
  { href: "/dashboard/scans",       icon: "scans",    label: "Scan History" },
  { href: "/dashboard/competitors", icon: "rank",     label: "Competitors" },
  { href: "/dashboard/actions",     icon: "actions",  label: "Action Plan" },
  { href: "/dashboard/settings",    icon: "settings", label: "Settings" },
];

function SidebarIcon({ name }: { name: string }) {
  const modifier = styles[`navIcon${name}`] ?? "";
  return <span className={`${styles.navIcon} ${modifier}`} aria-hidden="true" />;
}

function useAccountLabel(initialAccountLabel: string | null): string {
  const { data: session, status } = useSession();
  const [refreshedLabel, setRefreshedLabel] = useState<string | null>(null);

  useEffect(() => {
    const currentLabel = session?.user?.name || session?.user?.email;
    if (currentLabel || initialAccountLabel || status === "loading") return;

    let active = true;
    let attempts = 0;
    let retryId: ReturnType<typeof setTimeout> | null = null;

    async function refreshSessionLabel() {
      attempts += 1;
      const refreshed = await getSession();
      const label = refreshed?.user?.name || refreshed?.user?.email;

      if (!active) return;

      if (label) {
        setRefreshedLabel(label);
        return;
      }

      if (attempts < 10) {
        retryId = setTimeout(refreshSessionLabel, 500);
      }
    }

    void refreshSessionLabel();

    return () => {
      active = false;
      if (retryId) clearTimeout(retryId);
    };
  }, [initialAccountLabel, session?.user?.email, session?.user?.name, status]);

  return (
    session?.user?.name ||
    session?.user?.email ||
    refreshedLabel ||
    initialAccountLabel ||
    (status === "authenticated"
      ? "Loading account..."
      : status === "loading"
        ? "Loading account..."
        : "Loading account...")
  );
}

export default function Sidebar({
  initialAccountLabel,
}: {
  initialAccountLabel: string | null;
}) {
  const pathname = usePathname();
  const accountLabel = useAccountLabel(initialAccountLabel);
  const [showSignOutDialog, setShowSignOutDialog] = useState(false);

  function isActive(href: string) {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  }

  function confirmSignOut() {
    void signOut({ callbackUrl: "/" });
  }

  return (
    <>
      <aside className={styles.sidebar} aria-label="Dashboard navigation">
        <Link href="/" className={styles.logo} aria-label="AISO home">
          <span className={styles.logoMark}>A</span>
          <span className={styles.logoText}>AISO</span>
        </Link>

        <nav className={styles.nav} aria-label="Workspace">
          <span className={styles.groupLabel}>Workspace</span>
          {NAV_ITEMS.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`${styles.navItem} ${active ? styles.active : ""}`}
                aria-current={active ? "page" : undefined}
              >
                <SidebarIcon name={item.icon} />
                <span className={styles.navLabel}>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className={styles.sidebarSpacer} />

        <div className={styles.sidebarFooter}>
          <span className={styles.userEmail}>{accountLabel}</span>
          <button
            type="button"
            className={styles.signOutBtn}
            onClick={() => setShowSignOutDialog(true)}
          >
            Sign out
          </button>
        </div>
      </aside>

      {showSignOutDialog && (
        <div
          className={styles.dialogOverlay}
          role="presentation"
          onClick={() => setShowSignOutDialog(false)}
        >
          <div
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="signout-dialog-title"
            aria-describedby="signout-dialog-description"
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.dialogIcon} aria-hidden="true">A</div>
            <div>
              <h2 className={styles.dialogTitle} id="signout-dialog-title">
                Sign out of AISO?
              </h2>
              <p className={styles.dialogText} id="signout-dialog-description">
                You can sign back in anytime to continue from your dashboard.
              </p>
            </div>
            <div className={styles.dialogActions}>
              <button
                type="button"
                className={styles.dialogCancel}
                onClick={() => setShowSignOutDialog(false)}
              >
                Stay signed in
              </button>
              <button
                type="button"
                className={styles.dialogConfirm}
                onClick={confirmSignOut}
              >
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
