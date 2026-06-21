# TLS Runbook

How TLS is terminated, where the certs live, and how to rotate them.

## Architecture

Nginx terminates TLS on port 443 and proxies plaintext HTTP to the
`tron-api` upstream on the internal docker network. Everything a browser or
CLI client sees is HTTPS; the API container never handles raw TLS.

```
browser ──TLS 1.2/1.3──▶ nginx:443 ──HTTP──▶ tron-api:8000
                         │
                         └── X-Forwarded-Proto: https
```

`X-Forwarded-Proto` is critical — the FastAPI app reads it to mark its
session cookies `Secure` and to keep redirects on HTTPS. If that header is
dropped, the admin session cookie silently downgrades.

## Cert layout

The nginx container mounts the host directory `config/nginx/ssl` read-only
at `/etc/nginx/ssl`. Two files must exist there before nginx starts:

```
config/nginx/ssl/cert.pem   # PEM-encoded server cert + any intermediates
config/nginx/ssl/key.pem    # PEM-encoded private key, mode 0600
```

If either is missing nginx will fail to start with
`SSL_CTX_use_PrivateKey_file failed`.

## Local development

`make dev-cert` (or `./config/nginx/ssl/generate-dev-cert.sh`) produces a
self-signed 397-day cert covering `localhost`, `127.0.0.1`, `::1`, and the
`tron-nginx` service name. Browsers will warn; that is expected.

To include a custom hostname in the SAN (e.g. for testing a
`tron.my-lab.local` alias), set `TRON_DEV_CERT_HOSTNAME`:

```bash
TRON_DEV_CERT_HOSTNAME=tron.my-lab.local make dev-cert
```

To regenerate over an existing cert, set `TRON_DEV_CERT_FORCE=1`. The script
refuses to clobber by default so a hand-placed cert from another dev
workflow doesn't vanish.

## Production

You have three common options, roughly in order of "best for most people":

### 1. Let's Encrypt via certbot (HTTP-01)

Nginx is already set up for this: the port-80 vhost passes
`/.well-known/acme-challenge/` through to `/var/www/certbot`. Bring up a
certbot sidecar, bind-mount the same path, and issue the cert. After issue:

```bash
# Replace the mounted files with the newly-issued chain/key
cp /etc/letsencrypt/live/<domain>/fullchain.pem config/nginx/ssl/cert.pem
cp /etc/letsencrypt/live/<domain>/privkey.pem   config/nginx/ssl/key.pem
docker compose exec nginx nginx -s reload
```

Certbot's `renew --deploy-hook` should do the copy and reload automatically;
set that up once and forget.

### 2. Corporate / private CA

Put the leaf cert followed by any intermediates into `cert.pem` (order
matters — leaf first, then intermediates up to, but not including, the
root). Put the corresponding private key into `key.pem`. Confirm with:

```bash
openssl x509 -in config/nginx/ssl/cert.pem -noout -subject -issuer -dates
openssl rsa  -in config/nginx/ssl/key.pem  -noout -modulus | openssl md5
openssl x509 -in config/nginx/ssl/cert.pem -noout -modulus | openssl md5
# the two md5 hashes must match, else the key is not for this cert
```

### 3. Terminating upstream

If TLS is already terminated by an external load balancer (ALB, GCP LB,
Cloudflare), you can drop the HTTPS vhost and keep just the HTTP one — but
then the upstream MUST set `X-Forwarded-Proto: https` and the LB MUST reject
plaintext. Do not leave the HTTP vhost serving app traffic; the default
config will 301-redirect anything other than the ACME path.

## Rotation

Certs are swapped by replacing the two files and reloading nginx — no
container restart is needed:

```bash
# drop new cert/key into config/nginx/ssl/, then:
docker compose exec nginx nginx -t        # sanity-check the config
docker compose exec nginx nginx -s reload # graceful reload, no dropped conns
```

`nginx -s reload` re-reads the cert from disk. Workers drain gracefully —
existing TLS sessions stay on the old cert until they close, new sessions
pick up the new cert.

Set a calendar reminder 14 days before expiry (`openssl x509 -noout -enddate
-in cert.pem`). For Let's Encrypt this is automated; for a private CA it
usually isn't.

## Disabling TLS (don't)

There is no supported knob for "just serve plain HTTP." Every route in the
app's auth pipeline — cookie flags, HSTS, WS upgrade — assumes TLS is
present. If you need to bypass TLS for a smoke test, hit the upstream
directly over the internal docker network (`http://tron-api:8000`), not via
nginx.

## Verification

After rotation or a config change, check from outside the box:

```bash
# Protocol & cipher
openssl s_client -connect <host>:443 -tls1_2 </dev/null 2>/dev/null \
    | openssl x509 -noout -subject -dates

# HSTS is set
curl -Ik https://<host>/ | grep -i strict-transport-security

# HTTP → HTTPS redirect works
curl -sIk http://<host>/ | head -1   # expect: HTTP/1.1 301 Moved Permanently

# Forwarded-Proto is reaching the API (check a /api/health response)
curl -sk https://<host>/api/health
```

`tests/unit/test_nginx_tls_config.py` asserts the static shape of
`nginx.conf` — if any of the TLS knobs drift, CI fails fast.
