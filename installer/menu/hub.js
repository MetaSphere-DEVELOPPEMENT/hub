"use strict";
// Menu du HUB — logique.
//
// Le menu parle à hub-menu (Python) par window.webkit.messageHandlers.hub, en JSON :
//   → { type: "choix", mode }            un mode est lancé, le menu va se fermer
//   → { type: "reglages", donnees }      enregistrer ~/.config/hub/reglages.json
//   → { type: "meteo", lat, lon }        demander un relevé (Python le met en cache)
//   → { type: "geocodage", nom, langue } chercher une ville
//   → { type: "minuteur", minutes }      programmer (ou annuler avec 0) l'extinction
//   → { type: "infos" }                  machine, adresse IP, disque…
// Python répond en appelant window.hub.recevoir({ type, ... }), et y relaie aussi les
// commandes vocales de hub-voix ({ type: "commande", nom } / { type: "voix", ... }).
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
  nom: "Samuel",
  couleur: "turquoise",
  theme: "sombre",
  fond: "aurore",
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
  reglagesProteges: false,
  verrouVeille: false,
};
const DEFAUTS = {
  version: 1,
  profilActif: "samuel",
  profils: [{ id: "samuel", ...DEFAUTS_PROFIL }],
  systeme: {
    voix: true,
    sons: true,
    veille: 10,
    demanderProfil: false,
    echelle: 1,
    marge: 5,
    meteo: { active: true, ville: "Lyon", lat: 45.7640, lon: 4.8357 },
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
  r.profils = (r.profils.length ? r.profils : copie(DEFAUTS.profils)).map(p => ({ ...DEFAUTS_PROFIL, ...p }));
  if (!r.profils.some(p => p.id === r.profilActif)) r.profilActif = r.profils[0].id;
  return r;
})();

function profil() { return reglages.profils.find(p => p.id === reglages.profilActif); }
function meteoProfil() { return profil().meteo || reglages.systeme.meteo; }
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
  racine.style.setProperty("--marge", reglages.systeme.marge);
  document.body.classList.toggle("sans-animation", profil().animations === "reduites");
  const couleur = COULEURS_PROFIL[profil().couleur] || COULEURS_PROFIL.turquoise;
  habillerAvatar($("avatar-profil"), profil());
  $("nom-profil").textContent = profil().nom;
  extensions.apparence.forEach(f => f());
}

// ── Fonds animés ──────────────────────────────────────────────────────────
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
  minimal: {
    sombre: { base: "#0a0c13", nappes: [[42, 48, 70]] },
    clair: { base: "#eef1f6", nappes: [[255, 255, 255]] },
  },
};
const NAPPES = [
  { x: .18, y: .22, r: .50, vx: .021, vy: .017, phase: 0 },
  { x: .86, y: .18, r: .44, vx: -.016, vy: .023, phase: 2 },
  { x: .66, y: .95, r: .52, vx: .013, vy: -.019, phase: 4 },
  { x: .10, y: .90, r: .50, vx: .019, vy: .011, phase: 1 },
];

const toile = $("fond");
const ctx = toile.getContext("2d");
let accentCible = COULEURS_MODE.tv;
let accentCourant = [...COULEURS_MODE.tv];
let fondPret = false;
let boucleFond = false;
let etoiles;

function fondChoisi() {
  const f = profil().fond;
  if (f === "photos" && !(INITIAL.photos || []).length) return "aurore";
  return PALETTES[f] || f === "photos" ? f : "aurore";
}

function dessinerFond(temps) {
  const choix = fondChoisi();
  const theme = racine.dataset.theme === "clair" ? "clair" : "sombre";
  const palette = (PALETTES[choix] || PALETTES.aurore)[theme];
  const reduit = profil().animations === "reduites" || matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lent = document.body.classList.contains("ambiant") ? .4 : 1;
  const s = reduit ? 0 : (temps / 1000) * lent;
  const w = toile.width, h = toile.height;

  accentCourant = melange(accentCourant, accentCible, reduit ? 1 : .03);
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = palette.base;
  ctx.fillRect(0, 0, w, h);
  ctx.globalCompositeOperation = theme === "clair" ? "source-over" : "lighter";

  palette.nappes.forEach((teinteBase, i) => {
    const n = NAPPES[i];
    let x, y;
    if (choix === "ocean") {
      x = (n.x + Math.sin(s * n.vx * 3 + n.phase) * .3) * w;
      y = (n.y + Math.sin(s * .15 + n.phase) * .05) * h;
    } else if (choix === "braise") {
      x = (n.x + Math.sin(s * n.vx * 5 + n.phase) * .1) * w;
      y = ((n.y - (s * .012 * (i + 1)) % 1.4 + 1.4) % 1.4 - .2) * h;
    } else {
      x = (n.x + Math.sin(s * n.vx * 6 + n.phase) * .16) * w;
      y = (n.y + Math.cos(s * n.vy * 6 + n.phase) * .14) * h;
    }
    const r = (choix === "minimal" ? 1.1 : n.r) * w * (1 + Math.sin(s * .3 + n.phase) * .08);
    const teinter = profil().teinteMode && choix !== "minimal";
    const teinte = teinter ? melange(teinteBase, accentCourant, i === 0 ? .75 : .25) : teinteBase;
    const force = theme === "clair" ? (i === 0 ? .6 : .5) : (i === 3 ? .35 : i === 0 ? .34 : .2);
    const g = ctx.createRadialGradient(x, choix === "minimal" ? -h * .3 : y, 0, x, choix === "minimal" ? -h * .3 : y, r);
    g.addColorStop(0, `rgba(${teinte.map(Math.round).join(",")},${choix === "minimal" ? (theme === "clair" ? .9 : .5) : force})`);
    g.addColorStop(1, `rgba(${teinte.map(Math.round).join(",")},0)`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  });

  fondPret = true;
  // Un fond immobile n'a pas besoin de redessiner soixante fois par seconde.
  const immobile = reduit || choix === "minimal" || choix === "photos";
  if (immobile && Math.abs(accentCourant[0] - accentCible[0]) < 1) { boucleFond = false; return; }
  requestAnimationFrame(dessinerFond);
}
function relancerFond() {
  etoilesVisibles();
  photosVisibles();
  if (!boucleFond) { boucleFond = true; requestAnimationFrame(dessinerFond); }
}

function etoilesVisibles() {
  const visible = fondChoisi() === "nebuleuse" && racine.dataset.theme !== "clair";
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
  $("sous-salut").textContent = alerteMeteo() || t("salut.question");
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
  const actif = meteoProfil().active && meteo?.current;
  $("puce-meteo").hidden = !actif;
  $("ambiant-meteo").innerHTML = "";
  if (!actif) return;
  const c = meteo.current;
  const nuit = c.is_day === 0;
  $("meteo-picto-puce").innerHTML = pictoMeteo(c.weather_code, nuit);
  $("meteo-temp-puce").textContent = `${Math.round(c.temperature_2m)}°`;
  $("meteo-ville-puce").textContent = meteoProfil().ville;
  $("ambiant-meteo").innerHTML = `${pictoMeteo(c.weather_code, nuit)}<span>${Math.round(c.temperature_2m)}° · ${libelleMeteo(c.weather_code)} · ${meteoProfil().ville}</span>`;
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
  if (!active) return afficherMeteo();
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
      alerteMeteo() && el("div", { class: "lieu", style: "color:rgb(90 170 255)" }, alerteMeteo())),
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
        profil().meteo = { ...meteoProfil(), ville: v.name, lat: v.latitude, lon: v.longitude };
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

function calqueActif() { return $(pile.at(-1)); }
function candidats() {
  return [...calqueActif().querySelectorAll("[data-nav]")].filter(e => !e.hidden && !e.closest("[hidden]") && e.getClientRects().length);
}

function definirFocus(cible, silencieux = false) {
  if (!cible) return;
  const precedent = courant;
  if (courant && courant !== cible) courant.classList.remove("focus");
  const change = courant !== cible;
  // La carte qu'on atteint pivote un instant dans le sens du déplacement, comme
  // si on la faisait glisser : on sent la direction sans lire l'écran.
  if (change && precedent?.classList.contains("carte") && cible.classList.contains("carte") && profil().animations !== "reduites") {
    const sens = cartes.indexOf(cible) > cartes.indexOf(precedent) ? 1 : -1;
    cible.animate([
      { transform: `translateY(-.9rem) scale(1.06) rotateY(${sens * -9}deg)` },
      { transform: "translateY(-.9rem) scale(1.06) rotateY(0deg)" },
    ], { duration: 650, easing: "cubic-bezier(.34, 1.56, .64, 1)" });
    precedent.animate([
      { transform: `scale(.96) rotateY(${sens * 7}deg)` },
      { transform: "scale(.96) rotateY(0deg)" },
    ], { duration: 650, easing: "cubic-bezier(.2, .8, .2, 1)" });
  }
  courant = cible;
  cible.classList.add("focus");
  focusParCalque[pile.at(-1)] = cible;
  if (change && !silencieux) son("deplacer");

  if (cible.dataset.accent) accentuer(cible.dataset.accent);
  else if (pile.at(-1) === "accueil") accentuer(cartes.find(c => c.dataset.mode === profil().dernier)?.dataset.accent || "tv");
  if (cible.dataset.section && cible.dataset.section !== sectionCourante) {
    sectionCourante = cible.dataset.section;
    rendreSection(false);
  }
  defiler(cible);
}

function defiler(cible) {
  const zone = cible.closest(".contenu-defile");
  if (!zone) return;
  const cadre = zone.parentElement;
  const r = cible.getBoundingClientRect(), z = zone.getBoundingClientRect();
  const position = r.top - z.top;
  const hauteurUtile = cadre.clientHeight - parseFloat(getComputedStyle(cadre).paddingTop) * 2;
  const maximum = Math.max(0, zone.scrollHeight - hauteurUtile);
  const decalage = borne(position - hauteurUtile * .4, 0, maximum);
  zone.style.transform = `translateY(${-decalage}px)`;
}

// La navigation reste d'abord dans la zone où l'on est (contenu d'un réglage, sommaire,
// pied…) : sans ça, « haut » depuis un bouton du contenu sautait dans le sommaire voisin
// au lieu du bouton juste au-dessus.
const ZONES = ".contenu, .sommaire, .entete, .pied, .modes, .reprises, .editeur-identite, .editeur-securite, .choix, .pave";
function voisin(depart, direction) {
  const zone = depart.closest(ZONES);
  const dansZone = zone && voisinParmi(depart, direction, candidats().filter(e => zone.contains(e)));
  return dansZone || voisinParmi(depart, direction, candidats());
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

function deplacer(direction) {
  const liste = candidats();
  if (!courant || !liste.includes(courant)) return definirFocus(liste[0]);
  const suivant = voisin(courant, direction);
  if (suivant) definirFocus(suivant);
}

function ouvrirCalque(id, focusPremier = true) {
  if (pile.at(-1) === id) return;
  if (pile.includes(id)) pile.splice(pile.indexOf(id), 1);
  pile.push(id);
  $(id).classList.add("ouvert");
  document.body.classList.toggle("calque-ouvert", pile.length > 1);
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
  const liste = candidats();
  const precedent = focusParCalque[pile.at(-1)];
  definirFocus(liste.includes(precedent) ? precedent : liste[0], true);
  son("retour");
  if (verrouAccueil && pile.length === 1 && id !== "code") setTimeout(exigerDeverrouillage, 0);
}
function fermerTout() { while (pile.length > 1) fermerCalque(); }

// ── Accueil : lancer un mode ──────────────────────────────────────────────
const cartes = [...document.querySelectorAll(".carte")];

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
  if (APERCU) { son("ok"); return annoncer(t("apercu.mode", { mode: carte.querySelector(".nom").textContent })); }
  if (!modeAutorise(carte.dataset.mode)) { son("erreur"); return annoncer(t("mode.interdit")); }
  if (lancementRefuse(carte.dataset.mode)) return;
  if (carte.dataset.indisponible) {
    son("erreur");
    annoncer(t(carte.dataset.indisponible));
    carte.animate([{ translate: "0" }, { translate: "-.6rem" }, { translate: ".6rem" }, { translate: "-.3rem" }, { translate: "0" }], { duration: 420, easing: "ease-out" });
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

cartes.forEach(c => c.addEventListener("click", () => {
  if (pile.at(-1) !== "accueil") return;
  definirFocus(c, true);
  lancer(c);
}));

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
  const retrouve = cle && liste.querySelector(`[data-cle="${cle}"]`);
  if (pile.at(-1) === "profils") definirFocus(retrouve || liste.querySelector(`[data-cle="profil-${reglages.profilActif}"]`), true);
  else focusParCalque.profils = liste.querySelector(`[data-cle="profil-${reglages.profilActif}"]`);
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
  const carte = cartes.find(c => c.dataset.mode === profil().dernier) || cartes[0];
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
  const retrouve = cle && $("editeur-profil").querySelector(`[data-cle="${cle}"]`);
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
    }, `${actif ? "✓ " : ""}${t(cle)}`));
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
const ICONE_CADENAS = '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';
let deverrouilles = new Set();
let verrouAccueil = false;
let demande = null;
const echecsCode = {};

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

function empreinteCode(code, sel) { return sha256(`${sel}:${code}`); }
function nouveauSel() { return [...crypto.getRandomValues(new Uint8Array(8))].map(o => o.toString(16).padStart(2, "0")).join(""); }

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
  if (!demande) return;
  const blocage = echecsCode[demande.p.id];
  if (blocage?.jusqua > Date.now()) {
    son("erreur");
    $("code-detail").textContent = t("code.bloque", { s: Math.ceil((blocage.jusqua - Date.now()) / 1000) });
    return;
  }
  if (demande.saisie.length >= 4) return;
  demande.saisie += ch;
  son("deplacer");
  majPoints();
  if (demande.saisie.length === 4) setTimeout(validerCode, 180);
}
function effacerChiffre() {
  if (!demande) return;
  demande.saisie = demande.saisie.slice(0, -1);
  majPoints();
}
function refuserCode(message) {
  son("erreur");
  $("code-points").animate([{ translate: "0" }, { translate: "-1rem" }, { translate: "1rem" }, { translate: "-.5rem" }, { translate: "0" }], { duration: 380 });
  $("code-detail").textContent = message;
  demande.saisie = "";
  majPoints();
}
function validerCode() {
  if (!demande) return;
  const { p, mode, saisie } = demande;
  if (mode === "verifier") {
    // demande.verifier : un code accepté de plusieurs profils (n'importe quel parent).
    if (demande.verifier ? demande.verifier(saisie) : p.pin && empreinteCode(saisie, p.pin.sel) === p.pin.empreinte) {
      delete echecsCode[p.id];
      deverrouilles.add(p.id);
      if (p.id === profil().id) { verrouAccueil = false; document.body.classList.remove("verrouille"); }
      const { reussite } = demande;
      demande = null;
      son("ok");
      fermerCalque();
      reussite?.();
      return;
    }
    const echec = echecsCode[p.id] ||= { n: 0, jusqua: 0 };
    echec.n += 1;
    if (echec.n >= 5) { echec.n = 0; echec.jusqua = Date.now() + 30000; return refuserCode(t("code.bloque", { s: 30 })); }
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
  const sel = nouveauSel();
  const { reussite } = demande;
  demande = null;
  deverrouilles.add(p.id);
  fermerCalque();
  annoncer(t("code.defini"));
  reussite?.({ sel, empreinte: empreinteCode(saisie, sel) });
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
  ["telecommande", '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>'],
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
  if (["apparence", "fond", "langue", "voix", "meteo", "veille"].includes(sectionCourante)) {
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
      const vignettes = el("div", { class: "vignettes" });
      for (const f of ["aurore", "nebuleuse", "ocean", "braise", "minimal", "photos"]) {
        vignettes.append(el("button", {
          class: `vignette-fond apercu-${f}${p.fond === f ? " choisie" : ""}`, "data-nav": true, "data-cle": `fond-${f}`,
          onclick: () => {
            if (f === "photos" && !(INITIAL.photos || []).length) { son("erreur"); return annoncer(t("fond.photos.aucune")); }
            p.fond = f; sauver(); appliquerTout(); rendreSection(); son("ok");
          },
          html: f === "photos" ? '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m3 16 5-5 4 4 3-3 6 6"/></svg>' : "",
        }, el("span", {}, t(`fond.${f}`))));
      }
      zone.append(vignettes,
        el("div", { class: "aide", style: "margin-top:-.2rem" }, t("fond.photos.detail")),
        rangee(t("fond.couleur.mode"), null, options("teinte", [[true, t("oui")], [false, t("non")]], p.teinteMode, v => { p.teinteMode = v === true || v === "true"; })));
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
          el("span", { style: "display:flex;align-items:center;gap:.9rem" }, avatar(x), x.nom, x.pin && el("span", { class: "cadenas", html: ICONE_CADENAS }), x.id === reglages.profilActif ? " ✓" : ""),
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

    case "meteo":
      zone.append(
        rangee(t("meteo.afficher"), null, options("meteo", [[true, t("oui")], [false, t("non")]], meteoProfil().active, v => { p.meteo = { ...meteoProfil(), active: v === true || v === "true" }; chargerMeteo(); })),
        rangee(t("meteo.ville"), meteoProfil().ville, el("div", { class: "options" },
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
        el("div", { class: "options", style: "justify-content:flex-start;margin-top:.4rem" },
          el("button", { class: "option", "data-nav": true, "data-cle": "fermer-reglages", "data-action": "fermer" }, t("fermer"))));
      break;
    }
  }

  extensions.contenus[sectionCourante]?.(zone);

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
    texte = t(e.retour ? "maj.echec.retour" : `maj.echec.${e.raison || "installation"}`);
  } else if (maj.enCours) {
    texte = t("maj.recherche");
  } else if (v?.erreur) {
    texte = t(v.erreur === "configuration" ? "maj.sans.source" : "maj.injoignable");
  } else if (v) {
    texte = v.disponible ? t("maj.disponible", { v: v.distant }) : t("maj.a.jour");
  }
  if (!actif && !maj.enCours) {
    boutons.push(el("button", { class: "option", "data-nav": true, "data-cle": "maj-verifier", onclick: () => { maj.enCours = true; maj.etat = null; envoyer({ type: "maj-verifier" }); rendreSection(); } }, t("maj.rechercher")));
    if (v?.disponible && e?.etape !== "terminee") {
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

function contenuTelecommande() {
  if (!telecommande) {
    return rangee(t("telecommande.absente"), t("telecommande.absente.detail"), null, true);
  }
  const qr = el("div", { class: "qr" });
  if (window.qrSvg) qr.innerHTML = window.qrSvg(telecommande.url, { sombre: "#000", clair: "#fff", marge: 3 });
  const code = String(telecommande.code).replace(/(\d{3})(\d{3})/, "$1 $2");
  return el("div", { class: "appairage" },
    qr,
    el("div", { class: "etapes" },
      el("div", { class: "etape" }, el("b", {}, "1"), t("telecommande.etape1")),
      el("div", { class: "etape" }, el("b", {}, "2"), t("telecommande.etape2")),
      el("div", { class: "etape" }, el("b", {}, "3"), t("telecommande.etape3")),
      el("div", { class: "code-appairage" }, code),
      el("div", { class: "aide", id: "telecommande-expire" }, texteExpiration()),
      el("div", { class: "aide url" }, telecommande.url),
      el("div", { class: "aide" }, t("telecommande.telephones", { n: telecommande.telephones ?? 0 }))));
}
function texteExpiration() {
  if (!telecommande?.expire) return "";
  const s = Math.max(0, Math.round((telecommande.expire - Date.now()) / 1000));
  return t("telecommande.expire", { m: Math.floor(s / 60), s: String(s % 60).padStart(2, "0") });
}
setInterval(() => {
  const e = document.getElementById("telecommande-expire");
  if (e) e.textContent = texteExpiration();
}, 1000);

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
      ligne(["F12"], "rc.kodi")),
    el("div", { class: "sous-titre" }, t("raccourcis.voix")),
    el("div", { class: "raccourcis" }, ["vc.tv", "vc.jeux", "vc.bureau", "vc.retour", "vc.reglages", "vc.theme"].map(k => el("div", { class: "phrase" }, t(k)))));
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
  if (etat === "eveil") { pastille.classList.add("eveil"); $("voix-texte").textContent = t("voix.ecoute"); bulle(t("voix.ecoute"), 0, true); son("deplacer"); }
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
  if (nom in modes) {
    fermerTout();
    definirFocus(cartes[modes[nom]], true);
    return lancer(cartes[modes[nom]]);
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
    $("ambiant-corps").style.transform = `translate(${(Math.random() - .5) * 8}rem, ${(Math.random() - .5) * 5}rem)`;
  }
}, 30000);

// ── Clavier, manette, souris ──────────────────────────────────────────────
const DIRECTIONS = { ArrowLeft: "gauche", ArrowRight: "droite", ArrowUp: "haut", ArrowDown: "bas" };

addEventListener("keydown", e => {
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

addEventListener("mousemove", () => { document.body.classList.add("souris"); reveiller(); });
addEventListener("mouseover", e => {
  const cible = e.target.closest("[data-nav]");
  if (cible && calqueActif().contains(cible) && !verrou) definirFocus(cible, true);
});

const pressees = new Set();
function manettes() {
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
      case "maj": return recevoirMiseAJour(message);
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
  for (const carte of cartes) carte.hidden = !modeAutorise(carte.dataset.mode);
  rendreReprises();
  appliquerTextes();
  horloge();
  afficherMeteo();
  majMinuteur();
  $("voix-pastille").hidden = !reglages.systeme.voix || etatVoix.micro === null;
  relancerFond();
  if (pile.at(-1) === "accueil" && courant?.dataset.accent) accentuer(courant.dataset.accent);
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
requestAnimationFrame(manettes);

const carteDepart = cartes.find(c => c.dataset.mode === (INITIAL.dernier || profil().dernier)) || cartes[0];
definirFocus(carteDepart, true);
// Le dernier relevé en cache s'affiche tout de suite ; le relevé frais suit.
if (INITIAL.meteo) recevoirMeteo(INITIAL.meteo.donnees, INITIAL.meteo.releveLe, INITIAL.meteo.horsLigne);
chargerMeteo();

if (!INITIAL.retour) {
  if (profil().pin) verrouillerAccueil();
  if (reglages.systeme.demanderProfil && reglages.profils.length > 1) ACTIONS.profils();
  else if (verrouAccueil) setTimeout(exigerDeverrouillage, parametres.has("sans-intro") ? 0 : 1800);
}

// Mise au point : ?ecran=reglages&section=fond, ?ecran=meteo, ?theme=clair…
if (parametres.get("theme")) { profil().theme = parametres.get("theme"); appliquerTout(); }
if (parametres.get("fond")) { profil().fond = parametres.get("fond"); appliquerTout(); }
if (parametres.get("langue")) { profil().langue = parametres.get("langue"); appliquerTout(); }
const ecran = parametres.get("ecran");
if (ecran === "ambiant") setTimeout(entrerAmbiant, 300);
else if (ecran && ACTIONS[ecran]) setTimeout(() => ACTIONS[ecran](parametres.get("section") || undefined), 300);
if (parametres.get("voix")) setTimeout(() => { recevoirVoix("micro-present"); recevoirVoix("eveil"); }, 400);
