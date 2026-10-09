#!/usr/bin/env bash
# Publica worker/api.js em api.hellocurling.com. Token da Cloudflare em ~/.config/hello-curling/cf-token.
set -euo pipefail
cd "$(dirname "$0")"
T=$(cat ~/.config/hello-curling/cf-token)
CF=https://api.cloudflare.com/client/v4
auth=(-H "Authorization: Bearer $T")
A=$(curl -sf "${auth[@]}" $CF/accounts | python3 -c "import json,sys;print(json.load(sys.stdin)['result'][0]['id'])")
Z=$(curl -sf "${auth[@]}" "$CF/zones?name=hellocurling.com" | python3 -c "import json,sys;print(json.load(sys.stdin)['result'][0]['id'])")
ok() { python3 -c "import json,sys;d=json.load(sys.stdin);print('ok' if d['success'] else d['errors']);sys.exit(0 if d['success'] else 1)"; }
echo -n "script: "
curl -s "${auth[@]}" -X PUT "$CF/accounts/$A/workers/scripts/hello-curling-api" \
  -F 'metadata={"main_module":"api.js","compatibility_date":"2026-09-01"};type=application/json' \
  -F "api.js=@api.js;type=application/javascript+module" | ok
echo -n "domínio: "
curl -s "${auth[@]}" -X PUT "$CF/accounts/$A/workers/domains" -H "content-type: application/json" \
  -d "{\"hostname\":\"api.hellocurling.com\",\"service\":\"hello-curling-api\",\"zone_id\":\"$Z\",\"environment\":\"production\"}" | ok
