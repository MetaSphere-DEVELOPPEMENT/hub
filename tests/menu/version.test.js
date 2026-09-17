// Le numéro de version lisible : « Version 1.0.0 » dans À propos, dans l'annonce d'une
// mise à jour et pendant l'installation, l'empreinte du commit restant à côté, en petit.
// Un HUB installé avant les numéros n'en a pas : l'empreinte seule, comme avant.
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const RACINE = path.join(ici, "../..");
const PAGE = pathToFileURL(path.join(RACINE, "installer/menu/index.html")).href;

let navigateur, page;
before(async () => { navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" }); });
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

function fauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: t => window.__messages.push(JSON.parse(t)) } } };
  window.HUB_INITIAL = initial;
}
async function ouvrir(profil = {}) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  await page.route(/open-meteo\.com/, r => r.abort());
  await page.addInitScript(fauxPont, { retour: true, reglages: { profilActif: "p", profils: [{ id: "p", nom: "Samuel", animations: "reduites", ...profil }] } });
  await page.goto(PAGE + "?sans-intro");
  await page.waitForTimeout(250);
}
const infos = (extra = {}) => page.evaluate(i => window.hub.recevoir(i), {
  type: "infos", machine: "hub", systeme: "Ubuntu 26.04", adresse: "192.168.1.40",
  allumeDepuis: "2 h", disqueLibre: "180 Go",
  version: "1.0.0", commit: "a03afa7", versionDate: "2026-09-17",
  nouveautes: "Première version numérotée. Réglages → Affichage.", ...extra,
});
const apropos = async () => { await page.evaluate(() => ACTIONS.reglages("apropos")); await page.waitForTimeout(150); };

test("le dépôt porte un numéro, et NOUVEAUTES.md commence par lui", () => {
  const numero = readFileSync(path.join(RACINE, "VERSION"), "utf8").trim();
  assert.match(numero, /^\d+\.\d+\.\d+$/);
  const premiere = readFileSync(path.join(RACINE, "NOUVEAUTES.md"), "utf8").split("\n").find(l => l.startsWith("## "));
  assert.ok(premiere.startsWith(`## ${numero} — `), `${premiere} ne porte pas ${numero}`);
});

test("À propos : le numéro en grand, l'empreinte et la date en petit", async () => {
  await ouvrir();
  await apropos();
  await infos();
  await page.waitForTimeout(150);
  assert.equal(await page.textContent(".version-info .valeur"), "1.0.0");
  assert.equal(await page.textContent(".version-info .version-detail"), "commit a03afa7 · du 2026-09-17");
  // L'empreinte reste plus petite que le numéro : c'est le numéro qu'on lit de loin.
  const tailles = await page.evaluate(() => [".version-info .valeur", ".version-info .version-detail"]
    .map(s => parseFloat(getComputedStyle(document.querySelector(s)).fontSize)));
  assert.ok(tailles[0] > tailles[1], tailles.join(" / "));
  assert.deepEqual(page.erreurs, []);
});

test("À propos : ce qu'apporte la version, sous le bouton Installer", async () => {
  await ouvrir();
  await apropos();
  await infos();
  await page.waitForTimeout(150);
  assert.match(await page.textContent("#nouveautes"), /Nouveautés · 1\.0\.0/);
  assert.match(await page.textContent("#nouveautes .aide"), /Première version numérotée/);
  // Le HUB n'a pas de NOUVEAUTES.md : rien ne s'affiche, et surtout pas une carte vide.
  await infos({ nouveautes: null });
  await page.waitForTimeout(150);
  assert.equal(await page.locator("#nouveautes").count(), 0);
});

test("À propos : un HUB installé avant les numéros garde son empreinte", async () => {
  await ouvrir();
  await apropos();
  await infos({ version: null, versionDate: null });
  await page.waitForTimeout(150);
  assert.equal(await page.textContent(".version-info .valeur"), "inconnue");
  assert.equal(await page.textContent(".version-info .version-detail"), "commit a03afa7");
});

test("mise à jour : « version 1.1.0 disponible », et l'empreinte si aucun numéro", async () => {
  await ouvrir();
  await apropos();
  const verif = (v = {}) => page.evaluate(x => window.hub.recevoir({ type: "maj", verification: x, etat: null }), { disponible: true, verifiable: true, distant: "abc1234", installee: "a03afa7", ...v });
  await verif({ numeroDistant: "1.1.0" });
  await page.waitForTimeout(150);
  assert.match(await page.textContent("#contenu-reglages"), /Nouvelle version disponible \(1\.1\.0\)/);
  // Pas d'étiquette sur le commit distant : l'empreinte, comme avant, plutôt qu'un faux numéro.
  await verif();
  await page.waitForTimeout(150);
  assert.match(await page.textContent("#contenu-reglages"), /Nouvelle version disponible \(abc1234\)/);
});

test("mise à jour : l'annonce et les étapes disent le numéro quand il est connu", async () => {
  await ouvrir();
  await page.evaluate(() => window.hub.recevoir({
    type: "maj", auto: true, annoncer: true,
    verification: { disponible: true, verifiable: true, distant: "abc1234", numeroDistant: "1.1.0", installee: "a03afa7" },
  }));
  assert.equal(await page.textContent("#annonce"), "Nouvelle version du HUB (1.1.0) : Réglages → À propos.");
  await apropos();
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "telechargement", version: "abc1234", numero: "1.1.0" } }));
  await page.waitForTimeout(150);
  assert.match(await page.textContent("#contenu-reglages"), /Téléchargement de la version 1\.1\.0…/);
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "terminee", version: "abc1234", numero: "1.1.0" } }));
  await page.waitForTimeout(150);
  assert.match(await page.textContent("#annonce"), /Mise à jour installée \(1\.1\.0\)/);
});

test("anglais : le numéro et les nouveautés sont traduits", async () => {
  await ouvrir({ langue: "en" });
  await apropos();
  await infos();
  await page.waitForTimeout(150);
  assert.equal(await page.textContent(".version-info .valeur"), "1.0.0");
  assert.equal(await page.textContent(".version-info .version-detail"), "commit a03afa7 · of 2026-09-17");
  assert.match(await page.textContent("#nouveautes"), /What's new · 1\.0\.0/);
});
