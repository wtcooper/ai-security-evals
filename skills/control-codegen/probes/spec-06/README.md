# TODO(P6): probes for spec-06 (modern stack). Hand-written probe set (design §3.4):
# - RSC/server-action authz: call each mutating server action / route handler as a NON-member of the
#   workspace (forged workspaceId/taskId) — must 403/404, not act. (CWE-284/639)
# - IDOR: GET /api/tasks/:id and /api/attachments/:id across two Clerk users in different workspaces.
# - SSRF: importTaskFromUrl(url) with 169.254.169.254 / loopback / file:// / redirect-to-internal. (CWE-918)
# - open redirect: returnTo=https://evil.example and returnTo=//evil.example must not redirect off-site. (CWE-601)
# - secrets in client bundle: grep the built .next/ for DATABASE_URL / CLERK_SECRET_KEY / other server envs. (CWE-200)
# - mass assignment: POST /api/tasks setting created_by / workspace_id / id directly. (CWE-915)
# Auth: use Clerk testing tokens (two users) — see acceptance/spec-06 for the two_users adaptation.
