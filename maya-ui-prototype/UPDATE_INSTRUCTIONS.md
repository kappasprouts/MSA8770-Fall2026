# RiverView State Admissions UI Prototype

This package contains the redesigned Next.js admissions-officer workspace. It preserves the existing PostgreSQL, MinIO, dossier, document, and chat API integrations.

## Apply the update on Windows

1. Stop the prototype development server with `Ctrl+C`.
2. Place `maya-ui-prototype-updated.zip` in the repository root:
   `C:\msa8770project\MSA8770-Fall2026`
3. From that directory, run:

   ```powershell
   Expand-Archive `
     -Path .\maya-ui-prototype-updated.zip `
     -DestinationPath .\maya-ui-prototype `
     -Force

   cd .\maya-ui-prototype
   npm ci
   npm run dev -- --port 3002
   ```

4. Open `http://localhost:3002`.

The archive does not contain `.env.local`. Your existing local database and MinIO settings remain in place.

## Main interface areas

- Applicant queue and search
- Left navigation for Dashboard, Applicant Queue, Policies, Documents, Reports, and Settings
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
npm run build -- --webpack
```
