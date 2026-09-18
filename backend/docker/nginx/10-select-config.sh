#!/bin/sh
# Installed at /docker-entrypoint.d/10-select-config.sh. The stock nginx
# entrypoint runs every *.sh in that directory before starting nginx, sorted with
# `sort -V`, so this runs after `10-listen-on-ipv6-by-default.sh` (which edits the
# image's own default.conf -- we overwrite that file wholesale) and before nginx
# itself is exec'd.
#
# MUST BE EXECUTABLE. The entrypoint silently skips any script that is not, and
# the symptom is the stock nginx welcome page on :80 and nothing on :443:
#     chmod +x backend/docker/nginx/10-select-config.sh
#
# Why a script rather than the stock envsubst templates: `${DOMAIN}` is a string
# substitution, which envsubst handles, but "serve :443 or not" is a *structural*
# choice -- no variable can stop a `listen 443 ssl` block from trying to load a
# certificate that does not exist yet. (Driving the stock script instead would
# mean setting NGINX_ENVSUBST_TEMPLATE_DIR from a *.envsh file, since only .envsh
# is sourced while .sh runs as a child process -- a load-bearing dependency on
# three upstream implementation details.)
set -eu

: "${DOMAIN:?DOMAIN is not set; the nginx service passes it from backend/.env}"

CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
SRC=/etc/nginx/conf.d-src
TARGET=/etc/nginx/conf.d/default.conf

# Only the braced `${DOMAIN}` is substituted, so nginx's own unbraced variables
# ($host, $remote_addr, $request_uri, $proxy_add_x_forwarded_for) are untouched.
render() {
    if [ -f "$CERT" ]; then
        sed "s|\${DOMAIN}|${DOMAIN}|g" "$SRC/tls.conf"
    else
        sed "s|\${DOMAIN}|${DOMAIN}|g" "$SRC/http-only.conf"
    fi
}

render > "$TARGET"

if [ -f "$CERT" ]; then
    echo "nginx: certificate found for ${DOMAIN} -- serving HTTPS"
else
    echo "nginx: no certificate for ${DOMAIN} yet -- HTTP only."
    echo "nginx: the certbot service will issue one; re-checked every 6h."
fi

# nginx reads certificate files at reload, not per request, and a `listen 443 ssl`
# block can only be introduced at start. Without this loop a renewed certificate
# would sit unused on disk until someone restarted the container by hand, and the
# phase switch would need manual intervention.
#
# 21600s rather than `6h`: Alpine's busybox sleep has not always accepted unit
# suffixes.
(
    while :; do
        sleep 21600

        render > /tmp/default.conf.new

        if ! cmp -s /tmp/default.conf.new "$TARGET"; then
            cp /tmp/default.conf.new "$TARGET"
            nginx -s reload || true
            echo "nginx: phase changed, reloaded"
        elif [ -f "$CERT" ]; then
            nginx -s reload || true
            echo "nginx: periodic reload (a renewed certificate may be in place)"
        fi
    done
) &
