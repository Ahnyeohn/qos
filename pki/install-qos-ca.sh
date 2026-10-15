cat > install-qos-ca.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

EDGE_HOST="${EDGE_HOST:-10.20.13.157}"
EDGE_USER="${EDGE_USER:-n2sl}"
REMOTE_CERT="${REMOTE_CERT:-/home/n2sl/yeon/qos/pki/output/qos-ca.crt}"

TMP_CERT="/tmp/qos-ca.crt"
SYSTEM_CERT="/usr/local/share/ca-certificates/qos-ca.crt"

echo "========================================"
echo "[1] Downloading QOS CA from Edge"
echo "========================================"

scp \
  "${EDGE_USER}@${EDGE_HOST}:${REMOTE_CERT}" \
  "${TMP_CERT}"

echo
echo "========================================"
echo "[2] Checking certificate"
echo "========================================"

openssl x509 \
  -in "${TMP_CERT}" \
  -noout \
  -subject \
  -issuer \
  -fingerprint \
  -sha256

echo
echo "========================================"
echo "[3] Installing QOS CA"
echo "========================================"

sudo install \
  -m 0644 \
  "${TMP_CERT}" \
  "${SYSTEM_CERT}"

sudo update-ca-certificates

rm -f "${TMP_CERT}"

echo
echo "========================================"
echo "[QOS-CA] Installation complete"
echo "========================================"
echo
echo "Installed at:"
echo "  ${SYSTEM_CERT}"
echo
echo "Restart Chrome/Chromium/Edge before testing."
EOF

chmod +x install-qos-ca.sh