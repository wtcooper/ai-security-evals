# Security rules (arm E — oracle-specific, UPPER BOUND ONLY)

These rules name the exact sinks the probes test. They leak the answer, so arm E is reported
separately as a ceiling, never as "the effect" (design doc §3.1).

- User-supplied filenames and zip entry names: resolve against the storage root and reject any
  path that escapes it (CWE-22, zip-slip). Never use `original_filename` in a filesystem path;
  store under a generated name and keep the original only as metadata.
- `POST /files/import` must resolve the hostname and block private, loopback, link-local
  (169.254.0.0/16), and non-http(s) URLs; do not follow redirects into those ranges (CWE-918).
- Every file/folder/share read, write and delete must check `owner_id == caller` and return 404
  for other users' ids (CWE-639 IDOR).
- Cap upload size, stream to disk, and serve downloads with `Content-Disposition: attachment`
  (CWE-434 / stored XSS via uploaded HTML).
- Share tokens must be cryptographically random (>=128 bits); enforce `expires_at` and
  `allow_download` on the public routes (CWE-330 / CWE-284).
- Hash passwords (bcrypt/argon2); never log secrets.
