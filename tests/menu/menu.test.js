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
import { createHash } from "node:crypto";

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;

let navigateur, page;

// Le Chrome du système suffit ; HUB_NAVIGATEUR=chromium prend celui de Playwright s'il est installé.
before(async () => {
  navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });
});
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

test("Jeux ouvre le sous-écran des jeux en nuage, OK lance le service par son nom", async () => {
  await ouvrir({ retour: true });
  await touche("2");
  assert.deepEqual(await calques(), ["jeux"]);
  assert.deepEqual(await messages("choix"), [], "la carte Jeux n'est plus un départ");
  const tuiles = await page.$$eval("#contenu-jeux .tuile-service", t => t.map(e => e.dataset.cle));
  assert.deepEqual(tuiles, ["service-geforcenow", "service-xcloud", "service-boosteroid"], "sans relevé de hub-web, ni Steam ni Moonlight");
  assert.equal(await focus(), "service-geforcenow");
  assert.match(await page.textContent("#contenu-jeux"), /maintenu une seconde/);
  await touche("ArrowRight", "Enter");
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "web", service: "xcloud" }]);
});

test("Jeux : Steam et Moonlight n'apparaissent que détectés, un service sans navigateur refuse", async () => {
  const services = { geforcenow: { disponible: true, via: "appli" }, xcloud: { disponible: false, via: null }, boosteroid: { disponible: true, via: "navigateur" }, steam: { disponible: true, via: "appli" }, moonlight: { disponible: false, via: null } };
  await ouvrir({ retour: true, services: { navigateur: null, services } });
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "gaming" }));
  assert.deepEqual(await calques(), ["jeux"]);
  const tuiles = await page.$$eval("#contenu-jeux .tuile-service", t => t.map(e => e.dataset.cle));
  assert.deepEqual(tuiles, ["service-geforcenow", "service-xcloud", "service-boosteroid", "service-steam"]);
  assert.match(await page.textContent('#contenu-jeux [data-cle="service-geforcenow"]'), /Appli/);
  await page.click('#contenu-jeux [data-cle="service-xcloud"]');
  await page.waitForTimeout(700);
  assert.deepEqual(await messages("choix"), []);
  assert.match(await page.textContent("#annonce"), /navigateur manque/);
  await touche("Escape");
  assert.deepEqual(await calques(), []);
});

test("streaming sur l'accueil : Bas depuis les cartes, OK lance le service", async () => {
  await ouvrir({ retour: true });
  assert.equal(await page.locator("#applis .tuile-service").count(), 8);
  await touche("ArrowDown");
  assert.equal(await focus(), "service-netflix", "la tuile sous la carte TV");
  await touche("ArrowLeft");
  assert.equal(await focus(), "service-youtube");
  await touche("Enter");
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "web", service: "youtube" }]);
});

test("voix : « HUB, Netflix » lance le service, sauf s'il est masqué pour le profil", async () => {
  const reglages = { profilActif: "a", profils: [{ id: "a", nom: "Samuel", services: { netflix: false } }], systeme: { meteo: { active: false } } };
  await ouvrir({ retour: true, reglages });
  assert.equal(await page.locator('#applis [data-cle="service-netflix"]').count(), 0);
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "web:netflix" }));
  await page.waitForTimeout(700);
  assert.deepEqual(await messages("choix"), []);
  assert.match(await page.textContent("#annonce"), /masqué/);
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "web:inconnu" }));
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "web:francetv" }));
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "web", service: "francetv" }]);
});

test("réglages : masquer un service l'enlève de l'accueil et l'enregistre dans le profil", async () => {
  await ouvrir({ retour: true });
  await touche("r");
  await page.click('[data-section="services"]');
  await page.click('[data-cle="service-twitch-false"]');
  await attendreReglages(d => d.profils[0].services.twitch === false);
  await touche("Escape");
  assert.equal(await page.locator('#applis [data-cle="service-twitch"]').count(), 0);
  assert.equal(await page.locator("#applis .tuile-service").count(), 7);
});

test("profil sans TV : pas de streaming, services figés dans les réglages, voix refusée", async () => {
  const r = deuxProfils();
  r.profils[1].modes = { tv: false, gaming: true, bureau: true };
  r.profilActif = "alix";
  await ouvrir({ retour: true, reglages: r });
  assert.ok(!(await page.isVisible("#applis")));
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "web:youtube" }));
  await page.waitForTimeout(700);
  assert.deepEqual(await messages("choix"), []);
  assert.match(await page.textContent("#annonce"), /pas autorisé/);
  await touche("r");
  await page.click('[data-section="services"]');
  assert.match(await page.textContent("#contenu-reglages"), /seul un profil sans restriction/);
  assert.equal(await page.locator('[data-cle^="service-youtube-"]').count(), 0, "aucun bouton pour rallumer un service");
  await touche("Escape", "2");
  assert.deepEqual(await calques(), ["jeux"], "le mode Jeux, autorisé, garde ses services");
});

test("depuis une carte, Bas atteint le streaming puis les boutons du pied, Haut revient aux cartes", async () => {
  await ouvrir();
  await touche("ArrowDown");
  assert.match(await focus(), /^service-/);
  await touche("ArrowDown");
  assert.ok(["aide", "reglages", "arret", "minuteur"].includes(await focus()), `focus : ${await focus()}`);
  await touche("ArrowUp", "ArrowUp");
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

const PIN_1234 = { sel: "abc", empreinte: createHash("sha256").update("abc:1234").digest("hex") };
const deuxProfils = extra => ({
  profilActif: "samuel",
  profils: [{ id: "samuel", nom: "Samuel", pin: PIN_1234, ...extra }, { id: "alix", nom: "Alix", modes: { tv: true, gaming: true, bureau: false } }],
  systeme: { meteo: { active: false } },
});

test("code PIN : le SHA-256 du menu est le vrai SHA-256", async () => {
  await ouvrir({ retour: true });
  for (const texte of ["", "abc:1234", "é".repeat(80)]) {
    assert.equal(await page.evaluate(t => window.hubSha256(t), texte), createHash("sha256").update(texte).digest("hex"));
  }
});

test("code PIN : au démarrage, l'accueil reste fermé sans le bon code", async () => {
  await page?.close();
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(r => { window.__messages = []; window.webkit = { messageHandlers: { hub: { postMessage: m => window.__messages.push(JSON.parse(m)) } } }; window.HUB_INITIAL = { reglages: r }; }, deuxProfils());
  await page.goto(PAGE + "?sans-intro");
  await page.waitForFunction(() => document.querySelector("#code.ouvert"));
  assert.match(await page.textContent("#code-titre"), /Samuel/);
  await page.keyboard.type("0000");
  await page.waitForFunction(() => /incorrect/.test(document.querySelector("#code-detail").textContent));
  await touche("Escape");
  assert.deepEqual(await calques(), ["profils"], "annuler mène au choix du profil, pas à l'accueil");
  await touche("Escape");
  await page.waitForFunction(() => document.querySelector("#code.ouvert"));
  await touche("1");
  assert.deepEqual(await messages("choix"), []);
  await page.keyboard.type("234");
  await page.waitForFunction(() => !document.querySelector(".calque.ouvert"));
  assert.ok(!(await page.evaluate(() => document.body.classList.contains("verrouille"))));
  await touche("3");
  await attendreChoix();
});

test("code PIN : cinq erreurs bloquent la saisie", async () => {
  await ouvrir({ retour: true, reglages: deuxProfils() });
  await page.evaluate(() => { window.hub.recevoir({ type: "commande", nom: "profils" }); });
  await page.click('[data-cle="profil-alix"]');
  await page.click('[data-cle="profil-samuel"]');
  for (let i = 0; i < 5; i++) { await page.keyboard.type("9999"); await page.waitForTimeout(260); }
  await page.waitForFunction(() => /Réessaie dans/.test(document.querySelector("#code-detail").textContent));
  await page.keyboard.type("1234");
  await page.waitForTimeout(300);
  assert.ok(await page.isVisible("#code"), "même le bon code est refusé pendant le blocage");
});

test("code PIN : le définir dans l'éditeur l'enregistre haché, jamais en clair", async () => {
  await ouvrir({ retour: true });
  await touche("p");
  await page.click('[data-action="gerer-profils"]');
  await page.click('[data-cle="profil-samuel"]');
  await page.click('[data-cle="code-definir"]');
  await page.keyboard.type("2580");
  await page.waitForFunction(() => /seconde fois/.test(document.querySelector("#code-detail").textContent));
  await page.keyboard.type("2580");
  await page.waitForFunction(() => !document.querySelector("#code.ouvert"));
  await page.click('[data-cle="reglagesProteges-true"]');
  await page.click('[data-action="enregistrer-profil"]');
  await attendreReglages(d => !!d.profils[0].pin);
  const profil = (await messages("reglages")).at(-1).donnees.profils[0];
  assert.ok(!JSON.stringify(profil).includes("2580"));
  assert.equal(profil.pin.empreinte, createHash("sha256").update(`${profil.pin.sel}:2580`).digest("hex"));
  assert.equal(profil.reglagesProteges, true);
});

test("réglages protégés : R demande le code du profil", async () => {
  await ouvrir({ retour: true, reglages: deuxProfils({ reglagesProteges: true }) });
  await touche("r");
  assert.deepEqual(await calques(), ["code"]);
  await page.keyboard.type("1234");
  await page.waitForFunction(() => document.querySelector("#reglages.ouvert"));
});

test("profil restreint : Bureau masqué et refusé, profils non gérables", async () => {
  const r = deuxProfils();
  r.profilActif = "alix";
  await ouvrir({ retour: true, reglages: r });
  assert.ok(!(await page.isVisible('[data-mode="bureau"]')));
  await touche("3");
  await page.waitForTimeout(700);
  assert.deepEqual(await messages("choix"), []);
  assert.match(await page.textContent("#annonce"), /pas autorisé/);
  await touche("p");
  assert.ok(!(await page.isVisible('[data-action="gerer-profils"]')));
  assert.ok(!(await page.isVisible('[data-cle="profil-ajout"]')));
});

test("télécommande : QR code et code d'appairage, annonce quand un téléphone est relié", async () => {
  const etat = { url: "http://192.168.1.50:8790/", code: "482913", expire: Date.now() + 240000, telephones: 0, appairageLe: null };
  await ouvrir({ retour: true, telecommande: etat });
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "reglages" }));
  await page.click('[data-section="telecommande"]');
  await page.waitForFunction(() => document.querySelector(".qr svg"));
  assert.equal(await page.textContent(".code-appairage"), "482 913");
  await page.evaluate(e => window.hub.recevoir({ type: "telecommande", etat: { ...e, telephones: 1, appairageLe: Date.now() } }), etat);
  assert.match(await page.textContent("#annonce"), /Téléphone relié/);
  assert.match(await page.textContent(".appairage"), /Téléphones reliés : 1/);
  await page.evaluate(() => window.hub.recevoir({ type: "telecommande", etat: null }));
  assert.match(await page.textContent("#contenu-reglages"), /indisponible/);
});

test("mise à jour : rechercher, installer, suivre la progression puis relancer le menu", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "reglages" }));
  await page.click('[data-section="apropos"]');
  await page.click('[data-cle="maj-verifier"]');
  assert.equal((await messages("maj-verifier")).length, 1);
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: true, distant: "abc1234", installee: "0000000" }, etat: null }));
  assert.match(await page.textContent("#contenu-reglages"), /Nouvelle version disponible \(abc1234\)/);
  await page.click('[data-cle="maj-appliquer"]');
  assert.equal((await messages("maj-appliquer")).length, 1);
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "tests", version: "abc1234" } }));
  assert.ok(await page.isVisible(".barre-maj"));
  assert.ok(!(await page.isVisible('[data-cle="maj-verifier"]')), "pas de nouvelle recherche pendant l'installation");
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "terminee", version: "abc1234" } }));
  await page.waitForFunction(() => window.__messages.some(m => m.type === "relancer"), null, { timeout: 7000 });
});

test("mise à jour : échec des tests annoncé, rien d'installé", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "reglages" }));
  await page.click('[data-section="apropos"]');
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "echec", raison: "tests" } }));
  assert.match(await page.textContent("#contenu-reglages"), /rien n'a été installé/);
  await page.waitForTimeout(500);
  assert.deepEqual(await messages("relancer"), []);
});

test("clavier AZERTY : les touches 1 2 3 (sans Maj) ouvrent les modes et tapent le code", async () => {
  await ouvrir({ retour: true });
  await page.keyboard.down("Shift"); await page.keyboard.up("Shift");
  await page.dispatchEvent("body", "keydown", {});
  await page.evaluate(() => dispatchEvent(new KeyboardEvent("keydown", { key: '"', code: "Digit3", bubbles: true })));
  await attendreChoix();
  assert.deepEqual(await messages("choix"), [{ type: "choix", mode: "bureau" }]);
});

test("navigation : Haut depuis Fermer reste dans le contenu et atteint Rechercher", async () => {
  await ouvrir({ retour: true });
  await page.setViewportSize({ width: 1280, height: 800 });
  await touche("r");
  await page.click('[data-section="apropos"]');
  await page.evaluate(() => document.querySelector('[data-cle="fermer-reglages"]').dispatchEvent(new MouseEvent("mouseover", { bubbles: true })));
  await touche("ArrowUp");
  assert.equal(await focus(), "maj-verifier");
  assert.equal((await messages("maj-etat")).length >= 1, true, "l'état d'une mise à jour en cours est demandé à l'ouverture");
});

test("mise à jour : un état « terminee » ancien ne relance pas le menu", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "terminee", version: "abc" } }));
  await page.waitForTimeout(4600);
  assert.deepEqual(await messages("relancer"), []);
});

test("aperçu depuis la clé : bandeau, et aucun mode lancé", async () => {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.goto(PAGE + "?apercu&sans-intro");
  await page.waitForTimeout(300);
  assert.match(await page.textContent(".bandeau-apercu"), /rien n'est installé/);
  await page.keyboard.press("Enter");
  assert.match(await page.textContent("#annonce"), /s'ouvrira ici/);
  assert.ok(!(await page.evaluate(() => document.body.classList.contains("depart"))));
});

const LYON = { active: true, ville: "Lyon", lat: 45.76, lon: 4.84 };

test("météo : sans ville choisie, rien n'est demandé ni affiché", async () => {
  await ouvrir({ retour: true });
  await page.waitForTimeout(200);
  assert.deepEqual(await messages("meteo"), [], "aucune ville par défaut, donc aucun relevé");
  assert.ok(!(await page.isVisible("#puce-meteo")));
  await page.evaluate(() => ACTIONS.reglages("meteo"));
  assert.match(await page.textContent("#contenu-reglages"), /Aucune ville choisie/);
});

test("météo : une ville déjà enregistrée est gardée et relevée", async () => {
  await ouvrir({ retour: true, reglages: { profils: [{ id: "a", nom: "A" }], systeme: { meteo: LYON } } });
  await page.waitForFunction(() => window.__messages.some(m => m.type === "meteo"));
  assert.deepEqual(await messages("meteo"), [{ type: "meteo", lat: 45.76, lon: 4.84 }]);
});

test("météo reçue de hub-menu : puce, alerte pluie et panneau détaillé", async () => {
  await ouvrir({ reglages: { profils: [{ id: "a", nom: "A" }], systeme: { meteo: LYON } } });
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
  assert.equal(await page.textContent("#meteo-ville-puce"), "Lyon");
  await touche("m");
  assert.deepEqual(await calques(), ["meteo"]);
  assert.equal(await page.locator(".jour").count(), 6);
  assert.deepEqual(page.erreurs, []);
});

test("météo : un nom de ville reçu reste du texte, jamais du HTML", async () => {
  const piege = '<img src=x onerror="window.__piege=1">Lyon';
  await ouvrir({ retour: true, reglages: { profils: [{ id: "a", nom: "A" }], systeme: { meteo: { ...LYON, ville: piege } } } });
  await page.evaluate(() => window.hub.recevoir({ type: "meteo", releveLe: Date.now(), horsLigne: false,
    donnees: { current: { temperature_2m: 12, weather_code: 3, is_day: 1 }, hourly: { time: [] }, daily: {} } }));
  await touche("a");
  await page.waitForTimeout(200);
  assert.equal(await page.locator("#ambiant-meteo img").count(), 0);
  assert.equal(await page.locator("#ambiant-meteo svg").count(), 1, "le picto, lui, reste un dessin");
  assert.match(await page.textContent("#ambiant-meteo"), /onerror/);
  assert.equal(await page.evaluate(() => window.__piege), undefined);
});
