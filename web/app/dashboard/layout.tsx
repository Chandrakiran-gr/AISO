"use client";

import { useState } from "react";
import Sidebar from "@/components/Sidebar/Sidebar";
import styles from "./layout.module.css";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  return (
    <div className={styles.shell}>
      <Sidebar onExpandChange={setSidebarExpanded} />
      <main
        className={`${styles.main} ${sidebarExpanded ? styles.mainExpanded : ""}`}
      >
        {children}
      </main>
    </div>
  );
}
