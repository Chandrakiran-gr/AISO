import { redirect } from "next/navigation";
import styles from "./layout.module.css";
import Sidebar from "@/components/Sidebar/Sidebar";
import { auth } from "@/auth";
import { fetchEntitlements } from "@/lib/auth-api";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user) redirect("/login");

  // Route by state, not by which button the user clicked. A signed-in user with
  // no business (brand new, or returning after deleting their account) belongs in
  // onboarding rather than an empty dashboard. A stale session whose account no
  // longer exists (401) is sent back to log in. Backend hiccups fail open so a
  // transient error never locks anyone out of the dashboard.
  const userId = session.user.id || session.user.email;
  if (userId) {
    let entitlements;
    try {
      entitlements = await fetchEntitlements(userId);
    } catch {
      entitlements = undefined;
    }
    if (entitlements === null) redirect("/login");
    if (entitlements && entitlements.business_count === 0) redirect("/onboarding");
  }

  const accountLabel = session.user.name || session.user.email || null;

  return (
    <div className={styles.shell}>
      <Sidebar initialAccountLabel={accountLabel} />
      <main className={styles.main}>{children}</main>
    </div>
  );
}
