// Réglages → Affichage : la liste des modes de l'écran, le mode actif marqué, et le
// filet de 15 s qui revient en arrière quand la TV ne montre rien du nouveau mode.
// Le pont WebKit est un faux qui joue hub-menu : il répond aux messages « affichage-… »
// avec les modes relevés sur la vraie TV le 17/09/2026 (4K plafonné à 30 Hz).
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium, webkit } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

// Le moteur : « chrome » par défaut, « chromium » celui de Playwright, « webkit » celui de
// la famille de la TV. Un rendu peut n'exister que dans l'un d'eux — la WebKitGTK du HUB
// ignorait les `mask-image` en dégradé que Chromium applique, et ça ne s'est vu que sur une
// photo du salon (18/09/2026). HUB_NAVIGATEUR=webkit rejoue toute la suite dans WebKit.
const lancerNavigateur = () => process.env.HUB_NAVIGATEUR === "webkit" ? webkit.launch()
  : chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;

let navigateur, page;

const MODE = (nom, largeur, hauteur, frequence, courant = false) =>
  ({ nom, largeur, hauteur, frequence, courant, prefere: false });
const MODES_TV = [
  MODE("1920x1080@60.000", 1920, 1080, 60),
  MODE("1920x1080@50.000", 1920, 1080, 50),
  MODE("1280x720@60.000", 1280, 720, 60),
  MODE("3840x2160@30.000", 3840, 2160, 30, true),
];

// window.__affichage : ce que hub-menu répondra (modes, gdctl absent, échec…). Le faux
// pont refait ce que fait installer/hub-menu.py : il n'applique qu'un mode de sa liste,
// et le mode appliqué devient le mode courant.
function installerFauxPont({ initial, affichage }) {
  window.__messages = [];
  window.__affichage = affichage;
  const repondre = m => {
    const a = window.__affichage;
    const etat = () => ({ type: "affichage", gdctl: a.gdctl, connecteur: a.connecteur, nom: a.nom, ecrans: a.ecrans, erreur: a.erreur, modes: a.modes, filet: a.filet });
    if (m.type === "affichage-etat") return window.hub.recevoir(etat());
    if (m.type === "affichage-appliquer") {
      const choisi = a.modes.find(x => x.nom === m.mode);
      if (!a.gdctl) return window.hub.recevoir({ ...etat(), applique: false, raison: "absent", avant: null });
      if (!choisi) return window.hub.recevoir({ ...etat(), applique: false, raison: "inconnu", avant: null });
      if (a.echec) return window.hub.recevoir({ ...etat(), applique: false, raison: "echec", erreur: "No mode available", avant: null });
      const avant = a.modes.find(x => x.courant)?.nom || null;
      a.modes = a.modes.map(x => ({ ...x, courant: x.nom === m.mode }));
      a.avant = avant;
      return window.hub.recevoir({ ...etat(), applique: true, raison: null, avant });
    }
    if (m.type === "affichage-revenir") {
      a.modes = a.modes.map(x => ({ ...x, courant: x.nom === a.avant }));
      return window.hub.recevoir({ ...etat(), applique: false, raison: "revenu", avant: null });
    }
  };
  window.webkit = { messageHandlers: { hub: { postMessage: texte => { const m = JSON.parse(texte); window.__messages.push(m); setTimeout(() => repondre(m), 20); } } } };
  window.HUB_INITIAL = initial;
}

before(async () => { navigateur = await lancerNavigateur(); });
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

function etatTV(extra = {}) {
  return { gdctl: true, connecteur: "HDMI-2", nom: "SONY TV", ecrans: 1, erreur: null, filet: 15, modes: MODES_TV.map(m => ({ ...m })), ...extra };
}

async function ouvrir({ affichage = etatTV(), profil = {}, systeme = {} } = {}) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  await page.route(/open-meteo\.com/, r => r.abort());
  await page.addInitScript(installerFauxPont, {
    initial: { retour: true, reglages: { profilActif: "p", profils: [{ id: "p", nom: "Samuel", animations: "reduites", ...profil }], systeme } },
    affichage,
  });
  await page.goto(PAGE + "?sans-intro");
  await page.waitForTimeout(250);
  await page.evaluate(() => ACTIONS.reglages("affichage"));
  await page.waitForTimeout(250);
}

const messages = type => page.evaluate(t => window.__messages.filter(m => m.type === t), type);
const modes = () => page.evaluate(() => [...document.querySelectorAll(".mode-ecran")].map(b => ({
  cle: b.dataset.cle, texte: [...b.children].map(s => s.textContent.trim()).join(" "), actif: b.classList.contains("choisie"),
})));
const focus = () => page.evaluate(() => document.querySelector(".focus")?.dataset.cle);
const calques = () => page.evaluate(() => [...document.querySelectorAll(".calque.ouvert")].map(c => c.id));

test("la section existe dans le sommaire, juste après Apparence", async () => {
  await ouvrir();
  const entrees = await page.evaluate(() => [...document.querySelectorAll("#sommaire .entree")].map(e => e.dataset.section));
  assert.equal(entrees[entrees.indexOf("apparence") + 1], "affichage");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Affichage");
  assert.deepEqual(await messages("affichage-etat"), [{ type: "affichage-etat" }]);
  assert.deepEqual(page.erreurs, []);
});

test("la liste des modes s'affiche, du plus confortable au moins bon, le mode actif marqué", async () => {
  await ouvrir();
  const liste = await modes();
  assert.deepEqual(liste.map(m => m.cle), [
    "mode-1920x1080@60.000", "mode-1920x1080@50.000", "mode-1280x720@60.000", "mode-3840x2160@30.000"]);
  assert.equal(liste[0].texte, "1920×1080 60 Hz Fluide");
  // Le mode actif : marqué par la coche de .choisie, par le mot « Actif », et pour les
  // lecteurs d'écran par aria-current. Jamais par la seule couleur.
  assert.deepEqual(liste.map(m => m.actif), [false, false, false, true]);
  assert.match(liste[3].texte, /Saccadé Actif$/);
  assert.equal(await page.getAttribute('[data-cle="mode-3840x2160@30.000"]', "aria-current"), "true");
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector(".mode-ecran.choisie"), "::before").content), '"✓"');
  // La fréquence de l'écran, en clair, au-dessus de la liste.
  assert.equal(await page.textContent("#affichage-courant"), "3840×2160 à 30 Hzle mouvement paraît saccadé");
  assert.deepEqual(page.erreurs, []);
});

test("choisir un mode l'applique tout de suite et pose la question", async () => {
  await ouvrir();
  await page.click('[data-cle="mode-1920x1080@60.000"]');
  await page.waitForTimeout(200);
  assert.deepEqual(await messages("affichage-appliquer"), [{ type: "affichage-appliquer", mode: "1920x1080@60.000" }]);
  assert.deepEqual(await calques(), ["reglages", "affichage-filet"]);
  assert.equal(await page.textContent("#affichage-filet-titre"), "Garder ce mode ?");
  assert.match(await page.textContent("#affichage-filet-detail"), /^1920×1080 à 60 Hz — /);
  assert.equal(await focus(), "affichage-garder", "la télécommande tombe sur « Garder »");
  assert.match(await page.textContent("#affichage-filet-reste"), /Retour automatique dans 1[45] s/);
});

test("garder : le mode est confirmé, retenu dans les réglages, et la liste le marque", async () => {
  await ouvrir();
  await page.click('[data-cle="mode-1920x1080@60.000"]');
  await page.waitForTimeout(200);
  await page.click('[data-cle="affichage-garder"]');
  await page.waitForTimeout(700);
  assert.deepEqual(await calques(), ["reglages"]);
  assert.deepEqual(await messages("affichage-garder"), [{ type: "affichage-garder" }]);
  assert.deepEqual(await messages("affichage-revenir"), [], "rien n'est annulé après confirmation");
  const enregistre = await page.evaluate(() => window.__messages.filter(m => m.type === "reglages").at(-1)?.donnees.systeme.affichage);
  assert.deepEqual(enregistre, { retablir: true, mode: "1920x1080@60.000", connecteur: "HDMI-2" });
  const liste = await modes();
  assert.equal(liste.find(m => m.actif).cle, "mode-1920x1080@60.000");
  assert.equal(await page.textContent("#affichage-courant"), "1920×1080 à 60 Hztout est fluide");
  assert.deepEqual(page.erreurs, []);
});

// Le cas qui compte : la TV n'affiche rien du nouveau mode, personne ne peut répondre.
test("sans confirmation, le compte à rebours revient au mode précédent tout seul", async () => {
  await ouvrir({ affichage: etatTV({ filet: 2 }) });
  await page.click('[data-cle="mode-1920x1080@60.000"]');
  await page.waitForTimeout(200);
  assert.deepEqual(await calques(), ["reglages", "affichage-filet"]);
  assert.equal(await page.textContent("#affichage-filet-reste"), "Retour automatique dans 2 s");
  await page.waitForTimeout(2600);
  assert.deepEqual(await messages("affichage-revenir"), [{ type: "affichage-revenir" }]);
  assert.deepEqual(await calques(), ["reglages"], "le dialogue se referme seul");
  assert.deepEqual(await messages("affichage-garder"), []);
  const liste = await modes();
  assert.equal(liste.find(m => m.actif).cle, "mode-3840x2160@30.000");
  assert.equal(await page.textContent("#affichage-courant"), "3840×2160 à 30 Hzle mouvement paraît saccadé");
  assert.match(await page.textContent("#annonce"), /Mode précédent rétabli/);
  assert.deepEqual(page.erreurs, []);
});

test("revenir en arrière tout de suite, sans attendre la fin du compte à rebours", async () => {
  await ouvrir();
  await page.click('[data-cle="mode-1280x720@60.000"]');
  await page.waitForTimeout(200);
  await page.click('[data-cle="affichage-revenir"]');
  await page.waitForTimeout(300);
  assert.deepEqual(await messages("affichage-revenir"), [{ type: "affichage-revenir" }]);
  assert.deepEqual(await calques(), ["reglages"]);
  assert.equal((await modes()).find(m => m.actif).cle, "mode-3840x2160@30.000");
});

test("gdctl absent : la section est en lecture seule et dit pourquoi", async () => {
  await ouvrir({ affichage: { gdctl: false, connecteur: null, nom: null, ecrans: 0, erreur: null, filet: 15, modes: [] } });
  assert.deepEqual(await modes(), []);
  assert.match(await page.textContent("#affichage-message"), /gdctl est absent de cette machine/);
  assert.equal(await page.textContent("#affichage-courant"), "—");
  assert.deepEqual(page.erreurs, []);
});

test("modes illisibles, ou plusieurs écrans : rien n'est proposé, le message le dit", async () => {
  await ouvrir({ affichage: etatTV({ erreur: "sortie de gdctl non comprise" }) });
  assert.deepEqual(await modes(), []);
  assert.match(await page.textContent("#affichage-message"), /sortie de gdctl non comprise/);
  await page.close();
  await ouvrir({ affichage: etatTV({ ecrans: 2 }) });
  assert.deepEqual(await modes(), []);
  assert.match(await page.textContent("#affichage-message"), /Plusieurs écrans/);
});

test("anglais : la section, les modes et le filet sont traduits", async () => {
  await ouvrir({ affichage: etatTV({ filet: 2 }), profil: { langue: "en" } });
  assert.equal(await page.textContent("#contenu-reglages h3"), "Display");
  assert.match(await page.textContent("#sommaire"), /Display/);
  assert.equal((await modes())[0].texte, "1920×1080 60 Hz Smooth");
  assert.equal(await page.textContent("#affichage-courant"), "3840×2160 at 30 Hzmovement looks jerky");
  await page.click('[data-cle="mode-1920x1080@60.000"]');
  await page.waitForTimeout(200);
  assert.equal(await page.textContent("#affichage-filet-titre"), "Keep this mode?");
  assert.equal(await page.textContent("#affichage-filet-reste"), "Going back in 2 s");
  assert.equal(await page.textContent('[data-cle="affichage-garder"]'), "Keep");
});

// Lisibilité à trois mètres : mêmes seuils que lisibilite.test.js (audit du 17/09/2026).
test("lisibilité : aucun texte de la section sous 0,9 rem, anneau de focus conforme", async () => {
  for (const theme of ["sombre", "clair"]) {
    await page?.close();
    await ouvrir({ profil: { theme } });
    const petits = await page.evaluate(() => {
      const rem = parseFloat(getComputedStyle(document.documentElement).fontSize), petits = [];
      const marche = document.createTreeWalker(document.getElementById("contenu-reglages"), NodeFilter.SHOW_TEXT);
      for (let n = marche.nextNode(); n; n = marche.nextNode()) {
        const e = n.parentElement;
        if (!n.textContent.trim() || !e.getClientRects().length) continue;
        const px = parseFloat(getComputedStyle(e).fontSize);
        if (px / rem < .895) petits.push({ texte: n.textContent.trim().slice(0, 24), rem: px / rem });
      }
      return petits;
    });
    assert.deepEqual(petits, [], theme);
    for (const cle of ["mode-1920x1080@60.000", "mode-3840x2160@30.000", "affichage-retablir-true"]) {
      const anneau = await page.evaluate(c => {
        const e = document.querySelector(`[data-cle="${CSS.escape(c)}"]`);
        definirFocus(e, true);
        const cs = getComputedStyle(e), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
        const lin = x => { x /= 255; return x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; };
        const L = ([r, g, b]) => .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b);
        const a = L(cs.outlineColor.match(/[\d.]+/g).map(Number));
        const b = L(getComputedStyle(document.documentElement).backgroundColor.match(/[\d.]+/g).map(Number));
        return { style: cs.outlineStyle, largeur: parseFloat(cs.outlineWidth) / rem, decalage: parseFloat(cs.outlineOffset) / rem, contraste: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) };
      }, cle);
      assert.equal(anneau.style, "solid", `${theme} ${cle}`);
      assert.ok(anneau.largeur >= .15 && anneau.decalage > 0, `${theme} ${cle} : ${JSON.stringify(anneau)}`);
      assert.ok(anneau.contraste >= 3, `${theme} ${cle} : anneau à ${anneau.contraste.toFixed(2)}:1`);
    }
  }
});

// Contraste réel sur le fond peint, comme lisibilite.test.js : on photographie la page
// sans ses textes et on compare chaque texte à la médiane des pixels sous lui.
async function contrastes(selecteurs) {
  const textes = await page.evaluate(sels => sels.flatMap(sel => [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length).map(e => {
    let o = 1; for (let x = e; x; x = x.parentElement) o *= parseFloat(getComputedStyle(x).opacity);
    const c = getComputedStyle(e).color, v = c.match(/[\d.]+/g).map(Number);
    const rgb = c.startsWith("color(srgb") ? v.slice(0, 3).map(x => x * 255) : v.slice(0, 3);
    const a = v[3] ?? 1;
    const r = e.getBoundingClientRect();
    return { sel, texte: e.textContent.trim().slice(0, 20), rgb, a: a * o, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  })), selecteurs);
  const style = await page.addStyleTag({ content: "*, *::before, *::after { color: transparent !important; -webkit-text-fill-color: transparent !important; text-shadow: none !important; }" });
  await page.waitForTimeout(100);
  const png = (await page.screenshot()).toString("base64");
  await style.evaluate(s => s.remove());
  return page.evaluate(async ({ png, textes }) => {
    const i = new Image(); i.src = "data:image/png;base64," + png; await i.decode();
    const c = document.createElement("canvas"); c.width = i.width; c.height = i.height;
    const x = c.getContext("2d"); x.drawImage(i, 0, 0);
    const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
    const L = ([r, g, b]) => .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b);
    return textes.map(t => {
      const d = x.getImageData(t.x, t.y, Math.max(1, t.w), Math.max(1, t.h)).data, px = [];
      for (let k = 0; k < d.length; k += 4) px.push([d[k], d[k + 1], d[k + 2]]);
      px.sort((p, q) => L(p) - L(q));
      const fond = px[px.length >> 1];
      const texte = t.rgb.map((v, k) => v * t.a + fond[k] * (1 - t.a));
      const [a, b] = [L(texte), L(fond)];
      return { sel: t.sel, texte: t.texte, ratio: +((Math.max(a, b) + .05) / (Math.min(a, b) + .05)).toFixed(2) };
    });
  }, { png, textes });
}

test("contrastes : la section et le filet à 4,5:1 au moins, en sombre et en clair", async () => {
  for (const theme of ["sombre", "clair"]) {
    await page?.close();
    await ouvrir({ affichage: etatTV({ filet: 30 }), profil: { theme } });
    const section = await contrastes([
      "#affichage-courant .definition", "#affichage-courant .jugement",
      ".mode-ecran .definition", ".mode-ecran .frequence", ".mode-ecran .jugement", ".mode-ecran .actif",
      ".ecran-actuel .aide", "#contenu-reglages .rangee .aide"]);
    await page.click('[data-cle="mode-1920x1080@60.000"]');
    await page.waitForTimeout(400);
    const filet = await contrastes(["#affichage-filet-titre", "#affichage-filet-detail", "#affichage-filet-reste", "#affichage-filet-choix .bouton span"]);
    const faibles = [...section, ...filet].filter(m => m.ratio < 4.5);
    assert.deepEqual(faibles, [], `${theme} : ${JSON.stringify([...section, ...filet])}`);
  }
});
