# RiverView State Admissions UI Prototype

This package contains Maya's original RiverView State Next.js admissions-officer workspace with a new read-only Exception Triage screen. It preserves the navy sidebar, RiverView logo, applicant-review layout, Officer View, IT Admin View, PostgreSQL, MinIO, dossier, document, and chat integrations.

## Apply the update on Windows

1. Stop the prototype development server with `Ctrl+C`.
2. Place `maya-ui-prototype-riverview-exception-triage.zip` in the repository root:
   `C:\msa8770project\MSA8770-Fall2026`
3. From that directory, run:

   ```powershell
   Expand-Archive `
     -Path .\maya-ui-prototype-riverview-exception-triage.zip `
     -DestinationPath .\maya-ui-exception-triage `
     -Force

   Copy-Item .\maya-ui-prototype\.env.local .\maya-ui-exception-triage\.env.local

   cd .\maya-ui-exception-triage
   npm ci
   npm run dev -- --port 3003
   ```

4. Open `http://localhost:3003`.

The archive does not contain `.env.local`. Your existing local database and MinIO settings remain in place.

## Main interface areas

- Applicant queue and search
- Left navigation for Dashboard, Applicant Queue, Exception Triage, Policies, Documents, Reports, and Settings
- Read-only exception queue for ingestion failures, missing materials, unreadable files, summarizer validation failures, and orphan documents
- Search and filters for issue category and priority
- Exception detail panel with affected documents, audit history, responsible team, and a link back to any available dossier
- Applicant review dashboard
- Separate Admissions Officer and IT Admin dashboard views
- Prominent Officer Q&A and human action workflow
- Validation evidence and retries
- Source-document viewer
- Admissions policy alignment
- Grounded officer Q&A
- Simulated human officer action panel

The Officer Action panel is intentionally labeled as a simulation. It does not write admissions decisions to the database.

## Verification

The project was checked with:

```powershell
npm run lint
npm run build
```

Both checks pass. Next.js 16.4.0 also displays an upgrade recommendation because that dependency version has a published security advisory. Upgrade Next.js before any production deployment.
