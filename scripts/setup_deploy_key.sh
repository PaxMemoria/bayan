#!/usr/bin/env bash
# يُنشئ مفتاح نشر للقراءة فقط يستعمله خادم بيان لسحب مستودع الموقع.
# Creates a read-only deploy key that Bayan's server uses to pull the site
# repository.
# شغّله على خادم بيان، ثم أضف المفتاح العام في:
#   github.com/PaxMemoria/paxmemoria-site → Settings → Deploy keys
#   ☐ Allow write access   ← اتركه فارغاً. القراءة فقط.
# Run it on Bayan's server, then add the public key at:
#   github.com/PaxMemoria/paxmemoria-site → Settings → Deploy keys
#   ☐ Allow write access   ← leave it unchecked. Read only.
set -euo pipefail
KEY="$HOME/.ssh/bayan_deploy_key"
[ -f "$KEY" ] || ssh-keygen -t ed25519 -N '' -C 'bayan-readonly' -f "$KEY"
echo "أضف هذا المفتاح العام كـ Deploy key بصلاحية قراءة فقط:"
echo
cat "$KEY.pub"
echo
echo "ثم اضبط في .env:"
echo "SITE_REPO_URL=git@github.com:PaxMemoria/paxmemoria-site.git"
