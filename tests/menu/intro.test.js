// L'ouverture du HUB, à l'allumage : le logo s'allume au centre, puis vient se poser à la
// place exacte de celui de l'en-tête pendant que l'accueil apparaît. Ces tests MESURENT ce
// que l'œil juge depuis le canapé : un logo qui saute d'un pixel à l'arrivée, une image sans
// rien entre l'intro et l'accueil, une ouverture qui fait attendre le menu. Chaque image
// rendue par la page est relevée (requestAnimationFrame), pas seulement l'état final.
//
//   cd tests/menu && npm install && npm test

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
// L'intro d'avant : le voile partait à 1,7 s et le calque était retiré à 2,7 s. La nouvelle
// ne doit jamais faire attendre le menu plus longtemps.
const ANCIENNE_DUREE = 2700;

let navigateur, page;

function fauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: texte => window.__messages.push(JSON.parse(texte)) } } };
  window.HUB_INITIAL = initial;
}
// Le relevé : à chaque image rendue, où est le logo de l'intro, et ce qu'on voit de l'accueil.
function releverImages() {
  window.__images = [];
  const boite = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
  const opacite = e => { let o = 1; for (; e && e.nodeType === 1; e = e.parentElement) { const s = getComputedStyle(e); if (s.visibility === "hidden" || s.display === "none") return 0; o *= +s.opacity; } return o; };
  const releve = () => {
    const intro = document.getElementById("intro");
    const accueil = document.getElementById("accueil");
    if (intro && accueil) {
      const logo = intro.querySelector(".intro-marque");
      window.__images.push({
        t: performance.now(),
        intro: !intro.hidden,
        classes: document.body.className + " / " + intro.className,
        logoIntro: logo && !intro.hidden ? opacite(logo) : 0,
        boite: logo && !intro.hidden ? boite(logo) : null,
        pastille: logo && !intro.hidden ? boite(logo.querySelector("i")) : null,
        lettres: logo && !intro.hidden ? [...logo.querySelectorAll("span")].map(boite) : null,
        voile: intro.hidden ? 0 : opacite(intro.querySelector(".intro-voile")),
        accueil: opacite(accueil),
        logoEntete: opacite(document.querySelector(".entete .marque")),
        boiteEntete: boite(document.querySelector(".entete .marque")),
        transformEntete: getComputedStyle(document.querySelector(".entete .marque")).transform,
      });
    }
    requestAnimationFrame(releve);
  };
  requestAnimationFrame(releve);
}

before(async () => { navigateur = await lancerNavigateur(); });
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

async function ouvrir({ initial = {}, requete = "", ecran = { width: 1920, height: 1080 }, contexte = {}, avant = null } = {}) {
  page = await navigateur.newPage({ viewport: ecran, ...contexte });
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  await page.route(/open-meteo\.com/, r => r.abort());
  await page.addInitScript(fauxPont, initial);
  await page.addInitScript(releverImages);
  if (avant) await avant(page);
  // « domcontentloaded » : une photo qui ne répond jamais retient l'événement « load ».
  await page.goto(PAGE + requete, { waitUntil: "domcontentloaded" });
}
const profil = extra => ({ reglages: { profilActif: "p", profils: [{ id: "p", nom: "Salon", motif: "cinema", ...extra }], systeme: { meteo: { active: false } } } });
// L'intro rangée ET l'accueil entier : son fondu finit un peu après elle, et sur une machine
// chargée (toute la suite tourne en parallèle) le relevé lu trop tôt s'arrêtait à 97 %.
const finIntro = () => page.waitForFunction(() => document.getElementById("intro").hidden && !document.body.classList.contains("intro")
  && +getComputedStyle(document.getElementById("accueil")).opacity === 1 && window.__images.at(-1)?.accueil === 1, null, { timeout: 8000 });
const images = () => page.evaluate(() => window.__images);
// Le logo de l'en-tête : sa boîte et sa pastille.
const logoEntete = () => page.evaluate(() => {
  const boite = r => [r.left, r.top, r.width, r.height];
  const marque = document.querySelector(".entete .marque");
  return { boite: boite(marque.getBoundingClientRect()), pastille: boite(marque.querySelector("i").getBoundingClientRect()) };
});
const ecart = (a, b) => Math.max(...a.map((v, i) => Math.abs(v - b[i])));

for (const [nom, extra, ecran] of [
  ["sombre, 1920×1080", { theme: "sombre" }, { width: 1920, height: 1080 }],
  ["clair, 1920×1080", { theme: "clair" }, { width: 1920, height: 1080 }],
  ["sombre, 1280×800, mode Jeux", { theme: "sombre", dernier: "gaming" }, { width: 1280, height: 800 }],
]) {
  test(`intro : le logo va du centre à la place exacte du logo de l'en-tête, à sa taille (${nom})`, async () => {
    await ouvrir({ initial: profil(extra), ecran });
    assert.ok(await page.isVisible("#intro .intro-marque"), "l'intro ne joue pas");
    await finIntro();
    const releve = await images();
    const entete = await logoEntete();
    // Deux logos font le trajet, l'un sur l'autre : celui de l'intro, et le vrai, qui prend
    // le relais en vol. À CHAQUE image du trajet ils coïncident — sinon on verrait le logo
    // se dédoubler ou sauter au relais.
    const vol = releve.filter(i => i.intro && /\bpose\b/.test(i.classes));
    assert.ok(vol.length > 5, "le logo ne se pose pas");
    // (Un pixel À L'ARRIVÉE : au départ les logos sont trois fois plus grands, l'écart permis aussi.)
    for (const i of vol) {
      const permis = 1.5 * i.boite[2] / entete.boite[2];
      assert.ok(ecart(i.boite, i.boiteEntete) <= permis, `à ${Math.round(i.t)} ms, les deux logos s'écartent : ${i.boite.map(v => v.toFixed(1))} et ${i.boiteEntete.map(v => v.toFixed(1))}`);
    }
    // Et quand on les voit tous les deux — le relais —, c'est à un pixel près.
    const relais = releve.filter(i => i.logoIntro > .01 && i.logoEntete > .01);
    assert.ok(relais.length >= 3, `le relais n'a pas été relevé (${relais.length} images)`);
    for (const i of relais) assert.ok(ecart(i.boite, i.boiteEntete) <= 1, `relais à ${Math.round(i.t)} ms : ${i.boite.map(v => v.toFixed(1))} et ${i.boiteEntete.map(v => v.toFixed(1))}`);
    // Le trajet part bien du centre de l'écran, en grand. C'est l'ENCRE qui est centrée : la
    // boîte dépasse le B d'un interlettrage (un demi-cadratin), que l'œil ne voit pas.
    const corps = await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector(".intro-marque")).fontSize));
    const milieu = vol[0].boite[0] + (vol[0].boite[2] - corps / 2) / 2;
    assert.ok(Math.abs(milieu - ecran.width / 2) < 3 && vol[0].boite[2] > entete.boite[2] * 2.5, `départ : ${vol[0].boite.map(v => v.toFixed(1))}, milieu de l'encre à ${milieu.toFixed(1)}`);
    // … et le logo de l'intro ne s'efface qu'en fin de course, presque arrivé : le relais
    // n'est pas un fondu enchaîné entre le centre et l'en-tête.
    const derniere = releve.filter(i => i.intro && i.logoIntro > .01).at(-1);
    assert.ok(ecart(derniere.boite, entete.boite) <= 6, `le logo de l'intro disparaît loin de l'en-tête : ${derniere.boite.map(v => v.toFixed(1))} pour ${entete.boite.map(v => v.toFixed(1))}`);
    // À l'arrivée, ce qu'on voit EST le logo de l'en-tête, sans transformation : il ne peut
    // pas être ailleurs qu'à sa place.
    const fin = releve.at(-1);
    assert.equal(fin.transformEntete, "none");
    assert.ok(fin.logoEntete > .99 && !fin.intro);
    assert.ok(ecart(fin.boiteEntete, entete.boite) < .01);
    // Et c'est bien le même logo : même couleur de pastille, même graisse, même police.
    const styles = await page.evaluate(() => {
      const lire = (e, ...cles) => { const s = getComputedStyle(e); return cles.map(c => s[c]); };
      document.getElementById("intro").hidden = false;
      const r = {
        intro: [lire(document.querySelector(".intro-marque i"), "backgroundColor"), lire(document.querySelector(".intro-marque"), "color", "fontWeight", "fontFamily")],
        entete: [lire(document.querySelector(".entete .marque i"), "backgroundColor"), lire(document.querySelector(".entete .marque"), "color", "fontWeight", "fontFamily")],
      };
      document.getElementById("intro").hidden = true;
      return r;
    });
    assert.deepEqual(styles.intro, styles.entete);
    assert.deepEqual(page.erreurs, []);
  });
}

// Les boîtes ne disent pas tout : ce que l'œil voit, ce sont des pixels. La première version
// de l'intro échangeait les deux logos à l'arrêt, boîtes confondues au tiers de pixel — et
// les lettres sautaient pourtant d'un pixel, parce qu'un texte peint à sa taille est calé
// sur la grille et que le même, réduit par le compositeur, ne l'est pas. Le relais se fait
// donc en vol. Ici on arrête le vol à l'instant du relais, et on capture les deux logos l'un
// après l'autre : pastille et lettres doivent tomber au même endroit, à un pixel près.
test("intro : à l'instant du relais, les deux logos sont l'un sur l'autre à l'image", async () => {
  for (const [theme, ecran] of [["sombre", { width: 1920, height: 1080 }], ["clair", { width: 1920, height: 1080 }], ["sombre", { width: 1280, height: 800 }], ["sombre", { width: 3840, height: 2160 }]]) {
    await page?.close();
    // Fond immobile : entre les deux captures, seul le logo peut avoir changé.
    // Et une police sans taille optique. Sur un Mac, faute d'Ubuntu Sans, « system-ui » est
    // San Francisco, dont le dessin CHANGE avec le corps : à 110 px et à 37 px ce ne sont pas
    // les mêmes lettres, et elles tombent à un pixel l'une de l'autre sans que le menu y soit
    // pour rien (vérifié en grossissant les deux captures, 21/09/2026). Ubuntu Sans, sur le
    // HUB, n'a pas d'axe optique.
    const police = () => document.addEventListener("DOMContentLoaded", () => document.head.append(Object.assign(document.createElement("style"), { textContent: "html, body { font-family: Arial, Helvetica, 'DejaVu Sans', sans-serif !important; }" })));
    await ouvrir({ initial: profil({ theme, fond: "minimal" }), ecran, avant: p => p.addInitScript(police) });
    // L'instant du relais : le vrai logo vient de paraître. On fige toutes les transitions.
    // Les minuteries, elles, ne se figent pas : l'intro serait rangée pendant les captures.
    await page.evaluate(() => { INTRO.marge = 20000; });
    await page.waitForFunction(() => {
      if (!document.getElementById("intro").classList.contains("relais")) return false;
      // Figés AU MÊME instant du vol : mis en pause l'un après l'autre, les deux logos
      // s'arrêtaient parfois à une image d'écart dans le compositeur de WebKit (2 px).
      const vols = document.getAnimations().filter(a => a.transitionProperty === "transform");
      const instant = Math.min(...vols.map(a => a.currentTime));
      for (const a of document.getAnimations()) a.pause();
      for (const a of vols) a.currentTime = instant;
      return true;
    }, null, { timeout: 4000, polling: "raf" });
    await page.waitForTimeout(80);
    const zone = await page.evaluate(() => { const r = document.querySelector(".entete .marque").getBoundingClientRect(); return { x: Math.floor(r.left - r.height / 2), y: Math.floor(r.top - r.height / 2), width: Math.ceil(r.width + r.height / 2), height: Math.ceil(r.height * 2) }; });
    const seul = async (montre, cache) => {
      await page.evaluate(([m, c]) => { document.querySelector(m).style.cssText += ";opacity:1;visibility:visible"; document.querySelector(c).style.visibility = "hidden"; document.querySelector(".salut").style.visibility = "hidden"; }, [montre, cache]);
      return (await page.screenshot({ clip: zone })).toString("base64");
    };
    const intro = { png: await seul(".intro-marque", ".entete .marque") };
    const entete = { png: await seul(".entete .marque", ".intro-marque") };
    assert.equal(await page.evaluate(() => document.getElementById("intro").hidden), false, "l'intro a été rangée pendant les captures");
    // Dans chaque capture : les quatre formes (pastille, H, U, B), séparées par leurs colonnes
    // vides, avec leurs bords et leur centre de gravité. Le seuil est à mi-chemin entre le
    // fond et la forme : le logo de l'intro, réduit par le compositeur, est un peu plus doux
    // que du texte peint à sa taille, et ce flou ne doit pas compter pour un déplacement.
    const formes = await page.evaluate(async lot => {
      const r = [];
      for (const b64 of lot) {
        const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode();
        const c = document.createElement("canvas"); c.width = i.width; c.height = i.height;
        const x = c.getContext("2d"); x.drawImage(i, 0, 0);
        const d = x.getImageData(0, 0, c.width, c.height).data;
        const dist = k => Math.abs(d[k] - d[0]) + Math.abs(d[k + 1] - d[1]) + Math.abs(d[k + 2] - d[2]);
        let max = 0;
        for (let k = 0; k < d.length; k += 4) max = Math.max(max, dist(k));
        const plein = (px, py) => dist((py * c.width + px) * 4) > max / 2;
        const colonnes = Array.from({ length: c.width }, (_, px) => { let n = 0; for (let py = 0; py < c.height; py++) if (plein(px, py)) n++; return n; });
        const liste = [];
        for (let px = 0; px < c.width; px++) {
          if (!colonnes[px]) continue;
          const debut = px;
          while (px < c.width && colonnes[px]) px++;
          let sx = 0, sy = 0, n = 0, haut = c.height, bas = 0;
          for (let qx = debut; qx < px; qx++) for (let py = 0; py < c.height; py++) if (plein(qx, py)) { sx += qx; sy += py; n++; haut = Math.min(haut, py); bas = Math.max(bas, py); }
          liste.push({ gauche: debut, droite: px - 1, haut, bas, cx: sx / n, cy: sy / n });
        }
        r.push(liste);
      }
      return r;
    }, [intro.png, entete.png]);
    if (process.env.HUB_DEBUG) console.log(JSON.stringify(formes));
    assert.equal(formes[0].length, 4, `${theme} ${ecran.width} : ${formes[0].length} formes dans le logo de l'intro au lieu de 4 (pastille, H, U, B)`);
    assert.equal(formes[1].length, 4, `${theme} ${ecran.width} : ${formes[1].length} formes dans le logo de l'en-tête`);
    // Le logo entier : mêmes bords, même centre, à un pixel près.
    const ensemble = liste => ({ gauche: liste[0].gauche, droite: liste.at(-1).droite, haut: Math.min(...liste.map(f => f.haut)), bas: Math.max(...liste.map(f => f.bas)), cx: liste.reduce((t, f) => t + f.cx, 0) / 4, cy: liste.reduce((t, f) => t + f.cy, 0) / 4 });
    const [A, B] = formes.map(ensemble);
    for (const bord of ["gauche", "droite", "haut", "bas"]) assert.ok(Math.abs(A[bord] - B[bord]) <= 1, `${theme} ${ecran.width} : bord ${bord} du logo à ${A[bord]} px dans l'intro, ${B[bord]} px dans l'en-tête`);
    assert.ok(Math.max(Math.abs(A.cx - B.cx), Math.abs(A.cy - B.cy)) <= 1, `${theme} ${ecran.width} : logo déplacé de ${(A.cx - B.cx).toFixed(2)} × ${(A.cy - B.cy).toFixed(2)} px au relais`);
    // Et chaque forme. WebKit, la famille du moteur de la TV, cale le texte au pixel : l'écart
    // y vaut 0 ou 1 sur chaque axe, jamais plus. Chromium cale chaque glyphe d'un texte à l'échelle 1,01 à
    // sa façon, et pas deux fois pareil (le H à 1,67 px une fois, le U à 1,06 la suivante) :
    // on n'y refuse que le décalage franc.
    const permis = process.env.HUB_NAVIGATEUR === "webkit" ? 1.05 : 2;
    formes[0].forEach((f, k) => {
      const g = formes[1][k], nom = ["pastille", "H", "U", "B"][k];
      assert.ok(Math.max(Math.abs(f.cx - g.cx), Math.abs(f.cy - g.cy)) <= permis, `${theme} ${ecran.width}, ${nom} : centre déplacé de ${(f.cx - g.cx).toFixed(2)} × ${(f.cy - g.cy).toFixed(2)} px au relais`);
    });
  }
});

test("intro : de l'allumage à l'accueil, il y a toujours un logo à l'écran — jamais aucun, jamais deux", async () => {
  await ouvrir({ initial: profil({ theme: "sombre" }) });
  // Des captures pendant toute la séquence : l'image elle-même, pas seulement le DOM.
  const captures = [];
  const debut = Date.now();
  while (Date.now() - debut < 2900) {
    const t = await page.evaluate(() => performance.now());
    captures.push({ t, png: (await page.screenshot()).toString("base64") });
    await page.waitForTimeout(60);
  }
  await finIntro();
  const releve = await images();
  // Passé l'allumage de la pastille (les toutes premières images sont noires, c'est l'écran
  // qui s'allume), un logo entier est toujours là : celui de l'intro, puis celui de l'en-tête.
  const apres = releve.filter(i => i.t > releve[0].t + 700);
  // Au relais, les deux sont l'un sur l'autre : ce qu'on voit du logo, c'est leur somme.
  const trous = apres.filter(i => 1 - (1 - i.logoIntro) * (1 - i.logoEntete) < .9);
  assert.deepEqual(trous.map(i => Math.round(i.t)), [], "images où le logo s'efface");
  // Deux logos à la fois, seulement l'un SUR l'autre : c'est le relais en vol, où celui de
  // l'intro s'efface sur celui de l'en-tête. Ailleurs, on verrait le logo en double.
  const doubles = apres.filter(i => i.logoIntro > .01 && i.logoEntete > .01 && ecart(i.boite, i.boiteEntete) > 1);
  assert.deepEqual(doubles.map(i => Math.round(i.t)), [], "images avec deux logos à deux endroits");
  // L'accueil n'attend pas que le logo soit posé : il apparaît PENDANT qu'il se pose.
  const pose = releve.filter(i => /\bpose\b/.test(i.classes));
  assert.ok(pose.length > 5, "le logo ne se pose pas");
  assert.ok(pose.some(i => i.accueil > .5 && i.transformEntete !== "none"), "l'accueil n'apparaît pas pendant que le logo se pose");
  // L'accueil ne recule jamais une fois apparu : pas de clignotement.
  // Dès la toute première image : avant que hub.js ait tourné, l'accueil à nu (textes
  // vides, horloge « --:-- ») se voyait une image, juste avant le voile.
  assert.equal(releve[0].accueil, 0, "l'accueil se voit avant l'intro");
  let haut = 0;
  for (const i of releve) { assert.ok(i.accueil >= haut - .02, `l'accueil clignote à ${Math.round(i.t)} ms (${i.accueil} après ${haut})`); haut = Math.max(haut, i.accueil); }
  // Aucune capture vide : dans chacune (hors allumage), des pixels clairs — les lettres.
  const clairs = await page.evaluate(async lot => {
    const r = [];
    for (const b64 of lot) {
      const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode();
      const c = document.createElement("canvas"); c.width = i.width; c.height = i.height;
      const x = c.getContext("2d"); x.drawImage(i, 0, 0);
      const d = x.getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      for (let k = 0; k < d.length; k += 4) if (d[k] > 215 && d[k + 1] > 215 && d[k + 2] > 215) n++;
      r.push(n);
    }
    return r;
  }, captures.filter(c => c.t > 1250).map(c => c.png));
  assert.ok(clairs.length >= 5, `trop peu de captures (${clairs.length})`);
  clairs.forEach((n, k) => assert.ok(n > 400, `capture ${k} presque vide : ${n} pixels clairs`));
  assert.deepEqual(page.erreurs, []);
});

test("intro : le fond animé vit déjà sous le logo, l'accueil et la photo n'arrivent qu'ensuite", async () => {
  await ouvrir({ initial: profil({ theme: "sombre" }) });
  await page.waitForFunction(() => window.__images.some(i => i.intro && i.voile < .05 && !/\bpose\b/.test(i.classes)), null, { timeout: 3000 });
  const etat = await page.evaluate(() => {
    const fond = document.getElementById("fond");
    const d = fond.getContext("2d").getImageData(0, 0, fond.width, fond.height).data;
    let peints = 0;
    for (let k = 3; k < d.length; k += 4) if (d[k]) peints++;
    return { peints, accueil: +getComputedStyle(document.getElementById("accueil")).opacity, photo: +getComputedStyle(document.getElementById("visuel-mode")).opacity };
  });
  assert.ok(etat.peints > 1000, "le fond n'est pas encore dessiné quand le voile se lève");
  assert.equal(etat.accueil, 0);
  assert.equal(etat.photo, 0);
  await finIntro();
  assert.deepEqual(await page.evaluate(() => [+getComputedStyle(document.getElementById("accueil")).opacity > .99, +getComputedStyle(document.getElementById("visuel-mode")).opacity > .5]), [true, true]);
});

test("intro : jamais plus longue que l'ancienne, même quand une photo ne répond pas", async () => {
  for (const avant of [null, p => p.route(/mode-tv\.webp/, () => { /* ni réponse ni refus : la photo ne vient jamais */ })]) {
    await page?.close();
    await ouvrir({ initial: profil({ theme: "sombre" }), avant });
    await finIntro();
    const releve = await images();
    const debut = releve[0].t;
    const fin = releve.find(i => !i.intro).t - debut;
    const accueilEntier = releve.find(i => i.accueil > .99).t - debut;
    assert.ok(fin <= ANCIENNE_DUREE, `intro retirée à ${Math.round(fin)} ms (avant : ${ANCIENNE_DUREE})`);
    // L'ancienne montrait l'accueil entier vers 2,6 s, et lisible (90 % d'opacité) vers
    // 2,06 s : son voile partait à 1,7 s, en .9 s sur une courbe qui fait l'essentiel du
    // chemin au début. La nouvelle ne doit faire attendre ni l'un ni l'autre.
    assert.ok(accueilEntier <= 2600, `accueil entier à ${Math.round(accueilEntier)} ms`);
    const lisible = releve.find(i => i.accueil >= .9).t - debut;
    assert.ok(lisible <= 2060 + 60, `accueil lisible à ${Math.round(lisible)} ms (avant : 2060)`);
    // Et pas moins que le temps de la lire : le logo entier reste posé au centre un moment.
    const entier = releve.filter(i => i.logoIntro > .99 && !/\bpose\b/.test(i.classes));
    assert.ok(entier.length && entier.at(-1).t - debut >= 1200, "le logo part avant d'avoir été lu");
  }
});

test("intro : une touche l'abrège et agit tout de suite", async () => {
  await ouvrir({ initial: profil({ theme: "sombre", dernier: "tv" }) });
  await page.waitForTimeout(350);
  await page.keyboard.press("ArrowRight");
  await finIntro();
  const releve = await images();
  assert.ok(releve.find(i => !i.intro).t - releve[0].t < 1500, "l'intro n'a pas été abrégée");
  assert.equal(await page.evaluate(() => document.querySelector(".focus")?.dataset.mode), "gaming");
});

test("?sans-intro la saute entièrement, et le retour d'un mode aussi", async () => {
  for (const [initial, requete] of [[profil({}), "?sans-intro"], [{ retour: true, ...profil({}) }, ""]]) {
    await page?.close();
    await ouvrir({ initial, requete });
    await page.waitForTimeout(250);
    const releve = await images();
    assert.ok(releve.length > 3);
    assert.deepEqual(releve.filter(i => i.intro || /\bintro/.test(i.classes.split(" / ")[0])).length, 0, "l'intro a joué");
    assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector(".entete .marque")).visibility), "visible");
  }
});

for (const [nom, extra, contexte] of [
  ["réglage du profil", { animations: "reduites" }, {}],
  ["prefers-reduced-motion", {}, { reducedMotion: "reduce" }],
]) {
  test(`intro : animations réduites (${nom}), un fondu simple — rien ne bouge`, async () => {
    await ouvrir({ initial: profil({ theme: "sombre", ...extra }), contexte });
    assert.ok(await page.isVisible("#intro.reduite .intro-marque"), "pas d'intro réduite");
    // Aucune animation en cours dans l'intro, sinon le fondu du calque entier.
    const animations = await page.evaluate(() => document.getAnimations().filter(a => a.effect?.target?.closest?.("#intro")).map(a => a.animationName || a.transitionProperty));
    assert.deepEqual(animations.filter(a => a !== "opacity"), []);
    await finIntro();
    const releve = await images();
    const visibles = releve.filter(i => i.intro);
    // Le logo ne bouge pas d'un pixel du début à la fin…
    for (const i of visibles) assert.ok(ecart(i.boite, visibles[0].boite) < .5, "le logo bouge en animations réduites");
    assert.ok(!releve.some(i => /\bpose\b/.test(i.classes)), "le logo se pose en animations réduites");
    // … et l'intro s'efface par un fondu : des opacités intermédiaires, pas une coupure.
    const fondu = visibles.map(i => i.logoIntro).filter(o => o > .05 && o < .95);
    assert.ok(fondu.length >= 3, `pas de fondu (${fondu.length} images intermédiaires)`);
    assert.ok(releve.find(i => !i.intro).t - releve[0].t <= 1500, "l'intro réduite traîne");
    assert.deepEqual(page.erreurs, []);
  });
}

test("intro : un profil à code — le code n'est demandé qu'une fois le logo posé", async () => {
  await ouvrir({ initial: profil({ pin: { algo: "essai", sel: "00", empreinte: "x" } }) });
  // (Pas « finIntro » : sous le dialogue du code, l'accueil ne revient jamais à 100 %.)
  await page.waitForFunction(() => document.getElementById("intro").hidden && !document.body.classList.contains("intro"), null, { timeout: 8000 });
  const releve = await images();
  assert.ok(releve.filter(i => i.intro).every(i => !/calque-ouvert/.test(i.classes)), "le code s'ouvre sous l'intro");
  await page.waitForFunction(() => document.body.classList.contains("calque-ouvert"), null, { timeout: 2000 });
});

test("intro : allègement — ni masque, ni flou, ni filtre ; seuls transform et opacity s'animent", () => {
  const css = readFileSync(path.join(MENU, "hub.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const regles = css.split("}").filter(r => /(^|[\s,>+~])(#intro|\.intro-|body\.intro)/.test(r.slice(0, r.indexOf("{"))) && !/@keyframes/.test(r));
  assert.ok(regles.length > 5, "les règles de l'intro n'ont pas été trouvées");
  for (const r of regles) {
    assert.ok(!/mask|filter|blur/.test(r), `masque, flou ou filtre dans l'intro : ${r.trim()}`);
    for (const t of r.match(/transition(-property)?\s*:[^;]*/g) || []) {
      const proprietes = t.replace(/^[^:]*:/, "").split(",").map(x => x.trim().split(/\s+/)[0]);
      assert.deepEqual(proprietes.filter(p => !["transform", "opacity", "none"].includes(p)), [], `transition de l'intro : ${t}`);
    }
  }
  const images = [...css.matchAll(/@keyframes\s+(intro-[\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}/g)];
  assert.ok(images.length >= 3, "les animations de l'intro n'ont pas été trouvées");
  for (const [, nom, corps] of images) {
    const proprietes = [...corps.matchAll(/([\w-]+)\s*:/g)].map(m => m[1]);
    assert.deepEqual(proprietes.filter(p => !["transform", "opacity"].includes(p)), [], `@keyframes ${nom}`);
  }
});
