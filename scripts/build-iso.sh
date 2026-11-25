#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
project="$PWD"
base=${BASE_IMAGE:-ghcr.io/ublue-os/bazzite-deck:stable}
desktop=${LIVE_BASE_IMAGE:-ghcr.io/ublue-os/bazzite:stable}
payload=localhost/bazzite-deck-htpc:local
live=localhost/bazzite-htpc-live:latest
bazzite_rev=b42cdec64f91b8218ff710724099cce6245805e0
titanoboa_rev=5c457c3d0518bd17e754be0fd98a60d29d26abb4
out=$(realpath -m -- "${1:-output}")
mkdir -p -- "$out"
[[ -z $(ls -A -- "$out") ]] || { echo "Output directory must be empty: $out" >&2; exit 2; }
[[ $(uname -m) == x86_64 ]] || { echo 'An x86-64 Linux host is required.' >&2; exit 2; }
pd=(sudo podman)
if (( EUID == 0 )); then pd=(podman); fi

work=$(mktemp -d "${HTPC_BUILD_TMPDIR:-${TMPDIR:-/tmp}}/htpc-iso.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
git -C "$work" init -q upstream
git -C "$work/upstream" fetch -q --depth=1 https://github.com/ublue-os/bazzite.git "$bazzite_rev"
git -C "$work/upstream" checkout -q --detach FETCH_HEAD
[[ $(git -C "$work/upstream" rev-parse HEAD) == "$bazzite_rev" ]]
installer="$work/upstream/installer"
python3 scripts/prepare-live.py "$installer"
for file in build.sh titanoboa_hook_preinitramfs.sh titanoboa_hook_postrootfs.sh; do
    bash -n "$installer/$file"
done

"${pd[@]}" pull "$base"
base_digest=$("${pd[@]}" image inspect --format '{{index .RepoDigests 0}}' "$base")
"${pd[@]}" build --pull=never --build-arg "BASE_IMAGE=$base_digest" -t "$payload" .
payload_id=$("${pd[@]}" image inspect --format '{{.Id}}' "$payload")
# Redirect stdout from the privileged process, so the temporary file is owned
# by the caller and can always be removed by the cleanup trap.
"${pd[@]}" save --format oci-archive "$payload" > "$work/payload.oci"
"${pd[@]}" pull "$desktop"
desktop_digest=$("${pd[@]}" image inspect --format '{{index .RepoDigests 0}}' "$desktop")
"${pd[@]}" build --cap-add sys_admin --security-opt label=disable --pull=never     --volume "$work/payload.oci:/run/htpc-payload.oci:ro"     --build-arg "BASE_IMAGE=$desktop_digest"     --build-arg "INSTALL_IMAGE_PAYLOAD=$payload"     --build-arg FLATPAK_DIR_SHORTNAME=kde_flatpaks     -t "$live" "$installer"
rm -- "$work/payload.oci"

git -C "$work" init -q titanoboa
git -C "$work/titanoboa" fetch -q --depth=1 https://github.com/ublue-os/titanoboa.git "$titanoboa_rev"
git -C "$work/titanoboa" checkout -q --detach FETCH_HEAD
[[ $(git -C "$work/titanoboa" rev-parse HEAD) == "$titanoboa_rev" ]]
# Titanoboa invokes sudo podman and bind-mounts the output directory.
mkdir -- "$out/staging"
(
    cd -- "$work/titanoboa"
    TITANOBOA_OUTPUT_DIR="$out/staging" ./main.sh "$live"
)
mapfile -d '' isos < <(find "$out/staging" -maxdepth 1 -type f -name '*.iso' -print0)
(( ${#isos[@]} == 1 )) && [[ -s ${isos[0]} ]] || { echo 'Expected exactly one nonempty ISO.' >&2; exit 3; }
if (( EUID != 0 )); then sudo chown "$(id -u):$(id -g)" "${isos[0]}"; fi
mv -- "${isos[0]}" "$out/bazzite-htpc-amd64.iso"
rmdir -- "$out/staging"
(
    cd -- "$out"
    sha256sum bazzite-htpc-amd64.iso > SHA256SUMS
    printf 'deck=%s\ndesktop=%s\nembedded=%s\ninstaller=%s\ntitanoboa=%s\ncommit=%s\n'         "$base_digest" "$desktop_digest" "$payload_id" "$bazzite_rev" "$titanoboa_rev"         "$(git -C "$project" rev-parse HEAD 2>/dev/null || echo unknown)" > build-info.txt
)
