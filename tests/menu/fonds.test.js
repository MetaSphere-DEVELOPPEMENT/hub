// Fonds au choix (motif × couleur) et accueil « Cinéma » : compatibilité des profils
// enregistrés, dessin de chaque motif dans chaque couleur, rythmes, arrêts, réglage, héros
// et onglets. Chromium n'est pas WebKitGTK : on vérifie des choix, pas des images par seconde.
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
const MENU = path.join(ici, "../../installer/menu");
const PAGE = pathToFileURL(path.join(MENU, "index.html")).href;
const MOTIFS = ["cinema", "rubans", "profondeur", "faisceaux", "nappes"];
const COULEURS = ["aurore", "nebuleuse", "ocean", "braise", "emeraude", "crepuscule"];

let navigateur, page;
before(async () => { navigateur = await lancerNavigateur(); });
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

// Le reproche du 17/09/2026, deux fois : « le fond n'est toujours pas animé », puis, mesure
// à l'appui (la TV plafonne à 30 Hz en 4K, le menu y rend 29,4 images/s), « pas du tout
// animés ». Rien n'est en panne : c'est le mouvement qui était trop lent. À 30 images par
// seconde, un aller-retour de 25 s avance d'un millième d'écran par image et l'œil ne voit
// rien bouger. On mesure donc la part de l'image qui change en 1 s (30 images de la TV) et
// en 5 s, à huit instants du cycle — la moyenne pour le rythme d'ensemble, le pire instant
// pour qu'aucun motif ne se fige au passage d'un extremum.
test("mouvement : chaque motif change visiblement en 1 s et en 5 s, et aucune période ne dépasse 30 s", async () => {
  await ouvrir({});
  const releve = await page.evaluate(motifs => {
    const { peindreFond, periodesMotif, periodesFond } = window.hubFond;
    // Deux toiles pour toute la mesure, repeintes à chaque instant : en créer une par
    // instant (seize par motif) dépasse ce que Chromium garde en mémoire, et les suivantes
    // revenaient vides. La couche basse porte les nappes et les taches, celle des lignes le
    // sol, les étoiles et la poussière : un pixel compte si l'une des deux a changé.
    const [basse, lignes] = [0, 1].map(() => { const t = document.createElement("canvas"); t.width = 480; t.height = 270; return t.getContext("2d"); });
    const image = (motif, s) => {
      peindreFond(motif, "aurore", "sombre", s, [62, 224, 208], true, basse, lignes, true);
      return [basse.getImageData(0, 0, 480, 270).data, lignes.getImageData(0, 0, 480, 270).data];
    };
    const part = (A, B) => {
      let c = 0;
      for (let i = 0; i < A[0].length; i += 4) {
        const db = Math.abs(A[0][i] - B[0][i]) + Math.abs(A[0][i + 1] - B[0][i + 1]) + Math.abs(A[0][i + 2] - B[0][i + 2]);
        const dl = Math.abs(A[1][i] - B[1][i]) + Math.abs(A[1][i + 1] - B[1][i + 1]) + Math.abs(A[1][i + 2] - B[1][i + 2]) + Math.abs(A[1][i + 3] - B[1][i + 3]);
        if (db > 24 || dl > 24) c++;
      }
      return c / (A[0].length / 4);
    };
    return motifs.map(motif => {
      const periodes = motif === "nappes" ? periodesFond("aurore") : periodesMotif(motif);
      const parts = d => [2, 5, 8, 11, 14, 17, 20, 23].map(t => part(image(motif, t), image(motif, t + d)));
      const une = parts(1), cinq = parts(5);
      return { motif, periodes, moyenne1s: une.reduce((a, b) => a + b) / une.length, pire5s: Math.min(...cinq) };
    });
  }, MOTIFS);
  for (const { motif, periodes, moyenne1s, pire5s } of releve) {
    assert.ok(periodes.length > 0, motif);
    assert.ok(Math.max(...periodes) <= 30, `${motif} : période la plus longue ${Math.max(...periodes)} s`);
    // Avant d'accélérer : 1,9 % en 1 s pour les nappes, 9,2 % en 5 s pour profondeur.
    // Après : de 16 à 26 % en 1 s, de 19 à 60 % en 5 s au pire instant.
    assert.ok(moyenne1s >= .12, `${motif} : ${(moyenne1s * 100).toFixed(1)} % de l'image change en 1 s`);
    assert.ok(pire5s >= .15, `${motif} : ${(pire5s * 100).toFixed(1)} % en 5 s au pire instant`);
  }
  // Balayés finement plutôt qu'à trois instants : les périodes ont raccourci, et trois
  // instants bien espacés tombaient tous au même point du cycle (0° d'amplitude mesurée
  // pour un filigrane qui pivote pourtant de 16°).
  const pendules = await page.evaluate(() => {
    const { mouvementFiligrane, mouvementFaisceaux } = window.hubFond;
    const instants = Array.from({ length: 120 }, (_, i) => i * .25);
    const f = instants.map(s => mouvementFiligrane(s).angle);
    const b = instants.map(s => mouvementFaisceaux(s)[0].angle * 180 / Math.PI);
    return { filigrane: Math.max(...f) - Math.min(...f), faisceau: Math.max(...b) - Math.min(...b) };
  });
  assert.ok(pendules.filigrane >= 10, `le filigrane pivote de ${pendules.filigrane.toFixed(1)}°`);
  assert.ok(pendules.faisceau >= 15, `le faisceau balaie ${pendules.faisceau.toFixed(1)}°`);
});

// Retour de la TV du 18/09/2026 : « retire les cercles animés, elles cassent l'immersion ».
// Trois ondes concentriques partaient du centre de l'image du mode et la traversaient. Elles
// sont parties, et rien ne doit les ramener : on compte les arcs et les traits tracés pendant
// un cycle entier du motif, sur les deux toiles.
test("cinéma : aucun cercle, aucun trait — le motif ne touche plus la toile des lignes", async () => {
  await ouvrir({});
  const trace = await page.evaluate(() => {
    const P = CanvasRenderingContext2D.prototype;
    const compte = { arc: 0, ellipse: 0, arcTo: 0, stroke: 0, effacements: 0 };
    const origines = {};
    for (const nom of ["arc", "ellipse", "arcTo", "stroke"]) {
      origines[nom] = P[nom];
      P[nom] = function (...a) { compte[nom]++; return origines[nom].apply(this, a); };
    }
    const [basse, lignes] = [[320, 180], [960, 540]].map(([w, h]) => { const t = document.createElement("canvas"); t.width = w; t.height = h; return t.getContext("2d"); });
    const efface = lignes.clearRect.bind(lignes);
    lignes.clearRect = (...a) => { compte.effacements++; return efface(...a); };
    // Un cycle complet et large : les ondes duraient 6 s, le filigrane 14 s.
    for (let s = 0; s <= 30; s += .25) window.hubFond.peindreFond("cinema", "aurore", "sombre", s, [62, 224, 208], true, basse, lignes);
    const d = lignes.getImageData(0, 0, 960, 540).data;
    let poses = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i]) poses++;
    for (const nom of ["arc", "ellipse", "arcTo", "stroke"]) P[nom] = origines[nom];
    return { ...compte, poses };
  });
  assert.deepEqual(trace, { arc: 0, ellipse: 0, arcTo: 0, stroke: 0, effacements: 0, poses: 0 },
    "le motif cinéma trace encore quelque chose");
  // Et à l'écran : la toile des lignes reste cachée, les autres motifs la reprennent.
  await page.close();
  await ouvrir(profil({ motif: "cinema" }));
  assert.equal(await page.evaluate(() => document.getElementById("fond-lignes").hidden), true);
  await page.evaluate(() => { profil().motif = "profondeur"; appliquerTout(); });
  await page.waitForTimeout(200);
  assert.equal(await page.evaluate(() => document.getElementById("fond-lignes").hidden), false);
  assert.deepEqual(page.erreurs, []);
});

test("rythme : le motif cinéma est redessiné à 30 images par seconde au plus", async () => {
  await ouvrir(profil({ motif: "cinema", fond: "aurore" }));
  const { dessins, images } = await page.evaluate(() => new Promise(fin => {
    // Le voile du bas : un dégradé linéaire, créé une fois et une seule par image du motif
    // cinéma. Compté sur la toile du fond — celle des lignes ne sert plus à ce motif.
    const c = document.getElementById("fond").getContext("2d");
    const creer = c.createLinearGradient.bind(c);
    let n = 0;
    c.createLinearGradient = (...a) => { n++; return creer(...a); };
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
  assert.deepEqual(vignettes.map(v => v[0]), [...MOTIFS.map(m => `motif-${m}`), "motif-minimal", "motif-photos",
    ...COULEURS.map(c => `couleur-${c}`), "visuels-jeu-1", "visuels-jeu-2", "visuels-jeu-3", "visuels-pictogramme", "visuels-aucun"]);
  assert.deepEqual(vignettes.filter(v => v[1]).map(v => v[0]), ["motif-nappes", "couleur-ocean", "visuels-jeu-1"], "l'ancien profil : nappes, océan, jeu par défaut");
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

// Retour de la TV du 17/09/2026, planche motif × couleur : les six couleurs du motif cinéma
// étaient toutes violettes, la teinte du mode (92 % sur la grande tache) avait mangé la
// palette. On mesure la chromaticité moyenne du côté droit — là où vit la grande tache — et
// on demande que deux couleurs ne se ressemblent jamais, quel que soit le mode affiché.
test("fond : les six couleurs du motif cinéma se distinguent, teinte du mode allumée", async () => {
  await ouvrir({});
  const ecarts = await page.evaluate(([couleurs, accents]) => accents.map(([mode, accent]) => {
    // Chromaticité : la couleur moyenne ramenée à somme constante, la luminosité mise de côté.
    const chroma = couleur => {
      const v = window.hubFond.apercuFond("cinema", couleur, "sombre", 8, accent, true);
      const d = v.getContext("2d").getImageData(0, 0, v.width, v.height).data;
      let r = 0, g = 0, b = 0, n = 0;
      for (let y = 0; y < Math.round(v.height * .6); y++) for (let x = Math.round(v.width * .45); x < v.width; x++) {
        const i = 4 * (y * v.width + x); r += d[i]; g += d[i + 1]; b += d[i + 2]; n++;
      }
      const s = (r + g + b) / n || 1;
      return [r / n / s * 3, g / n / s * 3];
    };
    const points = couleurs.map(c => ({ c, xy: chroma(c) }));
    let pire = { ecart: Infinity };
    for (let i = 0; i < points.length; i++) for (let j = i + 1; j < points.length; j++) {
      const ecart = Math.hypot(points[i].xy[0] - points[j].xy[0], points[i].xy[1] - points[j].xy[1]);
      if (ecart < pire.ecart) pire = { mode, paire: `${points[i].c}/${points[j].c}`, ecart: +ecart.toFixed(3) };
    }
    return pire;
  }), [COULEURS, [["jeux", [179, 107, 255]], ["tv", [62, 224, 208]]]]);
  // Avant correction : .024 avec le violet des Jeux, .055 avec le turquoise de la TV.
  for (const p of ecarts) assert.ok(p.ecart >= .12, `mode ${p.mode} : ${p.paire} se ressemblent (${p.ecart})`);
  // Et le mode change quand même quelque chose : les mêmes couleurs, deux modes, deux rendus.
  assert.notDeepEqual(ecarts[0], ecarts[1]);
});

// Retour de la TV du 17/09/2026 : sur le motif profondeur, la grille du sol était l'élément
// le plus lumineux de l'écran, et les onglets, les tuiles et le pied semblaient posés
// dessus. Un écran de salon rend bien plus contrasté qu'un écran de bureau : la bande basse,
// là où vivent les rangées et le pied, doit rester calme sur tous les motifs. Mesuré sur le
// fond seul, sans le contenu : le 98e centile de luminance (le pixel presque le plus clair).
test("fond : sombre, la bande basse reste calme sur chaque motif et chaque couleur", async () => {
  await ouvrir({});
  const bandes = await page.evaluate(([motifs, couleurs]) => {
    const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
    const centile = (d, largeur, hauteur, a, b) => {
      const px = [];
      for (let y = Math.round(a * hauteur); y < Math.round(b * hauteur); y++)
        for (let x = 0; x < largeur; x++) { const i = 4 * (y * largeur + x); px.push(.2126 * lin(d[i]) + .7152 * lin(d[i + 1]) + .0722 * lin(d[i + 2])); }
      px.sort((u, w) => u - w);
      return +px[Math.floor(px.length * .98)].toFixed(3);
    };
    const r = [];
    for (const motif of motifs) for (const couleur of couleurs) {
      const v = window.hubFond.apercuFond(motif, couleur, "sombre", 8, [179, 107, 255], true);
      const d = v.getContext("2d").getImageData(0, 0, v.width, v.height).data;
      r.push({ motif, couleur, bas: centile(d, v.width, v.height, .72, 1) });
    }
    return r;
  }, [MOTIFS, COULEURS]);
  // Avant correction, le sol de profondeur montait à .126 ; il est à .023 aujourd'hui.
  const trop = bandes.filter(b => b.bas > .09);
  assert.deepEqual(trop, [], `bande basse trop lumineuse : ${JSON.stringify(bandes)}`);
});

// L'image du mode, à droite de l'accueil : trois jeux d'images posés dans le dépôt
// (installer/menu/images), le profil choisit le sien. Elles sont locales : seul le jeu
// choisi est chargé, une fois au départ, et jamais relu en changeant de mode.
const visuelVisible = () => page.evaluate(() => {
  const v = document.getElementById("visuel-mode");
  const vue = [...v.children].filter(i => i.classList.contains("visible")).map(i => i.dataset.visuel);
  return { cache: v.hidden, vue, filigrane: document.getElementById("filigrane").hidden, images: v.children.length, jeu: v.dataset.jeu };
});
// Chemins demandés au navigateur : « jeu-1/mode-tv.webp ».
const suivreImages = (demandes) => p => p.on("request", r => {
  const m = r.url().match(/\/images\/([^/]+\/mode-[^/]+)$/);
  if (m) demandes.push(m[1]);
});

test("image du mode : celle du mode choisi s'affiche à droite, change avec l'onglet, chargée une seule fois", async () => {
  const demandes = [];
  await ouvrir(profil({ motif: "cinema", dernier: "tv" }), "", suivreImages(demandes));
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 3, jeu: "jeu-1" });
  await touche("ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["jeux"], filigrane: true, images: 3, jeu: "jeu-1" });
  await touche("ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["bureau"], filigrane: true, images: 3, jeu: "jeu-1" });
  await touche("ArrowLeft", "ArrowLeft", "ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["jeux"], filigrane: true, images: 3, jeu: "jeu-1" });
  // Préchargement : les trois images du jeu choisi, une fois chacune — pas les neuf — et
  // rien de plus après six changements de mode.
  assert.deepEqual(demandes.sort(), ["jeu-1/mode-bureau.webp", "jeu-1/mode-jeux.webp", "jeu-1/mode-tv.webp"]);
  // Le fondu d'une image à l'autre reste court, et le masque ne bouge jamais.
  const fondu = await page.evaluate(() => {
    const cs = getComputedStyle(document.querySelector("#visuel-mode canvas"));
    return { durees: cs.transitionDuration.split(",").map(parseFloat), propriete: cs.transitionProperty };
  });
  assert.ok(Math.max(...fondu.durees) <= .2, `fondu ${fondu.durees}`);
  assert.equal(fondu.propriete, "opacity");
  // Un autre motif n'a ni image ni filigrane.
  await page.evaluate(() => { profil().motif = "rubans"; appliquerTout(); });
  await page.waitForTimeout(150);
  assert.deepEqual(await visuelVisible(), { cache: true, vue: [], filigrane: true, images: 3, jeu: "jeu-1" });
  assert.deepEqual(page.erreurs, []);
});

test("image du mode : animations réduites, aucun fondu ; image absente, le pictogramme en filigrane reprend", async () => {
  await ouvrir(profil({ motif: "cinema", dernier: "tv", animations: "reduites" }));
  const duree = await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector("#visuel-mode canvas")).transitionDuration));
  assert.ok(duree <= .01, `fondu en animations réduites : ${duree} s`);
  // Une image qui manque du dossier, ou illisible : elle quitte la page, le filigrane revient.
  await page.close();
  await ouvrir(profil({ motif: "cinema", dernier: "tv" }), "", p => p.route(/mode-jeux\.webp/, r => r.abort()));
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 2, jeu: "jeu-1" });
  await touche("ArrowRight");
  assert.deepEqual(await visuelVisible(), { cache: true, vue: [], filigrane: false, images: 2, jeu: "jeu-1" });
  assert.equal(await page.evaluate(() => document.getElementById("filigrane").dataset.picto), "jeux");
  assert.ok(await page.evaluate(() => document.querySelector("#filigrane svg").innerHTML.length > 0), "le pictogramme du mode est bien dessiné");
  await touche("ArrowLeft");
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 2, jeu: "jeu-1" });
  assert.deepEqual(page.erreurs, []);
});

test("image du mode : le jeu se choisit dans les réglages, s'enregistre, et « aucun » rend la place au filigrane", async () => {
  const demandes = [];
  await ouvrir(profil({ motif: "cinema", dernier: "tv", visuels: "jeu-2" }), "", suivreImages(demandes));
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 3, jeu: "jeu-2" });
  // Seul le jeu choisi est chargé : trois fichiers, jamais les neuf.
  assert.deepEqual(demandes.sort(), ["jeu-2/mode-bureau.webp", "jeu-2/mode-jeux.webp", "jeu-2/mode-tv.webp"]);
  // La rangée des réglages : quatre vignettes, celle du profil cochée, traduites.
  await page.evaluate(() => ACTIONS.reglages("fond"));
  await page.waitForTimeout(300);
  const rangee = await page.evaluate(() => [...document.querySelectorAll(".vignettes.visuels .vignette-fond")].map(v => ({
    cle: v.dataset.cle, choisie: v.classList.contains("choisie"), libelle: v.querySelector(".libelle").textContent,
    apercu: v.querySelector(".apercu-visuel")?.dataset.source || (v.querySelector(".apercu-filigrane") ? "filigrane" : null),
  })));
  assert.deepEqual(rangee, [
    { cle: "visuels-jeu-1", choisie: false, libelle: "Jeu 1", apercu: "images/jeu-1/mode-tv.webp" },
    { cle: "visuels-jeu-2", choisie: true, libelle: "Jeu 2", apercu: "images/jeu-2/mode-tv.webp" },
    { cle: "visuels-jeu-3", choisie: false, libelle: "Jeu 3", apercu: "images/jeu-3/mode-tv.webp" },
    { cle: "visuels-pictogramme", choisie: false, libelle: "Filigrane", apercu: "filigrane" },
    { cle: "visuels-aucun", choisie: false, libelle: "Aucun", apercu: null },
  ]);
  // Choisir « Jeu 3 » : l'accueil change de jeu, et le choix part dans les réglages enregistrés.
  await page.click('[data-cle="visuels-jeu-3"]');
  await attendreReglages(d => d.profils[0].visuels === "jeu-3");
  await page.evaluate(() => fermerTout());
  await page.waitForTimeout(300);
  assert.deepEqual(await visuelVisible(), { cache: false, vue: ["tv"], filigrane: true, images: 3, jeu: "jeu-3" });
  assert.deepEqual(demandes.filter(d => d.startsWith("jeu-3")).sort(), ["jeu-3/mode-bureau.webp", "jeu-3/mode-jeux.webp", "jeu-3/mode-tv.webp"]);
  // « Pictogramme » : plus d'image, le grand pictogramme du mode en filigrane reprend sa place.
  await page.evaluate(() => { profil().visuels = "pictogramme"; appliquerTout(); });
  await page.waitForTimeout(200);
  assert.deepEqual(await visuelVisible(), { cache: true, vue: [], filigrane: false, images: 0, jeu: "pictogramme" });
  // « Aucun » : rien à droite du tout, le fond animé et sa teinte de mode y suffisent.
  await page.evaluate(() => { profil().visuels = "aucun"; appliquerTout(); });
  await page.waitForTimeout(200);
  assert.deepEqual(await visuelVisible(), { cache: true, vue: [], filigrane: true, images: 0, jeu: "aucun" });
  // Ni l'un ni l'autre ne demande un fichier de plus (les vignettes des réglages ont chargé
  // les trois images de tête, c'est tout ce qui a bougé depuis).
  const avant = demandes.length;
  await page.evaluate(() => { profil().visuels = "pictogramme"; appliquerTout(); profil().visuels = "aucun"; appliquerTout(); });
  await page.waitForTimeout(300);
  assert.equal(demandes.length, avant, `fichiers chargés en trop : ${demandes.slice(avant)}`);
  // Une valeur inconnue (réglages écrits à la main) revient au jeu par défaut.
  await page.evaluate(() => { profil().visuels = "jeu-9"; appliquerTout(); });
  await page.waitForTimeout(200);
  assert.equal((await visuelVisible()).jeu, "jeu-1");
  assert.deepEqual(page.erreurs, []);
});

// Retour de la TV du 18/09/2026 : « la couleur du fond qui passe sur la totalité de l'image
// fait que l'image ne se voit pas bien ». Le fond passe maintenant DERRIÈRE l'image
// (index.html) et, en sombre, la photo est entière. La preuve se mesure : on photographie
// deux fois la même vue, une fois sur l'aurore (turquoise) et une fois sur la braise
// (orange), et on compare les pixels du cœur de l'image. Avant, l'écart moyen allait de 8 à
// 21 sur 255 — la couleur du fond repeignait la photo — et sa saturation doublait d'une
// palette à l'autre (jeu 3, mode TV : .27 sur l'aurore, .55 sur la braise). Aujourd'hui,
// en sombre, les deux captures sont identiques au pixel près.
const ZONE_IMAGE = { x: 1637, y: 350, largeur: 283, hauteur: 380 };
// Toute la boîte de l'image, telle qu'elle tient dans l'écran : #visuel-mode fait 104vh de
// large et déborde de 3vh à droite, de 6vh à 94vh en hauteur.
const BOITE_IMAGE = { x: 829, y: 65, largeur: 1091, hauteur: 950 };
async function coeurDeLImage(jeu, mode, theme, fond) {
  await page?.close();
  await ouvrir(profil({ motif: "cinema", fond, theme, visuels: jeu, animations: "reduites" }));
  await page.evaluate(m => definirFocus(document.querySelector(`.onglet[data-mode="${m}"]`), true), mode);
  await page.waitForTimeout(400);
  const png = (await page.screenshot()).toString("base64");
  const mesure = await page.evaluate(async ([png, z]) => {
    const i = new Image(); i.src = "data:image/png;base64," + png; await i.decode();
    const c = document.createElement("canvas"); c.width = z.largeur; c.height = z.hauteur;
    const x = c.getContext("2d");
    x.drawImage(i, z.x, z.y, z.largeur, z.hauteur, 0, 0, z.largeur, z.hauteur);
    const d = x.getImageData(0, 0, z.largeur, z.hauteur).data;
    const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
    const L = [];
    let sat = 0, n = 0;
    for (let k = 0; k < d.length; k += 4) {
      L.push(.2126 * lin(d[k]) + .7152 * lin(d[k + 1]) + .0722 * lin(d[k + 2]));
      const max = Math.max(d[k], d[k + 1], d[k + 2]), min = Math.min(d[k], d[k + 1], d[k + 2]);
      sat += max ? (max - min) / max : 0;
      n++;
    }
    const tri = [...L].sort((a, b) => a - b);
    return {
      pixels: [...d],
      contraste: +((tri[Math.floor(n * .95)] + .05) / (tri[Math.floor(n * .05)] + .05)).toFixed(2),
      saturation: +(sat / n).toFixed(3),
    };
  }, [png, ZONE_IMAGE]);
  return { ...mesure, png };
}
// Part de la boîte qui est de la vraie photo : les pixels que changer de palette ne change
// pas. Le reste, ce sont les bords où la photo s'éteint et où l'on voit la lueur du fond.
async function partDeVraiePhoto(a, b) {
  return page.evaluate(async ([x, y, z]) => {
    const lire = async b64 => { const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode(); const c = document.createElement("canvas"); c.width = z.largeur; c.height = z.hauteur; const t = c.getContext("2d"); t.drawImage(i, z.x, z.y, z.largeur, z.hauteur, 0, 0, z.largeur, z.hauteur); return t.getImageData(0, 0, z.largeur, z.hauteur).data; };
    const A = await lire(x), B = await lire(y);
    let pures = 0, n = 0;
    for (let i = 0; i < A.length; i += 4) { n++; if (A[i] === B[i] && A[i + 1] === B[i + 1] && A[i + 2] === B[i + 2]) pures++; }
    return pures / n;
  }, [a, b, BOITE_IMAGE]);
}
const ecartMoyen = (A, B) => {
  let s = 0;
  for (let i = 0; i < A.length; i += 4) s += (Math.abs(A[i] - B[i]) + Math.abs(A[i + 1] - B[i + 1]) + Math.abs(A[i + 2] - B[i + 2])) / 3;
  return 4 * s / A.length;
};

test("image du mode : le fond passe derrière elle — sa couleur ne déteint pas, et la photo garde son contraste", async () => {
  for (const jeu of ["jeu-1", "jeu-2", "jeu-3"]) {
    for (const mode of ["tv", "bureau"]) {
      const aurore = await coeurDeLImage(jeu, mode, "sombre", "aurore");
      const braise = await coeurDeLImage(jeu, mode, "sombre", "braise");
      const ecart = ecartMoyen(aurore.pixels, braise.pixels);
      assert.equal(ecart, 0, `${jeu} ${mode} : la couleur du fond déteint sur l'image (${ecart.toFixed(2)}/255)`);
      assert.deepEqual([aurore.contraste, aurore.saturation], [braise.contraste, braise.saturation], `${jeu} ${mode}`);
      // Sa propre étendue de lumière, pas celle d'un voile uni. Le pire des trois jeux
      // (le bureau du jeu 1, une pièce sombre) mesure 2,2 ; il était à 1,6 sous le voile.
      assert.ok(aurore.contraste >= 2, `${jeu} ${mode} : image délavée (contraste ${aurore.contraste}:1)`);
      // Second retour de la TV (1.0.3) : « est-ce que la lueur du haut et de gauche ne prend
      // pas trop d'espace sur l'image ? Les éléments sont un peu cachés ». Les fondus des
      // bords n'en laissaient que 32,7 % ; ils en laissent 58,7 % aujourd'hui. Le seuil est
      // à 50 % : de quoi refuser un retour en arrière sans casser au premier réglage fin.
      const part = await partDeVraiePhoto(aurore.png, braise.png);
      assert.ok(part >= .5, `${jeu} ${mode} : la lueur du fond mange l'image (${(part * 100).toFixed(1)} % de vraie photo)`);
    }
  }
  // En clair, l'image est volontairement retenue pour ne pas peser sur un fond pâle : le
  // fond transparaît donc encore un peu, mais la photo a gagné en contraste (jeu 3, bureau :
  // 1,62 sous le voile, 2,8 aujourd'hui) et ne change presque plus de couleur avec la palette.
  const clairA = await coeurDeLImage("jeu-3", "bureau", "clair", "aurore");
  const clairB = await coeurDeLImage("jeu-3", "bureau", "clair", "braise");
  assert.ok(ecartMoyen(clairA.pixels, clairB.pixels) < 20, `clair : le fond déteint encore (${ecartMoyen(clairA.pixels, clairB.pixels).toFixed(1)}/255)`);
  assert.ok(clairA.contraste >= 2.5, `clair : image délavée (contraste ${clairA.contraste}:1)`);
  assert.deepEqual(page.erreurs, []);
});

// Photo de la vraie TV sur la 1.0.7 : l'image du mode s'arrêtait sur une arête verticale
// franche, du haut en bas de l'écran, et le fond du motif occupait la bande du haut. La
// WebKitGTK du HUB n'applique pas les `mask-image` en dégradé que Chromium applique — un
// rendu qui ne se voit qu'une fois sur la TV. Deux garde-fous, pour que ça ne revienne pas
// sans TV : le menu ne doit plus contenir un seul masque, et ses calques de fond ne doivent
// s'écrire qu'en rgba() hérité, la syntaxe que tout moteur lit depuis quinze ans.
test("WebKitGTK : le rendu ne dépend plus d'aucun masque CSS", async () => {
  // La preuve par l'image : on rend l'accueil deux fois, une fois tel quel et une fois
  // tous masques coupés — comme le fait la WebKitGTK du HUB. Les deux captures doivent
  // être identiques au pixel près. Sur la 1.0.7, couper les masques faisait apparaître
  // une arête de 35 points sur 255 au bord gauche de l'image.
  await ouvrir(profil({ motif: "cinema", fond: "aurore", visuels: "jeu-2", dernier: "tv", animations: "reduites" }));
  await page.waitForTimeout(400);
  const avec = (await page.screenshot()).toString("base64");
  const style = await page.addStyleTag({ content: "*, *::before, *::after { -webkit-mask-image: none !important; mask-image: none !important; -webkit-mask-box-image: none !important; }" });
  await page.waitForTimeout(400);
  const sans = (await page.screenshot()).toString("base64");
  await style.evaluate(s => s.remove());
  assert.equal(avec, sans, "couper les masques change le rendu : le menu en dépend encore");
  assert.deepEqual(page.erreurs, []);
});

test("WebKitGTK : aucun masque dans la feuille, et les calques de fond en rgba() hérité", () => {
  const css = readFileSync(path.join(MENU, "hub.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const masques = css.match(/[^\n]*mask[^\n]*/g) || [];
  assert.deepEqual(masques, [], "un masque CSS est revenu dans hub.css");
  // Les calques plein écran : s'ils ne se peignent pas, l'écran entier change de visage.
  const calques = /(#fond|#fond-lignes|#filigrane|#visuel-mode|#photos|#ambiant|\.grain|\.vignette)(?![\w-])/;
  const modernes = [];
  for (const regle of css.split("}")) {
    const [tete, corps] = [regle.slice(0, regle.indexOf("{")), regle.slice(regle.indexOf("{") + 1)];
    if (!calques.test(tete)) continue;
    // « rgb(1 2 3 / .5) » : la syntaxe à espaces et barre oblique.
    for (const m of corps.match(/rgba?\([^)]*\/[^)]*\)/g) || []) modernes.push(`${tete.trim()} → ${m}`);
  }
  assert.deepEqual(modernes, [], "un calque de fond emploie la syntaxe de couleur moderne");
});

// L'arête, mesurée sans se laisser tromper par la photo elle-même (un écran, une bobine
// ont leurs propres bords francs). On photographie deux fois la même vue, sur deux palettes
// opposées, et on regarde colonne par colonne de combien les deux captures diffèrent : là où
// la photo est pleine, elles sont identiques ; là où elle est éteinte, elles diffèrent de
// toute la couleur du fond. Le profil de cet écart EST le fondu. S'il tombe d'un coup, c'est
// une arête. Les calques de fond seuls : le héros et les onglets ont leurs propres bords.
const SAUT_MAX = 3;
async function fondSeul(jeu, mode, theme, fond) {
  await page?.close();
  await ouvrir(profil({ motif: "cinema", fond, theme, visuels: jeu, animations: "reduites" }));
  await page.evaluate(m => definirFocus(document.querySelector(`.onglet[data-mode="${m}"]`), true), mode);
  const style = await page.addStyleTag({ content: ".ecran { visibility: hidden !important; }" });
  await page.waitForTimeout(450);
  const png = (await page.screenshot()).toString("base64");
  await style.evaluate(s => s.remove());
  return png;
}
async function profilDuBord(jeu, mode, theme) {
  const a = await fondSeul(jeu, mode, theme, "aurore");
  const b = await fondSeul(jeu, mode, theme, "braise");
  return page.evaluate(async ([x, y, zone]) => {
    const lire = async b64 => { const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode(); const c = document.createElement("canvas"); c.width = i.width; c.height = i.height; const t = c.getContext("2d"); t.drawImage(i, 0, 0); return t; };
    const [A, B] = [await lire(x), await lire(y)];
    const h = zone.bas - zone.haut;
    const colonne = cx => {
      const u = A.getImageData(cx, zone.haut, 1, h).data, v = B.getImageData(cx, zone.haut, 1, h).data;
      let s = 0;
      for (let k = 0; k < u.length; k += 4) s += (Math.abs(u[k] - v[k]) + Math.abs(u[k + 1] - v[k + 1]) + Math.abs(u[k + 2] - v[k + 2])) / 3;
      return s / h;
    };
    let pire = { saut: 0, x: 0 };
    let avant = colonne(zone.gauche);
    for (let cx = zone.gauche + 1; cx <= zone.droite; cx++) {
      const c = colonne(cx);
      if (Math.abs(c - avant) > pire.saut) pire = { saut: +Math.abs(c - avant).toFixed(2), x: cx };
      avant = c;
    }
    return pire;
  }, [a, b, { gauche: 800, droite: 1250, haut: 280, bas: 760 }]);
}

test("image du mode : aucune arête verticale là où elle entre, sur les trois jeux et les deux thèmes", async () => {
  const releve = [];
  for (const theme of ["sombre", "clair"]) {
    for (const jeu of ["jeu-1", "jeu-2", "jeu-3"]) {
      // Le mode TV du jeu 2 est le plus contrasté de ce côté-là : la bobine dorée sur le noir.
      releve.push({ theme, jeu, ...await profilDuBord(jeu, "tv", theme) });
    }
  }
  // Avec les masques ignorés, la photo entrait d'un coup : l'écart tombait de 30 à 0 en une
  // colonne. Peinte dans la toile, elle avance de moins d'un point sur 255 par colonne.
  const arêtes = releve.filter(r => r.saut > SAUT_MAX);
  assert.deepEqual(arêtes, [], `arête verticale : ${JSON.stringify(releve)}`);
  // Que la photo finisse par prendre toute la place, c'est l'affaire du test voisin (« sa
  // couleur ne déteint pas ») : ici on ne juge que la douceur du passage.
  assert.deepEqual(page.erreurs, []);
});

// Photo de la TV en mode ambiant : l'horloge, la date et la météo se retrouvaient posées en
// plein sur la bobine de film. L'horloge y dérive à chaque minute pour ne pas marquer la
// dalle : elle passera tôt ou tard sur le sujet, quel que soit le cadrage. L'image s'en va
// donc en ambiant, comme avant les images — et le fond y redevient calme (agitation du fond
// sous la date, thème clair : 22 avant, 2 aujourd'hui ; la date y tombait à 3,8:1).
test("mode ambiant : l'image du mode s'efface, et revient en sortant", async () => {
  await ouvrir(profil({ motif: "cinema", visuels: "jeu-2", dernier: "tv" }));
  const etat = () => page.evaluate(() => {
    const cs = getComputedStyle(document.getElementById("visuel-mode"));
    return { opacite: +cs.opacity, visibilite: cs.visibility, ambiant: document.body.classList.contains("ambiant") };
  });
  assert.deepEqual(await etat(), { opacite: 1, visibilite: "visible", ambiant: false });
  await touche("a");
  await page.waitForTimeout(1600);
  assert.deepEqual(await etat(), { opacite: 0, visibilite: "hidden", ambiant: true }, "l'image reste en ambiant");
  await touche("Escape");
  await page.waitForTimeout(1600);
  assert.deepEqual(await etat(), { opacite: 1, visibilite: "visible", ambiant: false }, "l'image ne revient pas");
  assert.deepEqual(page.erreurs, []);
});

test("image du mode : en anglais, la rangée des jeux est traduite", async () => {
  await ouvrir(profil({ motif: "cinema", langue: "en" }));
  await page.evaluate(() => ACTIONS.reglages("fond"));
  await page.waitForTimeout(300);
  assert.match(await page.textContent("#contenu-reglages"), /Mode pictures.*Set 1.*Set 2.*Set 3.*Watermark.*None/s);
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
