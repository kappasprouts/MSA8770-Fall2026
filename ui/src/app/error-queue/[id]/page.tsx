"use client";

import { useParams, useRouter } from "next/navigation";
import EaosShell from "@/components/EaosShell";
import ApplicantExceptionDetails from "@/components/ApplicantExceptionDetails";
import { dossierHref } from "@/lib/eaos-api";

export default function ErrorDetailsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  return (
    <EaosShell title="Exception Details" subtitle="Investigation, evidence, and technical audit trail." role="IT administrator">
      <ApplicantExceptionDetails
        key={params.id}
        exceptionId={params.id}
        onBack={() => router.push("/error-queue")}
        onOpenApplicant={(id) => router.push(dossierHref(id))}
      />
    </EaosShell>
  );
}
