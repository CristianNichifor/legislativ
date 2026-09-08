#!/usr/bin/env bash
# Sourced, never run: turns a Cloudflare API token into the S3 credentials rclone wants, and
# exports them as RCLONE_CONFIG_R2_*. The token value itself is unset before this returns.
#
# R2's S3 credentials are derived rather than stored: the Access Key ID is the token's own id, and
# the Secret Access Key is the SHA-256 of the token value (https://developers.cloudflare.com/r2/api/tokens/).
# So there is nothing to keep in a file, and nothing to rotate here when the token is rotated.
#
#   CF_ACCOUNT=… CF_R2_TOKEN_OP=op://vault/item/credential
#   . infra/acreditari-r2.sh
#
# Environment:
#   CF_ACCOUNT      Cloudflare account id                      (required)
#   CF_R2_TOKEN     the API token value                        (or CF_R2_TOKEN_OP)
#   CF_R2_TOKEN_OP  an op:// reference, read at run time       (needs the 1Password CLI)

[ -n "${CF_ACCOUNT:-}" ] || { echo "lipsește CF_ACCOUNT" >&2; exit 2; }

if [ -z "${CF_R2_TOKEN:-}" ]; then
  [ -n "${CF_R2_TOKEN_OP:-}" ] || { echo "lipsește CF_R2_TOKEN sau CF_R2_TOKEN_OP" >&2; exit 2; }
  command -v op >/dev/null || { echo "CF_R2_TOKEN_OP cere CLI-ul 1Password (op)" >&2; exit 2; }
  # Read once, here: a caller that uploads eight directories should not ask you to unlock eight times.
  CF_R2_TOKEN=$(op read "$CF_R2_TOKEN_OP")
fi

# Retried, because one transient 401 from the verify endpoint is not a bad token.
AKID=""
for i in 1 2 3 4 5; do
  AKID=$(curl -s -H "Authorization: Bearer $CF_R2_TOKEN" \
    https://api.cloudflare.com/client/v4/user/tokens/verify |
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result']['id'] if d.get('success') else '')" 2>/dev/null)
  [ -n "$AKID" ] && break
  sleep $((i * 3))
done
[ -n "$AKID" ] || { echo "tokenul nu se verifică la Cloudflare" >&2; exit 1; }

export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_REGION=auto
export RCLONE_CONFIG_R2_ENDPOINT="https://$CF_ACCOUNT.r2.cloudflarestorage.com"
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$AKID"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$(printf %s "$CF_R2_TOKEN" | sha256sum | cut -d' ' -f1)
# The token is scoped to one bucket, so it cannot ListBuckets — which is correct, not a fault.
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
unset CF_R2_TOKEN
