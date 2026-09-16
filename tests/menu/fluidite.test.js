// Fluidité du menu : ce qui bouge, à quel rythme, et ce qui s'arrête quand personne ne
// le voit. Ces tests vérifient des choix (périodes, boucles coupées), pas des images par
// seconde : Chromium n'est ni WebKitGTK ni l'UHD 630 de la TV (voir installer/menu/README.md).
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;
const FONDS_ANIMES = ["aurore", "nebuleuse", "ocean", "braise"];

let navigateur, page;

function installerFauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: texte => window.__messages.push(JSON.parse(texte)) } } };
  window.HUB_INITIAL = initial;
}

before(async () => {
  navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });
});
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

async function ouvrir(initial = {}, requete = "?sans-intro", avant = null) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  const erreurs = [];
  page.on("pageerror", e => erreurs.push(e.message));
  page.erreurs = erreurs;
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(installerFauxPont, { retour: true, ...initial });
  if (avant) await page.addInitScript(avant);
  await page.goto(PAGE + requete);
  await page.waitForTimeout(250);
}

const profilAvec = extra => ({ reglages: { profilActif: "a", profils: [{ id: "a", nom: "A", ...extra }], systeme: { meteo: { active: false } } } });

test("fond : chaque mouvement de nappe revient en 30 s au plus, sur une amplitude visible", async () => {
  await ouvrir();
  const releve = await page.evaluate(fonds => fonds.map(choix => {
    const { mouvementNappe, periodesFond } = window.hubFond;
    const periodes = periodesFond(choix);
    // Pour chaque nappe : l'étendue parcourue en 30 s, en largeur et en hauteur.
    const etendues = [0, 1, 2, 3].map(i => {
      const xs = [], ys = [];
      for (let s = 0; s <= 30; s += .1) { const m = mouvementNappe(choix, i, s); xs.push(m.x); ys.push(m.y); }
      return { x: Math.max(...xs) - Math.min(...xs), y: Math.max(...ys) - Math.min(...ys) };
    });
    return { choix, periodes, etendues };
  }), FONDS_ANIMES);
  for (const { choix, periodes, etendues } of releve) {
    assert.ok(periodes.length > 0, choix);
    assert.ok(Math.max(...periodes) <= 30, `${choix} : période la plus longue ${Math.max(...periodes)} s`);
    assert.ok(Math.min(...periodes) >= 10, `${choix} : un fond de salon reste calme`);
    // Au moins une direction parcourt un sixième de l'écran : ça se voit à trois mètres.
    for (const e of etendues) assert.ok(Math.max(e.x, e.y) >= .16, `${choix} : nappe presque immobile ${JSON.stringify(e)}`);
  }
});

test("fond : les mouvements sont périodiques, les braises s'éteignent avant de reboucler", async () => {
  await ouvrir();
  const ecarts = await page.evaluate(() => {
    const { mouvementNappe } = window.hubFond;
    const r = [];
    for (const [choix, t] of [["ocean", 22], ["aurore", 23]]) {
      const a = mouvementNappe(choix, 0, 3.7), b = mouvementNappe(choix, 0, 3.7 + t);
      r.push(Math.abs(a.x - b.x));
    }
    // Braise, nappe 0 (phase nulle) : traversée de 26 s ; juste avant et juste après le rebouclage.
    const avant = mouvementNappe("braise", 0, 26 - .01), apres = mouvementNappe("braise", 0, 26 + .01);
    return { r, avant: avant.eclat, apres: apres.eclat };
  });
  for (const e of ecarts.r) assert.ok(e < 1e-9);
  assert.ok(ecarts.avant < .01 && ecarts.apres < .01, JSON.stringify(ecarts));
});

test("fond : redessiné à 30 images par seconde, pas à chaque image de l'écran", async () => {
  await ouvrir(profilAvec({ fond: "ocean" }));
  const { dessins, images } = await page.evaluate(() => new Promise(fin => {
    const contexte = document.getElementById("fond").getContext("2d");
    const original = contexte.fillRect.bind(contexte);
    let remplissages = 0;
    contexte.fillRect = (...a) => { remplissages++; return original(...a); };
    let images = 0;
    const debut = performance.now();
    (function compter(t) { images++; if (t - debut < 2000) requestAnimationFrame(compter); else fin({ dessins: remplissages / 5, images }); })(debut);
  }));
  // Cinq fillRect par dessin (la base et quatre nappes).
  assert.ok(dessins <= 66, `${dessins} dessins en 2 s`);
  assert.ok(dessins >= 20, `${dessins} dessins en 2 s : le fond ne bouge plus`);
  assert.ok(images > dessins, `${images} images, ${dessins} dessins`);
});

test("fond : mouvement réduit, il ne bouge plus et la boucle s'arrête", async () => {
  await ouvrir(profilAvec({ fond: "ocean", animations: "reduites" }));
  await page.waitForTimeout(300);
  const avant = await page.evaluate(() => document.getElementById("fond").toDataURL());
  await page.waitForTimeout(600);
  assert.equal(await page.evaluate(() => document.getElementById("fond").toDataURL()), avant);
});
