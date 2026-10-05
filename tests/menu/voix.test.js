// Réglages → Voix et sons : le mot d'éveil. Ce que la page enregistre pour hub-voix
// (systeme.motEveil), ce qu'elle dit de ce que hub-voix écoute vraiment (voix.json), et
// le refus d'un prénom inconnu du modèle. Le pont WebKit est un faux qui note chaque message.
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium, webkit } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const lancerNavigateur = () => process.env.HUB_NAVIGATEUR === "webkit" ? webkit.launch()
  : chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;

let navigateur, page;

function installerFauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: texte => { window.__messages.push(JSON.parse(texte)); } } } };
  window.HUB_INITIAL = initial;
}
before(async () => { navigateur = await lancerNavigateur(); });
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

async function ouvrir(initial = {}) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  const erreurs = [];
  page.on("pageerror", e => erreurs.push(e.message));
  page.erreurs = erreurs;
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(installerFauxPont, initial);
  await page.goto(PAGE + "?sans-intro");
  await page.waitForTimeout(250);
}

const attendreReglages = verifie => page.waitForFunction(v => {
  const m = window.__messages.filter(x => x.type === "reglages").at(-1);
  return m && new Function("d", `return (${v})(d)`)(m.donnees);
}, verifie.toString(), { timeout: 5000 });
const section = () => page.textContent("#contenu-reglages");
const reglages = (systeme = {}, profil = {}) => ({ retour: true, reglages: { profilActif: "p", profils: [{ id: "p", nom: "Alex", ...profil }], systeme } });

test("par défaut, la page dit « OK HUB », pas « HUB » seul : c'est ce que hub-voix écoute", async () => {
  await ouvrir(reglages());
  await page.evaluate(() => ACTIONS.reglages("voix"));
  await page.waitForTimeout(200);
  assert.match(await section(), /Dis « OK HUB » puis ta commande/);
  assert.ok(await page.locator('[data-cle="mot-eveil-ok-hub"].choisie').count(), "le préréglage par défaut est marqué choisi");
  assert.deepEqual(page.erreurs, []);
});

test("choisir « Salut HUB » l'enregistre pour tout le HUB, et la phrase d'aide suit", async () => {
  await ouvrir(reglages());
  await page.evaluate(() => ACTIONS.reglages("voix"));
  await page.click('[data-cle="mot-eveil-salut-hub"]');
  await attendreReglages(d => d.systeme.motEveil === "salut-hub");
  assert.match(await section(), /Dis « Salut HUB » puis ta commande/);
  // La page redemande à hub-menu ce que hub-voix a retenu, après qu'il a relu les réglages.
  await page.waitForFunction(() => window.__messages.filter(m => m.type === "voix-mot").length >= 1, null, { timeout: 5000 });
});

test("un prénom se tape au clavier de l'écran ; refusé par hub-voix, la page dit pourquoi et ce qui est gardé", async () => {
  await ouvrir(reglages());
  await page.evaluate(() => ACTIONS.reglages("voix"));
  await page.click('[data-cle="mot-eveil-prenom"]');
  assert.ok(await page.locator("#clavier.ouvert").count(), "le clavier de l'écran s'ouvre");
  for (const lettre of "nestor") await page.click(`[data-cle="touche-${lettre}"]`);
  await page.click('[data-cle="valider"]');
  await attendreReglages(d => d.systeme.motEveil === "Nestor");
  assert.match(await section(), /Dis « Nestor » puis ta commande/);
  assert.ok(await page.locator('[data-cle="mot-eveil-prenom"].choisie').count());
  // hub-voix ne connaît pas ce prénom : il garde « OK HUB » et l'écrit dans voix.json.
  await page.evaluate(() => window.hub.recevoir({ type: "voix-mot", etat: { motEveil: "ok-hub", demande: "nestor", refus: "inconnu", phrases: ["okay hub", "ok hub"], langue: "fr" } }));
  await page.waitForTimeout(100);
  assert.match(await section(), /« Nestor » est inconnu du modèle de voix : « OK HUB » est gardé/);
  assert.match(await section(), /Dis « OK HUB » puis ta commande/, "la phrase d'aide dit ce que hub-voix écoute vraiment");
});

test("en anglais, les préréglages disent ce qu'on prononce : « Hey HUB » pour Salut et Dis HUB", async () => {
  await ouvrir(reglages({ motEveil: "dis-hub" }, { langue: "en" }));
  await page.evaluate(() => ACTIONS.reglages("voix"));
  await page.waitForTimeout(200);
  assert.match(await section(), /Say "Hey HUB \(Dis HUB\)" then your command/);
  assert.equal(await page.textContent('[data-cle="mot-eveil-salut-hub"]'), "Hey HUB (Salut HUB)");
});

test("l'état connu au démarrage (voix.json) prime sur le réglage demandé", async () => {
  await ouvrir({ ...reglages({ motEveil: "zorglub" }), voixEtat: { motEveil: "ok-hub", demande: "zorglub", refus: "inconnu", phrases: ["okay hub", "ok hub"], langue: "fr" } });
  await page.evaluate(() => ACTIONS.reglages("voix"));
  await page.waitForTimeout(200);
  assert.match(await section(), /Dis « OK HUB » puis ta commande/);
  assert.match(await section(), /« Zorglub » est inconnu du modèle de voix/);
});
