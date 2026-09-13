// Le menu du HUB piloté comme sur la TV : touches, commandes vocales, pont vers
// hub-menu. Le pont WebKit est remplacé par un faux qui note chaque message : ce
// que le menu envoie à Python est exactement ce que ces tests vérifient.
//
//   cd tests/menu && npm install && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;

let navigateur, page;

before(async () => { navigateur = await chromium.launch(); });
after(async () => { await navigateur?.close(); });

async function ouvrir(initial = {}) {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  const erreurs = [];
  page.on("pageerror", e => erreurs.push(e.message));
  page.erreurs = erreurs;
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(initial => {
    window.__messages = [];
    window.webkit = { messageHandlers: { hub: { postMessage: m => window.__messages.push(JSON.parse(m)) } } };
    window.HUB_INITIAL = initial;
  }, initial);
  await page.goto(PAGE);
  await page.waitForTimeout(200);
}

const messages = type => page.evaluate(t => window.__messages.filter(m => m.type === t), type);
const focus = () => page.evaluate(() => {
  const e = document.querySelector(".focus");
  return e && (e.dataset.mode || e.dataset.cle || e.dataset.action || e.textContent.trim());
});
const touche = async (...touches) => { for (const k of touches) { await page.keyboard.press(k); await page.waitForTimeout(60); } };
// La machine de test peut être chargée : on attend un état, jamais une durée fixe.
const attendreReglages = verifie => page.waitForFunction(v => {
  const m = window.__messages.filter(x => x.type === "reglages").at(-1);
  return m && new Function("d", `return (${v})(d)`)(m.donnees);
}, verifie.toString(), { timeout: 5000 });
const attendreChoix = () => page.waitForFunction(() => window.__messages.some(m => m.type === "choix"), null, { timeout: 5000 });
const calques = () => page.evaluate(() => [...document.querySelectorAll(".calque.ouvert")].map(c => c.id));

beforeEach(async () => { await page?.close(); });

test("au démarrage, la carte du dernier mode est sélectionnée et rien n'est envoyé", async () => {
  await ouvrir({ dernier: "bureau" });
  assert.equal(await focus(), "bureau");
  assert.deepEqual(await messages("choix"), []);
  assert.deepEqual(page.erreurs, []);
});

test("les flèches changent de carte, Entrée lance le mode", async () => {
  await ouvrir();
  assert.equal(await focus(), "tv");
  await touche("ArrowRight", "ArrowRight");
  assert.equal(await focus(), "bureau");
  await touche("Enter");
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "bureau" }]);
  await attendreReglages(d => d.profils[0].dernier === "bureau");
});

test("Jeux n'est pas configuré : un message, et le menu reste ouvert", async () => {
  await ouvrir();
  await touche("2");
  await page.waitForTimeout(800);
  assert.deepEqual(await messages("choix"), []);
  assert.match(await page.textContent("#annonce"), /Jeux arrive bientôt/);
});

test("depuis une carte, Bas atteint les boutons du pied, Haut revient aux cartes", async () => {
  await ouvrir();
  await touche("ArrowDown");
  assert.ok(["aide", "reglages", "arret", "minuteur"].includes(await focus()), `focus : ${await focus()}`);
  await touche("ArrowUp");
  assert.ok(["tv", "gaming", "bureau"].includes(await focus()));
});

test("éteindre demande confirmation, Annuler est sélectionné d'abord", async () => {
  await ouvrir();
  await touche("e");
  assert.deepEqual(await calques(), ["arret"]);
  await touche("Enter");
  assert.deepEqual(await calques(), []);
  assert.deepEqual(await messages("choix"), []);
  await touche("e", "ArrowRight", "Enter");
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "eteindre" }]);
});

test("réglages : parcourir le sommaire change la section, choisir un fond l'enregistre", async () => {
  await ouvrir();
  await touche("r");
  assert.deepEqual(await calques(), ["reglages"]);
  assert.equal(await page.textContent("#contenu-reglages h3"), "Apparence");
  await touche("ArrowDown");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Arrière-plan");
  await touche("ArrowRight");
  assert.equal(await focus(), "fond-aurore");
  await touche("ArrowRight", "Enter");
  await attendreReglages(d => d.profils[0].fond === "nebuleuse");
  assert.equal(await focus(), "fond-nebuleuse", "la sélection reste sur la vignette choisie");
  await touche("Escape");
  assert.deepEqual(await calques(), []);
});

test("thème et langue : T et L basculent, et c'est enregistré", async () => {
  await ouvrir();
  await touche("t");
  assert.equal(await page.getAttribute("html", "data-theme"), "clair");
  await touche("l");
  assert.match(await page.textContent("#salut"), /^Good/);
  await attendreReglages(d => d.profils[0].theme === "clair" && d.profils[0].langue === "en");
});

test("commandes vocales : ouvrir, revenir, lancer", async () => {
  await ouvrir();
  await page.evaluate(() => window.hub.recevoir({ type: "voix", etat: "eveil" }));
  assert.ok(await page.isVisible("#voix-pastille"));
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "reglages" }));
  assert.deepEqual(await calques(), ["reglages"]);
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "retour" }));
  assert.deepEqual(await calques(), []);
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "theme:clair" }));
  assert.equal(await page.getAttribute("html", "data-theme"), "clair");
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "tv" }));
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "tv" }]);
});

test("profils : créer un profil au clavier, puis l'utiliser", async () => {
  await ouvrir();
  await touche("p");
  assert.deepEqual(await calques(), ["profils"]);
  await touche("ArrowRight");
  assert.equal(await focus(), "profil-ajout");
  await touche("Enter");
  assert.deepEqual(await calques(), ["profils", "editeur-profil", "clavier"]);
  await page.keyboard.type("camille");
  await touche("Enter");
  assert.deepEqual(await calques(), ["profils", "editeur-profil"]);
  assert.equal(await page.textContent("#editeur-nom"), "Camille");
  await page.click('[data-action="enregistrer-profil"]');
  await attendreReglages(d => d.profils.length === 2);
  const donnees = (await messages("reglages")).at(-1).donnees;
  assert.deepEqual(donnees.profils.map(p => p.nom), ["Samuel", "Camille"]);
  await page.click(`[data-cle="profil-${donnees.profils[1].id}"]`);
  assert.match(await page.textContent("#salut"), /Camille$/);
  await page.waitForFunction(id => window.__messages.filter(m => m.type === "reglages").at(-1)?.donnees.profilActif === id, donnees.profils[1].id, { timeout: 3000 });
});

test("photo de profil : choisie dans l'éditeur, affichée partout, liste rafraîchie", async () => {
  const photo = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="red"/></svg>');
  await ouvrir({ retour: true, avatars: [] });
  await touche("p");
  await page.click('[data-action="gerer-profils"]');
  await page.click('[data-cle="profil-samuel"]');
  assert.deepEqual((await messages("avatars")).length, 1, "l'éditeur redemande la liste des photos");
  assert.ok(await page.isVisible("#aide-photo"));
  await page.evaluate(p => window.hub.recevoir({ type: "avatars", liste: [p] }), photo);
  assert.ok(!(await page.isVisible("#aide-photo")));
  await page.click('[data-cle="photo-0"]');
  await page.click('[data-action="enregistrer-profil"]');
  await attendreReglages(new Function("d", `return d.profils[0].photo === ${JSON.stringify(photo)}`));
  await page.waitForFunction(() => document.querySelector("#avatar-profil").classList.contains("avec-photo"));
});

test("les réglages reçus au démarrage s'appliquent : profil, thème, langue", async () => {
  await ouvrir({
    reglages: {
      profilActif: "b",
      profils: [{ id: "a", nom: "Samuel" }, { id: "b", nom: "Alix", theme: "clair", langue: "en" }],
      systeme: { meteo: { active: false } },
    },
  });
  assert.equal(await page.getAttribute("html", "data-theme"), "clair");
  assert.match(await page.textContent("#salut"), /Alix$/);
  assert.equal(await page.textContent('[data-mode="bureau"] .nom'), "Desktop");
  assert.ok(!(await page.isVisible("#puce-meteo")));
});

test("minuteur de veille : le choix part vers hub-menu, la réponse s'affiche", async () => {
  await ouvrir();
  await page.evaluate(() => { window.hub.recevoir({ type: "commande", nom: "reglages" }); });
  await page.click('[data-section="veille"]');
  await page.click('[data-cle="minuteur-30"]');
  assert.deepEqual((await messages("minuteur")).at(-1), { type: "minuteur", minutes: 30 });
  await page.evaluate(() => window.hub.recevoir({ type: "minuteur", fin: Date.now() + 30 * 60000 }));
  assert.ok(await page.isVisible("#bouton-minuteur"));
  assert.match(await page.textContent("#minuteur-texte"), /30 min/);
});

test("mode ambiant : la première touche réveille sans rien déclencher", async () => {
  await ouvrir();
  await touche("a");
  assert.ok(await page.evaluate(() => document.body.classList.contains("ambiant")));
  await touche("Enter");
  assert.ok(!(await page.evaluate(() => document.body.classList.contains("ambiant"))));
  await page.waitForTimeout(800);
  assert.deepEqual(await messages("choix"), []);
});

test("continuer à regarder : une tuile par reprise, OK relance Kodi sur le fichier", async () => {
  await ouvrir({
    retour: true,
    reprises: [
      { genre: "episode", titre: "Chernobyl", sousTitre: "S01 E03 · Le retour", fichier: "smb://nas/c-s01e03.mkv", position: 600, duree: 3600, image: null },
      { genre: "film", titre: "Dune", sousTitre: null, fichier: "/media/dune.mkv", position: 3600, duree: 9000, image: null },
    ],
  });
  assert.equal(await page.locator(".reprise").count(), 2);
  assert.match(await page.textContent(".reprise >> nth=0"), /Reste 50 min/);
  await touche("ArrowDown");
  assert.equal(await focus(), "reprise-0");
  await touche("ArrowRight", "Enter");
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "tv", fichier: "/media/dune.mkv" }]);
});

test("sans reprise, la ligne n'existe pas et l'intro ne joue qu'à l'allumage", async () => {
  await ouvrir({ retour: true });
  assert.ok(!(await page.isVisible("#reprises")));
  assert.ok(!(await page.isVisible("#intro")));
  await page.close();
  await ouvrir({});
  assert.ok(await page.isVisible("#intro"));
});

test("météo reçue de hub-menu : puce, alerte pluie et panneau détaillé", async () => {
  await ouvrir();
  // Open-Meteo (timezone=auto) donne des heures locales sans fuseau : on fait pareil.
  const heure = h => { const d = new Date(); d.setMinutes(0, 0, 0); d.setHours(d.getHours() + h); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
  const heures = Array.from({ length: 24 }, (_, i) => heure(i));
  await page.evaluate(({ heures }) => window.hub.recevoir({
    type: "meteo", releveLe: new Date().toISOString(), horsLigne: false,
    donnees: {
      current: { temperature_2m: 17.6, apparent_temperature: 16, weather_code: 61, is_day: 1, wind_speed_10m: 22, relative_humidity_2m: 80 },
      hourly: { time: heures, temperature_2m: heures.map(() => 15), weather_code: heures.map(() => 61), precipitation_probability: heures.map((_, i) => i === 2 ? 80 : 10), is_day: heures.map(() => 1) },
      daily: { time: ["2026-09-13", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"], weather_code: [61, 3, 0, 1, 2, 80], temperature_2m_max: [19, 20, 22, 21, 18, 17], temperature_2m_min: [12, 13, 14, 12, 11, 10], sunrise: Array(6).fill("2026-09-13T07:50"), sunset: Array(6).fill("2026-09-13T20:33"), precipitation_probability_max: [80, 10, 0, 5, 10, 60] },
    },
  }), { heures });
  assert.equal(await page.textContent("#meteo-temp-puce"), "18°");
  assert.match(await page.textContent("#sous-salut"), /Pluie probable vers/);
  await touche("m");
  assert.deepEqual(await calques(), ["meteo"]);
  assert.equal(await page.locator(".jour").count(), 6);
  assert.deepEqual(page.erreurs, []);
});
