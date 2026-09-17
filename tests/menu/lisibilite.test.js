// Lisible à trois mètres : tailles de texte, tenue à l'écran à chaque taille réglée.
// Les seuils viennent de l'audit de design du 17/09/2026 (installer/menu/README.md).
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const MENU = path.join(ici, "../../installer/menu");
const PAGE = pathToFileURL(path.join(MENU, "index.html")).href;

let navigateur, page;
before(async () => { navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" }); });
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

function fauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: t => window.__messages.push(JSON.parse(t)) } } };
  window.HUB_INITIAL = initial;
}
async function ouvrir(initial = {}, { largeur = 1920, hauteur = 1080 } = {}) {
  page = await navigateur.newPage({ viewport: { width: largeur, height: hauteur } });
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  await page.route(/open-meteo\.com/, r => r.abort());
  await page.addInitScript(fauxPont, { retour: true, ...initial });
  await page.goto(PAGE + "?sans-intro");
  await page.waitForTimeout(300);
}
const reglages = (systeme = {}, profil = {}) => ({ reglages: { profilActif: "p", profils: [{ id: "p", nom: "Samuel", ...profil }], systeme } });
const REPRISES = [{ titre: "Le Bureau des légendes", sousTitre: "S02 E04", fichier: "/a.mkv", position: 1200, duree: 3000 }, { titre: "Dune", fichier: "/b.mkv", position: 3000, duree: 9000 }];

// Tailles de tous les textes visibles sous « racine », en px ramenés à un écran de 1080 lignes.
const taillesTextes = racine => page.evaluate(sel => {
  const r = document.querySelector(sel), tailles = [];
  const marche = document.createTreeWalker(r, NodeFilter.SHOW_TEXT);
  for (let n = marche.nextNode(); n; n = marche.nextNode()) {
    const e = n.parentElement;
    if (!n.textContent.trim() || !e.getClientRects().length || e.closest("[hidden]")) continue;
    tailles.push({ texte: n.textContent.trim().slice(0, 30), px: parseFloat(getComputedStyle(e).fontSize) / innerHeight * 1080 });
  }
  return tailles;
}, racine);

test("typographie : toutes les tailles de police passent par les jetons de hub.css", () => {
  for (const fichier of ["hub.css", "extensions.css"]) {
    const css = readFileSync(path.join(MENU, fichier), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const enDur = [...css.matchAll(/font(?:-size)?:\s*([^;]+);/g)].map(m => m[1]).filter(v => !/var\(--t-|inherit|calc\(100vmin/.test(v));
    assert.deepEqual(enDur, [], `${fichier} : tailles en dur`);
  }
});

test("typographie : base de 1/44 du petit côté, aucun texte sous 22 px en 1080p", async () => {
  await ouvrir({ ...reglages(), reprises: REPRISES });
  assert.ok(Math.abs(await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize)) - 1080 / 44) < .1);
  for (const ecran of [null, "reglages", "meteo", "jeux", "aide"]) {
    if (ecran) await page.evaluate(e => { fermerTout(); ACTIONS[e](); }, ecran);
    await page.waitForTimeout(150);
    const racine = ecran ? `#${ecran}` : ".ecran";
    const petits = (await taillesTextes(racine)).filter(t => t.px < 22);
    assert.deepEqual(petits, [], `${racine} : textes trop petits`);
  }
});

// L'accueil ne défile pas : à chaque taille réglée et aux résolutions de la TV, avec la
// ligne « Continuer à regarder » et le streaming (le cas le plus chargé), tout tient.
for (const [largeur, hauteur] of [[1280, 720], [1920, 1080], [3840, 2160]]) {
  test(`tenue : l'accueil complet tient en ${largeur}×${hauteur} de S à XL`, async () => {
    await ouvrir({ ...reglages(), reprises: REPRISES }, { largeur, hauteur });
    for (const echelle of [.9, 1, 1.1, 1.2]) {
      const bilan = await page.evaluate(e => {
        reglages.systeme.echelle = e; appliquerTout();
        const ecran = document.querySelector(".ecran");
        const hors = [...ecran.querySelectorAll("[data-nav]")].filter(x => x.getClientRects().length).filter(x => {
          const r = x.getBoundingClientRect(); return r.bottom > innerHeight || r.right > innerWidth || r.left < 0 || r.top < 0;
        }).map(x => x.dataset.cle || x.dataset.mode || x.dataset.action);
        return { deborde: ecran.scrollHeight > ecran.clientHeight + 1, hors };
      }, echelle);
      assert.deepEqual(bilan, { deborde: false, hors: [] }, `taille ${echelle}`);
    }
  });
}
