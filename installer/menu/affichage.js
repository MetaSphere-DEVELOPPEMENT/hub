"use strict";
// Menu du HUB — Réglages → Affichage : la définition et la fréquence de l'écran.
//
// POURQUOI CE RÉGLAGE. Mesuré sur la TV le 17/09/2026 : l'EDID ne propose aucun
// 3840×2160 à 60 Hz (lien HDMI 1.4), le 4K plafonne à 30 Hz. Le compteur d'images du
// menu (installer/menu/README.md, HUB_FPS=1) relève 29,4 images/s en 3840×2160 à 30 Hz,
// avec trois images de plus de 50 ms, contre 60,0 images/s et aucune image longue en
// 1920×1080 à 60 Hz. Le propriétaire ne peut pas changer de câble tout de suite : il lui
// faut pouvoir choisir entre la netteté du 4K et la fluidité du 1080p, depuis le canapé.
//
// POURQUOI UNE SECTION À PART, PAS UNE CARTE DANS « À PROPOS ». À propos ne fait que
// dire ce qu'est la machine, sans rien y changer ; ici on change le mode de l'écran, avec
// une liste à parcourir et un compte à rebours qui a besoin de toute la place. La section
// se range juste après Apparence, où vivent déjà les réglages de l'écran communs au HUB
// (taille des textes, zone sûre de la TV) : une entrée plus bas dans le sommaire, donc
// atteignable d'un pas à la télécommande.
//
// hub-menu lit et applique les modes avec gdctl (installer/hub-menu.py, « Affichage »).
// La page n'envoie jamais qu'un nom de mode pris dans la liste qu'elle a reçue ; hub-menu
// le recompare à ce que gdctl vient de lire avant d'exécuter quoi que ce soit.
//
// LE FILET. Un mode refusé par la TV laisse l'écran noir : plus personne ne peut répondre.
// Après chaque application, 15 s pour dire « Garder ». Sans réponse, la page redemande le
// mode d'avant — et hub-menu fait de même quelques secondes plus tard, au cas où la page
// ne répondrait plus (rechargement, WebKit figé) ou si le menu se fermait entre-temps.

Object.assign(TEXTES.fr, {
  "section.affichage": "Affichage",
  "affichage.ecran": "Écran",
  "affichage.mode": "{l}×{h} à {f} Hz",
  "affichage.fluide": "tout est fluide",
  "affichage.saccade": "le mouvement paraît saccadé",
  "affichage.etiquette.fluide": "Fluide",
  "affichage.etiquette.saccade": "Saccadé",
  "affichage.detail": "À 30 Hz, le mouvement paraît saccadé : les fondus et les défilements avancent par à-coups. En 1920×1080 à 60 Hz, tout est fluide, au prix d'un texte un peu moins fin. Le 3840×2160 à 60 Hz demande un câble HDMI 2.0 et le « Format amélioré » (ou « HDMI signal format ») de l'entrée HDMI de la TV.",
  "affichage.modes": "Définition et fréquence",
  "affichage.modes.detail": "Le mode choisi s'applique tout de suite. Sans confirmation en 15 secondes, le HUB revient au précédent.",
  "affichage.actif": "Actif",
  "affichage.retablir": "Rétablir au démarrage",
  "affichage.retablir.detail": "Le HUB réapplique ce mode à chaque allumage, au cas où la TV revienne au sien.",
  "affichage.lecture": "Lecture des modes de l'écran…",
  "affichage.attente": "Application du mode…",
  "affichage.sans.gdctl": "gdctl est absent de cette machine : les modes de l'écran ne peuvent être ni lus ni changés ici. Il est livré avec mutter ; sinon, réglez l'écran depuis Paramètres → Écrans du bureau GNOME.",
  "affichage.erreur": "Modes de l'écran illisibles : {e}",
  "affichage.plusieurs": "Plusieurs écrans sont branchés : le HUB n'y touche pas, pour ne pas défaire leur disposition. Réglez-les depuis le bureau GNOME.",
  "affichage.refus.inconnu": "Ce mode n'est plus proposé par l'écran.",
  "affichage.refus.echec": "L'écran a refusé ce mode.",
  "affichage.refus.absent": "gdctl est absent : aucun mode ne peut être appliqué.",
  "affichage.refus.lecture": "Les modes de l'écran n'ont pas pu être relus.",
  "affichage.refus.plusieurs": "Plusieurs écrans sont branchés : le HUB n'y touche pas.",
  "affichage.revenu": "Mode précédent rétabli.",
  "affichage.garde": "Mode gardé.",
  "affichage.filet.titre": "Garder ce mode ?",
  "affichage.filet.detail": "Si l'image est bonne, gardez ce mode. Sans réponse, le HUB revient au précédent.",
  "affichage.filet.reste": "Retour automatique dans {s} s",
  "affichage.garder": "Garder",
  "affichage.revenir": "Revenir en arrière",
});
Object.assign(TEXTES.en, {
  "section.affichage": "Display",
  "affichage.ecran": "Screen",
  "affichage.mode": "{l}×{h} at {f} Hz",
  "affichage.fluide": "everything is smooth",
  "affichage.saccade": "movement looks jerky",
  "affichage.etiquette.fluide": "Smooth",
  "affichage.etiquette.saccade": "Jerky",
  "affichage.detail": "At 30 Hz movement looks jerky: fades and scrolling advance in steps. At 1920×1080 and 60 Hz everything is smooth, with slightly less crisp text. 3840×2160 at 60 Hz needs an HDMI 2.0 cable and the “Enhanced format” (or “HDMI signal format”) setting of the TV input.",
  "affichage.modes": "Resolution and refresh rate",
  "affichage.modes.detail": "The chosen mode applies straight away. Without confirmation within 15 seconds, the HUB goes back to the previous one.",
  "affichage.actif": "Active",
  "affichage.retablir": "Restore on start-up",
  "affichage.retablir.detail": "The HUB applies this mode again at every power on, in case the TV goes back to its own.",
  "affichage.lecture": "Reading the screen modes…",
  "affichage.attente": "Applying the mode…",
  "affichage.sans.gdctl": "gdctl is missing on this machine: screen modes can be neither read nor changed here. It ships with mutter; otherwise set the screen from Settings → Displays on the GNOME desktop.",
  "affichage.erreur": "Screen modes could not be read: {e}",
  "affichage.plusieurs": "Several screens are plugged in: the HUB leaves them alone, so as not to undo their layout. Set them from the GNOME desktop.",
  "affichage.refus.inconnu": "The screen no longer offers this mode.",
  "affichage.refus.echec": "The screen refused this mode.",
  "affichage.refus.absent": "gdctl is missing: no mode can be applied.",
  "affichage.refus.lecture": "The screen modes could not be read again.",
  "affichage.refus.plusieurs": "Several screens are plugged in: the HUB leaves them alone.",
  "affichage.revenu": "Previous mode restored.",
  "affichage.garde": "Mode kept.",
  "affichage.filet.titre": "Keep this mode?",
  "affichage.filet.detail": "If the picture is good, keep this mode. Without an answer, the HUB goes back to the previous one.",
  "affichage.filet.reste": "Going back in {s} s",
  "affichage.garder": "Keep",
  "affichage.revenir": "Go back",
});

// 50 Hz et au-delà : le mouvement est fluide. En dessous (30 Hz sur cette TV), il saccade.
const AFFICHAGE_FLUIDE_HZ = 50;
const AFFICHAGE_FILET_S = 15;

let etatAffichage = null;
// Le mode demandé tant que hub-menu n'a pas répondu : la section le dit plutôt que de
// paraître inerte pendant la seconde que prend gdctl.
let affichageDemande = null;
// { mode, avant, fin, minuterie } pendant le compte à rebours.
let filetAffichage = null;

function reglageAffichage() {
  const a = reglages.systeme.affichage ||= {};
  if (typeof a.retablir !== "boolean") a.retablir = true;
  return a;
}

function affichageFluide(mode) { return mode.frequence >= AFFICHAGE_FLUIDE_HZ; }
function affichageHz(mode) { return Math.round(mode.frequence); }
function modeLisible(mode) { return t("affichage.mode", { l: mode.largeur, h: mode.hauteur, f: affichageHz(mode) }); }
function modeJuge(mode) { return t(affichageFluide(mode) ? "affichage.fluide" : "affichage.saccade"); }

// Hors du HUB (navigateur, mise au point, captures) : les modes relevés sur la vraie TV
// le 17/09/2026, pour que la section se dessine sans hub-menu derrière.
function apercuAffichage() {
  return {
    gdctl: true, connecteur: "HDMI-2", nom: "SONY TV", ecrans: 1, erreur: null, filet: AFFICHAGE_FILET_S,
    modes: [
      { nom: "1920x1080@60.000", largeur: 1920, hauteur: 1080, frequence: 60, courant: false, prefere: false },
      { nom: "1920x1080@50.000", largeur: 1920, hauteur: 1080, frequence: 50, courant: false, prefere: false },
      { nom: "1280x720@60.000", largeur: 1280, hauteur: 720, frequence: 60, courant: false, prefere: false },
      { nom: "3840x2160@30.000", largeur: 3840, hauteur: 2160, frequence: 30, courant: true, prefere: true },
    ],
  };
}

function choisirMode(mode) {
  if (affichageDemande || filetAffichage) return;
  affichageDemande = mode.nom;
  son("ok");
  annoncer(t("affichage.attente"));
  rendreSection();
  envoyer({ type: "affichage-appliquer", mode: mode.nom });
}

// ── La section ────────────────────────────────────────────────────────────
function contenuAffichage(zone) {
  if (estRestreint()) { zone.append(el("div", { class: "aide" }, t("profils.restreint"))); return; }
  const e = etatAffichage;
  if (!e) { zone.append(el("div", { class: "aide", id: "affichage-message" }, t("affichage.lecture"))); return; }

  // La fréquence de l'écran, en clair : c'est la première question qu'on se pose devant
  // un menu qui saccade, et le compteur d'images (HUB_FPS=1) n'est pas allumé d'ordinaire.
  const courant = (e.modes || []).find(m => m.courant) || null;
  zone.append(el("div", { class: "rangee ecran-actuel" },
    el("div", {},
      el("div", { class: "titre" }, t("affichage.ecran"), e.nom ? ` · ${e.nom}` : "",
        el("span", { class: "portee-hub" }, t("portee.hub"))),
      el("div", { class: "aide" }, t("affichage.detail"))),
    el("div", { class: `mode-courant ${courant && affichageFluide(courant) ? "fluide" : "saccade"}`, id: "affichage-courant" },
      el("span", { class: "definition" }, courant ? modeLisible(courant) : "—"),
      el("span", { class: "jugement" }, courant ? modeJuge(courant) : ""))));

  // Lecture seule : on dit pourquoi, on ne propose rien qui échouerait.
  const empeche = !e.gdctl ? t("affichage.sans.gdctl")
    : e.erreur ? t("affichage.erreur", { e: e.erreur })
      : e.ecrans > 1 ? t("affichage.plusieurs") : null;
  if (empeche) { zone.append(el("div", { class: "aide alerte-affichage", id: "affichage-message" }, empeche)); return; }

  const liste = el("div", { class: "modes-ecran", id: "modes-ecran" }, (e.modes || []).map(m => el("button", {
    class: `option mode-ecran${m.courant ? " choisie" : ""}`, "data-nav": true, "data-cle": `mode-${m.nom}`,
    disabled: !!affichageDemande || null,
    "aria-current": m.courant ? "true" : null,
    onclick: () => choisirMode(m),
  },
  el("span", { class: "definition" }, `${m.largeur}×${m.hauteur}`),
  el("span", { class: "frequence" }, `${affichageHz(m)} Hz`),
  el("span", { class: `jugement ${affichageFluide(m) ? "fluide" : "saccade"}` }, t(affichageFluide(m) ? "affichage.etiquette.fluide" : "affichage.etiquette.saccade")),
  m.courant && el("span", { class: "actif" }, t("affichage.actif")))));
  zone.append(rangee(t("affichage.modes"), affichageDemande ? t("affichage.attente") : t("affichage.modes.detail"), liste, true, true));

  const a = reglageAffichage();
  zone.append(rangee(t("affichage.retablir"), t("affichage.retablir.detail"),
    options("affichage-retablir", [[true, t("oui")], [false, t("non")]], a.retablir,
      v => { a.retablir = v === true || v === "true"; }), false, true));
}

// ── Le filet : « Garder ce mode ? » ───────────────────────────────────────
function ouvrirFiletAffichage(mode, secondes) {
  arreterFiletAffichage();
  let dialogue = $("affichage-filet");
  if (!dialogue) {
    dialogue = el("div", { class: "calque voile", id: "affichage-filet" },
      el("div", { class: "dialogue" },
        el("span", { class: "pictogramme", style: "--c: var(--arret)", html: '<svg viewBox="0 0 24 24"><rect x="2.5" y="4" width="19" height="13.5" rx="2.5"/><path d="M8 21h8M12 17.5V21"/></svg>' }),
        el("h2", { id: "affichage-filet-titre" }),
        el("p", { id: "affichage-filet-detail" }),
        el("div", { class: "compte-a-rebours", id: "affichage-filet-reste", role: "status" }),
        el("div", { class: "choix", id: "affichage-filet-choix" })));
    document.body.append(dialogue);
  }
  $("affichage-filet-titre").textContent = t("affichage.filet.titre");
  $("affichage-filet-detail").textContent = `${mode ? `${modeLisible(mode)} — ` : ""}${t("affichage.filet.detail")}`;
  const choix = $("affichage-filet-choix");
  choix.innerHTML = "";
  choix.append(
    el("button", { class: "bouton", "data-nav": true, "data-cle": "affichage-revenir", onclick: () => revenirAffichage(true) }, el("span", {}, t("affichage.revenir"))),
    el("button", { class: "bouton", "data-nav": true, "data-cle": "affichage-garder", onclick: garderAffichage }, el("span", {}, t("affichage.garder"))));
  // Une échéance, pas un compteur de tours : une page qui rame ne gagne pas de secondes.
  filetAffichage = { mode: mode?.nom || null, fin: Date.now() + secondes * 1000, minuterie: null };
  battreFiletAffichage();
  filetAffichage.minuterie = setInterval(battreFiletAffichage, 250);
  ouvrirCalque("affichage-filet", false);
  definirFocus(choix.querySelector('[data-cle="affichage-garder"]'), true);
}

function battreFiletAffichage() {
  if (!filetAffichage) return;
  const reste = Math.max(0, Math.ceil((filetAffichage.fin - Date.now()) / 1000));
  const zone = $("affichage-filet-reste");
  if (zone) zone.textContent = t("affichage.filet.reste", { s: reste });
  if (reste <= 0) revenirAffichage(false);
}

function arreterFiletAffichage() {
  if (filetAffichage) clearInterval(filetAffichage.minuterie);
  filetAffichage = null;
}

function fermerFiletAffichage() {
  const cle = filetAffichage?.mode && `mode-${filetAffichage.mode}`;
  arreterFiletAffichage();
  if (pile.at(-1) !== "affichage-filet") return;
  // Le contenu des réglages a été redessiné pendant que le filet était ouvert : la cible
  // que fermerCalque voulait retrouver n'existe plus, et il retomberait sur la première
  // entrée du sommaire — or parcourir le sommaire change la section, on quitterait
  // Affichage. On lui désigne le mode qu'on vient d'essayer.
  const retour = cle && $("contenu-reglages").querySelector(`[data-cle="${CSS.escape(cle)}"]`);
  if (retour) focusParCalque.reglages = retour;
  fermerCalque();
}

function garderAffichage() {
  const mode = filetAffichage?.mode;
  fermerFiletAffichage();
  if (!mode) return;
  // Gardé à l'écran : le mode devient celui du HUB. hub-menu l'a déjà écrit dans
  // monitors.xml (gdctl --persistent) ; les réglages servent au rétablissement.
  const a = reglageAffichage();
  a.mode = mode;
  a.connecteur = etatAffichage?.connecteur || null;
  sauver();
  envoyer({ type: "affichage-garder" });
  son("ok");
  annoncer(t("affichage.garde"));
  if (pile.at(-1) === "reglages" && sectionCourante === "affichage") rendreSection();
}

function revenirAffichage(demande) {
  fermerFiletAffichage();
  if (demande) son("retour");
  envoyer({ type: "affichage-revenir" });
}

// ── Accroches ─────────────────────────────────────────────────────────────
extensions.sections.push({ id: "affichage", apres: "apparence", icone: '<rect x="2.5" y="4" width="19" height="13.5" rx="2.5"/><path d="M8 21h8M12 17.5V21"/>' });
extensions.contenus.affichage = zone => {
  if (!etatAffichage && !PONT) etatAffichage = apercuAffichage();
  contenuAffichage(zone);
  if (!etatAffichage) envoyer({ type: "affichage-etat" });
};
extensions.messages.affichage = message => {
  etatAffichage = message;
  affichageDemande = null;
  if (message.applique && message.avant) ouvrirFiletAffichage((message.modes || []).find(m => m.courant), message.filet || AFFICHAGE_FILET_S);
  else if (message.applique === false && message.raison) {
    fermerFiletAffichage();
    const cle = message.raison === "revenu" ? "affichage.revenu" : `affichage.refus.${message.raison}`;
    if (message.raison !== "revenu") son("erreur");
    annoncer(t(cle), message.raison === "echec" ? message.erreur : null);
  }
  // Le filet passe devant les réglages : la liste dessous se remet à jour quand même.
  if (pile.includes("reglages") && sectionCourante === "affichage") rendreSection();
};
