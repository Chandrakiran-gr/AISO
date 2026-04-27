import styles from "./layout.module.css";
import Sidebar from "@/components/Sidebar/Sidebar";
import { auth } from "@/auth";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  const accountLabel = session?.user?.name || session?.user?.email || null;

  return (
    <div className={styles.shell}>
      <Sidebar initialAccountLabel={accountLabel} />
      <main className={styles.main}>{children}</main>
    </div>
  );
}
