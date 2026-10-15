#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage:"
    echo "  $0 <IP1> [IP2] [IP3] ..."
    echo
    echo "Example:"
    echo "  $0 10.20.13.197 10.20.13.220 10.20.13.225"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# CA와 설정 파일 보관 위치.
PKI_DIR="${SCRIPT_DIR}/output"

# mediasoup StatefulSet의 hostPath.
# 다른 서버에서는 CERT_DIR 환경변수로 변경 가능.
CERT_DIR="${CERT_DIR:-${HOME}/yeon/qos/network/mediasoup-demo/server/certs}"

mkdir -p "${PKI_DIR}"

if [[ ! -d "${CERT_DIR}" ]]; then
    echo "[PKI] ERROR: mediasoup cert directory does not exist:"
    echo "  ${CERT_DIR}"
    exit 1
fi

CA_KEY="${PKI_DIR}/qos-ca.key"
CA_CERT="${PKI_DIR}/qos-ca.crt"
CA_CONF="${PKI_DIR}/qos-ca.cnf"

SERVER_CSR="${PKI_DIR}/edge-server.csr"
SERVER_CONF="${PKI_DIR}/edge-server.cnf"

# 최종적으로 mediasoup가 직접 읽는 파일.
SERVER_CERT="${CERT_DIR}/cert.pem"
SERVER_KEY="${CERT_DIR}/key.pem"

# 생성 중인 임시 파일.
TMP_CERT="${CERT_DIR}/.cert.pem.new"
TMP_KEY="${CERT_DIR}/.key.pem.new"

echo "========================================"
echo "[1] Preparing QOS Local CA"
echo "========================================"

cat > "${CA_CONF}" <<'CACONF'
[req]
prompt = no
distinguished_name = dn
x509_extensions = v3_ca

[dn]
C = KR
O = N2SL
CN = QOS Local CA

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
CACONF

# 이미 만든 CA가 있으면 절대 새로 만들지 않고 재사용.
if [[ -f "${CA_KEY}" && -f "${CA_CERT}" ]]; then
    echo "[PKI] Existing CA found. Reusing it."

elif [[ -f "${CA_KEY}" || -f "${CA_CERT}" ]]; then
    echo "[PKI] ERROR: Incomplete CA files."
    echo "[PKI] Both qos-ca.key and qos-ca.crt must exist together."
    exit 1

else
    echo "[PKI] Creating new QOS Local CA..."

    openssl genrsa \
        -out "${CA_KEY}" \
        4096

    chmod 600 "${CA_KEY}"

    openssl req \
        -x509 \
        -new \
        -sha256 \
        -days 3650 \
        -key "${CA_KEY}" \
        -out "${CA_CERT}" \
        -config "${CA_CONF}" \
        -extensions v3_ca
fi

echo
echo "========================================"
echo "[2] Creating server configuration"
echo "========================================"

cat > "${SERVER_CONF}" <<'SERVERCONF'
[req]
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
C = KR
O = N2SL
CN = mediasoup-edge

[req_ext]
subjectAltName = @alt_names

[server_ext]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer

[alt_names]
SERVERCONF

i=1

for ip in "$@"; do
    echo "IP.${i} = ${ip}" >> "${SERVER_CONF}"
    i=$((i + 1))
done

echo "[PKI] SAN addresses:"

for ip in "$@"; do
    echo "  - ${ip}"
done

echo
echo "========================================"
echo "[3] Creating cert.pem / key.pem"
echo "========================================"

# 기존 인증서가 있다면 자동 백업.
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

if [[ -f "${SERVER_CERT}" ]]; then
    cp -a "${SERVER_CERT}" \
        "${SERVER_CERT}.bak.${TIMESTAMP}"

    echo "[PKI] Existing cert.pem backed up."
fi

if [[ -f "${SERVER_KEY}" ]]; then
    cp -a "${SERVER_KEY}" \
        "${SERVER_KEY}.bak.${TIMESTAMP}"

    echo "[PKI] Existing key.pem backed up."
fi

rm -f "${TMP_CERT}" "${TMP_KEY}"

openssl genrsa \
    -out "${TMP_KEY}" \
    2048

chmod 600 "${TMP_KEY}"

openssl req \
    -new \
    -key "${TMP_KEY}" \
    -out "${SERVER_CSR}" \
    -config "${SERVER_CONF}"

openssl x509 \
    -req \
    -in "${SERVER_CSR}" \
    -CA "${CA_CERT}" \
    -CAkey "${CA_KEY}" \
    -CAcreateserial \
    -out "${TMP_CERT}" \
    -days 825 \
    -sha256 \
    -extfile "${SERVER_CONF}" \
    -extensions server_ext

echo
echo "========================================"
echo "[4] Verifying new certificate"
echo "========================================"

openssl verify \
    -CAfile "${CA_CERT}" \
    "${TMP_CERT}"

openssl x509 \
    -in "${TMP_CERT}" \
    -noout \
    -subject \
    -issuer \
    -ext subjectAltName

# 검증에 성공한 경우에만 실제 cert.pem/key.pem으로 교체.
mv "${TMP_CERT}" "${SERVER_CERT}"
mv "${TMP_KEY}" "${SERVER_KEY}"

chmod 644 "${SERVER_CERT}"
chmod 600 "${SERVER_KEY}"

echo
echo "========================================"
echo "[PKI] Complete"
echo "========================================"
echo
echo "CA certificate:"
echo "  ${CA_CERT}"
echo
echo "CA private key:"
echo "  ${CA_KEY}"
echo "  !!! DO NOT distribute this file !!!"
echo
echo "mediasoup server certificate:"
echo "  ${SERVER_CERT}"
echo
echo "mediasoup server private key:"
echo "  ${SERVER_KEY}"
