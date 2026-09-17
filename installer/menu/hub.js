"use strict";
// Menu du HUB — logique.
//
// Le menu parle à hub-menu (Python) par window.webkit.messageHandlers.hub, en JSON :
//   → { type: "choix", mode }            un mode est lancé, le menu va se fermer
//   → { type: "choix", mode: "web", service }  un service (« netflix ») : hub-web l'ouvre
//   → { type: "reglages", donnees }      enregistrer ~/.config/hub/reglages.json
//   → { type: "meteo", lat, lon }        demander un relevé (Python le met en cache)
//   → { type: "geocodage", nom, langue } chercher une ville
//   → { type: "minuteur", minutes }      programmer (ou annuler avec 0) l'extinction
//   → { type: "infos" }                  machine, adresse IP, disque…
//   → { type: "appairage", affiche }     l'écran d'appairage de la télécommande est (ou n'est plus) à l'écran
//   → { type: "recopie-code", nouveau }  le code de recopie d'écran (nouveau : en tirer un autre)
// Python répond en appelant window.hub.recevoir({ type, ... }), et y relaie aussi les
// état de l'enceinte réseau ({ type: "lecture", etat: {source, etat, titre, artiste, pochette, ecran…} | null })
// et les commandes vocales de hub-voix ({ type: "commande", nom } / { type: "voix", ... }).
//
// Sans pont (navigateur ordinaire, mise au point), les réglages vont dans
// localStorage et la météo est demandée directement à Open-Meteo.

const PONT = window.webkit?.messageHandlers?.hub || null;
const INITIAL = window.HUB_INITIAL || {};
const parametres = new URLSearchParams(location.search);
// Aperçu depuis la clé USB : le menu tourne dans un navigateur, rien n'est installé.
const APERCU = parametres.has("apercu");

const COULEURS_MODE = {
  tv: [62, 224, 208],
  jeux: [179, 107, 255],
  bureau: [255, 181, 71],
  arret: [255, 107, 107],
};
const COULEURS_PROFIL = {
  turquoise: [62, 224, 208],
  violet: [158, 110, 255],
  ambre: [255, 170, 60],
  corail: [255, 112, 102],
  bleu: [80, 150, 255],
  vert: [80, 200, 120],
  rose: [255, 100, 180],
};

const DEFAUTS_PROFIL = {
  // Neutre : le dépôt est public. Un reglages.json existant garde ses profils, leurs
  // identifiants et son profilActif (voir la fusion plus bas) ; seul un HUB neuf part de là.
  nom: "Profil 1",
  couleur: "turquoise",
  theme: "sombre",
  // La couleur du fond (une palette, « minimal » ou « photos ») et son motif. Un profil
  // neuf part du motif cinéma de l'accueil ; un profil enregistré sans « motif » garde
  // les nappes qu'il avait (voir la lecture des réglages plus bas).
  fond: "aurore",
  motif: "cinema",
  teinteMode: true,
  langue: "fr",
  horloge: "24",
  animations: "completes",
  dernier: "tv",
  photo: null,
  // null : le profil suit le réglage commun du HUB.
  sons: null,
  veille: null,
  meteo: null,
  pin: null,
  modes: { tv: true, gaming: true, bureau: true },
  // { netflix: false } : service masqué pour ce profil. Absent : affiché.
  services: {},
  reglagesProteges: false,
  verrouVeille: false,
};
const DEFAUTS = {
  version: 1,
  profilActif: "profil-1",
  profils: [{ id: "profil-1", ...DEFAUTS_PROFIL }],
  systeme: {
    voix: true,
    sons: true,
    veille: 10,
    demanderProfil: false,
    echelle: 1,
    marge: 5,
    // Enceinte réseau (installer/enceinte) : lu par hub-enceinte, qui relance le récepteur concerné.
    enceinte: { spotify: true, airplay: true, ecran: true, nom: "HUB" },
    // Pas de ville par défaut : le dépôt est public, et une ville inventée afficherait la
    // météo d'ailleurs. Choisir sa ville active la météo. Les réglages déjà enregistrés
    // gardent la leur (fusion avec ces défauts).
    meteo: { active: false, ville: null, lat: null, lon: null },
  },
};

// ── Petits outils ─────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const racine = document.documentElement;

function el(tag, attrs = {}, ...enfants) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") e.className = v;
    // « html » : pictos et icônes écrits dans ce code, jamais une donnée reçue (nom,
    // ville, titre) — la page a accès aux fichiers et parle à hub-menu.
    else if (k === "html") e.innerHTML = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of enfants.flat()) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(c));
  }
  return e;
}

// Une photo si le profil en a une (et qu'elle se charge), sinon l'initiale sur sa couleur.
function habillerAvatar(e, p) {
  const couleur = COULEURS_PROFIL[p.couleur] || COULEURS_PROFIL.turquoise;
  e.style.setProperty("--c", couleur.join(" "));
  e.textContent = (p.nom?.[0] || "?").toUpperCase();
  e.classList.remove("avec-photo");
  e.style.backgroundImage = "";
  if (!p.photo) return e;
  const image = new Image();
  image.onload = () => {
    e.classList.add("avec-photo");
    e.style.backgroundImage = `url("${encodeURI(decodeURI(p.photo))}")`;
  };
  image.src = p.photo;
  return e;
}
function avatar(p, attrs = {}) { return habillerAvatar(el("span", { class: "avatar", ...attrs }), p); }

function copie(o) { return JSON.parse(JSON.stringify(o)); }
function fusion(defaut, valeur) {
  if (Array.isArray(defaut)) return Array.isArray(valeur) ? valeur : defaut;
  if (defaut && typeof defaut === "object") {
    const r = { ...defaut };
    for (const k of Object.keys(valeur || {})) r[k] = k in defaut ? fusion(defaut[k], valeur[k]) : valeur[k];
    return r;
  }
  return valeur === undefined ? defaut : valeur;
}
function melange(a, b, t) { return a.map((v, i) => v + (b[i] - v) * t); }
function borne(v, min, max) { return Math.max(min, Math.min(max, v)); }

function envoyer(message) {
  if (PONT) PONT.postMessage(JSON.stringify(message));
  else console.log("→ hub-menu", message);
}

// ── Réglages ──────────────────────────────────────────────────────────────
let reglages = (() => {
  let brut = INITIAL.reglages;
  if (!brut && !PONT) {
    try { brut = JSON.parse(localStorage.getItem("hub-reglages")); } catch { brut = null; }
  }
  const r = fusion(copie(DEFAUTS), brut || {});
  // « motif » est venu après « fond » : un profil qui ne le porte pas a été réglé quand il
  // n'y avait que les nappes, et doit les garder.
  r.profils = (r.profils.length ? r.profils : copie(DEFAUTS.profils)).map(p => ({ ...DEFAUTS_PROFIL, motif: "nappes", ...p }));
  if (!r.profils.some(p => p.id === r.profilActif)) r.profilActif = r.profils[0].id;
  return r;
})();

function profil() { return reglages.profils.find(p => p.id === reglages.profilActif); }
function meteoProfil() { return profil().meteo || reglages.systeme.meteo; }
function meteoSituee(m = meteoProfil()) { return Number.isFinite(m?.lat) && Number.isFinite(m?.lon); }
function sonsActifs() { return profil().sons ?? reglages.systeme.sons; }
function veilleMinutes() { return profil().veille ?? reglages.systeme.veille; }
function modeAutorise(mode, p = profil()) { return p.modes?.[mode] !== false; }
// Fonctionnalités chargées à part (temps-ecran.js, allumage.js, cadre.js) : elles
// s'accrochent à ces points plutôt que de grossir ce fichier, que plusieurs mains modifient.
const extensions = { restrictions: [], apparence: [], avantLancer: [], sections: [], contenus: {}, messages: {}, ambiant: [] };
window.hubExtensions = extensions;
function estRestreint(p = profil()) {
  return ["tv", "gaming", "bureau"].some(m => !modeAutorise(m, p)) || extensions.restrictions.some(f => f(p));
}
function lancementRefuse(mode) { return extensions.avantLancer.some(f => f(mode) === false); }

// ── Services : streaming et jeu en nuage ──────────────────────────────────
// La liste blanche vit dans hub-web (adresse, agent utilisateur) ; ici, seulement ce
// qui se voit. Des tuiles typographiques aux couleurs du service, pas de logos : les
// marques déposées n'ont rien à faire dans le dépôt. tests/test_hub_web.py vérifie
// que les identifiants sont les mêmes des deux côtés.
const SERVICES = [
  { id: "youtube", categorie: "streaming", halo: "#ff3b30", nom: "YouTube", fond: "linear-gradient(135deg, #ff3b30, #b3001b)", encre: "#fff", style: "font-weight:800;letter-spacing:-.035em" },
  { id: "netflix", categorie: "streaming", halo: "#e50914", nom: "NETFLIX", fond: "radial-gradient(120% 140% at 50% 120%, #4a0508, #0b0b0b 65%)", encre: "#e50914", style: "font-weight:900;letter-spacing:.06em;transform:scaleY(1.15)" },
  { id: "primevideo", categorie: "streaming", halo: "#1f9bff", nom: "prime video", fond: "linear-gradient(135deg, #1f9bff, #0f171e 72%)", encre: "#fff", style: "font-weight:700;letter-spacing:-.02em;text-transform:lowercase" },
  { id: "disneyplus", categorie: "streaming", halo: "#3d6bff", nom: "Disney+", fond: "linear-gradient(140deg, #2a55d9, #0b1650 58%, #040a2c)", encre: "#fff", style: "font-weight:600;font-style:italic;letter-spacing:-.02em" },
  { id: "canalplus", categorie: "streaming", halo: "#c8ccd4", nom: "CANAL+", fond: "linear-gradient(160deg, #2b2b2b, #000 60%)", encre: "#fff", style: "font-weight:900;letter-spacing:.02em" },
  { id: "twitch", categorie: "streaming", halo: "#a970ff", nom: "twitch", fond: "linear-gradient(135deg, #a970ff, #6a2bd9)", encre: "#fff", style: "font-weight:800;letter-spacing:-.02em" },
  { id: "arte", categorie: "streaming", halo: "#ff6a2b", nom: "arte", fond: "linear-gradient(135deg, #ff6a2b, #d8350c)", encre: "#fff", style: "font-weight:800;letter-spacing:-.04em" },
  { id: "francetv", categorie: "streaming", halo: "#3b4bff", nom: "france.tv", fond: "linear-gradient(135deg, #3b4bff, #0b1b8f)", encre: "#fff", style: "font-weight:700;letter-spacing:-.02em" },
  { id: "geforcenow", categorie: "jeux", halo: "#76b900", nom: "GeForce NOW", fond: "linear-gradient(150deg, #1c1c1c, #070707 70%)", encre: "#76b900", style: "font-weight:800;letter-spacing:-.01em" },
  { id: "xcloud", categorie: "jeux", halo: "#17a317", nom: "Xbox Cloud", fond: "linear-gradient(135deg, #17a317, #0b4d0b)", encre: "#fff", style: "font-weight:700;letter-spacing:-.01em" },
  { id: "boosteroid", categorie: "jeux", halo: "#ff3d8b", nom: "Boosteroid", fond: "linear-gradient(135deg, #6a2cff, #ff3d8b)", encre: "#fff", style: "font-weight:800;letter-spacing:-.02em" },
  { id: "steam", categorie: "jeux", halo: "#66c0f4", nom: "STEAM", appli: true, fond: "linear-gradient(135deg, #2a475e, #171a21)", encre: "#c7d5e0", style: "font-weight:700;letter-spacing:.22em" },
  { id: "moonlight", categorie: "jeux", halo: "#aab4c8", nom: "Moonlight", appli: true, fond: "linear-gradient(135deg, #3a3f4b, #16181d)", encre: "#e8ecf5", style: "font-weight:600;letter-spacing:-.01em" },
];
function modeDuService(s) { return s.categorie === "jeux" ? "gaming" : "tv"; }
function etatService(s) { return INITIAL.services?.services?.[s.id] || null; }
// Steam et Moonlight n'existent que s'ils sont installés : sans relevé de hub-web (aperçu,
// mise au point), on ne les invente pas. Les pages web, elles, sont toujours montrées.
function serviceInstallable(s) { return !s.appli || !!etatService(s)?.disponible; }
function serviceDisponible(s) { return etatService(s) ? etatService(s).disponible : !s.appli; }
function serviceVisible(s, p = profil()) {
  return p.services?.[s.id] !== false && modeAutorise(modeDuService(s), p) && serviceInstallable(s);
}

let minuterieSauvegarde;
function sauver() {
  clearTimeout(minuterieSauvegarde);
  // Regroupées : parcourir une liste d'options ne réécrit pas le disque à chaque pas.
  minuterieSauvegarde = setTimeout(() => {
    if (PONT) envoyer({ type: "reglages", donnees: reglages });
    else try { localStorage.setItem("hub-reglages", JSON.stringify(reglages)); } catch { /* aperçu seulement */ }
  }, 400);
}

// ── Textes ────────────────────────────────────────────────────────────────
function t(cle, variables = {}) {
  const langue = profil().langue;
  let texte = TEXTES[langue]?.[cle] ?? TEXTES.fr[cle] ?? cle;
  for (const [k, v] of Object.entries(variables)) texte = texte.replace(`{${k}}`, v);
  return texte;
}
function locale() { return profil().langue === "en" ? "en-GB" : "fr-FR"; }
function appliquerTextes() {
  racine.lang = profil().langue;
  document.querySelectorAll("[data-t]").forEach(e => { e.textContent = t(e.dataset.t); });
}

// ── Sons de l'interface ───────────────────────────────────────────────────
// Synthétisés : aucun fichier, et un volume discret, pensé pour un salon.
let audio;
function son(nature) {
  if (!sonsActifs()) return;
  try {
    audio ||= new AudioContext();
    const notes = { deplacer: [[1320, .035]], ok: [[880, .06], [1320, .09]], retour: [[660, .05], [440, .08]], erreur: [[220, .09], [196, .12]] }[nature];
    let debut = audio.currentTime;
    for (const [frequence, duree] of notes) {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = "sine";
      osc.frequency.value = frequence;
      gain.gain.setValueAtTime(0, debut);
      gain.gain.linearRampToValueAtTime(nature === "deplacer" ? .025 : .05, debut + .008);
      gain.gain.exponentialRampToValueAtTime(.0001, debut + duree);
      osc.connect(gain).connect(audio.destination);
      osc.start(debut);
      osc.stop(debut + duree + .02);
      debut += duree * .7;
    }
  } catch { /* pas de sortie audio : le menu reste muet */ }
}

// ── Thème, taille, animations ─────────────────────────────────────────────
function themeEffectif() {
  const choix = profil().theme;
  if (choix !== "auto") return choix;
  const maintenant = new Date();
  const jour = meteo?.daily;
  if (jour?.sunrise?.[0] && jour?.sunset?.[0]) {
    return maintenant >= new Date(jour.sunrise[0]) && maintenant < new Date(jour.sunset[0]) ? "clair" : "sombre";
  }
  const h = maintenant.getHours();
  return h >= 8 && h < 20 ? "clair" : "sombre";
}
function appliquerApparence() {
  const theme = themeEffectif();
  if (racine.dataset.theme !== theme) {
    racine.dataset.theme = theme;
    fondPret = false;
  }
  racine.style.setProperty("--echelle", reglages.systeme.echelle);
  // L et XL : l'écran ne grandit pas avec le texte ; hub.css resserre l'accueil et la météo.
  racine.dataset.taille = Number(reglages.systeme.echelle) > 1 ? "grande" : "normale";
  racine.style.setProperty("--marge", reglages.systeme.marge);
  document.body.classList.toggle("sans-animation", profil().animations === "reduites");
  const couleur = COULEURS_PROFIL[profil().couleur] || COULEURS_PROFIL.turquoise;
  habillerAvatar($("avatar-profil"), profil());
  $("nom-profil").textContent = profil().nom;
  extensions.apparence.forEach(f => f());
}

// ── Fonds animés ──────────────────────────────────────────────────────────
// Un fond, c'est un motif (le dessin et son mouvement) et une couleur (la palette).
// Le profil garde la couleur dans « fond », comme avant : hub-theme la lit pour le bureau
// et Kodi, et un profil enregistré avant les motifs (« fond: "ocean" » seul) garde
// exactement son rendu, les nappes. Le motif vit dans « motif ». « minimal » et « photos »
// restent des valeurs de « fond » : ce sont des fonds entiers, sans variation de couleur.
// Chaque palette : une base et quatre teintes, [0] la principale (teintée par le mode),
// [1] et [2] les secondaires, [3] la plus profonde.
const PALETTES = {
  aurore: {
    sombre: { base: "#06070c", nappes: [[62, 224, 208], [110, 90, 255], [62, 140, 255], [30, 40, 90]] },
    clair: { base: "#e9edf5", nappes: [[120, 230, 215], [190, 175, 255], [150, 195, 255], [255, 214, 186]] },
  },
  nebuleuse: {
    sombre: { base: "#07050d", nappes: [[150, 50, 190], [220, 70, 130], [70, 50, 210], [25, 10, 45]] },
    clair: { base: "#f2edf7", nappes: [[225, 180, 245], [255, 190, 215], [195, 190, 255], [245, 230, 250]] },
  },
  ocean: {
    sombre: { base: "#030a14", nappes: [[10, 110, 176], [15, 60, 115], [20, 170, 190], [5, 22, 55]] },
    clair: { base: "#e6f1f8", nappes: [[140, 205, 240], [175, 215, 238], [150, 232, 230], [212, 236, 250]] },
  },
  braise: {
    sombre: { base: "#0c0605", nappes: [[200, 75, 30], [130, 30, 60], [235, 130, 40], [45, 12, 10]] },
    clair: { base: "#f8efe9", nappes: [[255, 192, 150], [245, 178, 196], [255, 216, 160], [250, 232, 220]] },
  },
  // Ajoutées avec les motifs (17/09/2026) : un vert de forêt la nuit, et un couchant
  // rose et or. Les quatre premières étaient toutes froides ou toutes rouges.
  emeraude: {
    sombre: { base: "#030b08", nappes: [[40, 200, 130], [20, 120, 110], [150, 215, 90], [6, 40, 30]] },
    clair: { base: "#e9f4ee", nappes: [[150, 225, 190], [170, 215, 205], [205, 235, 165], [225, 242, 232]] },
  },
  crepuscule: {
    sombre: { base: "#0d0709", nappes: [[255, 120, 150], [240, 170, 80], [150, 70, 170], [50, 15, 35]] },
    clair: { base: "#f8eef0", nappes: [[255, 190, 205], [255, 215, 160], [220, 190, 235], [250, 235, 238]] },
  },
  minimal: {
    sombre: { base: "#0a0c13", nappes: [[42, 48, 70]] },
    clair: { base: "#eef1f6", nappes: [[255, 255, 255]] },
  },
};
const COULEURS_FOND = ["aurore", "nebuleuse", "ocean", "braise", "emeraude", "crepuscule"];
// Dans l'ordre des réglages. « nappes » est le motif d'avant, gardé tel quel.
const MOTIFS = ["cinema", "rubans", "profondeur", "faisceaux", "nappes"];
const NAPPES = [
  { x: .18, y: .22, r: .50, phase: 0 },
  { x: .86, y: .18, r: .44, phase: 2 },
  { x: .66, y: .95, r: .52, phase: 4 },
  { x: .10, y: .90, r: .50, phase: 1 },
];
// Chaque nappe va et vient en 12 à 30 s, sur une fraction visible de l'écran. Les
// premières versions tiraient ces cycles de vitesses (s × vx × 3…) : l'océan mettait
// 100 à 160 s à faire un aller-retour, soit 2 % de la largeur par seconde, et vu du
// canapé le fond paraissait immobile (constaté sur la TV le 17/09/2026). Écrits en
// périodes, ils se lisent et se testent (tests/menu : aucune au-delà de 30 s).
// Périodes différentes d'une nappe à l'autre : le motif ne se répète pas à l'identique.
const MOUVEMENTS = {
  aurore: { x: { amplitude: .18, periodes: [23, 27, 19, 29] }, y: { amplitude: .14, periodes: [17, 21, 25, 15] }, rayon: { amplitude: .1, periodes: [13, 16, 14, 18] } },
  nebuleuse: { x: { amplitude: .16, periodes: [29, 23, 26, 20] }, y: { amplitude: .15, periodes: [21, 27, 17, 24] }, rayon: { amplitude: .12, periodes: [15, 12, 18, 14] } },
  // La houle : large de gauche à droite, à peine en hauteur.
  ocean: { x: { amplitude: .24, periodes: [22, 26, 18, 28] }, y: { amplitude: .07, periodes: [15, 17, 16, 19] }, rayon: { amplitude: .1, periodes: [14, 17, 13, 16] } },
  // Les braises montent : « periodes » y est le temps d'une traversée, bas → haut.
  braise: { x: { amplitude: .09, periodes: [16, 19, 14, 21] }, y: { montee: true, periodes: [26, 22, 30, 24] }, rayon: { amplitude: .1, periodes: [12, 15, 13, 17] } },
  emeraude: { x: { amplitude: .17, periodes: [21, 28, 24, 18] }, y: { amplitude: .14, periodes: [19, 16, 23, 27] }, rayon: { amplitude: .11, periodes: [14, 17, 12, 15] } },
  crepuscule: { x: { amplitude: .2, periodes: [25, 20, 29, 22] }, y: { amplitude: .12, periodes: [18, 24, 15, 21] }, rayon: { amplitude: .1, periodes: [16, 13, 17, 12] } },
};
// Les rythmes des quatre motifs des maquettes, en secondes. Les maquettes allaient
// jusqu'à 120 s (le filigrane : 60 s aller, 60 s retour) : on a vu avec les nappes que
// rien de plus lent que 30 s ne se voit du canapé. Même règle, même test.
const RYTHMES = {
  // Trois taches qui dérivent et respirent, trois ondes qui partent du filigrane.
  cinema: { derive: [23, 19, 27, 21, 25, 17], souffle: [13, 16, 14], onde: 9, filigrane: 28, flotte: 19 },
  // Trois rubans : l'ondulation qui court le long du ruban (vague, vague2), son épaisseur,
  // les rayons verticaux qui défilent, le glissement d'ensemble ; l'horizon qui respire ;
  // chaque étoile scintille à son rythme, entre 5 et 14 s.
  rubans: { vague: [14, 17, 12], vague2: [23, 19, 26], epaisseur: [11, 13, 9], rayons: [11, 13, 8], glisse: [29, 24, 27], horizon: 12, scintille: [5, 14] },
  // Une case du sol qui avance, le soleil qui pulse, les orbes (largeur, hauteur).
  profondeur: { case: 6, soleil: 16, orbes: [26, 30, 22], orbesY: [19, 23, 17] },
  // Les deux faisceaux qui balaient ; la poussière monte (une traversée en 22 à 30 s),
  // oscille (7 à 13 s) et scintille (3 à 8 s).
  faisceaux: { balaye: [20, 24], montee: [22, 30], oscille: [7, 13], scintille: [3, 8] },
};
// En mode ambiant, tout va deux fois moins vite : on regarde l'heure, pas le fond.
const LENTEUR_AMBIANT = .5;
// Les nappes tiennent dans 192×108 : le dessin ne coûte rien. Mais chaque image du fond
// oblige à recalculer tous les flous d'arrière-plan posés dessus, en 3840×2160 sur un
// UHD 630. 30 images par seconde suffisent à un mouvement de 20 s.
const IMAGES_FOND_PAR_SECONDE = 30;

// Deux toiles, deux finesses. Ce qui est flou par nature (taches, rubans, faisceaux,
// ciel, soleil) se dessine en 320×180, un vingt-quatrième de la largeur 4K : agrandi par
// le navigateur, il reste doux, et le remplir coûte 58 000 pixels par image. Les lignes
// fines (sol quadrillé, ondes, étoiles, poussière, orbes) seraient des traînées floues à
// cette taille : elles vont sur une seconde toile de 960 pixels de large, transparente,
// où un trait d'un pixel fait 2 px en 1080p et 4 px en 4K, l'épaisseur des maquettes.
// Elle n'est qu'effacée puis tracée (quelques dizaines de traits), et ses 518 000
// pixels sont un seizième de l'écran 4K. Aucun filtre, aucun masque animé : les fondus
// sont dans les couleurs. Les nappes gardent leur 192×108.
const RESOLUTIONS_FOND = { nappes: [192, 108], minimal: [192, 108], photos: [192, 108] };
const RESOLUTION_MOTIF = [320, 180];
const LARGEUR_LIGNES = 960;
const MOTIFS_A_LIGNES = ["cinema", "rubans", "profondeur", "faisceaux"];
// Centre des ondes et du filigrane du motif cinéma, en fractions de l'écran (maquette C :
// 1480 × 400 sur 1920 × 1080), et côté du filigrane en fraction de la hauteur.
const FILIGRANE = { x: .775, y: .4, taille: .76 };
// Ligne d'horizon du motif profondeur.
const HORIZON = .585;

// Position (fractions de l'écran), rayon (fraction de la largeur) et éclat (0–1) de la
// nappe i au temps s, en secondes de fond. Pure : les tests la parcourent.
function mouvementNappe(choix, i, s) {
  const n = NAPPES[i];
  const m = MOUVEMENTS[choix];
  if (!m) return { x: n.x, y: n.y, r: n.r, eclat: 1 };
  const onde = (axe, f = Math.sin) => f(2 * Math.PI * s / m[axe].periodes[i] + n.phase) * m[axe].amplitude;
  let y, eclat = 1;
  if (m.y.montee) {
    const p = ((s / m.y.periodes[i] + n.phase / (2 * Math.PI)) % 1 + 1) % 1;
    y = 1.2 - p * 1.4;
    // Elle s'éteint en sortant par le haut et se rallume en bas : sans ça, la nappe
    // sautait d'un bord à l'autre à chaque tour.
    eclat = Math.min(1, 3 * Math.sin(Math.PI * p));
  } else {
    y = n.y + onde("y", choix === "ocean" ? Math.sin : Math.cos);
  }
  return { x: n.x + onde("x"), y, r: n.r * (1 + onde("rayon")), eclat };
}
function periodesFond(choix) {
  const m = MOUVEMENTS[choix];
  return m ? Object.values(m).flatMap(axe => axe.periodes) : [];
}
function periodesMotif(motif) {
  return Object.values(RYTHMES[motif] || {}).flat();
}

// Tirages fixes : les mêmes étoiles et la même poussière à chaque démarrage, et des
// aperçus que les tests peuvent comparer.
function hasard(graine) {
  let a = graine >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let x = Math.imul(a ^ a >>> 15, 1 | a);
    x = (x + Math.imul(x ^ x >>> 7, 61 | x)) ^ x;
    return ((x ^ x >>> 14) >>> 0) / 4294967296;
  };
}
const ETOILES = (() => {
  const r = hasard(7);
  const [min, max] = RYTHMES.rubans.scintille;
  return Array.from({ length: 150 }, () => ({ x: r(), y: r() ** 1.3 * .72, taille: .55 + r() ** 3 * 1.4, eclat: .35 + r() * .65, periode: min + r() * (max - min), phase: r() * 6.283 }));
})();
const POUSSIERE = (() => {
  const r = hasard(11), R = RYTHMES.faisceaux;
  const entre = ([a, b]) => a + r() * (b - a);
  return Array.from({ length: 90 }, () => ({ x: r(), y: r(), taille: .7 + r() * 1.2, eclat: .3 + r() * .5, montee: entre(R.montee), oscille: entre(R.oscille), ampleur: .006 + r() * .018, scintille: entre(R.scintille), phase: r() * 6.283 }));
})();

const rvbHex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const rgba = (c, a) => `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${borne(a, 0, 1).toFixed(3)})`;
const onde = (s, periode, phase = 0) => Math.sin(2 * Math.PI * s / periode + phase);
// Un trait lisible sur le fond : éclairci sur le sombre, assombri sur le clair (les
// teintes claires sont des pastels qui disparaîtraient sur une base presque blanche).
const encreTrait = (c, clair) => clair ? melange(c, [16, 20, 36], .5) : melange(c, [255, 255, 255], .35);

// Une tache elliptique, du centre (alpha) vers le bord (rien) ; « milieu » : [position, part de l'alpha].
function tache(c, x, y, rx, ry, couleur, alpha, fin = .7, milieu = null) {
  c.save();
  c.translate(x, y);
  c.scale(Math.max(rx, .01), Math.max(ry, .01));
  const g = c.createRadialGradient(0, 0, 0, 0, 0, 1);
  g.addColorStop(0, rgba(couleur, alpha));
  if (milieu) g.addColorStop(milieu[0], rgba(couleur, alpha * milieu[1]));
  g.addColorStop(fin, rgba(couleur, 0));
  c.fillStyle = g;
  c.fillRect(-1, -1, 2, 2);
  c.restore();
}

// Tout ce que le dessin d'un motif doit savoir, pour l'écran comme pour les aperçus.
function environnementFond(couleur, theme, s, accent, teinter) {
  const palette = (PALETTES[couleur] || PALETTES.aurore)[theme];
  const n = palette.nappes;
  const teinte = (i, part) => teinter ? melange(n[i % n.length], accent, part) : n[i % n.length];
  // À moitié seulement pour la teinte principale (les nappes vont jusqu'aux trois quarts) :
  // sinon, teinte du mode allumée, les six couleurs d'un motif se ressemblaient toutes.
  return {
    theme, clair: theme === "clair", s, palette,
    accent, teinter,
    base: rvbHex(palette.base), c0: teinte(0, .5), c1: teinte(1, .25), c2: teinte(2, .25), c3: n[3] || n[0],
  };
}

// Les nappes, telles qu'avant les motifs : une base et quatre remplissages radiaux.
function peindreNappes(c, choix, e, accent, teinter) {
  const w = c.canvas.width, h = c.canvas.height, { palette, theme, s } = e;
  c.globalCompositeOperation = "source-over";
  c.fillStyle = palette.base;
  c.fillRect(0, 0, w, h);
  c.globalCompositeOperation = theme === "clair" ? "source-over" : "lighter";
  palette.nappes.forEach((teinteBase, i) => {
    const minimal = choix === "minimal";
    const m = mouvementNappe(choix, i, s);
    const x = m.x * w;
    const y = minimal ? -h * .3 : m.y * h;
    const r = (minimal ? 1.1 : m.r) * w;
    const teinte = teinter && !minimal ? melange(teinteBase, accent, i === 0 ? .75 : .25) : teinteBase;
    const force = (theme === "clair" ? (i === 0 ? .6 : .5) : (i === 3 ? .35 : i === 0 ? .34 : .2)) * m.eclat;
    const g = c.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, `rgba(${teinte.map(Math.round).join(",")},${minimal ? (theme === "clair" ? .9 : .5) : force})`);
    g.addColorStop(1, `rgba(${teinte.map(Math.round).join(",")},0)`);
    c.fillStyle = g;
    c.fillRect(0, 0, w, h);
  });
}

// C · Cinéma : un dégradé maillé de trois taches qui dérivent et respirent, le bas
// assombri pour les rangées. Les ondes et le filigrane sont à part (lignes, calque).
// Première version (17/09/2026) : teinte du mode mêlée à moitié, taches de 30 % de l'écran :
// l'accueil par défaut était presque noir, le reproche même de départ. Comme la maquette C,
// la grande tache prend franchement la couleur du mode et couvre la moitié de l'écran.
function peindreCinema(c, e) {
  const w = c.canvas.width, h = c.canvas.height, { s, clair } = e, R = RYTHMES.cinema;
  const n = e.palette.nappes;
  const vive = (i, part) => e.teinter ? melange(n[i % n.length], e.accent, part) : n[i % n.length];
  // Couleur saturée : on pousse chaque canal loin du gris (les palettes claires sont pastel).
  const sature = (col, k) => { const m = (col[0] + col[1] + col[2]) / 3; return col.map(v => borne(m + (v - m) * k, 0, 255)); };
  const principale = sature(vive(0, .92), clair ? 1.7 : 1.55);
  c.globalCompositeOperation = "source-over";
  c.fillStyle = rgba(e.base, 1);
  c.fillRect(0, 0, w, h);
  c.globalCompositeOperation = clair ? "source-over" : "lighter";
  [
    [.8, .36, .64, .9, principale, clair ? .55 : .9],
    [.97, .95, .42, .55, sature(vive(1, .2), 1.3), clair ? .45 : .42],
    [.06, 1.02, .5, .6, sature(vive(2, .2), 1.3), clair ? .4 : .36],
  ].forEach(([x, y, rx, ry, couleur, a], i) => {
    // Un dixième de l'écran d'amplitude : la maquette en faisait 5 %, invisible à trois mètres.
    const souffle = 1 + .12 * onde(s, R.souffle[i], i);
    tache(c, (x + .09 * onde(s, R.derive[2 * i], i * 1.7)) * w, (y + .07 * Math.cos(2 * Math.PI * s / R.derive[2 * i + 1] + i)) * h,
      rx * souffle * w, ry * souffle * h, couleur, a, 1, [.45, .55]);
  });
  c.globalCompositeOperation = "source-over";
  const g = c.createLinearGradient(0, h * .6, 0, h);
  g.addColorStop(0, rgba(e.base, 0));
  g.addColorStop(.5, rgba(e.base, .55));
  g.addColorStop(1, rgba(e.base, .8));
  c.fillStyle = g;
  c.fillRect(0, h * .6, w, h * .4);
}
function lignesCinema(l, e, k) {
  const w = l.canvas.width, h = l.canvas.height, { s, clair } = e, R = RYTHMES.cinema;
  const couleur = encreTrait(e.c0, clair);
  const x = FILIGRANE.x * w, y = FILIGRANE.y * h;
  for (let i = 0; i < 3; i++) {
    const p = (((s + i * R.onde / 3) / R.onde) % 1 + 1) % 1;
    // Maquette : de 0,4 à 5,5 fois un cercle de 100 px en 1080p, allumée à 15 % du trajet.
    const rayon = (.4 + p * 5.1) * .0926 * h;
    const alpha = (p < .15 ? p / .15 : (1 - p) / .85) * (clair ? .5 : .6);
    l.strokeStyle = rgba(couleur, alpha);
    l.lineWidth = (1.2 + p * 2.6) * k;
    l.beginPath();
    l.arc(x, y, rayon, 0, 2 * Math.PI);
    l.stroke();
  }
}
// Le filigrane pivote et flotte : transform seulement, posée par dessinerFond.
function mouvementFiligrane(s) {
  const R = RYTHMES.cinema;
  return { angle: -1 + 8 * onde(s, R.filigrane), decalage: .014 * onde(s, R.flotte, 1) };
}

// A · Aurore : ciel profond, trois rubans qui ondulent (l'onde court le long du ruban,
// des rayons verticaux y défilent), une lueur d'horizon qui respire. Étoiles sur les lignes.
const RUBANS = [
  { y: .1, epaisseur: .26, debut: .12, fin: .88, pente: -.05, couleurs: ["c0", "c0"], eclat: .36 },
  { y: .27, epaisseur: .42, debut: .02, fin: .95, pente: -.1, couleurs: ["c0", "c1"], eclat: .56 },
  { y: .37, epaisseur: .3, debut: .18, fin: 1.08, pente: .06, couleurs: ["c1", "c2"], eclat: .5 },
];
function peindreRubans(c, e) {
  const w = c.canvas.width, h = c.canvas.height, { s, clair } = e, R = RYTHMES.rubans;
  c.globalCompositeOperation = "source-over";
  c.fillStyle = rgba(e.base, 1);
  c.fillRect(0, 0, w, h);
  tache(c, w / 2, 0, 1.2 * w, .85 * h, clair ? melange(e.base, e.c1, .3) : melange(e.base, e.c3, .55), 1, 1, [.55, .45]);
  c.globalCompositeOperation = clair ? "source-over" : "lighter";
  const pas = 3;
  RUBANS.forEach((r, j) => {
    const glisse = .07 * onde(s, R.glisse[j], j);
    for (let x = 0; x < w; x += pas) {
      const u = (x + pas / 2) / w;
      const v = (u - r.debut - glisse) / (r.fin - r.debut);
      if (v <= 0 || v >= 1) continue;
      const centre = (r.y + r.pente * (u - .5) + .055 * Math.sin(2 * Math.PI * (u * 1.3 - s / R.vague[j]) + 2 * j) + .025 * Math.sin(2 * Math.PI * (u * 2.7 + s / R.vague2[j]) + j)) * h;
      const epaisseur = r.epaisseur * (1 + .24 * Math.sin(2 * Math.PI * (u * 1.9 - s / R.epaisseur[j]) + j)) * h;
      const rayons = .7 + .3 * Math.sin(2 * Math.PI * (u * 13 - s / R.rayons[j]) + 3 * j);
      const alpha = r.eclat * Math.sin(Math.PI * v) ** 1.5 * rayons * (clair ? 1.4 : 1);
      const couleur = melange(e[r.couleurs[0]], e[r.couleurs[1]], v);
      // Plus vif vers le bas, comme un rideau d'aurore qui s'efface vers le ciel.
      const haut = centre - epaisseur * .6;
      const g = c.createLinearGradient(0, haut, 0, haut + epaisseur);
      g.addColorStop(0, rgba(couleur, 0));
      g.addColorStop(.7, rgba(couleur, alpha));
      g.addColorStop(1, rgba(couleur, 0));
      c.fillStyle = g;
      c.fillRect(x, haut, pas, epaisseur);
    }
  });
  const p = .5 + .5 * onde(s, R.horizon);
  const echelle = .92 + .14 * p;
  tache(c, .5 * w, 1.065 * h, .68 * w * echelle, .42 * h * echelle, e.c0, (clair ? .6 : .55) * (.7 + .3 * p), 1, [.6, .22]);
}
function lignesRubans(l, e, k) {
  if (e.clair) return;
  const w = l.canvas.width, h = l.canvas.height, { s } = e;
  const teinte = melange([255, 255, 255], e.c0, .15);
  for (const et of ETOILES) {
    l.fillStyle = rgba(teinte, et.eclat * (.3 + .7 * (.5 + .5 * onde(s, et.periode, et.phase))));
    l.beginPath();
    l.arc(et.x * w, et.y * h, et.taille * k, 0, 2 * Math.PI);
    l.fill();
  }
}

// B · Profondeur : un ciel en bandes jusqu'à l'horizon, un soleil qui pulse, un voile sur
// le sol. Le quadrillage qui avance et les orbes sont sur les lignes.
function peindreProfondeur(c, e) {
  const w = c.canvas.width, h = c.canvas.height, { s, clair } = e, R = RYTHMES.profondeur;
  const blanc = [255, 255, 255];
  const g = c.createLinearGradient(0, 0, 0, h);
  if (clair) {
    g.addColorStop(0, rgba(melange(e.base, e.c1, .3), 1));
    g.addColorStop(.46, rgba(melange(e.base, e.c0, .25), 1));
    g.addColorStop(HORIZON - .005, rgba(melange(e.base, e.c0, .55), 1));
    g.addColorStop(HORIZON, rgba(melange(e.base, blanc, .45), 1));
    g.addColorStop(1, rgba(melange(e.base, e.c1, .18), 1));
  } else {
    g.addColorStop(0, rgba(melange(e.base, e.c3, .4), 1));
    g.addColorStop(.46, rgba(melange(e.base, e.c0, .14), 1));
    g.addColorStop(HORIZON - .005, rgba(melange(e.base, e.c0, .32), 1));
    g.addColorStop(HORIZON, rgba(melange(e.base, e.c0, .06), 1));
    g.addColorStop(1, rgba(e.base, 1));
  }
  c.globalCompositeOperation = "source-over";
  c.fillStyle = g;
  c.fillRect(0, 0, w, h);
  c.globalCompositeOperation = clair ? "source-over" : "lighter";
  const p = .5 + .5 * onde(s, R.soleil);
  const rayon = .417 * h * (.9 + .16 * p);
  tache(c, .5 * w, .648 * h, rayon, rayon, clair ? e.c0 : melange(e.c0, blanc, .35), (clair ? .7 : .6) * (.75 + .25 * p), .72, [.45, .4]);
  c.globalCompositeOperation = "source-over";
  const voile = c.createLinearGradient(0, .556 * h, 0, h);
  voile.addColorStop(0, rgba(e.base, clair ? .1 : .2));
  voile.addColorStop(.7, rgba(e.base, clair ? .45 : .75));
  voile.addColorStop(1, rgba(e.base, clair ? .5 : .8));
  c.fillStyle = voile;
  c.fillRect(0, .556 * h, w, .444 * h);
}
// Hors du héros (à gauche) et de l'en-tête : dans le ciel, de part et d'autre du soleil.
const ORBES = [{ x: .6, y: .25, r: .036, couleur: "c0" }, { x: .88, y: .36, r: .026, couleur: "c2" }, { x: .75, y: .18, r: .018, couleur: "c1" }];
function lignesProfondeur(l, e, k) {
  const w = l.canvas.width, h = l.canvas.height, { s, clair } = e, R = RYTHMES.profondeur;
  const horizon = HORIZON * h, sol = h - horizon;
  const couleur = encreTrait(e.c0, clair);
  // Visible à partir de 30 % du sol (le lointain se fond dans l'horizon), estompé en bas.
  const presence = y => { const q = (y - horizon) / sol; return borne(q / .3, 0, 1) * (1 - .45 * borne((q - .55) / .45, 0, 1)); };
  const avance = ((s / R.case) % 1 + 1) % 1;
  for (let n = 1; n < 44; n++) {
    // La ligne n est à la profondeur n − avance : en une case, elle prend la place de sa voisine.
    const z = n - avance;
    if (z <= .05) continue;
    const y = horizon + sol * 1.2 / z;
    if (y > h + 3) continue;
    const a = (clair ? .5 : .62) * presence(y);
    if (a < .01) continue;
    l.strokeStyle = rgba(couleur, a);
    l.lineWidth = (.8 + 1.8 * (y - horizon) / sol) * k;
    l.beginPath();
    l.moveTo(0, y);
    l.lineTo(w, y);
    l.stroke();
  }
  const fuyantes = l.createLinearGradient(0, horizon, 0, h);
  const a = clair ? .36 : .42;
  fuyantes.addColorStop(0, rgba(couleur, 0));
  fuyantes.addColorStop(.3, rgba(couleur, a));
  fuyantes.addColorStop(.55, rgba(couleur, a));
  fuyantes.addColorStop(1, rgba(couleur, a * .55));
  l.strokeStyle = fuyantes;
  l.lineWidth = 1.2 * k;
  l.beginPath();
  for (let i = -16; i <= 16; i++) {
    l.moveTo(w / 2, horizon);
    l.lineTo(w / 2 + i * w * .09, h);
  }
  l.stroke();
  ORBES.forEach((o, i) => {
    const x = (o.x + .04 * onde(s, R.orbes[i], i)) * w;
    const y = (o.y + .05 * Math.cos(2 * Math.PI * s / R.orbesY[i] + 2 * i)) * h;
    const r = o.r * h;
    const teinte = clair ? melange(e[o.couleur], [0, 0, 0], .15) : e[o.couleur];
    const g = l.createRadialGradient(x - .3 * r, y - .4 * r, 0, x - .3 * r, y - .4 * r, 1.9 * r);
    g.addColorStop(0, rgba(melange(teinte, [255, 255, 255], .6), .95));
    g.addColorStop(.4, rgba(teinte, .9));
    g.addColorStop(.72, rgba(teinte, 0));
    l.fillStyle = g;
    l.beginPath();
    l.arc(x, y, r, 0, 2 * Math.PI);
    l.fill();
  });
}

// D · Faisceaux : deux faisceaux qui balaient depuis le haut, une lueur au sol.
// La poussière est sur les lignes, et brille quand un faisceau la traverse.
function mouvementFaisceaux(s) {
  const R = RYTHMES.faisceaux, degre = Math.PI / 180;
  return [
    { x: .104, y: -.28, angle: (14 + 15 * onde(s, R.balaye[0])) * degre, demi: 11 * degre, couleur: "c0", alpha: .32 },
    { x: .896, y: -.28, angle: (-14 - 15 * onde(s, R.balaye[1], 1)) * degre, demi: 12 * degre, couleur: "c1", alpha: .36 },
  ];
}
function peindreFaisceaux(c, e) {
  const w = c.canvas.width, h = c.canvas.height, { s, clair } = e;
  c.globalCompositeOperation = "source-over";
  c.fillStyle = rgba(clair ? melange(e.base, e.c1, .3) : e.base, 1);
  c.fillRect(0, 0, w, h);
  tache(c, .5 * w, 1.1 * h, .9 * w, .75 * h, clair ? melange(e.base, e.c2, .45) : melange(e.base, e.c2, .3), 1);
  c.globalCompositeOperation = clair ? "source-over" : "lighter";
  const longueur = 1.7 * h;
  for (const f of mouvementFaisceaux(s)) {
    const ax = f.x * w, ay = f.y * h;
    const teinte = clair ? melange(e[f.couleur], [255, 255, 255], .35) : e[f.couleur];
    // Trois coins emboîtés : un cœur plus vif et des bords qui s'effacent, sans flou.
    for (const [largeur, part] of [[1, .3], [.6, .35], [.28, .35]]) {
      const g = c.createRadialGradient(ax, ay, 0, ax, ay, longueur);
      const a = f.alpha * part * (clair ? 3 : 1);
      g.addColorStop(0, rgba(teinte, a));
      g.addColorStop(.55, rgba(teinte, a * .6));
      g.addColorStop(1, rgba(teinte, 0));
      c.fillStyle = g;
      c.beginPath();
      c.moveTo(ax, ay);
      c.lineTo(ax + longueur * Math.sin(f.angle - f.demi * largeur), ay + longueur * Math.cos(f.angle - f.demi * largeur));
      c.lineTo(ax + longueur * Math.sin(f.angle + f.demi * largeur), ay + longueur * Math.cos(f.angle + f.demi * largeur));
      c.closePath();
      c.fill();
    }
  }
  c.globalCompositeOperation = "source-over";
  const sol = c.createLinearGradient(0, .74 * h, 0, h);
  sol.addColorStop(0, rgba(e.c1, 0));
  sol.addColorStop(1, rgba(e.c1, clair ? .18 : .1));
  c.fillStyle = sol;
  c.fillRect(0, .74 * h, w, .26 * h);
}
function lignesFaisceaux(l, e, k) {
  const w = l.canvas.width, h = l.canvas.height, { s, clair } = e;
  const faisceaux = mouvementFaisceaux(s);
  const teinte = clair ? encreTrait(e.c0, true) : melange([255, 255, 255], e.c0, .2);
  for (const p of POUSSIERE) {
    const y = (((p.y - s / p.montee) % 1) + 1) % 1 * 1.1 - .05;
    const x = p.x + p.ampleur * onde(s, p.oscille, p.phase);
    const fondu = Math.min(1, (y + .05) / .15, (1.05 - y) / .15);
    // Dans un faisceau (angle vu depuis sa source, en pixels carrés), la poussière s'allume.
    const lumiere = Math.max(0, ...faisceaux.map(f => 1 - Math.abs(Math.atan2((x - f.x) * w, (y - f.y) * h) - f.angle) / f.demi));
    const a = p.eclat * fondu * (.6 + .4 * onde(s, p.scintille, p.phase)) * (1 + 2.2 * lumiere) * (clair ? .4 : .5);
    if (a <= .01) continue;
    l.fillStyle = rgba(teinte, a);
    l.beginPath();
    l.arc(x * w, y * h, p.taille * k * (1 + .5 * lumiere), 0, 2 * Math.PI);
    l.fill();
  }
}

const PEINTRES = { cinema: peindreCinema, rubans: peindreRubans, profondeur: peindreProfondeur, faisceaux: peindreFaisceaux };
const TRACEURS = { cinema: lignesCinema, rubans: lignesRubans, profondeur: lignesProfondeur, faisceaux: lignesFaisceaux };

// Un motif sur deux toiles : « c » la basse résolution, « l » les lignes (effacée ici
// si « effacer »). Pure hormis les toiles : les aperçus et les tests l'appellent aussi.
function peindreFond(motif, couleur, theme, s, accent, teinter, c, l, effacer = true) {
  const e = environnementFond(couleur, theme, s, accent, teinter);
  if (!PEINTRES[motif]) {
    peindreNappes(c, couleur, e, accent, teinter);
  } else {
    PEINTRES[motif](c, e);
  }
  if (!l) return;
  if (effacer) l.clearRect(0, 0, l.canvas.width, l.canvas.height);
  l.globalCompositeOperation = "source-over";
  TRACEURS[motif]?.(l, e, l.canvas.width / LARGEUR_LIGNES);
}

const toile = $("fond");
const ctx = toile.getContext("2d");
const toileLignes = $("fond-lignes");
const ctxLignes = toileLignes.getContext("2d");
const filigrane = $("filigrane");
let accentCible = COULEURS_MODE.tv;
let accentCourant = [...COULEURS_MODE.tv];
let fondPret = false;
let boucleFond = false;
// Temps du fond, avancé image par image : passer en ambiant ralentit sans faire sauter
// les nappes (multiplier l'horloge murale par la lenteur les téléportait).
let horlogeFond = 0;
let dernierDessin = null;
let etoiles;

function fondChoisi() {
  const f = profil().fond;
  if (f === "photos" && !(INITIAL.photos || []).length) return "aurore";
  return PALETTES[f] || f === "photos" ? f : "aurore";
}
function motifDuProfil(p = profil()) { return MOTIFS.includes(p.motif) ? p.motif : "nappes"; }
// Le dessin à l'écran : « minimal » et « photos » passent avant le motif.
function motifChoisi() {
  const f = fondChoisi();
  return f === "minimal" || f === "photos" ? f : motifDuProfil();
}
window.hubFond = { mouvementNappe, periodesFond, periodesMotif, peindreFond, mouvementFiligrane, mouvementFaisceaux, motifChoisi, fondChoisi, MOTIFS, COULEURS_FOND, LARGEUR_LIGNES, RESOLUTION_MOTIF, LENTEUR_AMBIANT, IMAGES_FOND_PAR_SECONDE };

// Personne ne regarde le fond : page cachée, mode qui démarre, calque plein écran
// par-dessus (voile, et le verre de la feuille recalculé à chaque image du fond), ou
// cadre photo qui le recouvre en ambiant.
function fondSuspendu() {
  const corps = document.body.classList;
  return document.hidden || corps.contains("depart") || corps.contains("calque-ouvert") || corps.contains("cadre-actif");
}

// Taille des toiles et calques du motif : seulement quand le motif ou l'écran changent
// (redimensionner une toile l'efface et réalloue sa mémoire).
let preparation = "";
function preparerToiles(motif, theme, couleur) {
  const [largeur, hauteur] = RESOLUTIONS_FOND[motif] || RESOLUTION_MOTIF;
  const lignes = MOTIFS_A_LIGNES.includes(motif);
  const hauteurLignes = Math.round(LARGEUR_LIGNES * innerHeight / Math.max(1, innerWidth));
  const cle = [motif, theme, couleur, innerWidth, innerHeight].join();
  if (cle === preparation) return;
  preparation = cle;
  if (toile.width !== largeur || toile.height !== hauteur) { toile.width = largeur; toile.height = hauteur; }
  toileLignes.hidden = !lignes;
  if (lignes && (toileLignes.width !== LARGEUR_LIGNES || toileLignes.height !== hauteurLignes)) {
    toileLignes.width = LARGEUR_LIGNES;
    toileLignes.height = hauteurLignes;
  }
  filigrane.hidden = motif !== "cinema";
  document.body.dataset.motif = motif;
  // La couleur de base du fond, pour le voile du bas qui passe sur le filigrane (hub.css).
  racine.style.setProperty("--fond-base", rvbHex((PALETTES[couleur] || PALETTES.aurore)[theme].base).join(" "));
}
addEventListener("resize", () => { preparation = ""; relancerFond(); });

function dessinerFond(temps) {
  // Suspendu, on dessine encore une image si quelque chose a changé (thème, fond
  // choisi dans les réglages), puis la boucle s'arrête jusqu'à relancerFond.
  if (fondSuspendu() && fondPret) { boucleFond = false; dernierDessin = null; return; }
  // Une image sur deux à 60 Hz ; la marge de 4 ms évite de tomber à 20 images par
  // seconde quand la synchro arrive une milliseconde en avance.
  if (fondPret && dernierDessin !== null && temps - dernierDessin < 1000 / IMAGES_FOND_PAR_SECONDE - 4) {
    requestAnimationFrame(dessinerFond);
    return;
  }
  const choix = fondChoisi();
  const motif = motifChoisi();
  const theme = racine.dataset.theme === "clair" ? "clair" : "sombre";
  const reduit = profil().animations === "reduites" || matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lent = document.body.classList.contains("ambiant") ? LENTEUR_AMBIANT : 1;
  // Plafonné : après une pause (page cachée, calque), on reprend là où on était.
  const ecoule = dernierDessin === null ? 0 : Math.min(temps - dernierDessin, 100);
  dernierDessin = temps;
  if (!reduit) horlogeFond += ecoule / 1000 * lent;
  // Figé, un motif montre un instant où tout est en place (ondes à mi-course, orbes…).
  const s = reduit ? (motif === "nappes" ? 0 : 6) : horlogeFond;
  preparerToiles(motif, theme, choix === "photos" ? "aurore" : choix);

  // Même vitesse de fondu de la teinte qu'à 60 images par seconde (3 % par image).
  accentCourant = melange(accentCourant, accentCible, reduit ? 1 : 1 - Math.pow(.97, ecoule / (1000 / 60)));
  const teinter = !!profil().teinteMode;
  if (PEINTRES[motif]) {
    peindreFond(motif, choix, theme, s, accentCourant, teinter, ctx, ctxLignes);
    if (motif === "cinema") {
      const f = mouvementFiligrane(s);
      filigrane.style.transform = `translate3d(0, ${(f.decalage * innerHeight).toFixed(1)}px, 0) rotate(${f.angle.toFixed(2)}deg)`;
    }
  } else {
    peindreNappes(ctx, choix, environnementFond(PALETTES[choix] ? choix : "aurore", theme, s, accentCourant, teinter), accentCourant, teinter);
  }
  // Le scintillement suit le fond : une animation CSS à part, sur un calque 4K, faisait
  // recalculer les flous du dessus à chaque image, en plus de celles du fond.
  if (etoiles && !etoiles.hidden) etoiles.style.opacity = reduit ? "" : .775 - .225 * Math.cos(2 * Math.PI * s / 14);

  fondPret = true;
  // Un fond immobile n'a pas besoin de redessiner trente fois par seconde.
  const immobile = reduit || choix === "minimal" || choix === "photos";
  if (immobile && Math.abs(accentCourant[0] - accentCible[0]) < 1) { boucleFond = false; dernierDessin = null; return; }
  requestAnimationFrame(dessinerFond);
}
function relancerFond() {
  etoilesVisibles();
  photosVisibles();
  // Fond, thème ou teinte ont pu changer pendant la pause : une image au moins.
  fondPret = false;
  if (!boucleFond) { boucleFond = true; requestAnimationFrame(dessinerFond); }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) relancerFond(); });

// Aperçu d'un motif dans une couleur, pour les réglages : les mêmes fonctions de dessin,
// figées à 6 s, sur une toile de 480×270 (la vignette fait 10 à 14 rem de large).
function apercuFond(motif, couleur, theme, s = 6, accent = accentCourant, teinter = !!profil().teinteMode) {
  const vignette = document.createElement("canvas");
  vignette.width = 480; vignette.height = 270;
  const v = vignette.getContext("2d");
  const [largeur, hauteur] = RESOLUTIONS_FOND[motif] || RESOLUTION_MOTIF;
  const basse = document.createElement("canvas");
  basse.width = largeur; basse.height = hauteur;
  const b = basse.getContext("2d");
  if (PEINTRES[motif]) peindreFond(motif, couleur, theme, s, accent, teinter, b, null);
  else peindreNappes(b, motif === "minimal" ? "minimal" : couleur, environnementFond(motif === "minimal" ? "minimal" : couleur, theme, s, accent, teinter), accent, teinter);
  v.imageSmoothingEnabled = true;
  v.imageSmoothingQuality = "high";
  v.drawImage(basse, 0, 0, 480, 270);
  TRACEURS[motif]?.(v, environnementFond(couleur, theme, s, accent, teinter), 480 / LARGEUR_LIGNES);
  return vignette;
}
window.hubFond.apercuFond = apercuFond;

function etoilesVisibles() {
  const visible = fondChoisi() === "nebuleuse" && motifChoisi() === "nappes" && racine.dataset.theme !== "clair";
  if (visible && !etoiles) {
    etoiles = el("canvas", { id: "etoiles" });
    const echelle = Math.min(devicePixelRatio || 1, 2);
    etoiles.width = innerWidth * echelle;
    etoiles.height = innerHeight * echelle;
    const c = etoiles.getContext("2d");
    for (let i = 0; i < 420; i++) {
      const r = Math.random() ** 3 * 1.6 * echelle + .3;
      c.fillStyle = `rgba(255,255,255,${.25 + Math.random() * .7})`;
      c.beginPath();
      c.arc(Math.random() * etoiles.width, Math.random() * etoiles.height, r, 0, Math.PI * 2);
      c.fill();
    }
    toile.after(etoiles);
  }
  if (etoiles) etoiles.hidden = !visible;
}

let minuteriePhotos;
function photosVisibles() {
  const conteneur = $("photos");
  const liste = INITIAL.photos || [];
  const visible = fondChoisi() === "photos";
  conteneur.hidden = !visible;
  clearInterval(minuteriePhotos);
  if (!visible) return;
  if (!conteneur.children.length) {
    for (const uri of liste) conteneur.append(el("div", { style: `background-image:url("${uri}")` }));
  }
  let i = Math.floor(Math.random() * liste.length);
  const montrer = () => {
    [...conteneur.children].forEach((d, j) => d.classList.toggle("visible", j === i));
    i = (i + 1) % liste.length;
  };
  montrer();
  if (liste.length > 1) minuteriePhotos = setInterval(montrer, 45000);
}

(function grain() {
  const c = $("grain");
  c.width = 256; c.height = 256;
  const g = c.getContext("2d");
  const img = g.createImageData(256, 256);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = Math.random() * 255;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  c.style.backgroundImage = `url(${c.toDataURL()})`;
  c.style.backgroundSize = "256px 256px";
  c.width = 1; c.height = 1;
})();

function accentuer(nom) {
  const couleur = COULEURS_MODE[nom] || COULEURS_MODE.tv;
  accentCible = couleur;
  racine.style.setProperty("--accent", (racine.dataset.theme === "clair" ? couleur.map(v => Math.round(v * .78)) : couleur).join(" "));
  // Le filigrane du motif cinéma : le pictogramme du mode, le même que dans son onglet.
  const picto = document.querySelector(`#modes .onglet[data-accent="${nom}"] svg`);
  if (picto && filigrane.dataset.picto !== nom) {
    filigrane.dataset.picto = nom;
    filigrane.querySelector("svg").innerHTML = picto.innerHTML;
  }
  relancerFond();
}

// ── Horloge et salutation ─────────────────────────────────────────────────
function horloge() {
  const maintenant = new Date();
  const options = { hour: "2-digit", minute: "2-digit", hour12: profil().horloge === "12" };
  const heure = maintenant.toLocaleTimeString(locale(), options);
  const date = maintenant.toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "long" });
  $("heure").textContent = heure;
  $("date").textContent = date;
  $("ambiant-heure").textContent = heure;
  $("ambiant-date").textContent = date;

  const h = maintenant.getHours();
  const moment = h >= 5 && h < 12 ? "matin" : h >= 12 && h < 18 ? "aprem" : h >= 18 && h < 23 ? "soir" : "nuit";
  $("salut").textContent = `${t("salut." + moment)}, ${profil().nom}`;
  // Dans l'en-tête, la salutation reste courte : la ligne du dessous ne sert qu'à une alerte.
  const alerte = alerteMeteo();
  $("sous-salut").textContent = alerte || "";
  $("sous-salut").hidden = !alerte;
  appliquerApparence();
}

// ── Météo ─────────────────────────────────────────────────────────────────
let meteo = null;
let meteoReleve = null;
let meteoHorsLigne = false;

function nuage(classe = "nuage", dx = 0, dy = 0, echelle = 1) {
  return `<path class="${classe}" transform="translate(${dx} ${dy}) scale(${echelle})" d="M9 25h14.5a5.2 5.2 0 0 0 .6-10.4A7.2 7.2 0 0 0 10.3 16 4.5 4.5 0 0 0 9 25z"/>`;
}
function astre(nuit, x = 16, y = 16, r = 6) {
  if (nuit) return `<path class="lune" d="M${x + r * .35} ${y - r} a${r} ${r} 0 1 0 ${r * .65} ${r * 1.55} a${r * .78} ${r * .78} 0 1 1 -${r * .65} -${r * 1.55}z"/>`;
  const rayons = Array.from({ length: 8 }, (_, i) => {
    const a = i * Math.PI / 4;
    return `<line x1="${x + Math.cos(a) * (r + 2.4)}" y1="${y + Math.sin(a) * (r + 2.4)}" x2="${x + Math.cos(a) * (r + 5)}" y2="${y + Math.sin(a) * (r + 5)}"/>`;
  }).join("");
  return `<g class="rayons" style="transform-origin:${x}px ${y}px">${rayons}</g><circle class="soleil" cx="${x}" cy="${y}" r="${r}"/>`;
}
function pictoMeteo(code, nuit) {
  const type = (METEO_CODES[code] || METEO_CODES[3])[0];
  let corps;
  const gouttes = n => Array.from({ length: n }, (_, i) => `<line class="goutte" x1="${11 + i * 5}" y1="26.5" x2="${9.8 + i * 5}" y2="30"/>`).join("");
  switch (type) {
    case "soleil": corps = astre(nuit, 16, 16, 7); break;
    case "peu-nuageux": corps = astre(nuit, 11, 11, 5.2) + nuage("nuage", 2, 1, .95); break;
    case "nuageux": corps = nuage("nuage-sombre", -4, -5, .8) + nuage("nuage", 1, 0, 1); break;
    case "brouillard": corps = nuage("nuage", 0, -3, 1) + `<line class="brume" x1="6" y1="26" x2="24" y2="26"/><line class="brume" x1="9" y1="29.5" x2="27" y2="29.5"/>`; break;
    case "bruine": corps = nuage("nuage", 0, -4, 1) + gouttes(2); break;
    case "pluie": corps = nuage("nuage-sombre", -4, -8, .8) + nuage("nuage", 1, -4, 1) + gouttes(3); break;
    case "averses": corps = astre(nuit, 10, 9, 4.5) + nuage("nuage", 2, -3, .95) + gouttes(3); break;
    case "neige": corps = nuage("nuage", 0, -4, 1) + [11, 16, 21].map(x => `<circle class="flocon" cx="${x}" cy="27.5" r="1.3"/>`).join(""); break;
    case "orage": corps = nuage("nuage-sombre", 0, -4, 1) + `<path class="eclair" d="M16.5 20 12 26.5h3.6L14 31.5l5.5-7.3h-3.6l1.9-4.2z"/>`; break;
    default: corps = nuage();
  }
  return `<svg class="picto-meteo" viewBox="0 0 32 32">${corps}</svg>`;
}
function libelleMeteo(code) {
  const ligne = METEO_CODES[code] || METEO_CODES[3];
  return profil().langue === "en" ? ligne[2] : ligne[1];
}
function heureCourte(date) { return date.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", hour12: profil().horloge === "12" }); }

function indexHeureCourante() {
  if (!meteo?.hourly?.time) return 0;
  const maintenant = Date.now();
  const i = meteo.hourly.time.findIndex(h => new Date(h).getTime() > maintenant);
  return Math.max(0, i - 1);
}

function alerteMeteo() {
  if (!meteo?.hourly || !meteoProfil().active) return null;
  const debut = indexHeureCourante() + 1;
  for (let i = debut; i < debut + 6 && i < meteo.hourly.time.length; i++) {
    if ((meteo.hourly.precipitation_probability?.[i] ?? 0) >= 60) {
      return t("meteo.alerte.pluie", { h: heureCourte(new Date(meteo.hourly.time[i])) });
    }
  }
  return null;
}

function afficherMeteo() {
  const actif = meteoProfil().active && meteoSituee() && meteo?.current;
  $("puce-meteo").hidden = !actif;
  $("ambiant-meteo").replaceChildren();
  if (!actif) return;
  const c = meteo.current;
  const nuit = c.is_day === 0;
  $("meteo-picto-puce").innerHTML = pictoMeteo(c.weather_code, nuit);
  $("meteo-temp-puce").textContent = `${Math.round(c.temperature_2m)}°`;
  $("meteo-ville-puce").textContent = meteoProfil().ville;
  // Le picto est une construction interne ; le nom de ville vient du géocodage ou du
  // fichier de réglages : texte seulement, dans une page qui a accès aux fichiers.
  $("ambiant-meteo").append(el("span", { html: pictoMeteo(c.weather_code, nuit) }).firstChild,
    el("span", {}, `${Math.round(c.temperature_2m)}° · ${libelleMeteo(c.weather_code)} · ${meteoProfil().ville || ""}`));
  if (pile.at(-1) === "meteo") rendreMeteo();
  horloge();
}

function recevoirMeteo(donnees, releveLe, horsLigne) {
  if (!donnees?.current) return;
  meteo = donnees;
  meteoReleve = releveLe ? new Date(releveLe) : new Date();
  meteoHorsLigne = !!horsLigne;
  if (!PONT) try { localStorage.setItem("hub-meteo", JSON.stringify({ donnees, releveLe: meteoReleve })); } catch { /* aperçu */ }
  afficherMeteo();
}

const URL_METEO = "https://api.open-meteo.com/v1/forecast?current=temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m,relative_humidity_2m&hourly=temperature_2m,weather_code,precipitation_probability,is_day&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max&timezone=auto&forecast_days=7";

async function chargerMeteo() {
  const { active, lat, lon } = meteoProfil();
  if (!active || !meteoSituee()) return afficherMeteo();
  if (PONT) return envoyer({ type: "meteo", lat, lon });
  try {
    const reponse = await fetch(`${URL_METEO}&latitude=${lat}&longitude=${lon}`);
    recevoirMeteo(await reponse.json(), new Date(), false);
  } catch {
    try {
      const cache = JSON.parse(localStorage.getItem("hub-meteo"));
      if (cache) recevoirMeteo(cache.donnees, cache.releveLe, true);
    } catch { /* rien en cache */ }
  }
}

function rendreMeteo() {
  const zone = $("contenu-meteo");
  zone.innerHTML = "";
  zone.style.transform = "";
  const boutons = el("div", { class: "options", style: "margin-left:auto;align-self:flex-start" },
    el("button", { class: "option", "data-nav": true, "data-cle": "ville", onclick: chercherVille }, t("meteo.chercher")),
    el("button", { class: "option", "data-nav": true, "data-cle": "fermer", "data-action": "fermer" }, t("fermer")));
  if (!meteo?.current) {
    zone.append(el("div", { class: "meteo-tete" }, el("h3", {}, t("meteo.indisponible")), boutons));
    return;
  }
  const c = meteo.current, d = meteo.daily, hr = meteo.hourly;
  const releve = meteoHorsLigne ? `${t("meteo.hors.ligne")} ${heureCourte(meteoReleve)}` : t("meteo.releve", { h: heureCourte(meteoReleve) });
  zone.append(el("div", { class: "meteo-tete" },
    el("div", { html: pictoMeteo(c.weather_code, c.is_day === 0) }),
    el("div", { class: "grande-temp" }, `${Math.round(c.temperature_2m)}°`),
    el("div", {},
      el("div", { class: "etat" }, libelleMeteo(c.weather_code)),
      el("div", { class: "lieu" }, `${meteoProfil().ville} · ${releve}`),
      alerteMeteo() && el("div", { class: "lieu", style: "color:var(--pluie)" }, alerteMeteo())),
    boutons));

  const info = (etiquette, valeur) => el("div", { class: "info" }, el("div", { class: "etiquette" }, etiquette), el("div", { class: "valeur" }, valeur));
  zone.append(el("div", { class: "meteo-mesures" },
    info(t("meteo.ressenti"), `${Math.round(c.apparent_temperature)}°`),
    info(t("meteo.vent"), `${Math.round(c.wind_speed_10m)} km/h`),
    info(t("meteo.humidite"), `${c.relative_humidity_2m} %`),
    info(t("meteo.pluie"), `${d.precipitation_probability_max?.[0] ?? 0} %`),
    info(`${t("meteo.lever")} / ${t("meteo.coucher")}`, `${heureCourte(new Date(d.sunrise[0]))} – ${heureCourte(new Date(d.sunset[0]))}`)));

  zone.append(el("div", { class: "sous-titre" }, t("meteo.prochaines")));
  const heures = el("div", { class: "heures" });
  const debut = indexHeureCourante() + 1;
  for (let i = debut; i < debut + 8 && i < hr.time.length; i++) {
    const p = hr.precipitation_probability?.[i] ?? 0;
    heures.append(el("div", { class: "heure-meteo" },
      el("div", { class: "h" }, new Date(hr.time[i]).toLocaleTimeString(locale(), { hour: "2-digit", hour12: profil().horloge === "12" })),
      el("div", { html: pictoMeteo(hr.weather_code[i], hr.is_day?.[i] === 0) }),
      el("div", { class: "t" }, `${Math.round(hr.temperature_2m[i])}°`),
      el("div", { class: "p" }, p >= 20 ? `${p} %` : "")));
  }
  zone.append(heures);

  zone.append(el("div", { class: "sous-titre" }, t("meteo.jours")));
  const jours = el("div", { class: "jours" });
  const min = Math.min(...d.temperature_2m_min.slice(0, 6)), max = Math.max(...d.temperature_2m_max.slice(0, 6));
  for (let i = 0; i < Math.min(6, d.time.length); i++) {
    const nom = i === 0 ? t("meteo.aujourdhui") : new Date(d.time[i] + "T12:00").toLocaleDateString(locale(), { weekday: "long" });
    const gauche = (d.temperature_2m_min[i] - min) / (max - min || 1) * 100;
    const largeur = (d.temperature_2m_max[i] - d.temperature_2m_min[i]) / (max - min || 1) * 100;
    jours.append(el("div", { class: "jour" },
      el("div", { class: "j", style: "text-transform:capitalize" }, nom),
      el("div", { html: pictoMeteo(d.weather_code[i], false) }),
      el("div", { class: "etat-j" }, libelleMeteo(d.weather_code[i])),
      el("div", { class: "min" }, `${Math.round(d.temperature_2m_min[i])}°`),
      el("div", { class: "barre-temp" }, el("i", { style: `left:${gauche}%;width:${Math.max(largeur, 4)}%` })),
      el("div", { class: "max" }, `${Math.round(d.temperature_2m_max[i])}°`)));
  }
  zone.append(jours);
}

let rappelGeocodage = null;
function chercherVille() {
  ouvrirClavier(t("meteo.ville"), "", async nom => {
    if (!nom.trim()) return;
    rappelGeocodage = resultats => {
      rappelGeocodage = null;
      if (!resultats?.length) return annoncer(t("meteo.aucune.ville"));
      montrerVilles(resultats);
    };
    if (PONT) envoyer({ type: "geocodage", nom, langue: profil().langue });
    else {
      try {
        const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?count=6&language=${profil().langue}&name=${encodeURIComponent(nom)}`);
        rappelGeocodage((await r.json()).results || []);
      } catch { rappelGeocodage([]); }
    }
  });
}
function montrerVilles(resultats) {
  const liste = el("div", { class: "options", style: "justify-content:flex-start" });
  for (const v of resultats) {
    const precision = [v.admin1, v.country_code].filter(Boolean).join(", ");
    liste.append(el("button", {
      class: "option", "data-nav": true, "data-cle": `ville-${v.id}`,
      onclick: () => {
        profil().meteo = { ...meteoProfil(), active: true, ville: String(v.name ?? ""), lat: Number(v.latitude), lon: Number(v.longitude) };
        sauver();
        chargerMeteo();
        rendreSection();
        fermerCalque();
      },
    }, `${v.name} — ${precision}`));
  }
  const zone = $("contenu-meteo");
  zone.innerHTML = "";
  zone.append(el("h3", {}, t("meteo.resultats")), liste);
  if (pile.at(-1) !== "meteo") ouvrirCalque("meteo", false);
  definirFocus(liste.querySelector("[data-nav]"));
}

// ── Navigation spatiale ───────────────────────────────────────────────────
// Chaque calque (accueil, réglages, dialogues…) a ses éléments [data-nav] ; les
// flèches vont vers le plus proche dans la direction demandée. Pas de liste
// d'enchaînements à maintenir : ajouter un bouton suffit à le rendre atteignable.
const pile = ["accueil"];
const focusParCalque = {};
let courant = null;
let verrou = false;
// Flèche maintenue (répétition automatique du clavier ou de la télécommande).
let toucheRepetee = false;

function calqueActif() { return $(pile.at(-1)); }
function candidats() {
  return [...calqueActif().querySelectorAll("[data-nav]")].filter(e => !e.hidden && !e.closest("[hidden]") && e.getClientRects().length);
}

function definirFocus(cible, silencieux = false) {
  if (!cible) return;
  const precedent = courant;
  if (courant && courant !== cible) courant.classList.remove("focus");
  const change = courant !== cible;
  courant = cible;
  cible.classList.add("focus");
  focusParCalque[pile.at(-1)] = cible;
  retenirRangee(cible);
  if (change && !silencieux) son("deplacer");

  // Sur l'accueil, le héros, la pastille et la teinte du fond suivent l'onglet. Une tuile
  // (streaming, reprise) n'est pas un mode : le héros garde le dernier mode choisi, et le
  // fond sa couleur, plutôt que de passer au turquoise de la TV à chaque Bas.
  if (pile.at(-1) === "accueil") {
    if (cible.classList.contains("onglet")) montrerHeros(cible, change && !toucheRepetee && !!precedent);
    $("modes").classList.toggle("actif", cible.classList.contains("onglet"));
    accentuer(ongletHeros?.dataset.accent || "tv");
  } else if (cible.dataset.accent) accentuer(cible.dataset.accent);
  // Parcourir le sommaire change la section ; y revenir depuis le contenu, jamais : on
  // rentre sur la section qu'on quittait (voisin), et un focus égaré ne doit pas remplacer
  // sous les yeux la page qu'on était en train de régler (audit du 17/09/2026 : Haut depuis
  // « Sombre » ouvrait Arrière-plan).
  if (cible.dataset.section && cible.dataset.section !== sectionCourante && !precedent?.closest(".contenu")) {
    sectionCourante = cible.dataset.section;
    rendreSection(false);
  }
  defiler(cible);
}

function defiler(cible) {
  // Le sommaire ne tient pas toujours (taille XL : Allumage, Raccourcis et À propos passaient
  // sous le bord de la feuille, focus compris). Il défile d'une entrée d'avance, pour qu'on
  // voie qu'il en reste.
  const sommaire = cible.closest(".sommaire");
  if (sommaire) {
    const r = cible.getBoundingClientRect(), s = sommaire.getBoundingClientRect();
    const avance = r.height;
    const entrees = [...sommaire.querySelectorAll(".entree")];
    let haut = sommaire.scrollTop;
    if (cible === entrees[0]) haut = 0;
    else if (cible === entrees.at(-1)) haut = sommaire.scrollHeight - sommaire.clientHeight;
    else if (r.top < s.top + avance) haut -= s.top + avance - r.top;
    else if (r.bottom > s.bottom - avance) haut += r.bottom - (s.bottom - avance);
    if (haut !== sommaire.scrollTop) sommaire.scrollTo({ top: haut, behavior: profil().animations === "reduites" ? "auto" : "smooth" });
    return;
  }
  const zone = cible.closest(".contenu-defile");
  if (!zone) return;
  const cadre = zone.parentElement;
  const r = cible.getBoundingClientRect(), z = zone.getBoundingClientRect();
  const position = r.top - z.top;
  const hauteurUtile = cadre.clientHeight - parseFloat(getComputedStyle(cadre).paddingTop) * 2;
  const maximum = Math.max(0, zone.scrollHeight - hauteurUtile);
  // Sur la dernière cible, jusqu'en bas : une aide ou une note qui la suit doit se lire.
  const derniere = [...zone.querySelectorAll("[data-nav]")].filter(e => e.getClientRects().length).at(-1) === cible;
  const decalage = derniere ? maximum : borne(position - hauteurUtile * .4, 0, maximum);
  zone.style.transform = `translateY(${-decalage}px)`;
}

// La navigation reste d'abord dans la zone où l'on est (contenu d'un réglage, sommaire,
// pied…) : sans ça, « haut » depuis un bouton du contenu sautait dans le sommaire voisin
// au lieu du bouton juste au-dessus.
const ZONES = ".contenu, .sommaire, .entete, .pied, .modes, .reprises, .applis, .grille-jeux, .editeur-identite, .editeur-securite, .choix, .pave";
// L'accueil se lit en rangées : en-tête, cartes, reprises, streaming, pied. Gauche et Droite
// restent dans la rangée et s'arrêtent à son bout ; Haut et Bas passent à la rangée voisine,
// sur l'élément qu'on y avait sélectionné en dernier. La plus proche des cibles, en géométrie
// pure, menait ailleurs (audit du 17/09/2026 : Gauche depuis TV → YouTube puis le profil ;
// Haut depuis Jeux → la météo ; Bas depuis Netflix → le bouton Raccourcis) et 19 paires de
// déplacements n'étaient pas réversibles.
const RANGEES_ACCUEIL = [".entete", ".modes", ".reprises-liste", ".applis-liste", ".pied .actions"];
const memoireRangee = new Map();
function rangeesAccueil(liste) {
  return RANGEES_ACCUEIL.map(sel => document.querySelector(`#accueil ${sel}`))
    .map(r => r && liste.filter(e => r.contains(e)).sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left))
    .filter(r => r?.length);
}
function voisinAccueil(depart, direction, liste) {
  const rangees = rangeesAccueil(liste);
  const i = rangees.findIndex(r => r.includes(depart));
  if (i < 0) return undefined;
  const rangee = rangees[i], j = rangee.indexOf(depart);
  if (direction === "gauche") return rangee[j - 1] || null;
  if (direction === "droite") return rangee[j + 1] || null;
  const cible = rangees[direction === "haut" ? i - 1 : i + 1];
  if (!cible) return null;
  const retenu = memoireRangee.get(RANGEES_ACCUEIL.find(sel => cible[0].closest(`#accueil ${sel}`)));
  if (cible.includes(retenu)) return retenu;
  // L'en-tête, jamais visité : le profil, plutôt que la météo qui le précède.
  if (cible[0].closest("#accueil .entete")) return cible.find(e => e.id === "puce-profil") || cible[0];
  const a = depart.getBoundingClientRect(), x = a.left + a.width / 2;
  return cible.reduce((m, e) => { const r = e.getBoundingClientRect(); const d = Math.abs(r.left + r.width / 2 - x); return d < m.d ? { e, d } : m; }, { e: null, d: Infinity }).e;
}
function retenirRangee(cible) {
  if (pile.at(-1) !== "accueil") return;
  const sel = RANGEES_ACCUEIL.find(s => cible.closest(`#accueil ${s}`));
  if (sel) memoireRangee.set(sel, cible);
}

function voisin(depart, direction) {
  const zone = depart.closest(ZONES);
  const liste = candidats();
  if (pile.at(-1) === "accueil") {
    const v = voisinAccueil(depart, direction, liste);
    if (v !== undefined) return v;
  }
  const dansZone = zone && voisinParmi(depart, direction, liste.filter(e => zone.contains(e)));
  if (dansZone) return dansZone;
  // Le contenu d'une feuille est un cul-de-sac en haut et en bas : le sommaire est à
  // gauche, pas au-dessus. Gauche ramène sur l'entrée de la section affichée.
  // Du sommaire vers la droite : le premier réglage dans l'ordre de lecture, pas celui qui
  // se trouve à la hauteur de l'entrée (dans À propos, « Rechercher » n'était atteint que
  // par un détour, audit du 17/09/2026).
  if (zone?.classList.contains("sommaire") && direction === "droite") {
    const premier = liste.find(e => e.closest(".contenu") && zone.parentElement.contains(e));
    if (premier) return premier;
  }
  if (zone?.classList.contains("contenu")) {
    if (direction !== "gauche") return null;
    return liste.find(e => e.dataset.section === sectionCourante) || null;
  }
  return voisinParmi(depart, direction, liste);
}
function voisinParmi(depart, direction, liste) {
  const a = depart.getBoundingClientRect();
  const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
  let meilleur = null, score = Infinity;
  for (const e of liste) {
    if (e === depart) continue;
    const b = e.getBoundingClientRect();
    const bx = b.left + b.width / 2, by = b.top + b.height / 2;
    let principal, ecart;
    const ecartH = Math.max(0, b.left - a.right, a.left - b.right);
    const ecartV = Math.max(0, b.top - a.bottom, a.top - b.bottom);
    if (direction === "droite") { principal = bx - ax; ecart = ecartV + Math.abs(by - ay) * .1; if (b.left < a.right - a.width * .5) continue; }
    else if (direction === "gauche") { principal = ax - bx; ecart = ecartV + Math.abs(by - ay) * .1; if (b.right > a.left + a.width * .5) continue; }
    else if (direction === "bas") { principal = by - ay; ecart = ecartH + Math.abs(bx - ax) * .1; if (b.top < a.bottom - a.height * .5) continue; }
    else { principal = ay - by; ecart = ecartH + Math.abs(bx - ax) * .1; if (b.bottom > a.top + a.height * .5) continue; }
    if (principal <= 0) continue;
    const s = principal + ecart * 3;
    if (s < score) { score = s; meilleur = e; }
  }
  return meilleur;
}

// La flèche opposée défait le déplacement qu'on vient de faire : dans un calque dessiné
// librement (éditeur de profil), la cible la plus proche au retour n'était pas celle d'où
// l'on venait (25 allers-retours sur 16 cibles ne revenaient pas, audit du 17/09/2026).
// Sauf depuis le sommaire, où Droite mène toujours au premier réglage.
const OPPOSES = { haut: "bas", bas: "haut", gauche: "droite", droite: "gauche" };
let dernierDeplacement = null;
function deplacer(direction) {
  const liste = candidats();
  if (!courant || !liste.includes(courant)) return definirFocus(liste[0]);
  const d = dernierDeplacement;
  const defaire = d && d.vers === courant && d.direction === OPPOSES[direction] && liste.includes(d.depuis) && !courant.closest(".sommaire");
  const suivant = defaire ? d.depuis : voisin(courant, direction);
  if (!suivant) return;
  dernierDeplacement = { depuis: courant, vers: suivant, direction };
  definirFocus(suivant);
}

function ouvrirCalque(id, focusPremier = true) {
  if (pile.at(-1) === id) return;
  if (pile.includes(id)) pile.splice(pile.indexOf(id), 1);
  pile.push(id);
  // Le dernier ouvert passe devant : sans ça, l'ordre du HTML décidait, et l'éditeur de
  // profil ouvert depuis Réglages se retrouvait sous la feuille (constaté sur la TV le
  // 17/09/2026, quand la feuille élargie a fini par le recouvrir). Sous les annonces (20).
  $(id).style.zIndex = 10 + pile.length;
  $(id).classList.add("ouvert");
  document.body.classList.toggle("calque-ouvert", pile.length > 1);
  majAppairage();
  if (focusPremier) {
    const precedent = focusParCalque[id];
    const liste = candidats();
    definirFocus(liste.includes(precedent) ? precedent : liste[0], true);
  }
  son("ok");
}
function fermerCalque() {
  if (pile.length === 1) return;
  // Profil verrouillé : on ne revient pas à l'accueil sans son code.
  if (verrouAccueil && pile.length === 2 && pile[1] !== "code" && pile[1] !== "profils") return exigerDeverrouillage();
  const id = pile.pop();
  $(id).classList.remove("ouvert");
  if (id === "profils") document.body.classList.remove("gestion");
  document.body.classList.toggle("calque-ouvert", pile.length > 1);
  majAppairage();
  const liste = candidats();
  const precedent = focusParCalque[pile.at(-1)];
  definirFocus(liste.includes(precedent) ? precedent : liste[0], true);
  if (pile.length === 1) relancerFond();
  son("retour");
  if (verrouAccueil && pile.length === 1 && id !== "code") setTimeout(exigerDeverrouillage, 0);
}
function fermerTout() { while (pile.length > 1) fermerCalque(); }

// ── Accueil : le héros et les onglets des modes ───────────────────────────
// Maquette C « Cinéma », choisie le 17/09/2026 : le mode choisi en grand à gauche, les
// modes en onglets sous lui, une pastille à sa couleur qui glisse derrière l'onglet. Les
// trois cartes de verre d'avant se touchaient presque, avec l'anneau blanc collé autour
// (« trop bord à bord et compactes ») ; et leur flou d'arrière-plan était recalculé à
// chaque image du fond. Ni le héros, ni les onglets, ni les tuiles n'ont de flou.
const onglets = [...document.querySelectorAll("#modes .onglet")];
let ongletHeros = null;

function pastillesHeros(mode) {
  if (mode === "gaming") return SERVICES.filter(s => s.categorie === "jeux" && serviceVisible(s)).map(s => s.nom);
  if (mode === "tv") {
    const reprises = (INITIAL.reprises || []).length;
    return ["Kodi", t("heros.films"), t("heros.series"), t("heros.musique"), reprises && t("heros.reprises", { n: Math.min(reprises, 4) })].filter(Boolean);
  }
  return ["Ubuntu", t("heros.applications"), t("heros.fichiers")];
}

// Le héros dit le mode de l'onglet : titre, phrase, services, et ce que fait OK.
// « anime » : un fondu de 180 ms, jamais quand la touche est maintenue.
function montrerHeros(onglet = ongletHeros, anime = false) {
  const visibles = onglets.filter(o => !o.hidden);
  if (!onglet || onglet.hidden) onglet = visibles.find(o => o.dataset.mode === profil().dernier) || visibles[0];
  if (!onglet) return;
  const change = ongletHeros !== onglet;
  ongletHeros = onglet;
  const mode = onglet.dataset.mode;
  const nom = t({ tv: "mode.tv", gaming: "mode.jeux", bureau: "mode.bureau" }[mode]);
  $("heros-titre").textContent = nom;
  $("heros-texte").textContent = t(`heros.${mode}`);
  $("heros-services").replaceChildren(...pastillesHeros(mode).map(n => el("span", {}, n)));
  $("lancer-texte").textContent = t(mode === "gaming" ? "heros.ouvrir" : "heros.lancer", { mode: nom });
  onglets.forEach(o => o.classList.toggle("choisi", o === onglet));
  // La pastille glisse d'un onglet à l'autre (transform, 180 ms) : des colonnes égales,
  // elle n'a qu'à connaître son rang et leur nombre.
  $("modes").style.setProperty("--n", visibles.length);
  $("modes").style.setProperty("--i", Math.max(0, visibles.indexOf(onglet)));
  if (change && anime && profil().animations !== "reduites") {
    for (const e of [$("heros-titre"), $("heros-texte"), $("heros-services")]) {
      e.animate([{ opacity: .25, transform: "translateY(.45rem)" }, { opacity: 1, transform: "none" }], { duration: 180, easing: "cubic-bezier(.2, .7, .3, 1)" });
    }
  }
}

// ── Accueil : lancer un mode ──────────────────────────────────────────────

let minuterieAnnonce;
function annoncer(texte) {
  const a = $("annonce");
  a.textContent = texte;
  a.classList.add("visible");
  clearTimeout(minuterieAnnonce);
  minuterieAnnonce = setTimeout(() => a.classList.remove("visible"), 3200);
}

function lancer(carte) {
  if (verrou) return;
  if (!modeAutorise(carte.dataset.mode)) { son("erreur"); return annoncer(t("mode.interdit")); }
  if (lancementRefuse(carte.dataset.mode)) return;
  // Jeux n'est pas un programme mais un choix de services : un sous-écran, pas un départ.
  if (carte.dataset.mode === "gaming") return ACTIONS.jeux();
  if (APERCU) { son("ok"); return annoncer(t("apercu.mode", { mode: carte.querySelector(".nom").textContent })); }
  if (carte.dataset.indisponible) {
    son("erreur");
    annoncer(t(carte.dataset.indisponible));
    carte.animate([{ translate: "0" }, { translate: "-.45rem" }, { translate: ".45rem" }, { translate: "-.23rem" }, { translate: "0" }], { duration: 420, easing: "ease-out" });
    return;
  }
  verrou = true;
  son("ok");
  profil().dernier = carte.dataset.mode;
  if (PONT) envoyer({ type: "reglages", donnees: reglages });
  carte.classList.add("lance");
  document.body.classList.add("depart");
  setTimeout(() => envoyer({ type: "choix", mode: carte.dataset.mode }), profil().animations === "reduites" ? 0 : 620);
}

function eteindre() {
  if (APERCU) { fermerTout(); return annoncer(t("apercu.eteindre")); }
  verrou = true;
  document.body.classList.add("depart");
  setTimeout(() => envoyer({ type: "choix", mode: "eteindre" }), 620);
}

onglets.forEach(c => c.addEventListener("click", () => {
  if (pile.at(-1) !== "accueil") return;
  definirFocus(c, true);
  lancer(c);
}));
$("lancer").addEventListener("click", () => {
  if (pile.at(-1) !== "accueil" || !ongletHeros || verrou) return;
  definirFocus(ongletHeros, true);
  lancer(ongletHeros);
});

// ── Continuer à regarder ──────────────────────────────────────────────────
function rendreReprises() {
  const liste = modeAutorise("tv") ? INITIAL.reprises || [] : [];
  document.body.classList.toggle("avec-reprises", liste.length > 0);
  $("reprises").hidden = !liste.length;
  const zone = $("reprises-liste");
  zone.innerHTML = "";
  liste.slice(0, 4).forEach((r, i) => {
    const reste = Math.max(1, Math.round((r.duree - r.position) / 60));
    const tuile = el("button", {
      class: "reprise", "data-nav": true, "data-accent": "tv", "data-cle": `reprise-${i}`,
      style: r.image ? `background-image:linear-gradient(180deg, transparent, transparent), url("${encodeURI(r.image)}")` : null,
      onclick: () => lancerReprise(tuile, r),
    },
    !r.image && el("span", { class: "lettre" }, (r.titre[0] || "").toUpperCase()),
    el("span", { class: "lecture", html: '<svg viewBox="0 0 10 12"><path d="M0 0l10 6-10 6z"/></svg>' }),
    el("span", { class: "textes" },
      el("div", { class: "t1" }, r.titre),
      el("div", { class: "t2" }, [r.sousTitre, t("reprendre.reste", { m: reste })].filter(Boolean).join(" · "))),
    el("span", { class: "barre" }, el("i", { style: `width:${borne(r.position / r.duree * 100, 2, 100)}%` })));
    zone.append(tuile);
  });
}

function lancerReprise(tuile, reprise) {
  if (verrou || pile.at(-1) !== "accueil" || lancementRefuse("tv")) return;
  verrou = true;
  son("ok");
  profil().dernier = "tv";
  envoyer({ type: "reglages", donnees: reglages });
  tuile.classList.add("lance");
  document.body.classList.add("depart");
  setTimeout(() => envoyer({ type: "choix", mode: "tv", fichier: reprise.fichier }), profil().animations === "reduites" ? 0 : 620);
}

// ── Streaming sur l'accueil, jeux en sous-écran ───────────────────────────
// Le streaming est une rangée de l'accueil, à une touche Bas des cartes : on y va plus
// souvent qu'à Kodi pour certains, et un sous-écran « TV & streaming » aurait ajouté un
// OK de plus devant Kodi à tous les autres. Les jeux, eux, sont derrière la carte Jeux :
// on s'y installe pour un moment, et il y a de la place pour dire comment revenir.
function tuileService(s, grande = false) {
  const indisponible = !serviceDisponible(s);
  const tuile = el("button", {
    class: `tuile-service${grande ? " grande" : ""}${indisponible ? " indisponible" : ""}`,
    "data-nav": true, "data-cle": `service-${s.id}`, "data-accent": s.categorie === "jeux" ? "jeux" : "tv",
    style: `--fond:${s.fond};--encre:${s.encre};--halo:${s.halo}`,
    onclick: () => lancerService(tuile, s),
  },
  el("span", { class: "marque", style: s.style }, s.nom),
  grande && el("span", { class: "sous" }, t(`service.detail.${s.id}`)),
  indisponible ? el("span", { class: "etat-service" }, t("service.absent"))
    : grande && etatService(s)?.via === "appli" && el("span", { class: "etat-service" }, t("service.appli")));
  return tuile;
}

function rendreApplis() {
  const liste = SERVICES.filter(s => s.categorie === "streaming" && serviceVisible(s));
  const zone = $("applis-liste");
  const cle = pile.at(-1) === "accueil" ? courant?.dataset.cle : null;
  zone.innerHTML = "";
  for (const s of liste) zone.append(tuileService(s));
  $("applis").hidden = !liste.length;
  document.body.classList.toggle("avec-applis", liste.length > 0);
  const retrouve = cle && zone.querySelector(`[data-cle="${cle}"]`);
  if (retrouve) definirFocus(retrouve, true);
}

function rendreJeux() {
  const zone = $("contenu-jeux");
  zone.innerHTML = "";
  zone.style.transform = "";
  const liste = SERVICES.filter(s => s.categorie === "jeux" && serviceVisible(s));
  zone.append(el("div", { class: "jeux-tete" },
    el("h3", {}, t("jeux.titre")),
    el("button", { class: "option", "data-nav": true, "data-cle": "fermer-jeux", "data-action": "fermer" }, t("fermer"))));
  if (!liste.length) zone.append(el("div", { class: "aide" }, t("jeux.aucun")));
  const grille = el("div", { class: "grille-jeux" });
  for (const s of liste) grille.append(tuileService(s, true));
  zone.append(grille, el("div", { class: "retour-jeux" }, t("jeux.retour")));
}

function lancerService(tuile, s) {
  if (verrou || lancementRefuse("web")) return;
  if (!serviceVisible(s)) { son("erreur"); return annoncer(t(modeAutorise(modeDuService(s)) ? "service.masque" : "mode.interdit")); }
  if (APERCU) { son("ok"); return annoncer(t("apercu.mode", { mode: s.nom })); }
  if (!serviceDisponible(s)) {
    son("erreur");
    tuile?.animate([{ translate: "0" }, { translate: "-.38rem" }, { translate: ".38rem" }, { translate: "0" }], { duration: 380, easing: "ease-out" });
    return annoncer(t("service.absent.detail", { nom: s.nom }));
  }
  verrou = true;
  son("ok");
  if (PONT) envoyer({ type: "reglages", donnees: reglages });
  tuile?.classList.add("lance");
  document.body.classList.add("depart");
  setTimeout(() => envoyer({ type: "choix", mode: "web", service: s.id }), profil().animations === "reduites" ? 0 : 620);
}

// ── Actions nommées ───────────────────────────────────────────────────────
const ACTIONS = {
  profils: () => { rendreProfils(); ouvrirCalque("profils"); },
  "gerer-profils": () => { document.body.classList.toggle("gestion"); rendreProfils(); },
  reglages: (section) => {
    if (profil().pin && profil().reglagesProteges && !deverrouilles.has(profil().id)) {
      return demanderCode(profil(), () => ACTIONS.reglages(section), { detail: t("code.reglages") });
    }
    if (typeof section === "string") sectionCourante = section;
    rendreReglages();
    ouvrirCalque("reglages");
  },
  meteo: () => { rendreMeteo(); ouvrirCalque("meteo"); chargerMeteo(); },
  aide: () => { rendreAide(); ouvrirCalque("aide"); },
  jeux: () => {
    rendreJeux();
    // Les tuiles sont recréées à chaque ouverture : on revient sur le même service par sa clé.
    const cle = focusParCalque.jeux?.dataset.cle;
    focusParCalque.jeux = (cle && $("contenu-jeux").querySelector(`[data-cle="${cle}"]`)) || $("contenu-jeux").querySelector(".tuile-service");
    ouvrirCalque("jeux");
  },
  arret: () => ouvrirCalque("arret"),
  eteindre,
  fermer: fermerCalque,
  minuteur: () => ACTIONS.reglages("veille"),
  "editer-nom": () => ouvrirClavier(t("profils.nom"), brouillon.nom, nom => { if (nom.trim()) brouillon.nom = nom.trim().slice(0, 16); rendreEditeur(); }),
  "enregistrer-profil": enregistrerProfil,
  "supprimer-profil": supprimerProfil,
};

document.addEventListener("click", e => {
  const cible = e.target.closest("[data-action]");
  if (!cible || verrou) return;
  if (!calqueActif().contains(cible)) return;
  ACTIONS[cible.dataset.action]?.();
});

// ── Profils ───────────────────────────────────────────────────────────────
let brouillon = null;
let listeAvatars = INITIAL.avatars || [];

function tuileProfil(p) {
  const couleur = COULEURS_PROFIL[p.couleur] || COULEURS_PROFIL.turquoise;
  const tuile = el("button", {
    class: "tuile-profil", "data-nav": true, "data-cle": `profil-${p.id}`, style: `--c:${couleur.join(" ")}`,
    onclick: () => {
      if (document.body.classList.contains("gestion")) return ouvrirEditeur(p);
      choisirProfil(p.id);
    },
  }, avatar(p), el("span", { class: "nom-tuile" }, p.nom, p.pin && el("span", { class: "cadenas", html: ICONE_CADENAS })));
  return tuile;
}

function rendreProfils() {
  const liste = $("liste-profils");
  const cle = courant?.dataset.cle;
  liste.innerHTML = "";
  for (const p of reglages.profils) liste.append(tuileProfil(p));
  document.querySelector('[data-action="gerer-profils"]').hidden = estRestreint();
  if (reglages.profils.length < 6 && !estRestreint()) {
    liste.append(el("button", { class: "tuile-profil ajout", "data-nav": true, "data-cle": "profil-ajout", onclick: () => ouvrirEditeur(null) },
      el("span", { class: "avatar" }, "+"), t("profils.ajouter")));
  }
  const retrouve = cle && liste.querySelector(`[data-cle="${CSS.escape(cle)}"]`);
  if (pile.at(-1) === "profils") definirFocus(retrouve || liste.querySelector(`[data-cle="${CSS.escape(`profil-${reglages.profilActif}`)}"]`), true);
  else focusParCalque.profils = liste.querySelector(`[data-cle="${CSS.escape(`profil-${reglages.profilActif}`)}"]`);
}

function choisirProfil(id) {
  const cible = reglages.profils.find(p => p.id === id);
  if (!cible) return;
  if (cible.pin && !deverrouilles.has(id)) return demanderCode(cible, () => choisirProfil(id));
  // Changer de profil referme les autres : revenir à un profil protégé redemande son code.
  deverrouilles = new Set(cible.pin ? [id] : []);
  verrouAccueil = false;
  document.body.classList.remove("verrouille");
  reglages.profilActif = id;
  sauver();
  document.body.classList.remove("gestion");
  appliquerTout();
  fermerTout();
  const carte = onglets.find(c => c.dataset.mode === profil().dernier && !c.hidden) || onglets.find(c => !c.hidden);
  definirFocus(carte, true);
  annoncer(`${t("salut." + (new Date().getHours() < 18 ? "matin" : "soir"))}, ${profil().nom}`);
}

function ouvrirEditeur(p) {
  if (estRestreint() && (!p || p.id !== profil().id)) { son("erreur"); return annoncer(t("profils.restreint")); }
  if (p?.pin && !deverrouilles.has(p.id)) return demanderCode(p, () => ouvrirEditeur(p));
  brouillon = p ? { ...p } : { ...DEFAUTS_PROFIL, id: `p${Date.now().toString(36)}`, nom: "", couleur: Object.keys(COULEURS_PROFIL)[reglages.profils.length % 7], nouveau: true };
  rendreEditeur();
  ouvrirCalque("editeur-profil");
  envoyer({ type: "avatars" });
  if (brouillon.nouveau) ACTIONS["editer-nom"]();
}
function rendreEditeur() {
  habillerAvatar($("editeur-apercu"), brouillon);
  $("editeur-titre").textContent = brouillon.nouveau ? t("profils.nouveau") : t("profils.modifier");
  $("editeur-nom").textContent = brouillon.nom || "…";
  $("editeur-supprimer").hidden = !!brouillon.nouveau || estRestreint();
  rendreSecurite();
  const nuancier = $("nuancier");
  const cle = courant?.dataset.cle;
  nuancier.innerHTML = "";
  for (const [nom, rgb] of Object.entries(COULEURS_PROFIL)) {
    nuancier.append(el("button", {
      class: `nuance${nom === brouillon.couleur ? " choisie" : ""}`, "data-nav": true, "data-cle": `nuance-${nom}`, style: `--c:${rgb.join(" ")}`,
      onclick: () => { brouillon.couleur = nom; rendreEditeur(); },
    }));
  }
  const galerie = $("galerie-avatars");
  galerie.innerHTML = "";
  galerie.append(el("button", {
    class: `choix-photo sans-photo${!brouillon.photo ? " choisie" : ""}`, "data-nav": true, "data-cle": "photo-aucune",
    onclick: () => { brouillon.photo = null; rendreEditeur(); },
  }, (brouillon.nom[0] || "?").toUpperCase()));
  for (const [i, uri] of listeAvatars.entries()) {
    galerie.append(el("button", {
      class: `choix-photo${brouillon.photo === uri ? " choisie" : ""}`, "data-nav": true, "data-cle": `photo-${i}`,
      style: `background-image:url("${encodeURI(decodeURI(uri))}")`,
      onclick: () => { brouillon.photo = uri; rendreEditeur(); },
    }));
  }
  $("aide-photo").hidden = listeAvatars.length > 0;
  const retrouve = cle && $("editeur-profil").querySelector(`[data-cle="${CSS.escape(cle)}"]`);
  if (retrouve && pile.at(-1) === "editeur-profil") definirFocus(retrouve, true);
}
function enregistrerProfil() {
  if (!brouillon.nom.trim()) return ACTIONS["editer-nom"]();
  const { nouveau, ...p } = brouillon;
  const i = reglages.profils.findIndex(x => x.id === p.id);
  if (i >= 0) reglages.profils[i] = p; else reglages.profils.push(p);
  sauver();
  fermerCalque();
  rendreProfils();
  appliquerTout();
  if (pile.includes("reglages")) rendreSection();
}
function supprimerProfil() {
  if (reglages.profils.length <= 1) { son("erreur"); return annoncer(t("profils.supprimer.dernier")); }
  reglages.profils = reglages.profils.filter(p => p.id !== brouillon.id);
  if (reglages.profilActif === brouillon.id) reglages.profilActif = reglages.profils[0].id;
  sauver();
  fermerCalque();
  rendreProfils();
  appliquerTout();
  if (pile.includes("reglages")) rendreSection();
}

function rendreSecurite() {
  const restreint = estRestreint();
  const modes = $("editeur-modes");
  modes.innerHTML = "";
  for (const [mode, cle] of [["tv", "mode.tv"], ["gaming", "mode.jeux"], ["bureau", "mode.bureau"]]) {
    const actif = brouillon.modes?.[mode] !== false;
    modes.append(el("button", {
      class: `option${actif ? " choisie" : ""}`, "data-nav": !restreint, "data-cle": `mode-${mode}`, disabled: restreint,
      onclick: () => {
        const suivant = { tv: true, gaming: true, bureau: true, ...brouillon.modes, [mode]: !actif };
        if (!Object.values(suivant).some(Boolean)) { son("erreur"); return; }
        brouillon.modes = suivant;
        rendreEditeur();
      },
    }, t(cle)));
  }
  $("editeur-restreint").hidden = !restreint;
  // Une restriction ne tient que si on ne peut pas simplement passer sur un profil libre.
  const brouillonRestreint = ["tv", "gaming", "bureau"].some(m => brouillon.modes?.[m] === false);
  const librePasProtege = reglages.profils.some(x => x.id !== brouillon.id && !estRestreint(x) && !x.pin);
  $("editeur-conseil").hidden = restreint || !brouillonRestreint || !librePasProtege;

  const code = $("editeur-code");
  code.innerHTML = "";
  if (!brouillon.pin) {
    code.append(el("button", { class: "option", "data-nav": true, "data-cle": "code-definir", onclick: () => definirCode(brouillon, pin => { brouillon.pin = pin; rendreEditeur(); }) }, t("code.definir")));
  } else {
    code.append(
      el("button", { class: "option choisie", "data-nav": true, "data-cle": "code-changer", onclick: () => definirCode(brouillon, pin => { brouillon.pin = pin; rendreEditeur(); }) }, t("code.changer")),
      !restreint && el("button", { class: "option", "data-nav": true, "data-cle": "code-retirer", onclick: () => { brouillon.pin = null; brouillon.reglagesProteges = false; brouillon.verrouVeille = false; rendreEditeur(); } }, t("code.retirer")));
  }

  const protections = $("editeur-protections");
  protections.innerHTML = "";
  if (brouillon.pin) {
    const bascule = (champ, libelle) => el("div", { class: "ligne-protection" }, el("span", {}, t(libelle)),
      el("div", { class: "options" }, [[true, t("oui")], [false, t("non")]].map(([v, l]) => el("button", {
        class: `option${!!brouillon[champ] === v ? " choisie" : ""}`, "data-nav": true, "data-cle": `${champ}-${v}`,
        onclick: () => { brouillon[champ] = v; rendreEditeur(); },
      }, l))));
    protections.append(bascule("reglagesProteges", "profils.proteger"), bascule("verrouVeille", "profils.verrou.veille"));
  }
}

// ── Code PIN ──────────────────────────────────────────────────────────────
// Un verrou familial, pas un coffre-fort : il empêche d'ouvrir le profil ou les
// réglages d'un autre, il ne chiffre rien. Le code n'est jamais stocké en clair.
//
// C'est hub-menu qui vérifie (→ { type: "pin-verifier", demande, profils, code }) et
// qui hache un nouveau code (→ { type: "pin-creer", demande, code }) : il relit les
// empreintes sur disque et compte les échecs dans un fichier, là où ni une relance du
// menu ni une saisie scriptée depuis le téléphone ne les remettent à zéro. Réponse :
// { type: "pin", demande, resultat: "ok" | "refus" | "bloque" | "hache", attente, pin }.
// La page ne fait que l'afficher. Sans hub-menu (aperçu), elle vérifie elle-même.
const ICONE_CADENAS = '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';
let deverrouilles = new Set();
let verrouAccueil = false;
let demande = null;
// Le blocage annoncé par hub-menu, pour refuser les touches sans l'interroger à chaque chiffre.
let blocageCode = 0;
// Au-delà, hub-menu ne répondra plus (PBKDF2 dure moins d'une seconde) : on le dit.
const DELAI_REPONSE_CODE_MS = 15000;

function sha256(texte) {
  const k = [], h = [];
  let n = 2, trouves = 0;
  const frac = x => (x - Math.floor(x)) * 4294967296 | 0;
  while (trouves < 64) {
    let premier = true;
    for (let d = 2; d * d <= n; d++) if (n % d === 0) { premier = false; break; }
    if (premier) { if (trouves < 8) h[trouves] = frac(n ** (1 / 2)); k[trouves++] = frac(n ** (1 / 3)); }
    n++;
  }
  const octets = [...new TextEncoder().encode(texte)];
  const longueur = octets.length * 8;
  octets.push(0x80);
  while (octets.length % 64 !== 56) octets.push(0);
  for (let i = 7; i >= 0; i--) octets.push(i > 3 ? 0 : (longueur >>> (i * 8)) & 0xff);
  const rot = (x, r) => (x >>> r) | (x << (32 - r));
  for (let bloc = 0; bloc < octets.length; bloc += 64) {
    const w = [];
    for (let i = 0; i < 16; i++) w[i] = octets[bloc + i * 4] << 24 | octets[bloc + i * 4 + 1] << 16 | octets[bloc + i * 4 + 2] << 8 | octets[bloc + i * 4 + 3];
    for (let i = 16; i < 64; i++) {
      const s1 = rot(w[i - 2], 17) ^ rot(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      const s0 = rot(w[i - 15], 7) ^ rot(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let [a, b, c, d, e, f, g, hh] = h;
    for (let i = 0; i < 64; i++) {
      const t1 = (hh + (rot(e, 6) ^ rot(e, 11) ^ rot(e, 25)) + ((e & f) ^ (~e & g)) + k[i] + w[i]) | 0;
      const t2 = ((rot(a, 2) ^ rot(a, 13) ^ rot(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    [a, b, c, d, e, f, g, hh].forEach((v, i) => { h[i] = (h[i] + v) | 0; });
  }
  return h.map(v => (v >>> 0).toString(16).padStart(8, "0")).join("");
}
window.hubSha256 = sha256;

// Mêmes paramètres que hub-menu (PIN_ALGO, PIN_ITERATIONS) : un profil créé en aperçu
// reste lisible une fois installé.
const PIN_ITERATIONS = 600000;
const hex = octets => [...new Uint8Array(octets)].map(o => o.toString(16).padStart(2, "0")).join("");

async function pbkdf2(code, selHex, iterations) {
  const cle = await crypto.subtle.importKey("raw", new TextEncoder().encode(code), "PBKDF2", false, ["deriveBits"]);
  const sel = new Uint8Array(selHex.match(/../g).map(h => parseInt(h, 16)));
  return hex(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: sel, iterations }, cle, 256));
}

let numeroDemandeCode = 0;
const reponsesCode = new Map();
function demanderAuHub(message) {
  const numero = ++numeroDemandeCode;
  return new Promise(resoudre => {
    const minuterie = setTimeout(() => { reponsesCode.delete(numero); resoudre(null); }, DELAI_REPONSE_CODE_MS);
    reponsesCode.set(numero, reponse => { clearTimeout(minuterie); reponsesCode.delete(numero); resoudre(reponse); });
    envoyer({ ...message, demande: numero });
  });
}
function recevoirCode(message) { reponsesCode.get(message.demande)?.(message); }

// Aperçu seulement : aucun fichier à protéger, le compteur vit en mémoire.
const apercuCode = { echecs: 0, jusqua: 0 };
async function verifierCodeLocal(ids, code) {
  if (apercuCode.jusqua > Date.now()) return { resultat: "bloque", attente: Math.ceil((apercuCode.jusqua - Date.now()) / 1000) };
  for (const id of ids) {
    const pin = reglages.profils.find(x => x.id === id)?.pin;
    if (!pin) continue;
    const calcule = pin.algo === "pbkdf2-sha256" ? await pbkdf2(code, pin.sel, pin.iterations) : sha256(`${pin.sel}:${code}`);
    if (calcule === pin.empreinte) { apercuCode.echecs = 0; return { resultat: "ok", profil: id }; }
  }
  if (++apercuCode.echecs < 5) return { resultat: "refus", attente: 0 };
  apercuCode.echecs = 0;
  apercuCode.jusqua = Date.now() + 30000;
  return { resultat: "refus", attente: 30 };
}
function verifierCode(ids, code) {
  return PONT ? demanderAuHub({ type: "pin-verifier", profils: ids, code }) : verifierCodeLocal(ids, code);
}
async function creerCode(code) {
  if (PONT) return (await demanderAuHub({ type: "pin-creer", code }))?.pin || null;
  const sel = hex(crypto.getRandomValues(new Uint8Array(16)));
  return { algo: "pbkdf2-sha256", iterations: PIN_ITERATIONS, sel, empreinte: await pbkdf2(code, sel, PIN_ITERATIONS) };
}

function ouvrirPave(p, titre, detail) {
  $("code-titre").textContent = titre;
  $("code-detail").textContent = detail;
  habillerAvatar($("code-avatar"), p);
  const pave = $("code-pave");
  pave.innerHTML = "";
  for (const ch of ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✕"]) {
    pave.append(el("button", {
      class: "touche-code", "data-nav": true, "data-cle": `chiffre-${ch}`,
      onclick: () => ch === "⌫" ? effacerChiffre() : ch === "✕" ? annulerCode() : taperChiffre(ch),
    }, ch));
  }
  majPoints();
  ouvrirCalque("code");
  definirFocus(pave.querySelector('[data-cle="chiffre-5"]'), true);
}

function demanderCode(p, reussite, { detail = null, annuler = null } = {}) {
  demande = { p, mode: "verifier", saisie: "", reussite, annuler };
  ouvrirPave(p, t("code.titre", { nom: p.nom }), detail || t("code.saisir"));
}
function definirCode(p, reussite) {
  demande = { p, mode: "nouveau", saisie: "", reussite };
  ouvrirPave(p, p.nom || t("profils.nouveau"), t("code.nouveau"));
}

function majPoints() {
  [...$("code-points").children].forEach((point, i) => point.classList.toggle("plein", i < (demande?.saisie.length || 0)));
}
function taperChiffre(ch) {
  if (!demande || demande.enCours) return;
  if (blocageCode > Date.now()) {
    son("erreur");
    $("code-detail").textContent = t("code.bloque", { s: Math.ceil((blocageCode - Date.now()) / 1000) });
    return;
  }
  if (demande.saisie.length >= 4) return;
  demande.saisie += ch;
  son("deplacer");
  majPoints();
  if (demande.saisie.length === 4) setTimeout(validerCode, 180);
}
function effacerChiffre() {
  if (!demande || demande.enCours) return;
  demande.saisie = demande.saisie.slice(0, -1);
  majPoints();
}
function refuserCode(message) {
  son("erreur");
  $("code-points").animate([{ translate: "0" }, { translate: "-.76rem" }, { translate: ".76rem" }, { translate: "-.38rem" }, { translate: "0" }], { duration: 380 });
  $("code-detail").textContent = message;
  demande.saisie = "";
  majPoints();
}
// La demande peut avoir été annulée (Échap) ou remplacée pendant qu'on attendait hub-menu.
async function attendreHub(travail) {
  const enCours = demande;
  enCours.enCours = true;
  const reponse = await travail;
  if (demande !== enCours) return undefined;
  enCours.enCours = false;
  return reponse;
}

async function validerCode() {
  if (!demande || demande.enCours) return;
  const { p, mode, saisie } = demande;
  if (mode === "verifier") {
    // demande.profils : un code accepté de plusieurs profils (n'importe quel parent).
    const ids = demande.profils || (p.pin ? [p.id] : []);
    const reponse = await attendreHub(verifierCode(ids, saisie));
    if (reponse === undefined) return;
    if (reponse?.resultat === "ok") {
      // Empreinte refaite par hub-menu (ancien format) : la garder, sinon le prochain
      // enregistrement des réglages réécrirait l'ancienne.
      const ouvert = reglages.profils.find(x => x.id === reponse.profil);
      if (ouvert && reponse.pin) ouvert.pin = reponse.pin;
      blocageCode = 0;
      deverrouilles.add(p.id);
      if (p.id === profil().id) { verrouAccueil = false; document.body.classList.remove("verrouille"); }
      const { reussite } = demande;
      demande = null;
      son("ok");
      fermerCalque();
      reussite?.();
      return;
    }
    if (!reponse) return refuserCode(t("code.indisponible"));
    if (reponse.attente > 0) {
      blocageCode = Date.now() + reponse.attente * 1000;
      return refuserCode(t("code.bloque", { s: reponse.attente }));
    }
    return refuserCode(t("code.faux"));
  }
  if (mode === "nouveau") {
    demande.premier = saisie;
    demande.mode = "confirmer";
    demande.saisie = "";
    majPoints();
    $("code-detail").textContent = t("code.confirmer");
    return;
  }
  if (saisie !== demande.premier) {
    demande.mode = "nouveau";
    return refuserCode(t("code.different"));
  }
  const pin = await attendreHub(creerCode(saisie));
  if (pin === undefined) return;
  if (!pin) {
    demande.mode = "nouveau";
    return refuserCode(t("code.indisponible"));
  }
  const { reussite } = demande;
  demande = null;
  deverrouilles.add(p.id);
  fermerCalque();
  annoncer(t("code.defini"));
  reussite?.(pin);
}
function annulerCode() {
  const annuler = demande?.annuler;
  demande = null;
  fermerCalque();
  annuler?.();
}

function verrouillerAccueil() {
  if (!profil().pin) return;
  deverrouilles.delete(profil().id);
  verrouAccueil = true;
  document.body.classList.add("verrouille");
}
function exigerDeverrouillage() {
  if (!verrouAccueil || pile.at(-1) === "code") return;
  demanderCode(profil(), null, { annuler: () => setTimeout(() => { if (verrouAccueil) ACTIONS.profils(); }, 0) });
}

// ── Clavier à l'écran ─────────────────────────────────────────────────────
let saisie = null;
const DISPOSITIONS = {
  fr: ["1234567890", "azertyuiop", "qsdfghjklm", "wxcvbnéè'-"],
  en: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm.,-"],
};
function ouvrirClavier(libelle, valeur, rappel) {
  saisie = { valeur, rappel };
  $("libelle-saisie").textContent = libelle;
  const zone = $("touches-clavier");
  zone.innerHTML = "";
  for (const rangee of DISPOSITIONS[profil().langue] || DISPOSITIONS.fr) {
    for (const lettre of rangee) {
      zone.append(el("button", { class: "touche", "data-nav": true, "data-cle": `touche-${lettre}`, onclick: () => ecrire(lettre) }, lettre.toUpperCase()));
    }
  }
  zone.append(
    el("button", { class: "touche large", "data-nav": true, onclick: () => ecrire(" ") }, t("clavier.espace")),
    el("button", { class: "touche moyenne", "data-nav": true, onclick: () => ecrire(null) }, "⌫"),
    el("button", { class: "touche moyenne", "data-nav": true, onclick: () => { saisie.valeur = ""; majSaisie(); } }, t("clavier.effacer")),
    el("button", { class: "touche large", "data-nav": true, "data-cle": "valider", onclick: validerSaisie }, t("clavier.valider")));
  majSaisie();
  ouvrirCalque("clavier");
  definirFocus(zone.querySelector('[data-cle="touche-a"]') || zone.firstChild, true);
}
function ecrire(lettre) {
  if (lettre === null) saisie.valeur = saisie.valeur.slice(0, -1);
  else if (saisie.valeur.length < 32) saisie.valeur += saisie.valeur.length === 0 ? lettre.toUpperCase() : lettre;
  majSaisie();
}
function majSaisie() { $("texte-saisie").textContent = saisie.valeur; }
function validerSaisie() {
  const { valeur, rappel } = saisie;
  saisie = null;
  fermerCalque();
  rappel(valeur);
}

// ── Réglages ─────────────────────────────────────────────────────────────
const SECTIONS = [
  ["apparence", '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/>'],
  ["fond", '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="16" cy="8.5" r="1.5"/>'],
  ["profils", '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14.2a6.5 6.5 0 0 1 3.5 5.8"/>'],
  ["langue", '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'],
  ["voix", '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>'],
  ["enceinte", '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><circle cx="12" cy="14.5" r="3.2"/><circle cx="12" cy="7" r="1.2"/>'],
  ["telecommande", '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>'],
  ["services", '<rect x="3" y="4" width="18" height="13" rx="2.5"/><path d="m10.5 8 4 2.5-4 2.5zM8 21h8"/>'],
  ["meteo", '<path d="M7 18h10a4 4 0 0 0 .5-8A5.5 5.5 0 0 0 7 11a3.5 3.5 0 0 0 0 7z"/>'],
  ["veille", '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>'],
  ["raccourcis", '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h1M10.5 10h1M14.5 10h1M8 14h8"/>'],
  ["apropos", '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>'],
];
let sectionCourante = "apparence";
let infosMachine = null;

function rendreReglages() {
  const sommaire = $("sommaire");
  sommaire.querySelectorAll(".entree").forEach(e => e.remove());
  const sections = [...SECTIONS];
  for (const x of extensions.sections) {
    const i = sections.findIndex(([id]) => id === x.apres);
    sections.splice(i < 0 ? sections.length : i + 1, 0, [x.id, x.icone]);
  }
  for (const [id, icone] of sections) {
    sommaire.append(el("button", { class: "entree", "data-nav": true, "data-section": id, "data-cle": `section-${id}` },
      el("span", { html: `<svg viewBox="0 0 24 24">${icone}</svg>` }), t(`section.${id}`)));
  }
  focusParCalque.reglages = sommaire.querySelector(`[data-section="${sectionCourante}"]`);
  rendreSection(false);
  if (!infosMachine) envoyer({ type: "infos" });
  envoyer({ type: "maj-etat" });
}

function rangee(titre, aide, controle, large = false, commun = false) {
  return el("div", { class: `rangee${large ? " large" : ""}` },
    el("div", {}, el("div", { class: "titre" }, titre, commun && el("span", { class: "portee-hub" }, t("portee.hub"))), aide && el("div", { class: "aide" }, aide)),
    controle);
}
function options(cle, liste, valeur, changer) {
  return el("div", { class: "options" }, liste.map(([v, libelle]) => el("button", {
    class: `option${String(v) === String(valeur) ? " choisie" : ""}`, "data-nav": true, "data-cle": `${cle}-${v}`,
    onclick: () => { changer(v); sauver(); appliquerTout(); rendreSection(); son("ok"); },
  }, libelle)));
}

function rendreSection(garderFocus = true) {
  const zone = $("contenu-reglages");
  const cle = garderFocus ? courant?.dataset.cle : null;
  zone.innerHTML = "";
  zone.style.transform = "";
  document.querySelectorAll("#sommaire .entree").forEach(e => e.classList.toggle("courante", e.dataset.section === sectionCourante));
  const p = profil(), s = reglages.systeme;
  zone.append(el("h3", {}, t(`section.${sectionCourante}`)));
  // Dire à qui s'applique ce qu'on règle : chaque profil garde ses propres choix.
  if (["apparence", "fond", "langue", "voix", "services", "meteo", "veille"].includes(sectionCourante)) {
    zone.append(el("div", { class: "portee" }, avatar(p), t("portee.profil", { nom: p.nom })));
  }

  switch (sectionCourante) {
    case "apparence":
      zone.append(
        rangee(t("theme"), p.theme === "auto" ? t("theme.auto.detail") : null,
          options("theme", [["sombre", t("theme.sombre")], ["clair", t("theme.clair")], ["auto", t("theme.auto")]], p.theme, v => { p.theme = v; })),
        rangee(t("animations"), null,
          options("animations", [["completes", t("animations.completes")], ["reduites", t("animations.reduites")]], p.animations, v => { p.animations = v; })),
        rangee(t("taille"), t("taille.detail"),
          options("echelle", [[.9, "S"], [1, "M"], [1.1, "L"], [1.2, "XL"]], s.echelle, v => { s.echelle = Number(v); }), false, true),
        rangee(t("habillage"), t("habillage.detail"),
          options("habillage", [[true, t("oui")], [false, t("habillage.origine")]], s.habillage !== false, v => { s.habillage = v === true || v === "true"; }), false, true),
        rangee(t("zone"), null,
          options("marge", [[2, "2 %"], [5, "5 %"], [8, "8 %"]], s.marge, v => { s.marge = Number(v); }), false, true));
      break;

    case "fond": {
      // D'abord le motif, puis sa couleur. Chaque vignette est le vrai dessin, figé, dans
      // le thème affiché : on choisit ce qu'on verra, pas un pictogramme.
      const theme = racine.dataset.theme === "clair" ? "clair" : "sombre";
      const couleur = COULEURS_FOND.includes(p.fond) ? p.fond : null;
      const motif = ["minimal", "photos"].includes(p.fond) ? p.fond : motifDuProfil(p);
      const valider = changer => { changer(); sauver(); appliquerTout(); rendreSection(); son("ok"); };
      const vignette = (cle, choisie, libelle, apercu, onclick) => el("button", {
        class: `vignette-fond${choisie ? " choisie" : ""}`, "data-nav": true, "data-cle": cle, onclick,
      }, apercu, el("span", { class: "libelle" }, libelle));
      const motifs = el("div", { class: "vignettes motifs" });
      for (const m of [...MOTIFS, "minimal", "photos"]) {
        let apercu;
        if (m === "photos") apercu = el("span", { class: "apercu-photos", html: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m3 16 5-5 4 4 3-3 6 6"/></svg>' });
        else apercu = apercuFond(m, couleur || "aurore", theme);
        if (m === "cinema") apercu = el("span", { class: "apercu-cinema" }, apercu, el("span", { class: "apercu-filigrane", html: $("filigrane").innerHTML }));
        motifs.append(vignette(`motif-${m}`, motif === m, t(m === "minimal" || m === "photos" ? `fond.${m}` : `motif.${m}`), apercu, () => {
          if (m === "photos" && !(INITIAL.photos || []).length) { son("erreur"); return annoncer(t("fond.photos.aucune")); }
          valider(() => {
            if (m === "minimal" || m === "photos") p.fond = m;
            else { p.motif = m; if (!couleur) p.fond = "aurore"; }
          });
        }));
      }
      // Les couleurs montrent le motif animé du profil, même quand « minimal » ou « photos »
      // est choisi : en prendre une y revient.
      const couleurs = el("div", { class: "vignettes couleurs" });
      const motifCouleurs = motifDuProfil(p);
      for (const c of COULEURS_FOND) {
        const apercu = apercuFond(motifCouleurs, c, theme);
        couleurs.append(vignette(`couleur-${c}`, couleur === c, t(`fond.${c}`), apercu, () => valider(() => { p.fond = c; p.motif = motifCouleurs; })));
      }
      zone.append(
        el("div", { class: "sous-titre" }, t("fond.motif")),
        motifs,
        el("div", { class: "aide" }, t("fond.photos.detail")),
        el("div", { class: "sous-titre" }, t("fond.couleur")),
        ...(couleur ? [] : [el("div", { class: "aide" }, t("fond.couleur.aide", { motif: t(`motif.${motifCouleurs}`) }))]),
        couleurs,
        rangee(t("fond.couleur.mode"), t("fond.couleur.mode.detail"), options("teinte", [[true, t("oui")], [false, t("non")]], p.teinteMode, v => { p.teinteMode = v === true || v === "true"; })));
      break;
    }

    case "profils":
      if (estRestreint()) {
        zone.append(el("div", { class: "aide" }, t("profils.restreint")));
        break;
      }
      for (const x of reglages.profils) {
        const couleur = COULEURS_PROFIL[x.couleur] || COULEURS_PROFIL.turquoise;
        zone.append(rangee(
          el("span", { style: "display:flex;align-items:center;gap:.68rem" }, avatar(x), x.nom, x.pin && el("span", { class: "cadenas", html: ICONE_CADENAS }), x.id === reglages.profilActif ? " ✓" : ""),
          null,
          el("div", { class: "options" },
            x.id !== reglages.profilActif && el("button", { class: "option", "data-nav": true, "data-cle": `utiliser-${x.id}`, onclick: () => { choisirProfil(x.id); } }, "✓"),
            el("button", { class: "option", "data-nav": true, "data-cle": `modifier-${x.id}`, onclick: () => ouvrirEditeur(x) }, "✎"))));
      }
      zone.append(
        el("div", { class: "options", style: "justify-content:flex-start" },
          el("button", { class: "option", "data-nav": true, "data-cle": "ajouter-profil", onclick: () => ouvrirEditeur(null) }, `+ ${t("profils.ajouter")}`)),
        rangee(t("profils.demarrage"), null, options("demander", [[true, t("oui")], [false, t("non")]], s.demanderProfil, v => { s.demanderProfil = v === true || v === "true"; }), false, true));
      break;

    case "langue":
      zone.append(
        rangee(t("langue"), null, options("langue", LANGUES.map(l => [l.code, l.nom]), p.langue, v => { p.langue = v; })),
        rangee(t("horloge"), null, options("horloge", [["24", t("horloge.24")], ["12", t("horloge.12")]], p.horloge, v => { p.horloge = v; })));
      break;

    case "voix":
      zone.append(
        rangee(t("voix"), `${t("voix.detail")}${etatVoix.micro === false ? " — " + t("voix.micro.absent") : ""}`,
          options("voix", [[true, t("voix.active")], [false, t("voix.inactive")]], s.voix, v => { s.voix = v === true || v === "true"; }), false, true),
        rangee(t("sons"), null, options("sons", [[true, t("oui")], [false, t("non")]], sonsActifs(), v => { p.sons = v === true || v === "true"; })));
      break;

    case "services": {
      // Un profil restreint ne rallume pas lui-même ce qu'on lui a masqué ; les modes
      // interdits emportent leurs services (pas de Netflix sans le mode TV).
      const restreint = estRestreint();
      if (restreint) zone.append(el("div", { class: "aide" }, t("services.restreint")));
      for (const categorie of ["streaming", "jeux"]) {
        zone.append(el("div", { class: "sous-titre" }, t(`services.${categorie}`)));
        for (const sv of SERVICES.filter(x => x.categorie === categorie)) {
          const autorise = modeAutorise(modeDuService(sv));
          const actif = p.services?.[sv.id] !== false;
          const aide = [t(`service.qualite.${sv.id}`), !autorise && t("services.mode.interdit"),
            sv.appli && !serviceInstallable(sv) && t("services.non.installe")].filter(Boolean).join(" — ");
          zone.append(rangee(
            el("span", { class: "titre-service" }, el("span", { class: "mini-service", style: `--fond:${sv.fond};--encre:${sv.encre}` }, el("span", { style: sv.style }, sv.nom))),
            aide,
            restreint || !autorise ? el("div", { class: "options" }, el("span", { class: "etat-fige" }, t(actif && autorise ? "oui" : "non")))
              : options(`service-${sv.id}`, [[true, t("services.afficher")], [false, t("services.masquer")]], actif,
                v => { p.services = { ...p.services, [sv.id]: v === true || v === "true" }; })));
        }
      }
      zone.append(el("div", { class: "aide" }, t("services.qualite.detail")));
      break;
    }

    case "meteo":
      zone.append(
        rangee(t("meteo.afficher"), meteoSituee() ? null : t("meteo.sans.ville"), options("meteo", [[true, t("oui")], [false, t("non")]], meteoProfil().active && meteoSituee(), v => {
          p.meteo = { ...meteoProfil(), active: v === true || v === "true" };
          chargerMeteo();
          // Activer sans ville ne montrerait rien : on la demande tout de suite.
          if (p.meteo.active && !meteoSituee()) setTimeout(chercherVille, 0);
        })),
        rangee(t("meteo.ville"), meteoProfil().ville || t("meteo.sans.ville"), el("div", { class: "options" },
          el("button", { class: "option", "data-nav": true, "data-cle": "chercher-ville", onclick: chercherVille }, t("meteo.chercher")))));
      break;

    case "veille": {
      const reste = minuteurFin ? Math.max(0, Math.round((minuteurFin - Date.now()) / 60000)) : 0;
      zone.append(
        rangee(t("veille"), t("veille.detail"),
          options("veille", [[0, t("veille.jamais")], [5, "5 min"], [10, "10 min"], [30, "30 min"]], veilleMinutes(), v => { p.veille = Number(v); })),
        rangee(t("minuteur"), minuteurFin ? `${t("minuteur.actif")} ${reste} min` : t("minuteur.detail"),
          el("div", { class: "options" }, [[0, t("minuteur.aucun")], [15, "15 min"], [30, "30 min"], [60, "1 h"], [90, "1 h 30"]].map(([v, libelle]) =>
            el("button", {
              class: `option${(v === 0 && !minuteurFin) ? " choisie" : ""}`, "data-nav": true, "data-cle": `minuteur-${v}`,
              onclick: () => programmerMinuteur(v),
            }, libelle))), false, true));
      break;
    }

    case "enceinte":
      zone.append(...contenuEnceinte());
      break;

    case "telecommande":
      zone.append(contenuTelecommande());
      break;

    case "raccourcis":
      zone.append(contenuRaccourcis());
      break;

    case "apropos": {
      const i = infosMachine || {};
      const info = (etiquette, valeur) => el("div", { class: "info" }, el("div", { class: "etiquette" }, etiquette), el("div", { class: "valeur" }, valeur ?? "—"));
      zone.append(el("div", { class: "infos" },
        info(t("apropos.machine"), i.machine),
        info(t("apropos.systeme"), i.systeme),
        info(t("apropos.reseau"), i.adresse ? t("reseau.connecte") : t("reseau.deconnecte")),
        info(t("apropos.adresse"), i.adresse),
        info(t("apropos.allume"), i.allumeDepuis),
        info(t("apropos.disque"), i.disqueLibre),
        info(t("apropos.version"), i.version)),
        contenuMiseAJour(),
        el("div", { class: "options", style: "justify-content:flex-start;margin-top:.3rem" },
          el("button", { class: "option", "data-nav": true, "data-cle": "fermer-reglages", "data-action": "fermer" }, t("fermer"))));
      break;
    }
  }

  extensions.contenus[sectionCourante]?.(zone);
  majAppairage();

  if (cle && pile.at(-1) === "reglages") {
    const retrouve = zone.querySelector(`[data-cle="${CSS.escape(cle)}"]`);
    if (retrouve) definirFocus(retrouve, true);
  }
}

// ── Mise à jour ───────────────────────────────────────────────────────────
const maj = { verification: null, etat: null, enCours: false, suivie: false };
const ETAPES_MAJ = ["verification", "telechargement", "tests", "installation", "terminee"];

function contenuMiseAJour() {
  const { verification: v, etat: e } = maj;
  let texte = t("maj.detail"), boutons = [];
  const actif = e && !["terminee", "echec", "a-jour"].includes(e.etape);
  if (actif) {
    texte = t(`maj.etape.${e.etape}`, { v: e.version || "" });
  } else if (e?.etape === "terminee") {
    texte = t("maj.terminee", { v: e.version || "" });
  } else if (e?.etape === "echec") {
    // Une raison que ce menu ne connaît pas (hub-mise-a-jour plus récent) : le message
    // générique plutôt que la clé de traduction brute.
    const raison = `maj.echec.${e.raison || "installation"}`;
    texte = t(e.retour ? "maj.echec.retour" : raison in TEXTES.fr ? raison : "maj.echec.installation");
  } else if (maj.enCours) {
    texte = t("maj.recherche");
  } else if (v?.erreur) {
    texte = t(v.erreur === "configuration" ? "maj.sans.source" : "maj.injoignable");
  } else if (v) {
    // verifiable absent (ancien hub-mise-a-jour) : installable, comme avant.
    texte = !v.disponible ? t("maj.a.jour") : v.verifiable === false ? t("maj.non.verifiable", { v: v.distant }) : t("maj.disponible", { v: v.distant });
  }
  // Qui a signé la version en cours d'installation : dit discrètement, pas une étape de plus.
  if (typeof e?.signataire === "string" && e.signataire && ["tests", "installation", "terminee"].includes(e.etape)) {
    texte = `${texte} (${t("maj.signee", { s: e.signataire })})`;
  }
  if (!actif && !maj.enCours) {
    boutons.push(el("button", { class: "option", "data-nav": true, "data-cle": "maj-verifier", onclick: () => { maj.enCours = true; maj.etat = null; envoyer({ type: "maj-verifier" }); rendreSection(); } }, t("maj.rechercher")));
    if (v?.disponible && v.verifiable !== false && e?.etape !== "terminee") {
      boutons.push(el("button", { class: "option choisie", "data-nav": true, "data-cle": "maj-appliquer", onclick: () => { maj.etat = { etape: "verification" }; maj.suivie = true; envoyer({ type: "maj-appliquer" }); rendreSection(); } }, t("maj.installer")));
    }
  }
  const progression = actif ? el("div", { class: "barre-maj" }, el("i", { style: `width:${(ETAPES_MAJ.indexOf(e.etape) + 1) / ETAPES_MAJ.length * 100}%` })) : null;
  return rangee(t("maj.titre"), el("span", {}, texte, progression), el("div", { class: "options" }, boutons));
}

function recevoirMiseAJour(message) {
  if ("verification" in message) { maj.verification = message.verification; maj.enCours = false; }
  if ("etat" in message) maj.etat = message.etat;
  const actif = maj.etat && !["terminee", "echec", "a-jour"].includes(maj.etat.etape);
  if (actif) maj.suivie = true;
  // Ne relancer que si l'on a vu cette mise à jour se dérouler : un état « terminee »
  // resté d'une mise à jour passée ne doit pas faire redémarrer le menu en boucle.
  if (maj.etat?.etape === "terminee" && maj.suivie) {
    maj.suivie = false;
    annoncer(t("maj.terminee", { v: maj.etat.version || "" }));
    setTimeout(() => envoyer({ type: "relancer" }), 4000);
  }
  if (pile.at(-1) === "reglages" && sectionCourante === "apropos") rendreSection();
}

// ── Télécommande sur téléphone ────────────────────────────────────────────
let telecommande = INITIAL.telecommande || null;

// qrcode.js est installé à côté de la page ; dans le dépôt, il vit avec la télécommande.
(function chargerQr() {
  const script = document.createElement("script");
  script.src = "qrcode.js";
  script.onerror = () => {
    const secours = document.createElement("script");
    secours.src = "../telecommande/qrcode.js";
    secours.onload = () => { if (pile.at(-1) === "reglages" && sectionCourante === "telecommande") rendreSection(); };
    document.head.append(secours);
  };
  document.head.append(script);
})();

// L'écran d'appairage, ligne par ligne : la clé de l'état publié par hub-telecommande
// (relayé par hub-menu, CHAMPS_TELECOMMANDE), et sa mise en forme à partir de la valeur
// et de l'état entier. Une ligne dont la valeur manque n'est pas affichée, sauf
// « toujours ». Un champ de plus au contrat = une entrée de plus ici. Tout passe en
// texte : ces valeurs viennent d'un autre service.
const LIGNES_APPAIRAGE = [
  { etape: "telecommande.etape1" },
  { etape: "telecommande.etape2" },
  { etape: "telecommande.etape3" },
  // Le service n'accepte un téléphone que fenêtre ouverte : avant, un code serait refusé.
  { cle: "code", rendre: (v, e) => e.appairageOuvert === true
    ? el("div", { class: "code-appairage" }, String(v).replace(/(\d{3})(\d{3})/, "$1 $2"))
    : el("div", { class: "code-appairage attente" }, t("telecommande.ouverture")) },
  { cle: "empreinteRacineCourte", rendre: v => el("div", { class: "empreinte-appairage" },
    el("div", { class: "aide" }, t("telecommande.empreinte.courte")),
    el("div", { class: "empreinte-courte" }, v)) },
  { cle: "expire", toujours: true, rendre: (_, e) => el("div", { class: "aide", id: "telecommande-expire" }, e.appairageOuvert === true ? texteExpiration() : "") },
  { cle: "url", rendre: v => el("div", { class: "aide url" }, v) },
  { cle: "empreinteRacine", rendre: v => el("div", { class: "empreinte-paires", title: t("telecommande.empreinte") },
    groupesEmpreinte(v).map(ligne => el("div", {}, ligne))) },
  { cle: "telephones", toujours: true, rendre: v => el("div", { class: "aide" }, t("telecommande.telephones", { n: v ?? 0 })) },
];

// « AB:CD:… » (32 paires) → quatre lignes de huit paires, coupées en deux groupes de
// quatre : on compare sur le téléphone groupe par groupe, sans perdre sa ligne.
function groupesEmpreinte(empreinte) {
  const paires = String(empreinte).split(":");
  const lignes = [];
  for (let i = 0; i < paires.length; i += 8) {
    const huit = paires.slice(i, i + 8);
    lignes.push([huit.slice(0, 4).join(" "), huit.slice(4).join(" ")].filter(Boolean).join("   "));
  }
  return lignes;
}

function contenuTelecommande() {
  if (!telecommande) {
    return rangee(t("telecommande.absente"), t("telecommande.absente.detail"), null, true);
  }
  const qr = el("div", { class: "qr" });
  if (window.qrSvg) qr.innerHTML = window.qrSvg(telecommande.url, { sombre: "#000", clair: "#fff", marge: 3 });
  let numero = 0;
  const lignes = LIGNES_APPAIRAGE.map(l => {
    if (l.etape) return el("div", { class: "etape" }, el("b", {}, String(++numero)), t(l.etape));
    const valeur = telecommande[l.cle];
    return valeur == null && !l.toujours ? null : l.rendre(valeur, telecommande);
  });
  return el("div", { class: "appairage" }, qr, el("div", { class: "etapes" }, lignes));
}
function texteExpiration() {
  if (!telecommande?.expire) return "";
  const s = Math.max(0, Math.round((telecommande.expire - Date.now()) / 1000));
  return t("telecommande.expire", { m: Math.floor(s / 60), s: String(s % 60).padStart(2, "0") });
}
setInterval(() => {
  const e = document.getElementById("telecommande-expire");
  if (e && telecommande?.appairageOuvert === true) e.textContent = texteExpiration();
}, 1000);

// hub-telecommande n'ouvre l'appairage que pendant que cet écran est à la TV : on dit à
// hub-menu quand il apparaît et disparaît (changement de section, fermeture, mode ambiant).
let appairageAffiche = false;
function majAppairage() {
  const affiche = pile.at(-1) === "reglages" && sectionCourante === "telecommande";
  if (affiche === appairageAffiche) return;
  appairageAffiche = affiche;
  envoyer({ type: "appairage", affiche });
}

function recevoirTelecommande(etat) {
  const avant = telecommande;
  telecommande = etat;
  if (etat?.appairageLe && etat.appairageLe !== avant?.appairageLe) {
    son("ok");
    annoncer(t("telecommande.reliee"));
  }
  if (pile.at(-1) === "reglages" && sectionCourante === "telecommande") rendreSection();
}

function contenuRaccourcis() {
  const ligne = (touches, libelle) => el("div", { class: "raccourci" }, el("span", {}, t(libelle)),
    el("span", { class: "touches" }, touches.map(k => el("kbd", { class: k.length === 1 && "←→↑↓".includes(k) ? "fleche" : null }, k))));
  return el("div", {},
    el("div", { class: "raccourcis" },
      ligne(["←", "→", "↑", "↓"], "rc.naviguer"),
      ligne(["OK"], "rc.ouvrir"),
      ligne([t("touche.echap")], "rc.retour"),
      ligne(["1", "2", "3"], "rc.modes"),
      ligne(["R"], "rc.reglages"),
      ligne(["P"], "rc.profils"),
      ligne(["M"], "rc.meteo"),
      ligne(["T"], "rc.theme"),
      ligne(["L"], "rc.langue"),
      ligne(["A"], "rc.ambiant"),
      ligne(["?"], "rc.aide"),
      ligne(["E"], "rc.eteindre"),
      ligne(["F12"], "rc.kodi"),
      ligne(["F12", t("touche.guide")], "rc.service")),
    el("div", { class: "sous-titre" }, t("raccourcis.voix")),
    el("div", { class: "raccourcis" }, ["vc.tv", "vc.service", "vc.jeux", "vc.bureau", "vc.retour", "vc.reglages", "vc.theme"].map(k => el("div", { class: "phrase" }, t(k)))));
}

function rendreAide() {
  const zone = $("contenu-aide");
  zone.innerHTML = "";
  zone.append(
    el("div", { style: "display:flex;align-items:center;justify-content:space-between" },
      el("h3", {}, t("raccourcis.titre")),
      el("button", { class: "option", "data-nav": true, "data-action": "fermer" }, t("fermer"))),
    contenuRaccourcis());
}

// ── Minuteur de mise en veille ────────────────────────────────────────────
let minuteurFin = INITIAL.minuteurFin || null;
function programmerMinuteur(minutes) {
  if (PONT) envoyer({ type: "minuteur", minutes });
  else recevoirMinuteur(minutes ? Date.now() + minutes * 60000 : null);
  annoncer(minutes ? `${t("minuteur.regle")} ${minutes} min` : t("minuteur.annule"));
}
function recevoirMinuteur(fin) {
  minuteurFin = fin && fin > Date.now() ? fin : null;
  majMinuteur();
  if (pile.at(-1) === "reglages" && sectionCourante === "veille") rendreSection();
}
function majMinuteur() {
  const bouton = $("bouton-minuteur");
  if (minuteurFin && minuteurFin <= Date.now()) minuteurFin = null;
  bouton.hidden = !minuteurFin;
  if (minuteurFin) $("minuteur-texte").textContent = `${Math.ceil((minuteurFin - Date.now()) / 60000)} min`;
}

// ── Voix ──────────────────────────────────────────────────────────────────
const etatVoix = { micro: null };
let minuterieBulle;
function bulle(texte, duree = 0, ecoute = false) {
  const b = $("bulle-voix");
  $("bulle-texte").textContent = texte;
  b.querySelector(".ondes").hidden = !ecoute;
  b.classList.add("visible");
  clearTimeout(minuterieBulle);
  if (duree) minuterieBulle = setTimeout(() => b.classList.remove("visible"), duree);
}
function recevoirVoix(etat, texte) {
  const pastille = $("voix-pastille");
  pastille.hidden = !reglages.systeme.voix;
  reveiller();
  if (etat === "eveil") { pastille.classList.add("eveil"); bulle(t("voix.ecoute"), 0, true); son("deplacer"); }
  else if (etat === "entendu") { bulle(`« ${texte} »`, 2200); }
  else if (etat === "incompris") { pastille.classList.remove("eveil"); bulle(t("voix.incompris"), 2200); son("erreur"); }
  else if (etat === "repos") { pastille.classList.remove("eveil"); $("voix-texte").textContent = "HUB"; setTimeout(() => $("bulle-voix").classList.remove("visible"), 1500); }
  else if (etat === "micro-absent") { etatVoix.micro = false; pastille.classList.add("absent"); }
  else if (etat === "micro-present") { etatVoix.micro = true; pastille.classList.remove("absent"); }
}

function commande(nom) {
  reveiller();
  if (verrou) return;
  if (pile.at(-1) === "code") {
    if (nom === "retour") return annulerCode();
    if (["gauche", "droite", "haut", "bas"].includes(nom)) return deplacer(nom);
    if (nom === "ok") return courant?.click();
    return;
  }
  if (verrouAccueil) return exigerDeverrouillage();
  const modes = { tv: 0, gaming: 1, bureau: 2 };
  if (nom in modes && !modeAutorise(nom)) { son("erreur"); return annoncer(t("mode.interdit")); }
  if (nom.startsWith("web:")) {
    const s = SERVICES.find(x => x.id === nom.slice(4));
    if (!s) return;
    fermerTout();
    const tuile = document.querySelector(`[data-cle="service-${s.id}"]`);
    if (tuile && pile.at(-1) === "accueil") definirFocus(tuile, true);
    return lancerService(tuile, s);
  }
  if (nom in modes) {
    fermerTout();
    definirFocus(onglets[modes[nom]], true);
    return lancer(onglets[modes[nom]]);
  }
  if (nom.startsWith("theme:")) {
    profil().theme = nom.slice(6) === "clair" ? "clair" : "sombre";
    sauver(); appliquerTout();
    return;
  }
  const directions = { gauche: 1, droite: 1, haut: 1, bas: 1 };
  if (nom in directions) return deplacer(nom);
  if (nom === "ok") return courant?.click();
  if (nom === "retour") return fermerCalque();
  if (nom === "eteindre") { fermerTout(); return ACTIONS.arret(); }
  if (nom === "reglages" || nom === "aide" || nom === "meteo" || nom === "profils") { fermerTout(); return ACTIONS[nom](); }
}

// ── Mode ambiant ──────────────────────────────────────────────────────────
let derniereAction = Date.now();
function reveiller() {
  derniereAction = Date.now();
  if (!document.body.classList.contains("ambiant")) return false;
  document.body.classList.remove("ambiant");
  extensions.ambiant.forEach(f => f(false));
  relancerFond();
  if (verrouAccueil) setTimeout(exigerDeverrouillage, 0);
  return true;
}
function entrerAmbiant() {
  if (document.body.classList.contains("ambiant") || verrou) return;
  fermerTout();
  if (profil().verrouVeille) verrouillerAccueil();
  document.body.classList.add("ambiant");
  extensions.ambiant.forEach(f => f(true));
  relancerFond();
}
setInterval(() => {
  const minutes = veilleMinutes();
  if (minutes && Date.now() - derniereAction > minutes * 60000) entrerAmbiant();
  // L'horloge du mode ambiant glisse doucement : aucune image fixe ne marque l'écran.
  if (document.body.classList.contains("ambiant")) {
    $("ambiant-corps").style.transform = `translate(${(Math.random() - .5) * 6}rem, ${(Math.random() - .5) * 3.8}rem)`;
  }
}, 30000);

// ── Clavier, manette, souris ──────────────────────────────────────────────
const DIRECTIONS = { ArrowLeft: "gauche", ArrowRight: "droite", ArrowUp: "haut", ArrowDown: "bas" };

addEventListener("keydown", e => {
  toucheRepetee = e.repeat;
  document.body.classList.remove("souris");
  if (reveiller()) { e.preventDefault(); return; }
  if (verrou) return;
  const haut = pile.at(-1);

  // Sur un clavier AZERTY, la rangée du haut envoie « & é " » sans Maj : on lit la touche
  // physique (Digit1…) en plus du caractère.
  const chiffre = /^[0-9]$/.test(e.key) ? e.key : (/^(Digit|Numpad)([0-9])$/.exec(e.code || "") || [])[2];
  if (haut === "code") {
    if (chiffre) { e.preventDefault(); return taperChiffre(chiffre); }
    if (e.key === "Backspace") { e.preventDefault(); return effacerChiffre(); }
    if (e.key === "Escape") { e.preventDefault(); return annulerCode(); }
    if (DIRECTIONS[e.key]) { e.preventDefault(); return deplacer(DIRECTIONS[e.key]); }
    if (e.key === "Enter") { e.preventDefault(); return courant?.click(); }
    return;
  }
  if (verrouAccueil && haut === "accueil") { e.preventDefault(); return exigerDeverrouillage(); }

  if (haut === "clavier") {
    if (DIRECTIONS[e.key]) { e.preventDefault(); return deplacer(DIRECTIONS[e.key]); }
    // Entrée valide la saisie si on tape sur un vrai clavier ; avec une télécommande
    // (flèches puis OK), elle appuie sur la touche à l'écran sélectionnée.
    if (e.key === "Enter") { e.preventDefault(); return saisie?.physique ? validerSaisie() : courant?.click(); }
    if (e.key === "Escape") { e.preventDefault(); saisie = null; return fermerCalque(); }
    if (e.key === "Backspace") { e.preventDefault(); return ecrire(null); }
    if (e.key.length === 1) { e.preventDefault(); saisie.physique = true; return ecrire(e.key.toLowerCase()); }
    return;
  }

  if (DIRECTIONS[e.key]) { e.preventDefault(); return deplacer(DIRECTIONS[e.key]); }
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); return courant?.click(); }
  if (e.key === "Escape" || e.key === "Backspace" || e.key === "BrowserBack") { e.preventDefault(); return fermerCalque(); }
  if (e.key === "Home") { e.preventDefault(); return fermerTout(); }
  if (e.ctrlKey || e.altKey || e.metaKey) return;

  const touche = chiffre && ["1", "2", "3"].includes(chiffre) ? chiffre : e.key.toLowerCase();
  const raccourcis = {
    1: () => commande("tv"), 2: () => commande("gaming"), 3: () => commande("bureau"),
    r: () => { fermerTout(); ACTIONS.reglages(); },
    p: () => { fermerTout(); ACTIONS.profils(); },
    m: () => { fermerTout(); ACTIONS.meteo(); },
    "?": () => { fermerTout(); ACTIONS.aide(); },
    h: () => { fermerTout(); ACTIONS.aide(); },
    e: () => { fermerTout(); ACTIONS.arret(); },
    a: entrerAmbiant,
    t: () => {
      if (profil().pin && profil().reglagesProteges && !deverrouilles.has(profil().id)) return ACTIONS.reglages("apparence");
      profil().theme = themeEffectif() === "clair" ? "sombre" : "clair";
      sauver(); appliquerTout(); annoncer(`${t("theme")} : ${t("theme." + profil().theme)}`);
    },
    l: () => {
      if (profil().pin && profil().reglagesProteges && !deverrouilles.has(profil().id)) return ACTIONS.reglages("langue");
      const i = LANGUES.findIndex(l => l.code === profil().langue);
      profil().langue = LANGUES[(i + 1) % LANGUES.length].code;
      sauver(); appliquerTout(); annoncer(LANGUES[(i + 1) % LANGUES.length].nom);
    },
  };
  if (raccourcis[touche]) { e.preventDefault(); raccourcis[touche](); }
});

// Un contenu redessiné sous un pointeur immobile (section des réglages changée au
// clavier) déclenche « mouseover » : sans bouger, la souris volait alors la sélection
// qu'on venait de donner au clavier. Le pointeur doit avoir bougé depuis la dernière touche.
const pointeur = { x: null, y: null, touche: false };
addEventListener("keydown", () => { pointeur.touche = true; }, true);
addEventListener("mousemove", e => {
  if (e.clientX !== pointeur.x || e.clientY !== pointeur.y) pointeur.touche = false;
  pointeur.x = e.clientX; pointeur.y = e.clientY;
  document.body.classList.add("souris"); reveiller();
});
addEventListener("mouseover", e => {
  const immobile = e.clientX === pointeur.x && e.clientY === pointeur.y;
  pointeur.x = e.clientX; pointeur.y = e.clientY;
  if (immobile && pointeur.touche) return;
  pointeur.touche = false;
  const cible = e.target.closest("[data-nav]");
  if (cible && calqueActif().contains(cible) && !verrou) definirFocus(cible, true);
});

// La boucle ne tourne que manette branchée : sans elle, le menu demandait une image
// à chaque rafraîchissement de l'écran pour n'y trouver aucune manette.
const pressees = new Set();
let boucleManettes = false;
function manettesBranchees() { return [...(navigator.getGamepads?.() || [])].some(Boolean); }
function relancerManettes() {
  if (!boucleManettes && manettesBranchees()) { boucleManettes = true; requestAnimationFrame(manettes); }
}
addEventListener("gamepadconnected", relancerManettes);
function manettes() {
  if (!manettesBranchees()) { boucleManettes = false; pressees.clear(); return; }
  for (const m of navigator.getGamepads?.() || []) {
    if (!m) continue;
    const etat = {
      haut: m.buttons[12]?.pressed || m.axes[1] < -.6,
      bas: m.buttons[13]?.pressed || m.axes[1] > .6,
      gauche: m.buttons[14]?.pressed || m.axes[0] < -.6,
      droite: m.buttons[15]?.pressed || m.axes[0] > .6,
      ok: m.buttons[0]?.pressed,
      retour: m.buttons[1]?.pressed,
      profils: m.buttons[3]?.pressed,
      aide: m.buttons[8]?.pressed,
      reglages: m.buttons[9]?.pressed,
    };
    for (const [nom, appui] of Object.entries(etat)) {
      const cle = m.index + nom;
      if (appui && !pressees.has(cle)) {
        pressees.add(cle);
        if (!reveiller()) commande(nom);
      }
      if (!appui) pressees.delete(cle);
    }
  }
  requestAnimationFrame(manettes);
}

// ── Enceinte réseau : en cours de lecture ─────────────────────────────────
// hub-enceinte publie ce que jouent Spotify, AirPlay ou une recopie d'écran ; hub-menu le
// relaie. Le bandeau n'est qu'une information : on ne pilote pas la musique d'un
// téléphone depuis la TV, et un bouton de plus dans l'en-tête gênerait la navigation.
let lecture = null;
const SOURCES_LECTURE = { spotify: "Spotify", airplay: "AirPlay", ecran: "AirPlay" };

function texteLecture(e) {
  if (e.ecran && e.source === "ecran") {
    return { titre: t("lecture.recopie"), detail: e.appareil ? t("lecture.depuis", { appareil: e.appareil }) : SOURCES_LECTURE.ecran };
  }
  const titre = e.titre || t("lecture.sans.titre");
  const detail = [e.artiste, SOURCES_LECTURE[e.source] + (e.appareil ? ` · ${e.appareil}` : "")].filter(Boolean).join(" — ");
  return { titre, detail: e.etat === "pause" ? `${t("lecture.pause")} · ${detail}` : detail };
}

function habillerLecture(prefixe, e) {
  const bloc = $(prefixe);
  bloc.hidden = !e;
  if (!e) return;
  const { titre, detail } = texteLecture(e);
  $(`${prefixe}-titre`).textContent = titre;
  $(`${prefixe}-detail`).textContent = detail;
  const pochette = $(`${prefixe}-pochette`);
  const image = e.pochette ? `url("${encodeURI(decodeURI(e.pochette))}")` : "";
  if (pochette.dataset.image !== image) {
    pochette.dataset.image = image;
    pochette.style.backgroundImage = image;
  }
  pochette.classList.toggle("sans-image", !e.pochette);
  pochette.dataset.source = e.source;
  bloc.classList.toggle("en-pause", e.etat === "pause");
  bloc.dataset.source = e.source;
}

function rendreLecture() {
  habillerLecture("lecture", lecture);
  habillerLecture("ambiant-lecture", lecture);
}

function recevoirLecture(etat) {
  const avant = lecture;
  lecture = etat && typeof etat === "object" && etat.source ? etat : null;
  // Le mode ambiant est fait pour la musique : un morceau qui démarre ne le réveille pas.
  if (lecture && (!avant || avant.titre !== lecture.titre || avant.source !== lecture.source) && lecture.etat === "lecture" &&
      !document.body.classList.contains("ambiant") && pile.at(-1) === "accueil") {
    annoncer(texteLecture(lecture).titre);
  }
  rendreLecture();
}

// ── Recopie d'écran : code ────────────────────────────────────────────────
// hub-enceinte protège la recopie par un code à 4 chiffres. Réglages → Enceinte le
// montre et permet d'en tirer un autre ; pendant qu'un appareil le demande, hub-menu
// relaie { type: "recopie-appairage", etat: { code, jusqua } | null } et le code
// s'affiche en grand, par-dessus tout.
const recopie = { code: undefined, permise: null, demandeLe: 0, confirmer: false, appairage: INITIAL.recopieCode || null };

function demanderCodeRecopie(nouveau = false) {
  recopie.demandeLe = Date.now();
  if (!PONT) { recopie.code = null; return; }
  envoyer({ type: "recopie-code", nouveau });
}
function recevoirCodeRecopie(message) {
  recopie.code = typeof message.code === "string" && /^[0-9]{4}$/.test(message.code) ? message.code : null;
  recopie.permise = typeof message.permise === "boolean" ? message.permise : null;
  if (message.nouveau && recopie.code) annoncer(t("enceinte.code.change", { code: recopie.code }));
  if (pile.at(-1) === "reglages" && sectionCourante === "enceinte") rendreSection();
}

function lignesCodeRecopie(e) {
  // Relu à l'ouverture de la section, pas à chaque option touchée.
  if (Date.now() - recopie.demandeLe > 10000) demanderCodeRecopie();
  const lignes = [];
  if (e.ecran !== false && recopie.permise === false) lignes.push(el("div", { class: "aide recopie-coupee" }, t("enceinte.ecran.profil")));
  const valeur = recopie.code === undefined ? "…" : recopie.code || t("enceinte.code.indisponible");
  const boutons = recopie.confirmer
    ? [el("button", { class: "option", "data-nav": true, "data-cle": "recopie-code-annuler", onclick: () => { recopie.confirmer = false; rendreSection(); } }, t("annuler")),
      el("button", { class: "option choisie", "data-nav": true, "data-cle": "recopie-code-oui",
        onclick: () => { recopie.confirmer = false; recopie.code = undefined; demanderCodeRecopie(true); rendreSection(); } }, t("enceinte.code.oui"))]
    : [el("button", { class: "option", "data-nav": !!recopie.code, "data-cle": "recopie-code-changer", disabled: !recopie.code,
        onclick: () => { recopie.confirmer = true; rendreSection(); } }, t("enceinte.code.changer"))];
  lignes.push(rangee(el("span", { class: "code-recopie" }, t("enceinte.code", { code: valeur })),
    t(recopie.confirmer ? "enceinte.code.confirmer" : "enceinte.code.detail"), el("div", { class: "options" }, boutons), false, true));
  return lignes;
}

function recevoirAppairageRecopie(etat) {
  recopie.appairage = etat && typeof etat.code === "string" && /^[0-9]{4}$/.test(etat.code) ? etat : null;
  majAppairageRecopie();
}
function majAppairageRecopie() {
  const etat = recopie.appairage && recopie.appairage.jusqua * 1000 > Date.now() ? recopie.appairage : null;
  let panneau = $("recopie-appairage");
  if (!etat) { if (panneau) panneau.hidden = true; return; }
  if (!panneau) {
    panneau = el("div", { class: "recopie-appairage", id: "recopie-appairage", role: "status" },
      el("div", { class: "recopie-titre", id: "recopie-appairage-titre" }),
      el("div", { class: "recopie-saisir", id: "recopie-appairage-saisir" }),
      el("div", { class: "recopie-chiffres", id: "recopie-appairage-code" }));
    document.body.append(panneau);
  }
  $("recopie-appairage-titre").textContent = t("recopie.titre");
  $("recopie-appairage-saisir").textContent = t("recopie.saisir");
  $("recopie-appairage-code").textContent = etat.code;
  panneau.hidden = false;
}
setInterval(majAppairageRecopie, 1000);

// Réglages → Enceinte réseau. Commun au HUB : c'est la même enceinte pour toute la maison.
function contenuEnceinte() {
  const e = reglages.systeme.enceinte;
  const bascule = (cle, titre, aide) => rangee(t(titre), t(aide),
    options(`enceinte-${cle}`, [[true, t("oui")], [false, t("non")]], e[cle] !== false, v => { e[cle] = v === true || v === "true"; }), false, true);
  return [
    bascule("spotify", "enceinte.spotify", "enceinte.spotify.detail"),
    bascule("airplay", "enceinte.airplay", "enceinte.airplay.detail"),
    bascule("ecran", "enceinte.ecran", "enceinte.ecran.detail"),
    ...lignesCodeRecopie(e),
    rangee(t("enceinte.nom"), t("enceinte.nom.detail", { nom: e.nom || "HUB" }), el("div", { class: "options" },
      el("button", {
        class: "option", "data-nav": true, "data-cle": "enceinte-nom",
        onclick: () => ouvrirClavier(t("enceinte.nom"), e.nom || "HUB", nom => {
          // Les caractères que l'annonce réseau n'aime pas sont retirés aussi par hub-enceinte.
          const propre = [...nom].filter(ch => ch >= " ").join("").trim().slice(0, 40);
          if (propre) { e.nom = propre; sauver(); }
          rendreSection();
        }),
      }, `${e.nom || "HUB"} ✎`)), false, true),
    el("div", { class: "aide" }, t("enceinte.limites")),
  ];
}

setInterval(rendreLecture, 5000);
majAppairageRecopie();
// Au retour de Kodi, la musique jouait peut-être déjà : on l'affiche sans l'annoncer.
lecture = INITIAL.lecture?.source ? INITIAL.lecture : null;
rendreLecture();

// ── Réception depuis hub-menu ─────────────────────────────────────────────
window.hub = {
  recevoir(message) {
    if (typeof message === "string") message = JSON.parse(message);
    switch (message.type) {
      case "commande": return commande(message.nom);
      case "voix": return recevoirVoix(message.etat, message.texte);
      case "meteo": return recevoirMeteo(message.donnees, message.releveLe, message.horsLigne);
      case "geocodage": return rappelGeocodage?.(message.resultats || []);
      case "minuteur": return recevoirMinuteur(message.fin);
      case "telecommande": return recevoirTelecommande(message.etat);
      case "lecture": return recevoirLecture(message.etat);
      case "maj": return recevoirMiseAJour(message);
      case "pin": return recevoirCode(message);
      case "recopie-code": return recevoirCodeRecopie(message);
      case "recopie-appairage": return recevoirAppairageRecopie(message.etat);
      case "texte":
        // Texte tapé sur le téléphone : il remplit la saisie en cours, s'il y en a une.
        if (saisie && typeof message.texte === "string") { saisie.valeur = message.texte.slice(0, 32); majSaisie(); }
        return;
      case "avatars":
        listeAvatars = Array.isArray(message.liste) ? message.liste : [];
        if (brouillon && pile.includes("editeur-profil")) rendreEditeur();
        return;
      case "infos":
        infosMachine = message;
        if (pile.at(-1) === "reglages" && sectionCourante === "apropos") rendreSection();
        return;
      default:
        return extensions.messages[message.type]?.(message);
    }
  },
};

// ── Démarrage ─────────────────────────────────────────────────────────────
function appliquerTout() {
  appliquerApparence();
  for (const onglet of onglets) onglet.hidden = !modeAutorise(onglet.dataset.mode);
  rendreReprises();
  rendreApplis();
  appliquerTextes();
  horloge();
  afficherMeteo();
  majMinuteur();
  $("voix-pastille").hidden = !reglages.systeme.voix || etatVoix.micro === null;
  // Textes, services visibles, onglets cachés : le héros se refait sur le même mode.
  montrerHeros();
  relancerFond();
  if (pile.at(-1) === "accueil") accentuer(ongletHeros?.dataset.accent || "tv");
}

appliquerTout();
rendreReprises();
if (APERCU) document.body.append(el("div", { class: "bandeau-apercu" }, t("apercu.bandeau")));
setInterval(() => { horloge(); majMinuteur(); }, 5000);

// Intro à l'allumage seulement : revenir de Kodi doit être immédiat.
if (!INITIAL.retour && !parametres.get("ecran") && !parametres.has("sans-intro") && profil().animations !== "reduites" && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const intro = $("intro");
  intro.hidden = false;
  son("ok");
  setTimeout(() => intro.classList.add("fin"), 1700);
  setTimeout(() => { intro.hidden = true; }, 2700);
}
setInterval(chargerMeteo, 20 * 60000);
// Une manette déjà branchée au retour de Kodi ne renvoie pas « gamepadconnected ».
relancerManettes();
window.hubBoucles = () => ({ fond: boucleFond, manettes: boucleManettes });

const carteDepart = onglets.find(c => c.dataset.mode === (INITIAL.dernier || profil().dernier) && !c.hidden) || onglets.find(c => !c.hidden);
definirFocus(carteDepart, true);
// Le dernier relevé en cache s'affiche tout de suite ; le relevé frais suit.
if (INITIAL.meteo) recevoirMeteo(INITIAL.meteo.donnees, INITIAL.meteo.releveLe, INITIAL.meteo.horsLigne);
chargerMeteo();

if (!INITIAL.retour) {
  if (profil().pin) verrouillerAccueil();
  if (reglages.systeme.demanderProfil && reglages.profils.length > 1) ACTIONS.profils();
  else if (verrouAccueil) setTimeout(exigerDeverrouillage, parametres.has("sans-intro") ? 0 : 1800);
}

// Mise au point : ?ecran=reglages&section=fond, ?ecran=meteo, ?theme=clair, ?motif=profondeur&fond=emeraude…
if (parametres.get("theme")) { profil().theme = parametres.get("theme"); appliquerTout(); }
if (parametres.get("fond")) { profil().fond = parametres.get("fond"); appliquerTout(); }
if (parametres.get("motif")) { profil().motif = parametres.get("motif"); appliquerTout(); }
if (parametres.get("langue")) { profil().langue = parametres.get("langue"); appliquerTout(); }
const ecran = parametres.get("ecran");
if (ecran === "ambiant") setTimeout(entrerAmbiant, 300);
else if (ecran && ACTIONS[ecran]) setTimeout(() => ACTIONS[ecran](parametres.get("section") || undefined), 300);
if (parametres.get("voix")) setTimeout(() => { recevoirVoix("micro-present"); recevoirVoix("eveil"); }, 400);
