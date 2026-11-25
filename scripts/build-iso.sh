#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
base=${BASE_IMAGE:-ghcr.io/ublue-os/bazzite-deck:stable}
builder=${BUILDER_IMAGE:-quay.io/centos-bootc/bootc-image-builder:latest}
image=${TARGET_IMAGE:-localhost/bazzite-htpc-iso:latest}
out=$(realpath -m -- "${1:-output}")
mkdir -p -- "$out"
[[ -z $(ls -A -- "$out") ]] || { echo "Output directory must be empty: $out" >&2; exit 2; }
command -v podman >/dev/null
if (( EUID == 0 )); then pd=(podman); else pd=(sudo podman); fi
"${pd[@]}" pull "$base"
base_digest=$("${pd[@]}" image inspect --format '{{index .RepoDigests 0}}' "$base")
"${pd[@]}" pull "$builder"
builder_digest=$("${pd[@]}" image inspect --format '{{index .RepoDigests 0}}' "$builder")
"${pd[@]}" build --pull=never --build-arg "BASE_IMAGE=$base_digest" -t "$image" .
store=$("${pd[@]}" info --format '{{.Store.GraphRoot}}')
"${pd[@]}" run --rm --privileged --security-opt label=disable \
  -v "$store:/var/lib/containers/storage" \
  -v "$out:/output" \
  -v "$PWD/disk-config.toml:/config.toml:ro" \
  "$builder_digest" --type anaconda-iso --rootfs btrfs \
  --config /config.toml --chown "$(id -u):$(id -g)" "$image"
mapfile -d '' isos < <(find "$out" -type f -name '*.iso' -print0)
(( ${#isos[@]} == 1 )) || { echo "Expected one ISO; got ${#isos[@]}" >&2; exit 3; }
mv -- "${isos[0]}" "$out/bazzite-htpc-amd64.iso"
(
  cd -- "$out"
  sha256sum bazzite-htpc-amd64.iso > SHA256SUMS
  printf 'base=%s\nbuilder=%s\nimage=%s\ncommit=%s\n' \
    "$base_digest" "$builder_digest" "$image" "$(git -C "$OLDPWD" rev-parse HEAD 2>/dev/null || echo unknown)" > build-info.txt
)
