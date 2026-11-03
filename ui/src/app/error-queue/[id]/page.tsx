"use client";

import { useParams, useRouter } from "next/navigation";
import EaosShell from "@/components/EaosShell";
import ApplicantExceptionDetails from "@/components/ApplicantExceptionDetails";

export default function ErrorDetailsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  return (
    <EaosShell title="System Error Details" subtitle="Investigation, evidence, and technical audit trail." role="IT administrator">
      <ApplicantExceptionDetails exceptionId={params.id} onBack={() => router.push('/error-queue')} onOpenApplicant={(id) => router.push(`/applicant-review?applicant=${encodeURIComponent(id)}`)} />
    </EaosShell>
  );
}
