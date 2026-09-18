// Le mode ambiant seul, ouvert sur le bureau Ubuntu par hub-veille-bureau
// (hub-menu --ambiant) : directement l'horloge, jamais l'accueil, et sortir du mode
// ambiant demande à hub-menu de fermer la fenêtre sans rien lancer.
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

function installerFauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: texte => window.__messages.push(JSON.parse(texte)) } } };
  window.HUB_INITIAL = initial;
}

before(async () => {
  navigateur = await lancerNavigateur();
});
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

async function ouvrir(initial) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(installerFauxPont, initial);
  await page.goto(PAGE);
}
const types = () => page.evaluate(() => window.__messages.map(m => m.type));
const ambiant = () => page.evaluate(() => document.body.classList.contains("ambiant"));
const PIN = { sel: "abc", empreinte: "0".repeat(64) };

test("ambiant seul : l'horloge d'emblée, l'accueil jamais visible, aucune demande de code", async () => {
  await ouvrir({ retour: true, ambiantSeul: true, reglages: { profils: [{ id: "a", nom: "Camille", pin: PIN, verrouVeille: true }] } });
  assert.equal(await ambiant(), true);
  assert.equal(await page.evaluate(() => getComputedStyle(document.getElementById("accueil")).visibility), "hidden");
  assert.equal(await page.isVisible("#ambiant-heure"), true);
  assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll(".calque.ouvert")].map(c => c.id)), []);
  assert.deepEqual(page.erreurs, []);
});

test("ambiant seul : sortir du mode ambiant demande la fermeture, et rien ne se lance", async () => {
  await ouvrir({ retour: true, ambiantSeul: true });
  // La manette passe par reveiller() comme une touche : on l'appelle comme elle.
  await page.evaluate(() => reveiller());
  assert.deepEqual(await types(), ["ambiant-fin"]);
  // Même si des touches arrivaient malgré le filtre de GTK : aucun mode ne part.
  for (const k of ["3", "Enter", "1"]) { await page.keyboard.press(k); await page.waitForTimeout(80); }
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "tv" }));
  await page.waitForTimeout(900);
  assert.equal((await types()).includes("choix"), false);
});

test("menu ordinaire : l'extension ne fait rien", async () => {
  await ouvrir({ retour: true });
  await page.waitForTimeout(200);
  assert.equal(await ambiant(), false);
  assert.equal(await page.evaluate(() => document.documentElement.classList.contains("ambiant-seul")), false);
  await page.keyboard.press("a");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(200);
  assert.equal((await types()).includes("ambiant-fin"), false);
});
