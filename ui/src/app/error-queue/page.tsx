"use client";

import { useRouter } from "next/navigation";
import EaosShell from "@/components/EaosShell";
import ErrorQueuePanel from "@/components/ErrorQueuePanel";

export default function ErrorQueuePage() {
  const router = useRouter();
  return (
    <EaosShell title="IT Error Queue" subtitle="Technical failures only. Missing student materials and fields remain in application processing." role="IT administrator">
      <ErrorQueuePanel onViewDetails={(id) => router.push(`/error-queue/${encodeURIComponent(id)}`)} />
    </EaosShell>
  );
}
