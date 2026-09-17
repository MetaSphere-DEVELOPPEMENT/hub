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

// Contraste réel sur le fond peint : on photographie la page sans ses textes, puis on compare la
// couleur de chaque texte (opacités des ancêtres comprises) à la médiane des pixels sous lui.
// Le fond animé est figé (animations réduites) pour que la mesure se répète.
async function contrastes(selecteurs) {
  const textes = await page.evaluate(sels => sels.flatMap(sel => [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length).map(e => {
    let o = 1; for (let x = e; x; x = x.parentElement) o *= parseFloat(getComputedStyle(x).opacity);
    const c = getComputedStyle(e).color, v = c.match(/[\d.]+/g).map(Number);
    const rgb = c.startsWith("color(srgb") ? v.slice(0, 3).map(x => x * 255) : v.slice(0, 3);
    const a = (c.startsWith("color(srgb") ? v[3] : v[3]) ?? 1;
    const r = e.getBoundingClientRect();
    return { sel, texte: e.textContent.trim().slice(0, 20), rgb, a: a * o, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  })), selecteurs);
  const style = await page.addStyleTag({ content: "*, *::before, *::after { color: transparent !important; -webkit-text-fill-color: transparent !important; text-shadow: none !important; } svg { visibility: hidden !important; } kbd { box-shadow: none !important; }" });
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

test("contrastes : accueil sombre, textes secondaires à 4,5:1 au moins", async () => {
  await ouvrir(reglages({}, { animations: "reduites" }));
  await page.evaluate(() => definirFocus(document.querySelector('[data-mode="gaming"]'), true));
  await page.waitForTimeout(200);
  const mesures = await contrastes([".carte:not(.focus) .detail", ".carte .touche-rapide", ".aides > span > span", ".carte.focus .ouvrir > span", ".reprises-titre"]);
  const faibles = mesures.filter(m => m.ratio < 4.5);
  assert.deepEqual(faibles, [], JSON.stringify(mesures));
});

test("contrastes : thème clair et initiales des avatars à 4,5:1 au moins", async () => {
  const telecommande = { url: "http://192.168.1.40:8790/", code: "482913", appairageOuvert: true, expire: Date.now() + 240000, telephones: 0 };
  for (const theme of ["clair", "sombre"]) {
    await page?.close();
    await ouvrir({ ...reglages({}, { theme, animations: "reduites", couleur: "ambre" }), telecommande });
    await page.evaluate(() => definirFocus(document.querySelector('[data-mode="bureau"]'), true));
    await page.waitForTimeout(200);
    const accueil = await contrastes(["#avatar-profil", ".carte.focus .ouvrir > span", ".carte:not(.focus) .detail", ".aides > span > span"]);
    await page.evaluate(() => ACTIONS.reglages("telecommande"));
    await page.waitForTimeout(400);
    const reglage = await contrastes([".code-appairage", "#contenu-reglages .aide", ".portee .avatar"]);
    const faibles = [...accueil, ...reglage].filter(m => m.ratio < 4.5);
    assert.deepEqual(faibles, [], `${theme} : ${JSON.stringify([...accueil, ...reglage])}`);
  }
});

test("contrastes : les couleurs d'état (jauge, pluie) sont des jetons du thème, pas des couleurs en dur", () => {
  const ext = readFileSync(path.join(MENU, "extensions.css"), "utf8");
  assert.doesNotMatch(ext.match(/\.jauge-temps[^\n]*\n/g).join(""), /#[0-9a-f]{3,6}/i);
  assert.doesNotMatch(readFileSync(path.join(MENU, "hub.js"), "utf8"), /color:\s*rgb\(90 170 255\)/);
});

// Audit du 17/09/2026 : anneaux de 1,5 à 2 px d'accent semi-transparent, option choisie
// distinguée par la seule couleur (1,48:1 en sombre, 1,25:1 en clair).
test("sélection : anneau épais et décalé sur toute cible, coche sur l'option choisie", async () => {
  for (const theme of ["sombre", "clair"]) {
    await page?.close();
    await ouvrir(reglages({}, { theme }));
    const cibles = ['[data-mode="gaming"]', '[data-cle="service-netflix"]', "#puce-profil", '[data-action="reglages"]', '[data-action="arret"]'];
    await page.evaluate(() => ACTIONS.reglages("apparence"));
    await page.waitForTimeout(300);
    for (const sel of [...cibles, '[data-cle="theme-clair"]', '[data-cle="section-fond"]']) {
      const anneau = await page.evaluate(s => {
        const e = document.querySelector(s);
        if (!e.closest(".calque")) { fermerTout(); }
        definirFocus(e, true);
        const cs = getComputedStyle(e), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
        const v = cs.outlineColor.match(/[\d.]+/g).map(Number);
        const lin = x => { x /= 255; return x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; };
        const L = ([r, g, b]) => .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b);
        const fond = getComputedStyle(document.documentElement).backgroundColor.match(/[\d.]+/g).map(Number);
        const [a, b] = [L(v), L(fond)];
        const r = { style: cs.outlineStyle, largeur: parseFloat(cs.outlineWidth) / rem, decalage: parseFloat(cs.outlineOffset) / rem, contraste: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) };
        if (e.closest(".calque") === null) ACTIONS.reglages("apparence");
        return r;
      }, sel);
      assert.equal(anneau.style, "solid", `${theme} ${sel}`);
      assert.ok(anneau.largeur >= .15 && anneau.decalage > 0, `${theme} ${sel} : ${JSON.stringify(anneau)}`);
      assert.ok(anneau.contraste >= 3, `${theme} ${sel} : anneau à ${anneau.contraste.toFixed(2)}:1 sur le fond`);
    }
    const coches = await page.evaluate(() => {
      const c = document.querySelector("#contenu-reglages .option.choisie"), n = c.parentElement.querySelector(".option:not(.choisie)");
      return [getComputedStyle(c, "::before").content, getComputedStyle(n, "::before").content];
    });
    assert.deepEqual(coches, ['"✓"', "none"], theme);
  }
});

// Audit du 17/09/2026 : les feuilles (réglages, météo, jeux, aide) étaient posées à 3 % du haut
// et 2,2 % de la droite, quelle que soit la marge de sécurité réglée pour la TV.
test("zone sûre : les feuilles respectent la marge de sécurité réglée", async () => {
  for (const marge of [5, 8]) {
    await page?.close();
    await ouvrir(reglages({ marge }));
    for (const calque of ["reglages", "meteo", "jeux", "aide"]) {
      const bords = await page.evaluate(c => {
        fermerTout(); ACTIONS[c]();
        const f = document.querySelector(`#${c} .feuille-corps`);
        f.style.transition = "none"; f.style.transform = "none";
        const r = f.getBoundingClientRect();
        return { haut: r.top / innerHeight * 100, bas: (innerHeight - r.bottom) / innerHeight * 100, droite: (innerWidth - r.right) / innerWidth * 100, gauche: r.left / innerWidth * 100 };
      }, calque);
      for (const [cote, v] of Object.entries(bords)) assert.ok(v >= marge - .1, `${calque}, marge ${marge} % : ${cote} à ${v.toFixed(1)} %`);
    }
  }
});

// Audit du 17/09/2026 : focus en .45 à .55 s avec rebond, rotation de 650 ms à chaque carte.
test("mouvement : la sélection suit en 200 ms au plus, sans rebond ; rien en touche maintenue", async () => {
  await ouvrir(reglages());
  const transitions = await page.evaluate(() => [".carte", ".tuile-service", ".puce", ".bouton", ".reprise"].map(sel => {
    const e = document.querySelector(sel); if (!e) return null;
    const cs = getComputedStyle(e);
    return { sel, durees: cs.transitionDuration.split(",").map(parseFloat), courbes: cs.transitionTimingFunction };
  }).filter(Boolean));
  for (const t of transitions) {
    assert.ok(Math.max(...t.durees) <= .2, `${t.sel} : ${t.durees}`);
    assert.doesNotMatch(t.courbes, /1\.56/, `${t.sel} : rebond`);
  }
  // Les rotations sont notées au moment où la page les lance : sur une machine chargée, une
  // animation de 180 ms peut être finie avant qu'on aille la chercher.
  await page.evaluate(() => {
    window.__rotations = [];
    const animer = Element.prototype.animate;
    Element.prototype.animate = function (k, o) { if (this.classList.contains("carte")) window.__rotations.push(o.duration); return animer.call(this, k, o); };
    definirFocus(document.querySelector('[data-mode="tv"]'), true);
    window.__rotations = [];
  });
  await page.keyboard.press("ArrowRight");
  const tournent = await page.evaluate(() => window.__rotations);
  assert.ok(tournent.length && tournent.every(d => d <= 200), `durées ${tournent}`);
  await page.evaluate(() => { definirFocus(document.querySelector('[data-mode="tv"]'), true); window.__rotations = []; });
  await page.evaluate(() => dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", repeat: true })));
  assert.deepEqual(await page.evaluate(() => window.__rotations), [], "aucune rotation pendant la répétition de la touche");
});
