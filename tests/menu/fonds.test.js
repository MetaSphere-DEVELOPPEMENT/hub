// Fonds au choix (motif × couleur) et accueil « Cinéma » : compatibilité des profils
// enregistrés, dessin de chaque motif dans chaque couleur, rythmes, arrêts, réglage, héros
// et onglets. Chromium n'est pas WebKitGTK : on vérifie des choix, pas des images par seconde.
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;
const MOTIFS = ["cinema", "rubans", "profondeur", "faisceaux", "nappes"];
const COULEURS = ["aurore", "nebuleuse", "ocean", "braise", "emeraude", "crepuscule"];

let navigateur, page;
before(async () => { navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" }); });
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); page = null; });

function fauxPont(initial) {
  window.__messages = [];
  window.webkit = { messageHandlers: { hub: { postMessage: t => window.__messages.push(JSON.parse(t)) } } };
  window.HUB_INITIAL = initial;
}
async function ouvrir(initial = {}, requete = "", avant = null) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  await page.route(/open-meteo\.com/, r => r.abort());
  await page.addInitScript(fauxPont, { retour: true, ...initial });
  // « avant » voit la page avant son chargement : compter les requêtes, en refuser une.
  if (avant) await avant(page);
  await page.goto(PAGE + "?sans-intro" + requete);
  await page.waitForTimeout(300);
}
const profil = extra => ({ reglages: { profilActif: "p", profils: [{ id: "p", nom: "Samuel", ...extra }], systeme: { meteo: { active: false } } } });
const touche = async (...touches) => { for (const k of touches) { await page.keyboard.press(k); await page.waitForTimeout(60); } };
const focus = () => page.evaluate(() => { const e = document.querySelector(".focus"); return e && (e.dataset.mode || e.dataset.cle || e.dataset.action); });
const attendreReglages = verifie => page.waitForFunction(v => {
  const m = window.__messages.filter(x => x.type === "reglages").at(-1);
  return m && new Function("d", `return (${v})(d)`)(m.donnees);
}, verifie.toString(), { timeout: 5000 });

test("compatibilité : un profil enregistré avec « fond » seul garde les nappes et sa couleur", async () => {
  for (const fond of ["aurore", "ocean", "braise", "nebuleuse", "minimal"]) {
    await page?.close();
    await ouvrir(profil({ fond }));
    const etat = await page.evaluate(() => ({
      motif: window.hubFond.motifChoisi(), fond: window.hubFond.fondChoisi(),
      toile: [document.getElementById("fond").width, document.getElementById("fond").height],
      lignes: document.getElementById("fond-lignes").hidden, filigrane: document.getElementById("filigrane").hidden,
    }));
    assert.deepEqual(etat, { motif: fond === "minimal" ? "minimal" : "nappes", fond, toile: [192, 108], lignes: true, filigrane: true }, fond);
  }
  // Rien n'est réécrit tant qu'on ne touche à rien ; au premier enregistrement, le motif est écrit.
  await page.keyboard.press("t");
  await attendreReglages(d => d.profils[0].motif === "nappes" && d.profils[0].fond === "minimal");
  assert.deepEqual(page.erreurs, []);
});

test("compatibilité : un HUB neuf et un profil créé partent du motif cinéma, couleur aurore, teinte du mode", async () => {
  await ouvrir({});
  assert.deepEqual(await page.evaluate(() => [window.hubFond.motifChoisi(), window.hubFond.fondChoisi(), profil().teinteMode]), ["cinema", "aurore", true]);
  // L'image du mode prend la place du filigrane, qui reste en repli.
  assert.deepEqual(await page.evaluate(() => [document.getElementById("visuel-mode").hidden, document.getElementById("filigrane").hidden]), [false, true]);
  await page.close();
  await ouvrir(profil({ fond: "ocean" }));
  await page.evaluate(() => ouvrirEditeur(null));
  assert.equal(await page.evaluate(() => brouillon.motif), "cinema");
});

test("dessin : chaque motif, dans chaque couleur, en sombre et en clair, sans erreur et pas uni", async () => {
  await ouvrir({});
  const bilan = await page.evaluate(([motifs, couleurs]) => {
    const { apercuFond } = window.hubFond;
    const r = [];
    for (const motif of motifs) for (const couleur of couleurs) for (const theme of ["sombre", "clair"]) {
      try {
        const v = apercuFond(motif, couleur, theme, 3, [179, 107, 255], true);
        const d = v.getContext("2d").getImageData(0, 0, v.width, v.height).data;
        let min = 255, max = 0, somme = 0;
        for (let i = 0; i < d.length; i += 16) { const l = (d[i] + d[i + 1] + d[i + 2]) / 3; min = Math.min(min, l); max = Math.max(max, l); somme += l; }
        r.push({ motif, couleur, theme, etendue: max - min, moyenne: somme / (d.length / 16) });
      } catch (e) { r.push({ motif, couleur, theme, erreur: e.message }); }
    }
    return r;
  }, [MOTIFS, COULEURS]);
  assert.deepEqual(bilan.filter(b => b.erreur), []);
  for (const b of bilan) assert.ok(b.etendue >= 12, `${b.motif} ${b.couleur} ${b.theme} : presque uni (${b.etendue.toFixed(1)})`);
  // Le clair est clair, le sombre sombre : les textes du thème restent lisibles dessus.
  for (const motif of MOTIFS) for (const couleur of COULEURS) {
    const s = bilan.find(b => b.motif === motif && b.couleur === couleur && b.theme === "sombre");
    const c = bilan.find(b => b.motif === motif && b.couleur === couleur && b.theme === "clair");
    assert.ok(s.moyenne < 90 && c.moyenne > 150, `${motif} ${couleur} : sombre ${s.moyenne.toFixed(0)}, clair ${c.moyenne.toFixed(0)}`);
  }
});

// Le reproche du 17/09/2026 : « le fond n'est toujours pas animé ». Entre t et t + 5 s, une
// part visible de l'image change, pour chaque motif.
test("mouvement : chaque motif change visiblement en 5 s, et aucune période ne dépasse 30 s", async () => {
  await ouvrir({});
  const releve = await page.evaluate(motifs => motifs.map(motif => {
    const { apercuFond, periodesMotif, periodesFond } = window.hubFond;
    const periodes = motif === "nappes" ? periodesFond("aurore") : periodesMotif(motif);
    const image = s => apercuFond(motif, "aurore", "sombre", s, [62, 224, 208], true).getContext("2d").getImageData(0, 0, 480, 270).data;
    const a = image(10), b = image(15);
    let changes = 0;
    for (let i = 0; i < a.length; i += 4) if (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]) > 24) changes++;
    return { motif, periodes, part: changes / (a.length / 4) };
  }), MOTIFS);
  for (const { motif, periodes, part } of releve) {
    assert.ok(periodes.length > 0, motif);
    assert.ok(Math.max(...periodes) <= 30, `${motif} : période la plus longue ${Math.max(...periodes)} s`);
    assert.ok(part >= .05, `${motif} : ${(part * 100).toFixed(1)} % de l'image change en 5 s`);
  }
  const pendules = await page.evaluate(() => {
    const { mouvementFiligrane, mouvementFaisceaux } = window.hubFond;
    const f = [0, 7, 14, 21].map(s => mouvementFiligrane(s).angle);
    const b = [0, 5, 10].map(s => mouvementFaisceaux(s)[0].angle * 180 / Math.PI);
    return { filigrane: Math.max(...f) - Math.min(...f), faisceau: Math.max(...b) - Math.min(...b) };
  });
  assert.ok(pendules.filigrane >= 10, `le filigrane pivote de ${pendules.filigrane.toFixed(1)}°`);
  assert.ok(pendules.faisceau >= 15, `le faisceau balaie ${pendules.faisceau.toFixed(1)}°`);
});

test("rythme : le motif cinéma est redessiné à 30 images par seconde au plus, toiles comprises", async () => {
  await ouvrir(profil({ motif: "cinema", fond: "aurore" }));
  const { dessins, images } = await page.evaluate(() => new Promise(fin => {
    const c = document.getElementById("fond-lignes").getContext("2d");
    const effacer = c.clearRect.bind(c);
    let n = 0;
    c.clearRect = (...a) => { n++; return effacer(...a); };
    let images = 0;
    const debut = performance.now();
    (function compter(t) { images++; if (t - debut < 2000) requestAnimationFrame(compter); else fin({ dessins: n, images }); })(debut);
  }));
  assert.ok(dessins <= 66 && dessins >= 20, `${dessins} dessins en 2 s`);
  assert.ok(images > dessins, `${images} images, ${dessins} dessins`);
});

test("arrêts : animations réduites, image fixe et boucle arrêtée ; sous un calque, figé ; ralenti en ambiant", async () => {
  for (const motif of ["cinema", "rubans", "profondeur", "faisceaux"]) {
    await page?.close();
    await ouvrir(profil({ motif, animations: "reduites" }));
    await page.waitForTimeout(300);
    const image = () => page.evaluate(() => [document.getElementById("fond").toDataURL(), document.getElementById("fond-lignes").toDataURL(), document.getElementById("filigrane").style.transform]);
    const avant = await image();
    await page.waitForTimeout(700);
    assert.deepEqual(await image(), avant, `${motif} : l'image bouge encore`);
    assert.equal(await page.evaluate(() => window.hubBoucles().fond), false, `${motif} : la boucle tourne`);
  }
  await page.close();
  await ouvrir(profil({ motif: "faisceaux" }));
  assert.equal(await page.evaluate(() => window.hubBoucles().fond), true);
  await touche("r");
  await page.waitForFunction(() => window.hubBoucles().fond === false, null, { timeout: 3000 });
  const fige = await page.evaluate(() => document.getElementById("fond-lignes").toDataURL());
  await page.waitForTimeout(500);
  assert.equal(await page.evaluate(() => document.getElementById("fond-lignes").toDataURL()), fige);
  await touche("Escape");
  await page.waitForFunction(() => window.hubBoucles().fond === true, null, { timeout: 3000 });
  // En ambiant, l'horloge du fond avance deux fois moins vite que le temps.
  const vitesse = async () => page.evaluate(() => new Promise(fin => {
    const t0 = performance.now(), f0 = horlogeFond;
    setTimeout(() => fin((horlogeFond - f0) / ((performance.now() - t0) / 1000)), 1500);
  }));
  const normale = await vitesse();
  await touche("a");
  const ambiante = await vitesse();
  assert.ok(normale > .8 && ambiante < .65 && ambiante > .35, `normale ${normale.toFixed(2)}, ambiante ${ambiante.toFixed(2)}`);
  assert.deepEqual(page.erreurs, []);
});

test("réglage : motif puis couleur enregistrés ; minimal puis une couleur ramène le motif", async () => {
  await ouvrir(profil({ fond: "ocean" }), "&ecran=reglages&section=fond");
  await page.waitForFunction(() => document.querySelector("#reglages.ouvert"));
  const vignettes = await page.evaluate(() => [...document.querySelectorAll("#contenu-reglages .vignette-fond")].map(v => [v.dataset.cle, v.classList.contains("choisie"), !!v.querySelector("canvas")]));
  assert.deepEqual(vignettes.map(v => v[0]), [...MOTIFS.map(m => `motif-${m}`), "motif-minimal", "motif-photos", ...COULEURS.map(c => `couleur-${c}`)]);
  assert.deepEqual(vignettes.filter(v => v[1]).map(v => v[0]), ["motif-nappes", "couleur-ocean"], "l'ancien profil : nappes, océan");
  assert.ok(vignettes.filter(v => v[0] !== "motif-photos").every(v => v[2]), "un vrai aperçu dessiné par vignette");
  await page.click('[data-cle="motif-faisceaux"]');
  await attendreReglages(d => d.profils[0].motif === "faisceaux" && d.profils[0].fond === "ocean");
  await page.click('[data-cle="couleur-crepuscule"]');
  await attendreReglages(d => d.profils[0].motif === "faisceaux" && d.profils[0].fond === "crepuscule");
  await page.click('[data-cle="motif-minimal"]');
  await attendreReglages(d => d.profils[0].fond === "minimal" && d.profils[0].motif === "faisceaux");
  assert.equal(await page.evaluate(() => window.hubFond.motifChoisi()), "minimal");
  assert.match(await page.textContent("#contenu-reglages"), /Choisir une couleur revient au motif Faisceaux/);
  await page.click('[data-cle="couleur-emeraude"]');
  await attendreReglages(d => d.profils[0].fond === "emeraude" && d.profils[0].motif === "faisceaux");
  assert.equal(await page.evaluate(() => window.hubFond.motifChoisi()), "faisceaux");
  // Au clavier, et la sélection reste sur la vignette.
  await page.evaluate(() => definirFocus(document.querySelector('[data-cle="motif-rubans"]')));
  await touche("Enter");
  await attendreReglages(d => d.profils[0].motif === "rubans");
  assert.equal(await focus(), "motif-rubans");
  // En anglais, traduit.
  await page.evaluate(() => { profil().langue = "en"; appliquerTout(); rendreSection(); });
  assert.match(await page.textContent("#contenu-reglages"), /Pattern.*Northern lights.*Colour.*Emerald.*Dusk/s);
  assert.deepEqual(page.erreurs, []);
});

test("héros : il suit l'onglet, garde le dernier mode sur une tuile, et le filigrane et la teinte suivent", async () => {
  await ouvrir(profil({ motif: "cinema", dernier: "tv" }));
  const etat = () => page.evaluate(() => ({
    titre: document.getElementById("heros-titre").textContent,
    services: [...document.querySelectorAll("#heros-services span")].map(s => s.textContent),
    lancer: document.getElementById("lancer-texte").textContent,
    filigrane: document.getElementById("filigrane").dataset.picto,
    accent: getComputedStyle(document.documentElement).getPropertyValue("--accent").trim(),
  }));
  assert.deepEqual(await etat(), { titre: "TV", services: ["Kodi", "Films", "Séries", "Musique"], lancer: "Lancer TV", filigrane: "tv", accent: "62 224 208" });
  await touche("ArrowRight");
  assert.deepEqual(await etat(), { titre: "Jeux", services: ["GeForce NOW", "Xbox Cloud", "Boosteroid"], lancer: "Ouvrir Jeux", filigrane: "jeux", accent: "179 107 255" });
  await touche("ArrowDown");
  assert.match(await focus(), /^service-/);
  assert.deepEqual((await etat()).titre, "Jeux", "une tuile de streaming ne change pas le mode montré");
  assert.equal((await etat()).accent, "179 107 255", "ni la teinte du fond");
  await touche("ArrowUp", "ArrowRight");
  assert.deepEqual(await etat(), { titre: "Bureau", services: ["Ubuntu", "Applications", "Fichiers"], lancer: "Lancer Bureau", filigrane: "bureau", accent: "255 181 71" });
  // Le bouton dit ce que fait OK, et la souris peut s'en servir.
  await page.click("#lancer");
  await page.waitForFunction(() => window.__messages.some(m => m.type === "choix"), null, { timeout: 3000 });
  assert.deepEqual(await page.evaluate(() => window.__messages.filter(m => m.type === "choix")), [{ type: "choix", mode: "bureau" }]);
  assert.deepEqual(page.erreurs, []);
});

// L'image du mode, à droite de l'accueil : une photo par mode, posée dans le dépôt
// (installer/menu/images). Elles sont locales : chargées une fois au départ, jamais
// relues en changeant de mode.
const visuelVisible = () => page.evaluate(() => {
  const v = document.getElementById("visuel-mode");
  const vue = [...v.children].filter(i => i.classList.contains("visible")).map(i => i.dataset.visuel);
  return { cache: v.hidden, vue, filigrane: document.getElementById("filigrane").hidden, images: v.children.length };
});

test("image du mode : celle du mode choisi s'affiche à droite, change avec l'onglet, chargée une seule fois", async () => {
  const demandes = [];
  await ouvrir(profil({ motif: "cinema", dernier: "tv" }), "",
    p => p.on("request", r => { if (/\/images\/mode-/.test(r.url())) demandes.push(r.url().split("/").pop()); }));
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 3 });
  await touche("ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["jeux"], filigrane: true, images: 3 });
  await touche("ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["bureau"], filigrane: true, images: 3 });
  await touche("ArrowLeft", "ArrowLeft", "ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["jeux"], filigrane: true, images: 3 });
  // Préchargement : les trois images, une fois chacune, et rien de plus après six changements.
  assert.deepEqual(demandes.sort(), ["mode-bureau.webp", "mode-jeux.webp", "mode-tv.webp"]);
  // Le fondu d'une image à l'autre reste court, et le masque ne bouge jamais.
  const fondu = await page.evaluate(() => {
    const cs = getComputedStyle(document.querySelector("#visuel-mode img"));
    return { durees: cs.transitionDuration.split(",").map(parseFloat), propriete: cs.transitionProperty };
  });
  assert.ok(Math.max(...fondu.durees) <= .2, `fondu ${fondu.durees}`);
  assert.equal(fondu.propriete, "opacity");
  // Un autre motif n'a ni image ni filigrane.
  await page.evaluate(() => { profil().motif = "rubans"; appliquerTout(); });
  await page.waitForTimeout(150);
  assert.deepEqual(await visuelVisible(), { cache: true, vue: [], filigrane: true, images: 3 });
  assert.deepEqual(page.erreurs, []);
});

test("image du mode : animations réduites, aucun fondu ; image absente, le pictogramme en filigrane reprend", async () => {
  await ouvrir(profil({ motif: "cinema", dernier: "tv", animations: "reduites" }));
  const duree = await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector("#visuel-mode img")).transitionDuration));
  assert.ok(duree <= .01, `fondu en animations réduites : ${duree} s`);
  // Une image qui manque du dossier, ou illisible : elle quitte la page, le filigrane revient.
  await page.close();
  await ouvrir(profil({ motif: "cinema", dernier: "tv" }), "", p => p.route(/mode-jeux\.webp/, r => r.abort()));
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 2 });
  await touche("ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: true, vue: [], filigrane: false, images: 2 });
  assert.equal(await page.evaluate(() => document.getElementById("filigrane").dataset.picto), "jeux");
  assert.ok(await page.evaluate(() => document.querySelector("#filigrane svg").innerHTML.length > 0), "le pictogramme du mode est bien dessiné");
  await touche("ArrowLeft");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 2 });
  assert.deepEqual(page.erreurs, []);
});

test("héros : en anglais, avec des reprises, et Jeux sans ses services masqués", async () => {
  await ouvrir({ ...profil({ langue: "en", services: { xcloud: false }, dernier: "gaming" }), reprises: [{ titre: "Dune", fichier: "/d.mkv", position: 60, duree: 600 }] });
  assert.equal(await page.textContent("#heros-titre"), "Games");
  assert.deepEqual(await page.$$eval("#heros-services span", s => s.map(e => e.textContent)), ["GeForce NOW", "Boosteroid"]);
  assert.equal(await page.textContent("#lancer-texte"), "Open Games");
  await touche("ArrowLeft");
  assert.match(await page.textContent("#heros-services"), /1 to resume/);
  assert.equal(await page.textContent(".heros-sur"), "Selected mode");
});

test("onglets : la pastille glisse sous l'onglet choisi, pleine seulement quand il a le focus ; profil restreint", async () => {
  await ouvrir(profil({ dernier: "tv", animations: "reduites" }));
  const sous = () => page.evaluate(() => {
    const p = document.querySelector(".pastille-onglet").getBoundingClientRect();
    const o = [...document.querySelectorAll(".onglet")].filter(x => !x.hidden).find(x => { const r = x.getBoundingClientRect(); return Math.abs(r.left + r.width / 2 - (p.left + p.width / 2)) < 4; });
    return { onglet: o?.dataset.mode, actif: document.getElementById("modes").classList.contains("actif") };
  });
  await page.waitForTimeout(100);
  assert.deepEqual(await sous(), { onglet: "tv", actif: true });
  await touche("ArrowRight", "ArrowRight");
  await page.waitForTimeout(100);
  assert.deepEqual(await sous(), { onglet: "bureau", actif: true });
  await touche("ArrowDown");
  await page.waitForTimeout(100);
  assert.deepEqual(await sous(), { onglet: "bureau", actif: false }, "focus sur le streaming : la pastille reste, en retrait");
  // Écart entre les onglets et les tuiles : de l'air, pas bord à bord.
  const air = await page.evaluate(() => {
    const t = [...document.querySelectorAll("#applis .tuile-service")].map(e => e.getBoundingClientRect());
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    return { entreTuiles: (t[1].left - t[0].right) / rem, rangees: (t[0].top - document.getElementById("modes").getBoundingClientRect().bottom) / rem };
  });
  assert.ok(air.entreTuiles >= .9 && air.rangees >= 1, JSON.stringify(air));
  await page.close();
  await ouvrir({ reglages: { profilActif: "e", profils: [{ id: "e", nom: "Alix", modes: { tv: true, gaming: false, bureau: true }, dernier: "bureau" }], systeme: {} } });
  await page.waitForTimeout(250);
  assert.deepEqual(await page.$$eval(".onglet", o => o.filter(x => !x.hidden).map(x => x.dataset.mode)), ["tv", "bureau"]);
  assert.deepEqual(await sous(), { onglet: "bureau", actif: true }, "deux onglets : la pastille se cale sur le second");
  await touche("2");
  assert.match(await page.textContent("#annonce"), /pas autorisé/);
});
