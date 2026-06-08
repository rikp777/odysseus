#!/bin/sh
set -eu

DATA_DIR="${PHOTON_DATA_DIR:-/photon}"
DB_DIR="${DATA_DIR}/photon_data"
DB_URL="${PHOTON_DB_URL:-https://download1.graphhopper.com/public/europe/netherlands/photon-db-netherlands-1.0-latest.tar.bz2}"
HEAP="${PHOTON_HEAP:-4G}"

mkdir -p "$DATA_DIR"

if [ ! -d "$DB_DIR" ] || [ -z "$(find "$DB_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    tmp_dir="$(mktemp -d "${DATA_DIR}/.photon-download.XXXXXX")"
    archive="${tmp_dir}/photon-db.tar.bz2"
    cleanup() {
        rm -rf "$tmp_dir"
    }
    trap cleanup EXIT INT TERM

    echo "Downloading Photon database from ${DB_URL}"
    curl -fL --retry 3 --retry-delay 5 -o "$archive" "$DB_URL"
    bzip2 -cd "$archive" | tar -x -C "$tmp_dir"

    found="$(find "$tmp_dir" -maxdepth 3 -type d -name photon_data -print -quit)"
    if [ -z "$found" ]; then
        echo "Photon database archive did not contain photon_data" >&2
        exit 1
    fi

    rm -rf "$DB_DIR"
    mv "$found" "$DB_DIR"
    trap - EXIT INT TERM
    cleanup
fi

cd "$DATA_DIR"
exec java ${JAVA_OPTS:-"-Xmx${HEAP}"} -jar /opt/photon.jar serve \
    -listen-ip 0.0.0.0 \
    -listen-port 2322 \
    -default-language "${PHOTON_DEFAULT_LANGUAGE:-nl}"
