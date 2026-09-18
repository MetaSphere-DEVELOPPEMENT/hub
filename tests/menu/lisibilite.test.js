// Lisible à trois mètres : tailles de texte, tenue à l'écran à chaque taille réglée.
// Les seuils viennent de l'audit de design du 17/09/2026 (installer/menu/README.md).
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium, webkit } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
import path from "node:path";

// Le moteur : « chrome » par défaut, « chromium » celui de Playwright, « webkit » celui de
// la famille de la TV. Un rendu peut n'exister que dans l'un d'eux — la WebKitGTK du HUB
// ignorait les `mask-image` en dégradé que Chromium applique, et ça ne s'est vu que sur une
// photo du salon (18/09/2026). HUB_NAVIGATEUR=webkit rejoue toute la suite dans WebKit.
const lancerNavigateur = () => process.env.HUB_NAVIGATEUR === "webkit" ? webkit.launch()
  : chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });

const ici = path.dirname(fileURLToPath(import.meta.url));
const MENU = path.join(ici, "../../installer/menu");
const PAGE = pathToFileURL(path.join(MENU, "index.html")).href;

let navigateur, page;
before(async () => { navigateur = await lancerNavigateur(); });
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
// Un second profil au nom le plus long que le menu accepte (16 caractères) : c'est lui
// qu'on efface dans les essais de la confirmation de suppression.
const DEUX_PROFILS = (profil = {}) => ({
  retour: true,
  reglages: { profilActif: "p", profils: [{ id: "p", nom: "Samuel", ...profil }, { id: "q", nom: "Marie-Ségolène K" }], systeme: {} },
});
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
    // L'indicateur Internet sélectionné, libellé le plus long déplié : le pire cas de l'en-tête.
    await page.evaluate(() => { window.hub.recevoir({ type: "internet", etat: "local" }); definirFocus(document.querySelector("#puce-internet"), true); });
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

// L'accueil « Cinéma » : chaque motif de fond, figé (animations réduites), sous les mêmes textes.
const TEXTES_ACCUEIL = ["#salut", ".date", ".heros-sur", ".heros-texte", ".heros-services span", ".lancer > span", ".onglet.focus .nom", ".onglet:not(.focus) .nom", ".aides > span > span", ".reprises-titre"];
test("contrastes : accueil sombre, sur chaque motif, textes à 4,5:1 au moins", async () => {
  for (const motif of ["cinema", "rubans", "profondeur", "faisceaux", "nappes"]) {
    await page?.close();
    await ouvrir({ ...reglages({}, { animations: "reduites", motif }), reprises: REPRISES });
    await page.evaluate(() => definirFocus(document.querySelector('[data-mode="gaming"]'), true));
    await page.waitForTimeout(250);
    const mesures = await contrastes(TEXTES_ACCUEIL);
    const faibles = mesures.filter(m => m.ratio < 4.5);
    assert.deepEqual(faibles, [], `${motif} : ${JSON.stringify(mesures)}`);
  }
});

test("contrastes : thème clair et initiales des avatars à 4,5:1 au moins", async () => {
  const telecommande = { url: "http://192.168.1.40:8790/", code: "482913", appairageOuvert: true, expire: Date.now() + 240000, telephones: 0 };
  for (const theme of ["clair", "sombre"]) {
    await page?.close();
    await ouvrir({ ...reglages({}, { theme, animations: "reduites", couleur: "ambre", motif: "cinema" }), telecommande });
    await page.evaluate(() => definirFocus(document.querySelector('[data-mode="bureau"]'), true));
    await page.waitForTimeout(200);
    const accueil = await contrastes(["#avatar-profil", ...TEXTES_ACCUEIL]);
    await page.evaluate(() => ACTIONS.reglages("telecommande"));
    await page.waitForTimeout(400);
    const reglage = await contrastes([".code-appairage", "#contenu-reglages .aide", ".portee .avatar"]);
    const faibles = [...accueil, ...reglage].filter(m => m.ratio < 4.5);
    assert.deepEqual(faibles, [], `${theme} : ${JSON.stringify([...accueil, ...reglage])}`);
  }
});

// L'image du mode (installer/menu/images) occupe la moitié droite de l'accueil : le héros
// reste à gauche, l'heure et le profil passent au-dessus d'elle. Mesuré sur les trois images
// de chacun des trois jeux, dans les deux thèmes, fond figé — le jeu 2, le plus lumineux,
// est celui à surveiller. Le titre du héros est un texte d'affiche : 3:1 suffirait
// (WCAG 1.4.3), on le tient au même seuil que le reste.
test("contrastes : le héros et l'en-tête au-dessus de chaque image, les trois jeux, sombre et clair", async () => {
  const faibles = [], mesures = [];
  for (const theme of ["sombre", "clair"]) {
    for (const jeu of ["jeu-1", "jeu-2", "jeu-3"]) {
      for (const [mode, image] of [["tv", "tv"], ["gaming", "jeux"], ["bureau", "bureau"]]) {
        await page?.close();
        await ouvrir({ ...reglages({}, { theme, animations: "reduites", motif: "cinema", visuels: jeu }), reprises: REPRISES });
        await page.evaluate(m => definirFocus(document.querySelector(`.onglet[data-mode="${m}"]`), true), mode);
        await page.waitForTimeout(250);
        assert.deepEqual(await page.evaluate(() => {
          const v = document.getElementById("visuel-mode");
          return [v.dataset.jeu, ...[...v.querySelectorAll("canvas.visible")].map(i => i.dataset.visuel)];
        }), [jeu, image], `${theme} ${jeu} ${mode} : ce n'est pas l'image attendue`);
        const m = await contrastes(["#heros-titre", ".heure", "#nom-profil", ...TEXTES_ACCUEIL]);
        mesures.push(...m.map(x => ({ theme, jeu, image, ...x })));
        faibles.push(...m.filter(x => x.ratio < 4.5).map(x => ({ theme, jeu, image, ...x })));
      }
    }
  }
  assert.deepEqual(faibles, [], JSON.stringify(mesures));
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
    const cibles = ['[data-cle="service-netflix"]', "#puce-profil", '[data-action="reglages"]', '[data-action="arret"]'];
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

// Les onglets n'ont pas d'anneau : la pastille pleine est l'indicateur de focus. WCAG 2.4.13 :
// elle couvre l'onglet, et ses pixels changent d'au moins 3:1 entre l'onglet sélectionné et
// le même onglet quand le focus est sur une autre rangée (pastille en retrait), comme contre
// le rail d'un onglet non choisi.
test("sélection : la pastille des onglets est un indicateur de focus conforme", async () => {
  for (const theme of ["sombre", "clair"]) {
    for (const mode of ["tv", "gaming", "bureau"]) {
      await page?.close();
      await ouvrir(reglages({}, { theme, animations: "reduites", motif: "cinema", dernier: mode }));
      const autre = mode === "tv" ? "bureau" : "tv";
      const zones = await page.evaluate(([m, a]) => {
        const o = document.querySelector(`[data-mode="${m}"]`);
        definirFocus(o, true);
        const r = o.getBoundingClientRect(), p = document.querySelector(".pastille-onglet").getBoundingClientRect(), b = document.querySelector(`[data-mode="${a}"]`).getBoundingClientRect();
        const recouvre = Math.max(0, Math.min(r.right, p.right) - Math.max(r.left, p.left)) * Math.max(0, Math.min(r.bottom, p.bottom) - Math.max(r.top, p.top)) / (r.width * r.height);
        // Une bande sous le libellé, dans la pastille : là où ni le texte ni le pictogramme ne passent.
        const bande = x => ({ x: Math.round(x.left + x.width * .1), y: Math.round(x.bottom - x.height * .28), w: Math.round(x.width * .8), h: Math.round(x.height * .12) });
        return { recouvre, onglet: bande(r), rail: bande(b) };
      }, [mode, autre]);
      assert.ok(zones.recouvre > .9, `${theme} ${mode} : la pastille couvre ${zones.recouvre}`);
      const luminance = async zone => {
        await page.waitForTimeout(250);
        const png = (await page.screenshot({ clip: { x: zone.x, y: zone.y, width: zone.w, height: zone.h } })).toString("base64");
        return page.evaluate(async png => {
          const i = new Image(); i.src = "data:image/png;base64," + png; await i.decode();
          const c = document.createElement("canvas"); c.width = i.width; c.height = i.height;
          const x = c.getContext("2d"); x.drawImage(i, 0, 0);
          const d = x.getImageData(0, 0, i.width, i.height).data, px = [];
          for (let k = 0; k < d.length; k += 4) px.push([d[k], d[k + 1], d[k + 2]]);
          const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
          const L = ([r, g, b]) => .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b);
          px.sort((p, q) => L(p) - L(q));
          return L(px[px.length >> 1]);
        }, png);
      };
      const ratio = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      const pleine = await luminance(zones.onglet);
      const rail = await luminance(zones.rail);
      await page.evaluate(() => definirFocus(document.querySelector('[data-cle="service-youtube"]'), true));
      const enRetrait = await luminance(zones.onglet);
      assert.ok(ratio(pleine, enRetrait) >= 3, `${theme} ${mode} : pastille pleine / en retrait ${ratio(pleine, enRetrait).toFixed(2)}:1`);
      assert.ok(ratio(pleine, rail) >= 3, `${theme} ${mode} : pastille / rail ${ratio(pleine, rail).toFixed(2)}:1`);
    }
  }
});

// Le menu d'arrêt : six entrées, nom en --t-2 et explication en --t-1 (le plancher). Mesuré
// une entrée sélectionnée, là où le fond change sous le texte, puis sur la confirmation.
test("contrastes : le menu d'arrêt et sa confirmation, sombre et clair", async () => {
  const faibles = [], mesures = [];
  for (const theme of ["sombre", "clair"]) {
    await page?.close();
    await ouvrir(reglages({}, { theme, animations: "reduites", motif: "cinema" }));
    await page.evaluate(() => { ACTIONS.arret(); definirFocus(document.querySelector('[data-cle="arret-eteindre"]'), true); });
    await page.waitForTimeout(350);
    const menu = await contrastes(["#arret h2", "#arret .dialogue > p", ".action-nom", ".action-detail"]);
    await page.evaluate(() => ACTIONS.eteindre());
    await page.waitForTimeout(350);
    const confirmation = await contrastes(["#confirmer-titre", "#confirmer-detail", "#confirmer .bouton span"]);
    mesures.push(...[...menu, ...confirmation].map(m => ({ theme, ...m })));
    faibles.push(...[...menu, ...confirmation].filter(m => m.ratio < 4.5).map(m => ({ theme, ...m })));
  }
  assert.deepEqual(faibles, [], JSON.stringify(mesures));
});

// La même question, posée avant d'effacer un profil : le nom du profil y est deux fois, et
// la phrase qui dit ce qu'on perd s'enroule sur plusieurs lignes.
test("contrastes : la confirmation de suppression d'un profil, sombre et clair", async () => {
  const faibles = [], mesures = [];
  for (const theme of ["sombre", "clair"]) {
    await page?.close();
    await ouvrir(DEUX_PROFILS({ theme, animations: "reduites", motif: "cinema" }));
    await page.evaluate(() => { ouvrirEditeur(reglages.profils[1]); ACTIONS["supprimer-profil"](); });
    await page.waitForTimeout(400);
    const m = await contrastes(["#confirmer-titre", "#confirmer-detail", "#confirmer .bouton span"]);
    mesures.push(...m.map(x => ({ theme, ...x })));
    faibles.push(...m.filter(x => x.ratio < 4.5).map(x => ({ theme, ...x })));
  }
  assert.deepEqual(faibles, [], JSON.stringify(mesures));
});

// Le nom du profil (16 caractères au plus) passe dans le titre et sur le bouton : à la
// taille XL et en anglais, rien ne doit sortir de l'écran ni du dialogue.
for (const langue of ["fr", "en"]) {
  test(`tenue : la confirmation de suppression tient de S à XL en ${langue}`, async () => {
    await ouvrir(DEUX_PROFILS({ langue }), { largeur: 1280, hauteur: 720 });
    await page.evaluate(() => { ouvrirEditeur(reglages.profils[1]); ACTIONS["supprimer-profil"](); });
    await page.waitForTimeout(300);
    for (const echelle of [.9, 1, 1.1, 1.2]) {
      const bilan = await page.evaluate(e => {
        reglages.systeme.echelle = e; appliquerTout();
        const d = document.querySelector("#confirmer .dialogue").getBoundingClientRect();
        const hors = [...document.querySelectorAll("#confirmer [data-nav]")].filter(x => {
          const r = x.getBoundingClientRect();
          return r.bottom > innerHeight || r.right > innerWidth || r.left < 0 || r.top < 0;
        }).map(x => x.dataset.cle);
        // Un nom trop long serait coupé par le bouton plutôt que de déborder.
        const coupes = [...document.querySelectorAll("#confirmer .bouton span")]
          .filter(x => x.scrollWidth > x.clientWidth + 1).map(x => x.textContent);
        return { hors, coupes, dedans: d.top >= 0 && d.bottom <= innerHeight };
      }, echelle);
      assert.deepEqual(bilan, { hors: [], coupes: [], dedans: true }, `taille ${echelle}`);
    }
  });
}

// Six entrées de deux lignes dans un dialogue : c'est le calque le plus haut du menu. Chaque
// explication tient sur UNE ligne, en français comme en anglais — deux lignes et la liste
// perd son rythme, puis sa place à l'écran.
for (const [largeur, hauteur] of [[1280, 720], [1920, 1080], [3840, 2160]]) {
  test(`tenue : le menu d'arrêt tient en ${largeur}×${hauteur} de S à XL`, async () => {
    await ouvrir(reglages(), { largeur, hauteur });
    await page.evaluate(() => ACTIONS.arret());
    await page.waitForTimeout(250);
    for (const langue of ["fr", "en"]) {
      for (const echelle of [.9, 1, 1.1, 1.2]) {
        const bilan = await page.evaluate(([e, l]) => {
          reglages.systeme.echelle = e; profil().langue = l; appliquerTout();
          const boite = document.querySelector("#arret .dialogue").getBoundingClientRect();
          const hors = [...document.querySelectorAll("#arret [data-nav]")].filter(x => {
            const r = x.getBoundingClientRect();
            return r.bottom > innerHeight || r.right > innerWidth || r.left < 0 || r.top < 0;
          }).map(x => x.dataset.cle);
          const surDeuxLignes = [...document.querySelectorAll("#arret .action-detail")]
            .filter(x => x.clientHeight > parseFloat(getComputedStyle(x).lineHeight) * 1.5)
            .map(x => x.textContent.slice(0, 24));
          return { hors, surDeuxLignes, dedans: boite.top >= 0 && boite.bottom <= innerHeight };
        }, [echelle, langue]);
        assert.deepEqual(bilan, { hors: [], surDeuxLignes: [], dedans: true }, `${langue}, taille ${echelle}`);
      }
    }
  });
}

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
  const transitions = await page.evaluate(() => [".onglet", ".pastille-onglet", ".tuile-service", ".puce", ".bouton", ".reprise"].map(sel => {
    const e = document.querySelector(sel); if (!e) return null;
    const cs = getComputedStyle(e);
    return { sel, durees: cs.transitionDuration.split(",").map(parseFloat), courbes: cs.transitionTimingFunction };
  }).filter(Boolean));
  for (const t of transitions) {
    assert.ok(Math.max(...t.durees) <= .2, `${t.sel} : ${t.durees}`);
    assert.doesNotMatch(t.courbes, /1\.56/, `${t.sel} : rebond`);
  }
  // Le fondu du héros est noté au moment où la page le lance : sur une machine chargée, une
  // animation de 180 ms peut être finie avant qu'on aille la chercher.
  await page.evaluate(() => {
    window.__fondus = [];
    const animer = Element.prototype.animate;
    Element.prototype.animate = function (k, o) { if (this.closest("#heros")) window.__fondus.push(o.duration); return animer.call(this, k, o); };
    definirFocus(document.querySelector('[data-mode="tv"]'), true);
    window.__fondus = [];
  });
  await page.keyboard.press("ArrowRight");
  const fondus = await page.evaluate(() => window.__fondus);
  assert.ok(fondus.length && fondus.every(d => d <= 200), `durées ${fondus}`);
  await page.evaluate(() => { definirFocus(document.querySelector('[data-mode="tv"]'), true); window.__fondus = []; });
  await page.evaluate(() => dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", repeat: true })));
  assert.deepEqual(await page.evaluate(() => window.__fondus), [], "aucun fondu pendant la répétition de la touche");
});

// Défauts mineurs de l'audit du 17/09/2026.
test("détails : badges et empreinte d'une pièce, pastilles d'étapes rondes, rien ne tourne caché, voix sans doublon", async () => {
  const telecommande = { url: "http://192.168.1.40:8790/", code: "482913", appairageOuvert: true, empreinteRacineCourte: "1146 7BB0 E51A 4F84", telephones: 0 };
  await ouvrir({ ...reglages({ meteo: { active: true, ville: "Lyon", lat: 45.7, lon: 4.8 } }), telecommande });
  await page.evaluate(() => ACTIONS.reglages("apparence"));
  await page.waitForTimeout(300);
  const badges = await page.evaluate(() => [...document.querySelectorAll(".portee-hub")].map(b => b.getClientRects().length));
  assert.ok(badges.length && badges.every(n => n === 1), `badges sur plusieurs lignes : ${badges}`);
  await page.evaluate(() => ACTIONS.reglages("telecommande"));
  await page.waitForTimeout(300);
  const detail = await page.evaluate(() => ({
    empreinte: document.querySelector(".empreinte-courte").getClientRects().length === 1 && document.querySelector(".empreinte-courte").scrollWidth <= document.querySelector(".empreinte-courte").clientWidth + 1,
    pastilles: [...document.querySelectorAll(".etape b")].map(b => Math.abs(b.offsetWidth - b.offsetHeight) <= 1),
    accueilCache: parseFloat(getComputedStyle(document.querySelector(".ecran")).opacity) <= .2,
    tournentCaches: document.getAnimations().filter(a => a.playState === "running" && a.constructor.name === "CSSAnimation" && a.effect?.target && (a.effect.target.closest?.(".ecran, .calque:not(.ouvert)"))).length,
  }));
  assert.deepEqual(detail, { empreinte: true, pastilles: [true, true, true], accueilCache: true, tournentCaches: 0 });
  await page.evaluate(() => { fermerTout(); window.hub.recevoir({ type: "voix", etat: "micro-present" }); window.hub.recevoir({ type: "voix", etat: "eveil" }); });
  const ecoute = await page.evaluate(() => [...document.querySelectorAll("#voix-texte, #bulle-texte")].filter(e => e.getClientRects().length && e.textContent.includes("écoute")).length);
  assert.equal(ecoute, 1, "« J'écoute… » une seule fois à l'écran");
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-appairage", etat: { code: "4821", jusqua: Date.now() / 1000 + 60 } }));
  assert.match(await page.evaluate(() => getComputedStyle(document.querySelector("#recopie-appairage")).boxShadow), /100vmax|\d{4,}px/, "voile sous le code de recopie");
});

// L'indicateur Internet : libellé à 4,5:1, pictogramme (graphique) à 3:1, dans chaque thème et
// sur chaque motif ; et, dans À propos, l'état du réseau et le détail d'un échec de mise à jour.
test("contrastes : indicateur Internet et détail d'échec de mise à jour, thèmes et motifs", async () => {
  const faibles = [];
  for (const theme of ["sombre", "clair"]) {
    for (const motif of ["cinema", "rubans", "profondeur", "faisceaux", "nappes"]) {
      await page?.close();
      await ouvrir(reglages({}, { theme, animations: "reduites", motif }));
      for (const etat of ["internet", "local", "aucun"]) {
        await page.evaluate(e => { window.hub.recevoir({ type: "internet", etat: e }); definirFocus(document.querySelector("#puce-internet"), true); }, etat);
        await page.waitForTimeout(200);
        const m = await contrastes(["#internet-libelle", "#puce-internet .picto-internet"]);
        faibles.push(...m.filter(x => x.ratio < (x.sel.includes("picto") ? 3 : 4.5)).map(x => ({ theme, motif, etat, ...x })));
      }
    }
    await page.evaluate(() => {
      ACTIONS.reglages("apropos");
      window.hub.recevoir({ type: "internet", etat: "local", nuance: "portail" });
      window.hub.recevoir({ type: "maj", etat: { etape: "echec", raison: "reseau", detail: "fatal: unable to access 'https://github.com/x/hub.git/': Could not resolve host: github.com" } });
    });
    await page.waitForTimeout(400);
    const m = await contrastes([".detail-maj", ".reseau-info .valeur", ".reseau-info .picto-internet"]);
    faibles.push(...m.filter(x => x.ratio < (x.sel.includes("picto") ? 3 : 4.5)).map(x => ({ theme, apropos: true, ...x })));
  }
  assert.deepEqual(faibles, []);
});
