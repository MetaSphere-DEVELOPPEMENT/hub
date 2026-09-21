// Les images des modes en thème clair. Les photos des trois jeux sont sombres : sur un fond
// pâle on doit les retenir à 55 % d'opacité, et elles paraissent voilées — aucun réglage ne
// le rattrape. Le menu accepte donc, à côté de chaque photo, une variante claire
// (« mode-tv-clair.webp ») : en thème clair, si elle existe, c'est elle qu'on voit, entière ;
// sinon, rien ne change. Le dossier livré n'en contient pas tant que le propriétaire n'a pas
// déposé les siennes : ces tests FABRIQUENT les leurs, dans une copie du menu posée dans le
// dossier temporaire. De vrais fichiers, lus en file:// comme dans le kiosque — et de vrais
// fichiers absents : WebKit refuse un fichier local qui n'existe pas avant même d'émettre
// une requête, si bien qu'aucune interception de Playwright ne peut le simuler.
//
//   cd tests/menu && npm install && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium, webkit } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Le moteur : « chrome » par défaut, « chromium » celui de Playwright, « webkit » celui de
// la famille de la TV. Un rendu peut n'exister que dans l'un d'eux — la WebKitGTK du HUB
// ignorait les `mask-image` en dégradé que Chromium applique, et ça ne s'est vu que sur une
// photo du salon (18/09/2026). HUB_NAVIGATEUR=webkit rejoue toute la suite dans WebKit.
const lancerNavigateur = () => process.env.HUB_NAVIGATEUR === "webkit" ? webkit.launch()
  : chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });

const ici = path.dirname(fileURLToPath(import.meta.url));
const MENU = path.join(ici, "../../installer/menu");
const JEUX = ["jeu-1", "jeu-2", "jeu-3"], MODES = ["tv", "jeux", "bureau"];

let navigateur, page, variante, copie, PAGE;

function fauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: texte => window.__messages.push(JSON.parse(texte)) } } };
  window.HUB_INITIAL = initial;
}

before(async () => {
  navigateur = await lancerNavigateur();
  // La variante claire factice, aux proportions du jeu 2 (16/9) : un fond pâle, un sujet
  // orange vif à droite, et une bande SOMBRE en haut — si l'ombre de l'en-tête est bien à la
  // couleur claire du fond, cette bande ressort claire de la cuisson.
  const p = await navigateur.newPage();
  const donnees = await p.evaluate(() => {
    const c = document.createElement("canvas"); c.width = 1600; c.height = 900;
    const x = c.getContext("2d");
    x.fillStyle = "#eef1f7"; x.fillRect(0, 0, 1600, 900);
    x.fillStyle = "#ff7a00"; x.beginPath(); x.arc(1150, 480, 260, 0, 2 * Math.PI); x.fill();
    x.fillStyle = "#181818"; x.fillRect(0, 0, 1600, 60);
    return c.toDataURL("image/png").split(",")[1];
  });
  await p.close();
  // Un PNG sous un nom en .webp : les deux moteurs décodent une image à son contenu.
  variante = Buffer.from(donnees, "base64");
  copie = mkdtempSync(path.join(tmpdir(), "hub-menu-clair-"));
  cpSync(MENU, copie, { recursive: true });
  PAGE = pathToFileURL(path.join(copie, "index.html")).href;
});
after(async () => { await navigateur?.close(); if (copie) rmSync(copie, { recursive: true, force: true }); });
beforeEach(async () => { await page?.close(); });

// Chaque source donnée à une image par la page, dans l'ordre : ce que le menu DEMANDE, que
// le fichier existe ou non (WebKit n'émet pas de requête pour un fichier local absent).
function suivreSources() {
  window.__sources = [];
  const d = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
  Object.defineProperty(HTMLImageElement.prototype, "src", { ...d, set(v) { window.__sources.push(String(v)); d.set.call(this, v); } });
}
// « claires » : les variantes qui existent (« jeu-1/mode-tv »…, ou « * » pour toutes).
async function ouvrir(extra = {}, claires = []) {
  for (const jeu of JEUX) for (const mode of MODES) {
    const fichier = path.join(copie, "images", jeu, `mode-${mode}-clair.webp`);
    if (claires.includes("*") || claires.includes(`${jeu}/mode-${mode}`)) writeFileSync(fichier, variante);
    else rmSync(fichier, { force: true });
  }
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  await page.route(/open-meteo\.com/, r => r.abort());
  await page.addInitScript(suivreSources);
  await page.addInitScript(fauxPont, { retour: true, reglages: { profilActif: "p", profils: [{ id: "p", nom: "Salon", motif: "cinema", dernier: "tv", ...extra }], systeme: { meteo: { active: false } } } });
  await page.goto(PAGE + "?sans-intro");
  await page.waitForTimeout(400);
}
const demandes = async () => (await page.evaluate(() => window.__sources)).map(u => u.match(/images\/([^/]+\/mode-[^/]+)\.webp$/)?.[1]).filter(Boolean);
const toiles = () => page.evaluate(() => Object.fromEntries([...document.querySelectorAll("#visuel-mode canvas")].map(c => [c.dataset.visuel, {
  source: c.dataset.source.replace("images/", "").replace(".webp", ""), variante: c.dataset.variante, cuite: !!c.dataset.cuisson,
  opacite: c.classList.contains("visible") ? +(+getComputedStyle(c).opacity).toFixed(2) : null,
}])));
const touche = async (...touches) => { for (const k of touches) { await page.keyboard.press(k); await page.waitForTimeout(250); } };
const compter = async (filtre = () => true) => { const d = (await demandes()).filter(filtre); return Object.fromEntries([...new Set(d)].sort().map(n => [n, d.filter(x => x === n).length])); };
// Couleur moyenne, À L'ÉCRAN, d'un carré de la boîte de l'image (fractions de sa largeur et de
// sa hauteur : 104 × 94 % de la hauteur de l'écran, collée en haut à droite). Sur capture et
// non dans la toile : une image lue en file:// rend sa toile illisible par la page, et c'est
// de toute façon ce que voit le canapé — opacité comprise.
const couleur = async (fx, fy) => {
  const x = Math.round(1920 - 1080 * 1.04 + 1080 * 1.04 * fx) - 4, y = Math.max(0, Math.round(1080 * .94 * fy) - 4);
  const png = (await page.screenshot({ clip: { x, y, width: 8, height: 8 } })).toString("base64");
  return page.evaluate(async b64 => {
    const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode();
    const c = document.createElement("canvas"); c.width = 8; c.height = 8;
    const t = c.getContext("2d"); t.drawImage(i, 0, 0);
    const d = t.getImageData(0, 0, 8, 8).data, s = [0, 0, 0];
    for (let k = 0; k < d.length; k += 4) for (let j = 0; j < 3; j++) s[j] += d[k + j] / 64;
    return s.map(Math.round);
  }, png);
};
const ORANGE = c => Math.abs(c[0] - 255) < 12 && Math.abs(c[1] - 122) < 12 && c[2] < 16;

test("thème clair : la variante claire, quand elle existe, est cuite à la place de la photo sombre — entière", async () => {
  await ouvrir({ theme: "clair" }, ["*"]);
  assert.deepEqual(await toiles(), {
    tv: { source: "jeu-1/mode-tv-clair", variante: "claire", cuite: true, opacite: 1 },
    jeux: { source: "jeu-1/mode-jeux-clair", variante: "claire", cuite: true, opacite: null },
    bureau: { source: "jeu-1/mode-bureau-clair", variante: "claire", cuite: true, opacite: null },
  });
  // C'est bien elle qu'on voit : le sujet orange à droite…
  // … à l'écran, sa couleur EXACTE : ni voile, ni retenue, ni teinte du fond par-dessus.
  const sujet = await couleur(.72, .55);
  assert.ok(ORANGE(sujet), `sujet : ${sujet} au lieu de 255,122,0`);
  // … les trois variantes ont été lues une fois, et AUCUNE photo sombre : elle ne servirait à rien.
  assert.deepEqual(await compter(), { "jeu-1/mode-bureau-clair": 1, "jeu-1/mode-jeux-clair": 1, "jeu-1/mode-tv-clair": 1 });
  // Les autres modes aussi sont entiers, et le jeu 2 (retenu à .46 quand il est sombre) de même.
  await touche("ArrowRight");
  assert.equal((await toiles()).jeux.opacite, 1);
  await page.evaluate(() => { profil().visuels = "jeu-2"; appliquerTout(); });
  await page.waitForTimeout(500);
  assert.deepEqual((await toiles()).jeux, { source: "jeu-2/mode-jeux-clair", variante: "claire", cuite: true, opacite: 1 });
  assert.deepEqual(page.erreurs, []);
});

test("thème clair : ses fondus vont vers le clair du fond — bord éteint, ombre de l'en-tête claire", async () => {
  // Fond figé (animations réduites) : entre deux captures, seule la photo peut avoir changé.
  await ouvrir({ theme: "clair", animations: "reduites" }, ["*"]);
  // La bande sombre du haut de l'image ressort claire : l'ombre de l'en-tête est à la couleur
  // de base du thème clair, pas au noir du thème sombre.
  const haut = await couleur(.8, .02);
  assert.ok(Math.min(...haut) > 190, `haut de l'image : ${haut}`);
  // Le bord gauche de la boîte est éteint : avec ou sans photo, la page y est la même.
  const avec = (await page.screenshot({ clip: { x: 797, y: 300, width: 4, height: 300 } })).toString("base64");
  await page.evaluate(() => { document.getElementById("visuel-mode").style.visibility = "hidden"; });
  const sans = (await page.screenshot({ clip: { x: 797, y: 300, width: 4, height: 300 } })).toString("base64");
  const ecart = await page.evaluate(async lot => {
    const lire = async b64 => { const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode(); const c = document.createElement("canvas"); c.width = i.width; c.height = i.height; const t = c.getContext("2d"); t.drawImage(i, 0, 0); return t.getImageData(0, 0, c.width, c.height).data; };
    const [a, b] = [await lire(lot[0]), await lire(lot[1])];
    let max = 0;
    for (let k = 0; k < a.length; k++) max = Math.max(max, Math.abs(a[k] - b[k]));
    return max;
  }, [avec, sans]);
  // Deux niveaux sur 255 : le tramage des dégradés n'est pas le même d'une capture à l'autre.
  assert.ok(ecart <= 2, `la photo se voit encore à son bord gauche (${ecart}/255)`);
});

test("thème clair : sans variante, rien ne change — la photo sombre, retenue à .55 (.46 pour le jeu 2)", async () => {
  await ouvrir({ theme: "clair" }, []);
  assert.deepEqual(await toiles(), {
    tv: { source: "jeu-1/mode-tv", variante: "sombre", cuite: true, opacite: .55 },
    jeux: { source: "jeu-1/mode-jeux", variante: "sombre", cuite: true, opacite: null },
    bureau: { source: "jeu-1/mode-bureau", variante: "sombre", cuite: true, opacite: null },
  });
  await page.evaluate(() => { profil().visuels = "jeu-2"; appliquerTout(); });
  await page.waitForTimeout(500);
  assert.deepEqual((await toiles()).tv, { source: "jeu-2/mode-tv", variante: "sombre", cuite: true, opacite: .46 });
  // Aucune erreur de page, le filigrane ne reprend pas (la photo sombre est là)…
  assert.deepEqual(page.erreurs, []);
  assert.deepEqual(await page.evaluate(() => [document.getElementById("visuel-mode").hidden, document.getElementById("filigrane").hidden]), [false, true]);
  // … et chaque variante absente n'a été cherchée qu'UNE fois, quoi qu'on fasse ensuite :
  // changer de mode, rouvrir les réglages, passer en sombre et revenir, changer de jeu et revenir.
  await touche("ArrowRight", "ArrowRight", "ArrowLeft");
  await page.evaluate(() => ACTIONS.reglages("fond"));
  await page.waitForTimeout(400);
  await page.evaluate(() => { fermerTout(); profil().theme = "sombre"; appliquerTout(); });
  await page.waitForTimeout(400);
  await page.evaluate(() => { profil().theme = "clair"; profil().visuels = "jeu-1"; appliquerTout(); });
  await page.waitForTimeout(400);
  await page.evaluate(() => ACTIONS.reglages("fond"));
  await page.waitForTimeout(400);
  const claires = Object.entries(await compter(nom => nom.endsWith("-clair")));
  assert.ok(claires.length >= 6, `variantes cherchées : ${claires.map(c => c[0])}`);
  assert.deepEqual(claires.filter(([, n]) => n > 1), [], "une variante absente a été redemandée");
  assert.deepEqual(page.erreurs, []);
});

test("thème clair : une variante sur trois — elle seule est entière, les deux autres se replient", async () => {
  await ouvrir({ theme: "clair", visuels: "jeu-3" }, ["jeu-3/mode-jeux"]);
  assert.deepEqual(await toiles(), {
    tv: { source: "jeu-3/mode-tv", variante: "sombre", cuite: true, opacite: .55 },
    jeux: { source: "jeu-3/mode-jeux-clair", variante: "claire", cuite: true, opacite: null },
    bureau: { source: "jeu-3/mode-bureau", variante: "sombre", cuite: true, opacite: null },
  });
  await touche("ArrowRight");
  assert.equal((await toiles()).jeux.opacite, 1);
  await touche("ArrowRight");
  assert.equal((await toiles()).bureau.opacite, .55);
  // La photo sombre du mode qui a sa variante n'a pas été lue.
  assert.deepEqual(await compter(), { "jeu-3/mode-bureau": 1, "jeu-3/mode-bureau-clair": 1, "jeu-3/mode-jeux-clair": 1, "jeu-3/mode-tv": 1, "jeu-3/mode-tv-clair": 1 });
  assert.deepEqual(page.erreurs, []);
});

test("thème sombre : les variantes claires ne sont jamais demandées", async () => {
  await ouvrir({ theme: "sombre" }, ["*"]);
  assert.deepEqual(await toiles(), {
    tv: { source: "jeu-1/mode-tv", variante: "sombre", cuite: true, opacite: 1 },
    jeux: { source: "jeu-1/mode-jeux", variante: "sombre", cuite: true, opacite: null },
    bureau: { source: "jeu-1/mode-bureau", variante: "sombre", cuite: true, opacite: null },
  });
  await touche("ArrowRight", "ArrowLeft");
  await page.evaluate(() => ACTIONS.reglages("fond"));
  await page.waitForTimeout(400);
  assert.deepEqual((await demandes()).filter(d => d.endsWith("-clair")), []);
});

test("sombre ↔ clair : les bonnes images sont recuites sans recharger la page ni relire un fichier deux fois", async () => {
  await ouvrir({ theme: "sombre" }, ["*"]);
  await page.evaluate(() => { window.__memePage = true; });
  const vers = async theme => { await page.evaluate(t => { profil().theme = t; appliquerTout(); }, theme); await page.waitForTimeout(500); };
  await vers("clair");
  assert.deepEqual((await toiles()).tv, { source: "jeu-1/mode-tv-clair", variante: "claire", cuite: true, opacite: 1 });
  assert.ok(ORANGE(await couleur(.72, .55)), `la toile n'a pas été recuite avec la variante : ${await couleur(.72, .55)}`);
  await vers("sombre");
  assert.deepEqual((await toiles()).tv, { source: "jeu-1/mode-tv", variante: "sombre", cuite: true, opacite: 1 });
  assert.ok(!ORANGE(await couleur(.72, .55)), "la toile n'est pas revenue à la photo sombre");
  await vers("clair");
  await vers("sombre");
  await vers("clair");
  assert.equal((await toiles()).tv.variante, "claire");
  // Six fichiers en tout, chacun lu une fois : trois photos, trois variantes.
  assert.deepEqual(Object.values(await compter()), [1, 1, 1, 1, 1, 1], JSON.stringify(await compter()));
  assert.equal(await page.evaluate(() => window.__memePage), true, "la page a été rechargée");
  assert.deepEqual(page.erreurs, []);
});

test("thème auto : au lever du jour, l'accueil passe aux variantes claires tout seul", async () => {
  await ouvrir({ theme: "auto" }, ["*"]);
  // L'heure est celle de la machine de test : on la fixe, de nuit puis de jour, et on laisse
  // le menu s'en apercevoir comme il le fait toutes les cinq secondes (« horloge »).
  await page.clock.setFixedTime(new Date(2026, 8, 21, 23, 30));
  await page.evaluate(() => horloge());
  await page.waitForTimeout(500);
  assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "sombre");
  assert.equal((await toiles()).tv.variante, "sombre");
  await page.clock.setFixedTime(new Date(2026, 8, 22, 10, 0));
  await page.evaluate(() => horloge());
  await page.waitForTimeout(600);
  assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "clair");
  assert.deepEqual((await toiles()).tv, { source: "jeu-1/mode-tv-clair", variante: "claire", cuite: true, opacite: 1 });
  assert.deepEqual(page.erreurs, []);
});

test("réglages : en clair, la vignette d'un jeu montre sa variante claire, entière ; sinon la photo retenue", async () => {
  await ouvrir({ theme: "clair" }, ["jeu-2/mode-tv"]);
  await page.evaluate(() => ACTIONS.reglages("fond"));
  await page.waitForTimeout(600);
  const vignettes = await page.evaluate(() => [...document.querySelectorAll(".vignettes.visuels .apercu-visuel")].map(v => [v.dataset.source, v.dataset.variante, +(+getComputedStyle(v).opacity).toFixed(2)]));
  assert.deepEqual(vignettes, [
    ["images/jeu-1/mode-tv.webp", "sombre", .55],
    ["images/jeu-2/mode-tv-clair.webp", "claire", 1],
    ["images/jeu-3/mode-tv.webp", "sombre", .55],
  ]);
  assert.deepEqual(page.erreurs, []);
});

test("le dossier livré : un LISEZ-MOI dit quoi déposer, et aucune variante factice n'y traîne", () => {
  const dossier = path.join(MENU, "images");
  const notice = path.join(dossier, "LISEZ-MOI.md");
  assert.ok(existsSync(notice), "images/LISEZ-MOI.md manque");
  const texte = readFileSync(notice, "utf8");
  // Les neuf noms attendus y sont, tels que le menu les cherche.
  for (const jeu of JEUX) for (const mode of MODES) {
    assert.ok(texte.includes(`${jeu}/mode-${mode}-clair.webp`), `${jeu}/mode-${mode}-clair.webp n'est pas dans le LISEZ-MOI`);
  }
  // Une variante claire dans le dépôt doit être une vraie image, à côté de sa photo sombre.
  for (const jeu of JEUX) for (const f of readdirSync(path.join(dossier, jeu))) {
    assert.match(f, /^mode-(tv|jeux|bureau)(-clair)?\.webp$/, `fichier inattendu : ${jeu}/${f}`);
    if (f.includes("-clair")) assert.ok(existsSync(path.join(dossier, jeu, f.replace("-clair", ""))), `${jeu}/${f} n'a pas sa photo sombre`);
  }
});
