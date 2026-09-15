# Image de preuve de l'enceinte réseau : Ubuntu 26.04, les paquets que pose
# l'installateur, et de quoi simuler une session (PipeWire, Avahi, Weston sans écran).
FROM ubuntu:26.04
RUN sed -i "s/^Components: main.*/Components: main universe restricted multiverse/" /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get update -qq \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
      shairport-sync uxplay avahi-daemon avahi-utils dbus dbus-user-session libpulse0 libasound2t64 \
      python3 procps iproute2 ca-certificates curl pipewire pipewire-pulse wireplumber \
      gstreamer1.0-plugins-bad gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-tools \
      libglib2.0-bin systemd weston >/dev/null
