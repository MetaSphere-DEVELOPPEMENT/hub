// L'enceinte réseau vue du menu : bandeau « en cours de lecture » (accueil et mode
// ambiant) et réglages. Le pont WebKit est remplacé par un faux qui note les messages ;
// hub-menu envoie l'état par window.hub.recevoir({ type: "lecture", etat }).
//
//   cd tests/menu && npm install && node --test lecture.test.js

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href + "?sans-intro";

let navigateur, page;

before(async () => {
  navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });
});
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

async function ouvrir(initial = {}) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  const erreurs = [];
  page.on("pageerror", e => erreurs.push(e.message));
  page.erreurs = erreurs;
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(initial => {
    window.__messages = [];
    window.webkit = { messageHandlers: { hub: { postMessage: m => window.__messages.push(JSON.parse(m)) } } };
    window.HUB_INITIAL = initial;
  }, initial);
  await page.goto(PAGE);
  await page.waitForTimeout(200);
}

const recevoir = message => page.evaluate(m => window.hub.recevoir(m), message);
const visible = id => page.evaluate(i => !document.getElementById(i).hidden, id);
const texte = id => page.evaluate(i => document.getElementById(i).textContent, id);
const touche = async (...touches) => { for (const k of touches) { await page.keyboard.press(k); await page.waitForTimeout(60); } };

const SPOTIFY = { source: "spotify", etat: "lecture", titre: "Clair de lune", artiste: "Debussy", album: null,
  appareil: "Pixel de Sam", pochette: null, ecran: false };

test("rien ne joue : ni puce ni ligne en mode ambiant", async () => {
  await ouvrir();
  assert.equal(await visible("lecture"), false);
  assert.equal(await visible("ambiant-lecture"), false);
  assert.deepEqual(page.erreurs, []);
});

test("Spotify démarre : la puce montre titre, artiste et source, puis disparaît à l'arrêt", async () => {
  await ouvrir();
  await recevoir({ type: "lecture", etat: SPOTIFY });
  assert.equal(await visible("lecture"), true);
  assert.equal(await texte("lecture-titre"), "Clair de lune");
  assert.equal(await texte("lecture-detail"), "Debussy — Spotify · Pixel de Sam");
  assert.match(await texte("annonce"), /Clair de lune/);
  await recevoir({ type: "lecture", etat: { ...SPOTIFY, etat: "pause" } });
  assert.match(await texte("lecture-detail"), /^En pause/);
  assert.equal(await page.evaluate(() => document.getElementById("lecture").classList.contains("en-pause")), true);
  await recevoir({ type: "lecture", etat: null });
  assert.equal(await visible("lecture"), false);
  assert.deepEqual(page.erreurs, []);
});

test("la puce n'est pas un arrêt de la navigation : les flèches restent sur les cartes", async () => {
  await ouvrir({ lecture: SPOTIFY });
  assert.equal(await visible("lecture"), true);
  assert.equal(await page.evaluate(() => document.getElementById("lecture").hasAttribute("data-nav")), false);
  await touche("ArrowUp", "ArrowRight");
  const focus = await page.evaluate(() => document.querySelector(".focus")?.id || document.querySelector(".focus")?.className);
  assert.notEqual(focus, "lecture");
});

test("au retour de Kodi, la musique en cours est affichée sans être annoncée", async () => {
  await ouvrir({ lecture: SPOTIFY, retour: true });
  assert.equal(await visible("lecture"), true);
  assert.doesNotMatch(await texte("annonce"), /Clair de lune/);
});

test("AirPlay avec pochette, et en mode ambiant", async () => {
  const pochette = pathToFileURL(path.join(ici, "../../installer/menu/pochette essai.jpg")).href;
  await ouvrir();
  await recevoir({ type: "lecture", etat: { source: "airplay", etat: "lecture", titre: "Titre", artiste: null, album: null,
    appareil: "iPhone", pochette, ecran: false } });
  const fond = await page.evaluate(() => document.getElementById("lecture-pochette").style.backgroundImage);
  assert.match(fond, /pochette%20essai\.jpg/);
  assert.equal(await page.evaluate(() => document.getElementById("lecture-pochette").classList.contains("sans-image")), false);
  await touche("a");
  assert.equal(await page.evaluate(() => document.body.classList.contains("ambiant")), true);
  assert.equal(await visible("ambiant-lecture"), true);
  assert.equal(await texte("ambiant-lecture-titre"), "Titre");
  // Un morceau suivant ne réveille pas le mode ambiant.
  await recevoir({ type: "lecture", etat: { source: "airplay", etat: "lecture", titre: "Suivant", pochette: null, ecran: false } });
  assert.equal(await page.evaluate(() => document.body.classList.contains("ambiant")), true);
  assert.equal(await texte("ambiant-lecture-titre"), "Suivant");
});

test("recopie d'écran : le bandeau dit d'où elle vient", async () => {
  await ouvrir();
  await recevoir({ type: "lecture", etat: { source: "ecran", etat: "lecture", appareil: "iPad de Camille", ecran: true } });
  assert.equal(await texte("lecture-titre"), "Recopie d'écran");
  assert.equal(await texte("lecture-detail"), "depuis iPad de Camille");
});

test("Réglages → Enceinte réseau : couper la recopie et renommer l'appareil sont enregistrés", async () => {
  await ouvrir({ reglages: { profilActif: "s", profils: [{ id: "s", nom: "Sam" }], systeme: { enceinte: { spotify: true, airplay: true, ecran: true, nom: "HUB" } } } });
  await page.evaluate(() => { location.hash = ""; });
  await touche("r");
  await page.click('[data-section="enceinte"]');
  await page.waitForSelector('[data-cle="enceinte-ecran-false"]');
  assert.match(await page.textContent("#contenu-reglages"), /Spotify Connect/);
  await page.click('[data-cle="enceinte-ecran-false"]');
  await page.waitForFunction(() => window.__messages.some(m => m.type === "reglages" && m.donnees.systeme.enceinte.ecran === false), null, { timeout: 5000 });
  await page.click('[data-cle="enceinte-nom"]');
  await page.waitForSelector("#clavier.ouvert");
  for (let i = 0; i < 3; i++) await page.keyboard.press("Backspace");
  await page.keyboard.type("salon");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => window.__messages.some(m => m.type === "reglages" && m.donnees.systeme.enceinte.nom === "Salon"), null, { timeout: 5000 });
  const dernier = await page.evaluate(() => window.__messages.filter(m => m.type === "reglages").at(-1).donnees.systeme.enceinte);
  assert.deepEqual(dernier, { spotify: true, airplay: true, ecran: false, nom: "Salon" });
  assert.deepEqual(page.erreurs, []);
});

test("des réglages anciens sans enceinte reçoivent les valeurs par défaut", async () => {
  await ouvrir({ reglages: { profilActif: "s", profils: [{ id: "s", nom: "Sam" }], systeme: { voix: true } } });
  const enceinte = await page.evaluate(() => { window.hub.recevoir({ type: "commande", nom: "reglages" }); return null; });
  assert.equal(enceinte, null);
  await page.click('[data-section="enceinte"]');
  await page.waitForSelector('[data-cle="enceinte-spotify-true"].choisie');
  assert.match(await page.textContent('[data-cle="enceinte-nom"]'), /HUB/);
});
