ARG BASE_IMAGE=ghcr.io/ublue-os/bazzite-deck:stable
FROM ${BASE_IMAGE}
COPY rootfs/ /
RUN dnf -y install google-noto-sans-sc-fonts && dnf clean all
RUN chmod 0755 /usr/libexec/bazzite-htpc-flatpaks /usr/bin/bazzite-htpc-kodi \
    && systemctl enable bazzite-htpc-flatpaks.timer \
    && bootc container lint
