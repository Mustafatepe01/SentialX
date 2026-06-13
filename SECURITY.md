# Security Policy

## Secrets

Do not commit API keys, service-account credentials, `.env` files, camera
passwords, private keys, signed URLs, or production database connection
strings.

Use the checked-in `.env.example` files as templates and keep real values in
Google Secret Manager or an equivalent secret store.

If a credential is committed or shared accidentally, remove it from the
repository and rotate it immediately. Removing the text from a later commit
does not make the old credential safe.

## Reporting

Please report security issues privately to the repository owner. Do not open
a public issue containing credentials, infrastructure identifiers, personal
data, or a working exploit.

