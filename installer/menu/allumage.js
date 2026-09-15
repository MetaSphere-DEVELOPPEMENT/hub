"use strict";
// Menu du HUB — allumage et extinction programmés, allumage à distance.
//
// Réglage commun au HUB (une seule machine, une seule horloge) : reglages.systeme.allumage
// = { reveils: [lun…dim], extinctions: [lun…dim] }, "HH:MM" ou null. Après chaque
// changement, la page demande → { type: "allumage-appliquer" } : hub-menu démarre
// hub-allumage.service (root, autorisé par polkit), qui arme rtcwake et le minuteur
// d'extinction, puis répond { type: "allumage", reveil, extinction, erreur, ethernet }.
//
// Allumé par le réveil programmé (INITIAL.reveilProgramme), le menu s'ouvre directement
// en mode ambiant : horloge, météo, et le cadre photo si le profil l'a activé.
//
// Allumage à distance : un téléphone ne peut PAS réveiller le HUB depuis la télécommande
// web (page servie par le HUB éteint, et pas d'UDP dans un navigateur). On affiche donc
// l'adresse MAC et les vraies options (installer/allumage/README.md).

Object.assign(TEXTES.fr, {
  "section.allumage": "Allumage",
  "allumage.reveil": "Allumer le HUB",
  "allumage.reveil.detail": "Les jours choisis, le HUB s'allume seul et affiche l'horloge et la météo.",
  "allumage.extinction": "Éteindre le HUB",
  "allumage.extinction.detail": "Les jours choisis, le HUB s'éteint à cette heure, même pendant un film.",
  "allumage.heure": "À",
  "allumage.jamais": "Jamais",
  "allumage.prochain": "Prochain allumage : {q}",
  "allumage.prochaine.extinction": "Prochaine extinction : {q}",
  "allumage.rien": "Rien de programmé.",
  "allumage.erreur": "Programmation refusée par la machine : {e}",
  "allumage.non.installe": "Service d'allumage absent : relancer l'installateur.",
  "allumage.materiel": "Le réveil depuis l'arrêt dépend du BIOS (Power → Automatic Power On). La TV, elle, reste éteinte.",
  "allumage.distance": "Allumer à distance",
  "allumage.distance.detail": "La télécommande du téléphone ne peut pas allumer le HUB : elle est servie par le HUB lui-même. Enregistrez cette adresse dans une application Wake-on-LAN, ou utilisez la fonction de réveil de votre box. HUB branché en Ethernet uniquement.",
  "allumage.mac": "Adresse MAC",
  "allumage.sans.ethernet": "Aucune carte Ethernet détectée : pas d'allumage à distance possible par le wifi.",
});
Object.assign(TEXTES.en, {
  "section.allumage": "Power schedule",
  "allumage.reveil": "Power on the HUB",
  "allumage.reveil.detail": "On the chosen days, the HUB powers on by itself and shows the clock and weather.",
  "allumage.extinction": "Power off the HUB",
  "allumage.extinction.detail": "On the chosen days, the HUB powers off at this time, even during a movie.",
  "allumage.heure": "At",
  "allumage.jamais": "Never",
  "allumage.prochain": "Next power on: {q}",
  "allumage.prochaine.extinction": "Next power off: {q}",
  "allumage.rien": "Nothing scheduled.",
  "allumage.erreur": "The machine refused the schedule: {e}",
  "allumage.non.installe": "Power schedule service missing: run the installer again.",
  "allumage.materiel": "Waking from power off depends on the BIOS (Power → Automatic Power On). The TV stays off.",
  "allumage.distance": "Power on remotely",
  "allumage.distance.detail": "The phone remote can't power on the HUB: the HUB itself serves it. Save this address in a Wake-on-LAN app, or use your router's wake feature. Wired Ethernet only.",
  "allumage.mac": "MAC address",
  "allumage.sans.ethernet": "No Ethernet card detected: no remote power on over Wi-Fi.",
});

let etatAllumage = INITIAL.allumage || null;
let minuterieAllumage;

function programmeAllumage() {
  const a = reglages.systeme.allumage ||= {};
  for (const cle of ["reveils", "extinctions"]) {
    if (!Array.isArray(a[cle]) || a[cle].length !== 7) a[cle] = [null, null, null, null, null, null, null];
  }
  return a;
}

function appliquerAllumage() {
  clearTimeout(minuterieAllumage);
  // Après l'écriture des réglages (sauver() attend 400 ms) : le service relit le fichier.
  minuterieAllumage = setTimeout(() => { if (PONT) envoyer({ type: "allumage-appliquer" }); }, 1200);
}

function quandLisible(epoch) {
  const d = new Date(epoch * 1000);
  return `${d.toLocaleDateString(locale(), { weekday: "long" })} ${heureCourte(d)}`;
}

// Jours (lundi d'abord) puis une heure commune aux jours choisis : sept horaires
// différents se règlent mal à la télécommande, et personne ne les veut.
function blocHoraire(cle, liste, heures) {
  const heure = liste.find(Boolean) || heures[1];
  const noms = [...Array(7)].map((_, i) => new Date(2026, 8, 14 + i).toLocaleDateString(locale(), { weekday: "short" }));
  const jours = el("div", { class: "options jours-allumage" }, noms.map((nom, i) => el("button", {
    class: `option${liste[i] ? " choisie" : ""}`, "data-nav": true, "data-cle": `${cle}-jour-${i}`,
    onclick: () => { liste[i] = liste[i] ? null : heure; sauver(); appliquerAllumage(); rendreSection(); son("ok"); },
  }, nom)));
  const horaires = options(`${cle}-heure`, heures.map(h => [h, h]), heure, h => {
    for (let i = 0; i < 7; i++) if (liste[i]) liste[i] = h;
    appliquerAllumage();
  });
  return el("div", { class: "horaire-allumage" }, jours, horaires);
}

function contenuAllumage(zone) {
  if (estRestreint()) { zone.append(el("div", { class: "aide" }, t("profils.restreint"))); return; }
  const a = programmeAllumage();
  zone.append(
    rangee(t("allumage.reveil"), t("allumage.reveil.detail"), blocHoraire("reveil", a.reveils, ["06:30", "07:00", "07:30", "08:00", "09:00"]), true, true),
    rangee(t("allumage.extinction"), t("allumage.extinction.detail"), blocHoraire("extinction", a.extinctions, ["22:00", "23:00", "23:30", "00:30", "01:00"]), true, true));

  const e = etatAllumage;
  const lignes = [];
  if (e?.lance === false) lignes.push(t("allumage.non.installe"));
  else if (e?.erreur) lignes.push(t("allumage.erreur", { e: e.erreur }));
  if (e?.reveil) lignes.push(t("allumage.prochain", { q: quandLisible(e.reveil) }));
  if (e?.extinction) lignes.push(t("allumage.prochaine.extinction", { q: quandLisible(e.extinction) }));
  if (e && !e.reveil && !e.extinction && !e.erreur && e.lance !== false) lignes.push(t("allumage.rien"));
  zone.append(el("div", { class: "aide etat-allumage", id: "etat-allumage" }, [...lignes, t("allumage.materiel")].join(" · ")));

  const cartes = e?.ethernet || [];
  zone.append(rangee(t("allumage.distance"), t("allumage.distance.detail"),
    el("div", { class: "adresses-mac" }, cartes.length
      ? cartes.map(c => el("div", { class: "info" }, el("div", { class: "etiquette" }, `${t("allumage.mac")} · ${c.interface}`), el("div", { class: "valeur mac" }, c.adresse)))
      : el("div", { class: "aide" }, t("allumage.sans.ethernet"))), true, true));
}

extensions.sections.push({ id: "allumage", apres: "veille", icone: '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/><circle cx="19" cy="4.5" r="2.2"/>' });
extensions.contenus.allumage = zone => {
  contenuAllumage(zone);
  if (!etatAllumage && PONT) envoyer({ type: "allumage-etat" });
};
extensions.messages.allumage = message => {
  etatAllumage = message;
  if (pile.at(-1) === "reglages" && sectionCourante === "allumage") rendreSection();
};

// Allumé par le réveil du matin : directement l'horloge et la météo (et le cadre photo).
// Après l'éventuelle demande de code du démarrage (1,8 s), que le mode ambiant referme.
if (INITIAL.reveilProgramme) setTimeout(entrerAmbiant, 2000);
