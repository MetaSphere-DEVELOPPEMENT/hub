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
const FONDS_ANIMES = ["aurore", "nebuleuse", "ocean", "braise", "emeraude", "crepuscule"];

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
    // Pour chaque nappe : l'étendue parcourue en 8 s (c'était 30 s), en largeur et en
    // hauteur — on regarde le fond quelques secondes, pas une demi-minute.
    const etendues = [0, 1, 2, 3].map(i => {
      const xs = [], ys = [];
      for (let s = 0; s <= 8; s += .1) { const m = mouvementNappe(choix, i, s); xs.push(m.x); ys.push(m.y); }
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
    // Période en x de la première nappe, accélérée le 17/09/2026 avec les autres (22 → 13,
    // 23 → 12) : à 30 images par seconde, un aller-retour de 22 s paraissait immobile.
    for (const [choix, t] of [["ocean", 13], ["aurore", 12]]) {
      const a = mouvementNappe(choix, 0, 3.7), b = mouvementNappe(choix, 0, 3.7 + t);
      r.push(Math.abs(a.x - b.x));
    }
    // Braise, nappe 0 (phase nulle) : traversée de 15 s ; juste avant et juste après le rebouclage.
    const avant = mouvementNappe("braise", 0, 15 - .01), apres = mouvementNappe("braise", 0, 15 + .01);
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

const boucles = () => page.evaluate(() => window.hubBoucles());
const attendreBoucle = (nom, valeur) => page.waitForFunction(([n, v]) => window.hubBoucles()[n] === v, [nom, valeur], { timeout: 3000 });

test("fond : figé sous un calque, relancé en le refermant", async () => {
  await ouvrir(profilAvec({ fond: "aurore" }));
  assert.equal((await boucles()).fond, true);
  await page.keyboard.press("r");
  await attendreBoucle("fond", false);
  await page.keyboard.press("Escape");
  await attendreBoucle("fond", true);
  assert.deepEqual(page.erreurs, []);
});

test("fond : arrêté quand la page est cachée ou qu'un mode démarre", async () => {
  await ouvrir(profilAvec({ fond: "nebuleuse" }));
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  // Chromium ne coupe pas requestAnimationFrame d'une page qu'on dit cachée : c'est la boucle elle-même qui s'arrête.
  await attendreBoucle("fond", false);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await attendreBoucle("fond", true);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await attendreBoucle("fond", false);
});

test("manettes : pas de boucle sans manette ; une manette branchée pilote, débranchée la boucle s'arrête", async () => {
  await ouvrir({}, "?sans-intro", () => {
    window.__manette = null;
    navigator.getGamepads = () => [window.__manette];
  });
  await page.waitForTimeout(200);
  assert.equal((await boucles()).manettes, false);
  await page.evaluate(() => {
    window.__manette = { index: 0, axes: [0, 0], buttons: Array.from({ length: 16 }, () => ({ pressed: false })) };
    window.dispatchEvent(new Event("gamepadconnected"));
  });
  await attendreBoucle("manettes", true);
  await page.evaluate(() => { window.__manette.buttons[15] = { pressed: true }; });
  await page.waitForFunction(() => document.querySelector(".onglet.focus")?.dataset.mode === "gaming", null, { timeout: 3000 });
  await page.evaluate(() => { window.__manette = null; });
  await attendreBoucle("manettes", false);
});

// Le liseré tournant des anciennes cartes repeignait un dégradé conique masqué à chaque image.
// Les onglets n'ont aucune animation continue : la pastille glisse (transform), puis s'arrête.
test("onglets : aucune animation continue, la pastille glisse par transform", async () => {
  await ouvrir({ dernier: "gaming" });
  await page.waitForTimeout(1200);
  const enCours = () => page.evaluate(() => document.getAnimations().filter(a => a.playState === "running" && a.effect?.target?.closest?.("#modes")).length);
  assert.equal(await enCours(), 0);
  const transition = await page.evaluate(() => getComputedStyle(document.querySelector(".pastille-onglet")).transitionProperty);
  assert.equal(transition, "transform");
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(400);
  assert.equal(await enCours(), 0);
});

test("allègement : ni flou plein écran animé, ni flou d'arrière-plan sur les voiles et les puces", async () => {
  await ouvrir();
  const flous = await page.evaluate(() => {
    const flou = e => { const s = getComputedStyle(e); return [s.filter, s.backdropFilter || s.webkitBackdropFilter].filter(v => v && v !== "none"); };
    const r = { ecran: flou(document.querySelector(".ecran")) };
    document.body.classList.add("calque-ouvert");
    r.calque = flou(document.querySelector(".ecran"));
    document.body.classList.replace("calque-ouvert", "ambiant");
    r.ambiant = flou(document.querySelector(".ecran"));
    r.voiles = [...document.querySelectorAll(".voile, .feuille, #profils, #clavier, .puce, .bouton")].flatMap(flou);
    r.transitions = [...document.querySelectorAll(".ecran, .onglet, .pastille-onglet, .tuile-service, .puce, .bouton, .option")].map(e => getComputedStyle(e).transitionProperty).filter(t => /\ball\b|filter|box-shadow/.test(t));
    return r;
  });
  assert.deepEqual(flous, { ecran: [], calque: [], ambiant: [], voiles: [], transitions: [] });
});

test("compteur d'images : absent par défaut ; activé par hub-menu, il affiche et envoie son relevé", async () => {
  await ouvrir();
  assert.equal(await page.locator("#compteur-fps").count(), 0);
  await page.close();
  await ouvrir({ fps: true }, "?sans-intro&fps=1");
  await page.waitForFunction(() => window.__messages.some(m => m.type === "fps"), null, { timeout: 5000 });
  const releve = (await page.evaluate(() => window.__messages.filter(m => m.type === "fps")))[0];
  assert.equal(releve.ecran, "accueil");
  assert.ok(releve.moyenne > 5 && releve.min >= 0 && releve.pire > 0 && releve.fenetre >= 1, JSON.stringify(releve));
  assert.match(await page.textContent("#compteur-fps"), /i\/s .* accueil$/);
  assert.deepEqual(page.erreurs, []);
});

test("compteur d'images : HUB_INITIAL.fps suffit, sans paramètre d'adresse", async () => {
  await ouvrir({ fps: true });
  assert.equal(await page.locator("#compteur-fps").count(), 1);
});
