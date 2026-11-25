"""Adapt a staged copy of the pinned upstream Bazzite live installer."""
import pathlib
import sys


def replace_once(path, old, new):
    data = path.read_text()
    if data.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one upstream anchor: {old!r}")
    path.write_text(data.replace(old, new, 1))


source = pathlib.Path(sys.argv[1])
# The exact local tag is passed in as INSTALL_IMAGE_PAYLOAD. The host image
# archive is mounted read-only during the live-container build and not copied
# as a separate file into its layers.
replace_once(
    source / "build.sh",
    '''if mountpoint -q /usr/lib/containers/storage; then
    # We load our image from the host container storage if possible
    podman save --format oci-archive "$INSTALL_IMAGE_PAYLOAD" | podman load --storage-opt additionalimagestore=''
else
    podman pull "$INSTALL_IMAGE_PAYLOAD"
fi''',
    '''podman load --input /run/htpc-payload.oci
podman image exists "$INSTALL_IMAGE_PAYLOAD"''',
)

discovery = '''imageref="$(podman images --format '{{ index .Names 0 }}\\n' 'bazzite*' | head -1)"
imageref="${imageref##*://}"
imageref="${imageref%%:*}"'''
replace_once(source / "titanoboa_hook_preinitramfs.sh", discovery,
             'imageref="${INSTALL_IMAGE_PAYLOAD%:*}"')
post = source / "titanoboa_hook_postrootfs.sh"
replace_once(post, discovery + '''\nimagetag="$(podman images --format '{{ .Tag }}\\n' "$imageref" | head -1)"''',
             'imageref="${INSTALL_IMAGE_PAYLOAD%:*}"\nimagetag="${INSTALL_IMAGE_PAYLOAD##*:}"')
# Keep all upstream installer hooks except the switch to a registry image.
# No registry copy or custom OTA image exists for this project.
replace_once(post,
             'bootc switch --mutate-in-place --enforce-container-sigpolicy --transport registry $imageref:$imagetag',
             '# Stay on the embedded custom deployment; there is no registry counterpart.\n:')
