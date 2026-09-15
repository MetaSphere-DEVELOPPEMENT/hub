#!/bin/bash
# Preuve en conteneur : les trois récepteurs démarrent par hub-enceinte et s'annoncent en mDNS.
#
#   docker build -t hub-enceinte-preuve installer/enceinte/preuve
#   docker run --rm -v "$PWD":/depot:ro hub-enceinte-preuve bash /depot/installer/enceinte/preuve/preuve.sh
#
# Sans systemd dans le conteneur : les unités sont vérifiées par systemd-analyze, puis
# les commandes qu'elles lancent sont exécutées à la main, dans une session D-Bus avec
# PipeWire et un Weston sans écran (UxPlay veut un Wayland pour démarrer).
set -u
echo "== empreinte du paquet raspotify"
curl -sSfL -o /tmp/r.deb "https://github.com/dtcooper/raspotify/releases/download/0.48.2/raspotify_0.48.2.librespot.v0.8.0-9c7d756_amd64.deb" || exit 1
echo "7f2c232af89834608bc393f6f9295a22a2659fe938f65c108b78a70c8b539733  /tmp/r.deb" | sha256sum -c - || exit 1
mkdir -p /tmp/deb /opt/hub-enceinte && dpkg-deb -x /tmp/r.deb /tmp/deb && install -m 0755 /tmp/deb/usr/bin/librespot /opt/hub-enceinte/librespot
/opt/hub-enceinte/librespot --version 2>&1 | tail -1
install -D -m 0755 /depot/installer/enceinte/hub_enceinte.py /usr/local/bin/hub-enceinte
echo "== unités (systemd-analyze verify)"
mkdir -p /tmp/u && cp /depot/installer/enceinte/*.service /tmp/u/
sed -i '/^After=\|^Wants=\|^PartOf=\|^Documentation=/d' /tmp/u/*.service
SYSTEMD_LOG_LEVEL=err systemd-analyze verify --user /tmp/u/*.service 2>&1 | grep -v 'Failed to\|Cannot\|user manager' ; echo "verify: fini"
mkdir -p /run/dbus && dbus-daemon --system --fork && avahi-daemon -D --no-drop-root 2>/dev/null; sleep 2
useradd -m hub
cat > /home/hub/session.sh <<'EOS'
export XDG_RUNTIME_DIR=/tmp/run-hub; mkdir -p -m 0700 $XDG_RUNTIME_DIR
weston --backend=headless --socket=wl-hub >/tmp/weston.log 2>&1 & sleep 2; export WAYLAND_DISPLAY=wl-hub
pipewire >/tmp/pw.log 2>&1 & sleep 1; wireplumber >/tmp/wp.log 2>&1 & pipewire-pulse >/tmp/pwp.log 2>&1 & sleep 2
mkdir -p ~/.config/hub && echo '{"profils":[{"id":"s"}],"systeme":{"enceinte":{"nom":"HUB Preuve"}}}' > ~/.config/hub/reglages.json
for s in spotify airplay ecran; do hub-enceinte actif $s; echo "actif $s -> $?"; done
hub-enceinte servir >/tmp/coord.log 2>&1 &
sleep 1
hub-enceinte lancer spotify >/tmp/spotify.log 2>&1 &
hub-enceinte lancer airplay >/tmp/airplay.log 2>&1 &
hub-enceinte lancer ecran >/tmp/ecran.log 2>&1 &
sleep 8
echo "== processus"; ps -eo user,comm,args | grep -E 'librespot|shairport|uxplay|hub-enceinte' | grep -v grep | cut -c1-160
echo "== ports à l'écoute"; ss -lntup 2>/dev/null | grep -E 'librespot|shairport|uxplay' | awk '{print $1, $5, $7}'
echo "== mDNS (avahi-browse)"; avahi-browse -a -t -r -p 2>/dev/null | grep '^=' | grep IPv4 | cut -d';' -f4,5,9 | sort -u
echo "== journaux"; for f in spotify airplay ecran coord; do echo "-- $f"; tail -n 6 /tmp/$f.log; done
echo "== config airplay générée"; grep name $XDG_RUNTIME_DIR/hub/shairport-sync.conf
echo "== crochet librespot -> état"; PLAYER_EVENT=track_changed NAME="Titre essai" ARTISTS="Artiste" TRACK_ID=x hub-enceinte evenement spotify; PLAYER_EVENT=playing hub-enceinte evenement spotify; sleep 1; cat $XDG_RUNTIME_DIR/hub/lecture.json; echo
echo "== MPRIS de shairport-sync sur le bus de session"; gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames | tr ',' '\n' | grep -i shairport
EOS
chmod +x /home/hub/session.sh
su - hub -c 'dbus-run-session -- bash /home/hub/session.sh'
