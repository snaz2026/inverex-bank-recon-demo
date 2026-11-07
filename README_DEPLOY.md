# INVEREX Bank Recon — synthetic-only cloud demo

Continuation of V3; NOT a production company reconciliation system. No real financial data, employee emails, or credentials are contained in this folder.

Deployable on Render via render.yaml (Render connection required). Configure RECON_ADMIN_PASSWORD as a strong, unique deployment secret. Login: admin@local.invalid. HTTPS served by hosting platform. No Microsoft OTP, admin approval or production RBAC.

Demo limitations: SQLite is on ephemeral filesystem; edits reset at redeploy/sleep; uploads are disabled to protect company data. Automatic matching of actual bank PDFs/XLSX is NOT supported. Source reports in V3 remain untouched and are intentionally omitted.

Before real production: IT-approved authenticated email integration, external durable PostgreSQL and object storage, file virus scanning, bank-specific extraction tests, session rate limits and CSRF protection, backup recovery, proper multiuser role isolation, and security review.
