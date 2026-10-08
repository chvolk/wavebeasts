#!/usr/bin/env bash
# One-time Google Cloud setup for Google Play Billing on wavebeasts.com.
#
# Creates (idempotently) the Cloud project, enables the Android Publisher + Pub/Sub APIs, creates the
# service account the site uses to verify purchases, creates the Real-time Developer Notification (RTDN)
# topic, grants Google Play permission to publish to it, and creates a push subscription that delivers to
# the site's webhook with an OIDC token signed by a dedicated push service account.
#
# Prereqs: `gcloud auth login` done as the Play developer account owner, and a billing account id if the
# project must be new (Pub/Sub needs billing enabled even at zero cost):
#   gcloud billing accounts list
#
# Usage:
#   scripts/setup-play-cloud.sh [--project wavebeasts-play] [--billing ACCOUNT_ID] [--site https://wavebeasts.com]
#
# Afterwards, two manual steps in the Play Console (https://play.google.com/console):
#   1. Setup > API access > link the Cloud project, then grant the service account
#      "View financial data" + "Manage orders and subscriptions" on the WaveBeasts app.
#   2. Monetize > Monetization setup > Real-time developer notifications: paste the topic name
#      printed at the end and "Send test notification".
# Then set these Railway env vars on the site (printed at the end):
#   PLAY_PACKAGE_NAME, PLAY_SERVICE_ACCOUNT_JSON (base64 of the key file), PLAY_RTDN_AUDIENCE,
#   PLAY_RTDN_SERVICE_ACCOUNT
set -euo pipefail
GCLOUD=${GCLOUD:-$HOME/.local/opt/google-cloud-sdk/bin/gcloud}
PROJECT=wavebeasts-play
BILLING=""
SITE=https://wavebeasts.com
PACKAGE=net.wavebeasts.app
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT=$2; shift 2;;
    --billing) BILLING=$2; shift 2;;
    --site) SITE=${2%/}; shift 2;;
    *) echo "unknown arg $1" >&2; exit 2;;
  esac
done
say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
OUT=${OUT:-$HOME/.config/wavebeast}
mkdir -p "$OUT"; chmod 700 "$OUT"

say "project $PROJECT"
if ! "$GCLOUD" projects describe "$PROJECT" >/dev/null 2>&1; then
  "$GCLOUD" projects create "$PROJECT" --name="WaveBeasts Play"
fi
"$GCLOUD" config set project "$PROJECT" >/dev/null
if [ -n "$BILLING" ]; then
  "$GCLOUD" billing projects link "$PROJECT" --billing-account="$BILLING"
fi
PROJECT_NUMBER=$("$GCLOUD" projects describe "$PROJECT" --format='value(projectNumber)')

say "enabling APIs"
"$GCLOUD" services enable androidpublisher.googleapis.com pubsub.googleapis.com iam.googleapis.com

say "service account for purchase verification"
VERIFY_SA=play-verify@$PROJECT.iam.gserviceaccount.com
"$GCLOUD" iam service-accounts describe "$VERIFY_SA" >/dev/null 2>&1 || \
  "$GCLOUD" iam service-accounts create play-verify --display-name="WaveBeasts Play purchase verification"
KEY=$OUT/play-verify-key.json
if [ ! -f "$KEY" ]; then
  "$GCLOUD" iam service-accounts keys create "$KEY" --iam-account="$VERIFY_SA"
  chmod 600 "$KEY"
fi

say "service account that signs RTDN push tokens"
PUSH_SA=play-rtdn-push@$PROJECT.iam.gserviceaccount.com
"$GCLOUD" iam service-accounts describe "$PUSH_SA" >/dev/null 2>&1 || \
  "$GCLOUD" iam service-accounts create play-rtdn-push --display-name="WaveBeasts RTDN push"
# Pub/Sub's own service agent must be allowed to mint OIDC tokens for the push SA.
"$GCLOUD" projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountTokenCreator --condition=None >/dev/null

say "RTDN topic + Google Play publisher grant"
TOPIC=play-rtdn
"$GCLOUD" pubsub topics describe "$TOPIC" >/dev/null 2>&1 || "$GCLOUD" pubsub topics create "$TOPIC"
"$GCLOUD" pubsub topics add-iam-policy-binding "$TOPIC" \
  --member=serviceAccount:google-play-developer-notifications@system.gserviceaccount.com \
  --role=roles/pubsub.publisher >/dev/null

say "push subscription -> $SITE/webhooks/play"
SUB=play-rtdn-site
AUD=$SITE/webhooks/play
if "$GCLOUD" pubsub subscriptions describe "$SUB" >/dev/null 2>&1; then
  "$GCLOUD" pubsub subscriptions update "$SUB" --push-endpoint="$AUD" \
    --push-auth-service-account="$PUSH_SA" --push-auth-token-audience="$AUD"
else
  "$GCLOUD" pubsub subscriptions create "$SUB" --topic="$TOPIC" --push-endpoint="$AUD" \
    --push-auth-service-account="$PUSH_SA" --push-auth-token-audience="$AUD" \
    --ack-deadline=30 --message-retention-duration=7d --expiration-period=never
fi

cat <<EOF

Done. Next:
  Play Console > Setup > API access: link project "$PROJECT"; grant $VERIFY_SA
    permissions "View financial data" and "Manage orders and subscriptions" for $PACKAGE.
  Play Console > Monetize > Monetization setup > RTDN topic:
    projects/$PROJECT/topics/$TOPIC

Railway env for the site:
  PLAY_PACKAGE_NAME=$PACKAGE
  PLAY_SERVICE_ACCOUNT_JSON=\$(base64 -w0 $KEY)
  PLAY_RTDN_AUDIENCE=$AUD
  PLAY_RTDN_SERVICE_ACCOUNT=$PUSH_SA
EOF
