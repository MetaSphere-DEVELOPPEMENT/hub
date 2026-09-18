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

// Le faux pont joue aussi le rôle de hub-menu pour les codes PIN : il vérifie l'ancien
// format sha256 (celui de PIN_1234) et compte les échecs comme lui (quatre libres, puis
// 30 s). window.__pinSilencieux : hub-menu ne répond pas.
function installerFauxPont(initial) {
  window.__messages = [];
  const faux = { echecs: 0, jusqua: 0 };
  const repondre = m => {
    if (window.__pinSilencieux) return;
    let r;
    if (m.type === "pin-creer") {
      r = { resultat: "hache", pin: { algo: "essai", sel: "00", empreinte: window.hubSha256(`00:${m.code}`) } };
    } else if (m.type === "pin-verifier") {
      if (faux.jusqua > Date.now()) r = { resultat: "bloque", attente: Math.ceil((faux.jusqua - Date.now()) / 1000) };
      else {
        // eslint-disable-next-line no-undef -- les réglages de la page, déclarés par hub.js
        const p = reglages.profils.find(x => m.profils.includes(x.id) && x.pin && window.hubSha256(`${x.pin.sel}:${m.code}`) === x.pin.empreinte);
        if (p) { faux.echecs = 0; r = { resultat: "ok", attente: 0, profil: p.id }; }
        else if (++faux.echecs >= 5) { faux.echecs = 0; faux.jusqua = Date.now() + 30000; r = { resultat: "refus", attente: 30 }; }
        else r = { resultat: "refus", attente: 0 };
      }
    } else return;
    setTimeout(() => window.hub.recevoir({ type: "pin", demande: m.demande, ...r }), 30);
  };
  window.webkit = { messageHandlers: { hub: { postMessage: texte => { const m = JSON.parse(texte); window.__messages.push(m); repondre(m); } } } };
  window.HUB_INITIAL = initial;
}

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
  await page.addInitScript(installerFauxPont, initial);
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

test("streaming sur l'accueil : Bas depuis les onglets, OK lance le service", async () => {
  await ouvrir({ retour: true });
  assert.equal(await page.locator("#applis .tuile-service").count(), 8);
  await touche("ArrowDown");
  assert.equal(await focus(), "service-youtube", "la tuile sous l'onglet TV");
  await touche("ArrowRight", "ArrowLeft", "ArrowLeft");
  assert.equal(await focus(), "service-youtube", "Gauche s'arrête au bout de la rangée");
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

test("depuis un onglet, Bas atteint le streaming puis les boutons du pied, Haut revient aux onglets", async () => {
  await ouvrir();
  await touche("ArrowDown");
  assert.match(await focus(), /^service-/);
  await touche("ArrowDown");
  assert.ok(["aide", "reglages", "arret", "minuteur"].includes(await focus()), `focus : ${await focus()}`);
  await touche("ArrowUp", "ArrowUp");
  assert.ok(["tv", "gaming", "bureau"].includes(await focus()));
});

// Le bouton Éteindre du pied ouvre un menu d'actions, pas un interrupteur. Annuler ouvre
// la liste et la garde à chaque ouverture : la mémoire de focus des calques ramènerait
// sinon sur la dernière entrée choisie, et un OK parti trop vite couperait la machine.
test("arrêt : six actions expliquées, Annuler sélectionné à chaque ouverture", async () => {
  await ouvrir();
  await touche("e");
  assert.deepEqual(await calques(), ["arret"]);
  const entrees = await page.evaluate(() => [...document.querySelectorAll("#arret [data-nav]")].map(e => ({
    cle: e.dataset.cle, nom: e.querySelector(".action-nom").textContent, detail: e.querySelector(".action-detail").textContent,
  })));
  assert.deepEqual(entrees.map(e => e.cle),
    ["arret-annuler", "arret-eteindre", "arret-redemarrer", "arret-veille", "arret-ambiant", "arret-profils"]);
  assert.deepEqual(entrees.filter(e => !e.nom.trim() || !e.detail.trim()), [], "chaque action porte son nom et sa ligne d'explication");
  assert.match(entrees[4].nom, /Always-On Display/);
  assert.equal(await focus(), "arret-annuler");
  await touche("ArrowDown", "ArrowDown");
  assert.equal(await focus(), "arret-redemarrer", "les flèches parcourent la liste");
  await touche("Escape");
  assert.deepEqual(await calques(), []);
  await touche("e");
  assert.equal(await focus(), "arret-annuler", "rouvert, le menu repart d'Annuler");
  await touche("Enter");
  assert.deepEqual(await calques(), [], "Annuler ramène à l'accueil");
  assert.deepEqual(await messages("choix"), []);
});

test("arrêt : éteindre et redémarrer confirment avant d'envoyer leur mode", async () => {
  for (const [cle, mode, titre] of [["arret-eteindre", "eteindre", /Éteindre le HUB/], ["arret-redemarrer", "redemarrer", /Redémarrer le HUB/]]) {
    await page?.close();
    await ouvrir();
    await touche("e");
    await page.click(`[data-cle="${cle}"]`);
    assert.deepEqual(await calques(), ["arret", "confirmer"], cle);
    assert.match(await page.textContent("#confirmer-titre"), titre);
    assert.equal(await focus(), "confirmer-annuler");
    await touche("Enter");
    assert.deepEqual(await calques(), ["arret"], "Annuler revient au menu, sans rien couper");
    assert.deepEqual(await messages("choix"), []);
    await page.click(`[data-cle="${cle}"]`);
    await touche("ArrowRight", "Enter");
    await attendreChoix();
    assert.deepEqual(await messages("choix"), [{ type: "choix", mode }]);
  }
});

test("arrêt : mettre en veille passe en ambiant et demande la veille à hub-menu", async () => {
  await ouvrir();
  await touche("e");
  await page.click('[data-cle="arret-veille"]');
  assert.deepEqual(await calques(), []);
  assert.ok(await page.evaluate(() => document.body.classList.contains("ambiant")));
  assert.deepEqual(await messages("veille"), [{ type: "veille" }]);
  assert.deepEqual(await messages("choix"), []);
  // Refusée (fenêtre du mode ambiant) : l'écran ne reste pas à faire croire que ça dort.
  await page.evaluate(() => window.hub.recevoir({ type: "veille", resultat: "refus", raison: "ambiant" }));
  assert.ok(!(await page.evaluate(() => document.body.classList.contains("ambiant"))));
  assert.match(await page.textContent("#annonce"), /pas possible/);
});

test("arrêt : l'écran permanent bascule en mode ambiant sans rien arrêter", async () => {
  await ouvrir();
  await touche("e");
  await page.click('[data-cle="arret-ambiant"]');
  assert.deepEqual(await calques(), []);
  assert.ok(await page.evaluate(() => document.body.classList.contains("ambiant")));
  await page.waitForTimeout(400);
  assert.deepEqual(await messages("choix"), []);
  assert.deepEqual(await messages("veille"), []);
  await touche("Enter");
  assert.ok(!(await page.evaluate(() => document.body.classList.contains("ambiant"))), "la première touche réveille");
});

test("arrêt : changer de profil ouvre la liste des profils", async () => {
  await ouvrir({ retour: true, reglages: deuxProfils() });
  await touche("e");
  await page.click('[data-cle="arret-profils"]');
  // calques() suit l'ordre du HTML, pas celui de la pile : la liste s'ouvre par-dessus le menu.
  assert.deepEqual((await calques()).sort(), ["arret", "profils"]);
  assert.equal(await page.locator("#liste-profils .tuile-profil").count(), 3, "les deux profils et l'ajout");
});

// Un profil restreint ne coupe pas la machine de toute la maison : le code d'un parent
// (profil sans restriction, protégé par un code) est demandé d'abord — le même gardien que
// pour accorder du temps d'écran.
test("arrêt : sur un profil restreint, éteindre demande le code d'un parent", async () => {
  const r = deuxProfils();
  r.profilActif = "alix";
  await ouvrir({ retour: true, reglages: r });
  await touche("e");
  await page.click('[data-cle="arret-eteindre"]');
  await page.waitForFunction(() => document.querySelector("#code.ouvert"));
  await page.keyboard.type("0000");
  await page.waitForFunction(() => /incorrect/.test(document.querySelector("#code-detail").textContent));
  assert.deepEqual(await messages("choix"), []);
  await page.keyboard.type("1234");
  await page.waitForFunction(() => document.querySelector("#confirmer.ouvert"));
  assert.equal(await focus(), "confirmer-annuler", "même là, la confirmation repart d'Annuler");
  // Ce qui se défait d'un geste ne demande pas de code : la veille et l'écran permanent.
  await touche("Escape");
  await page.click('[data-cle="arret-veille"]');
  assert.deepEqual(await messages("veille"), [{ type: "veille" }]);
});

test("arrêt : profil restreint sans parent protégé, la confirmation suffit", async () => {
  const r = deuxProfils();
  r.profilActif = "alix";
  delete r.profils[0].pin;
  await ouvrir({ retour: true, reglages: r });
  await touche("e");
  await page.click('[data-cle="arret-eteindre"]');
  assert.deepEqual(await calques(), ["arret", "confirmer"], "sans code parent, la restriction ne tient pas : on n'enferme personne");
});

test("anglais : le menu d'arrêt et sa confirmation sont traduits", async () => {
  await ouvrir({ retour: true, reglages: { profilActif: "a", profils: [{ id: "a", nom: "Sam", langue: "en" }], systeme: { meteo: { active: false } } } });
  await touche("e");
  assert.equal(await page.textContent("#arret h2"), "What should the HUB do?");
  assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll("#arret .action-nom")].map(e => e.textContent)),
    ["Cancel", "Power off", "Restart", "Sleep", "Always-On Display", "Switch profile"]);
  await page.click('[data-cle="arret-redemarrer"]');
  assert.equal(await page.textContent("#confirmer-titre"), "Restart the HUB?");
  assert.equal(await page.textContent("#confirmer-oui"), "Restart");
});

// Sur la TV, la télécommande n'a pas de bouton d'arrêt : c'est « retour » qui ouvre le
// menu, comme sur une box. Il ne faisait rien sur l'accueil (constaté sur la TV le
// 18/09/2026 : il fallait viser le bouton Éteindre du pied).
test("accueil : Échap ouvre le menu d'arrêt ; dans un calque, il ferme comme avant", async () => {
  await ouvrir();
  await touche("Escape");
  assert.deepEqual(await calques(), ["arret"]);
  assert.equal(await focus(), "arret-annuler");
  await touche("Escape");
  assert.deepEqual(await calques(), [], "dans le menu, Échap referme");
  await touche("r");
  assert.deepEqual(await calques(), ["reglages"]);
  await touche("Escape");
  assert.deepEqual(await calques(), [], "depuis un calque, Échap ferme le calque, il n'ouvre rien");
  await touche("Backspace");
  assert.deepEqual(await calques(), ["arret"], "l'autre touche de retour fait la même chose");
  await touche("Escape");
  // « HUB, retour » (voix, télécommande) suit la même règle que la touche.
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "retour" }));
  await page.waitForTimeout(200);
  assert.deepEqual(await calques(), ["arret"]);
  assert.deepEqual(await messages("choix"), []);
});

// Effacer un profil est la seule action du menu qui détruit des réglages : elle passait
// sans rien demander (constaté sur la TV le 18/09/2026).
test("supprimer un profil demande confirmation, son nom dans la question et sur le bouton", async () => {
  await ouvrir({ retour: true, reglages: deuxProfils() });
  await touche("p");
  await page.click('[data-action="gerer-profils"]');
  await page.click('[data-cle="profil-alix"]');
  await page.click('[data-action="supprimer-profil"]');
  assert.ok((await calques()).includes("confirmer"), await calques());
  assert.match(await page.textContent("#confirmer-titre"), /Supprimer Alix/);
  assert.match(await page.textContent("#confirmer-oui"), /Supprimer Alix/, "le bouton dit ce qu'il fait, pas « OK »");
  assert.equal(await focus(), "confirmer-annuler");
  await touche("Enter");
  assert.ok(!(await calques()).includes("confirmer"));
  assert.equal(await page.locator("#liste-profils .tuile-profil").count(), 3, "annulé, le profil est toujours là");
  await page.click('[data-action="supprimer-profil"]');
  await page.click('[data-cle="confirmer-oui"]');
  await attendreReglages(d => d.profils.length === 1);
  assert.deepEqual(await calques(), ["profils"], "l'éditeur et la confirmation se referment");
  assert.equal(await page.locator("#liste-profils .tuile-profil").count(), 2, "le profil restant et la tuile d'ajout");
});

test("anglais : la confirmation de suppression est traduite", async () => {
  const r = deuxProfils();
  r.profils[0].langue = "en";
  await ouvrir({ retour: true, reglages: r });
  await touche("p");
  await page.click('[data-action="gerer-profils"]');
  await page.click('[data-cle="profil-alix"]');
  await page.click('[data-action="supprimer-profil"]');
  assert.equal(await page.textContent("#confirmer-titre"), "Delete Alix?");
  assert.equal(await page.textContent("#confirmer-oui"), "Delete Alix");
  assert.equal(await page.textContent("#confirmer-annuler"), "Cancel");
});

test("réglages : parcourir le sommaire change la section, choisir un motif puis une couleur l'enregistre", async () => {
  await ouvrir();
  await touche("r");
  assert.deepEqual(await calques(), ["reglages"]);
  assert.equal(await page.textContent("#contenu-reglages h3"), "Apparence");
  // Apparence, puis Affichage (affichage.js, les modes de l'écran), puis Arrière-plan.
  await touche("ArrowDown");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Affichage");
  await touche("ArrowDown");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Arrière-plan");
  await touche("ArrowRight");
  assert.equal(await focus(), "motif-cinema", "un profil neuf a le motif cinéma");
  await touche("ArrowRight", "ArrowRight", "Enter");
  await attendreReglages(d => d.profils[0].motif === "profondeur" && d.profils[0].fond === "aurore");
  assert.equal(await focus(), "motif-profondeur", "la sélection reste sur la vignette choisie");
  // Deux rangées de motifs (quatre, puis trois), puis les couleurs.
  await touche("ArrowDown", "ArrowDown");
  assert.match(await focus(), /^couleur-/);
  await page.evaluate(() => definirFocus(document.querySelector('[data-cle="couleur-emeraude"]')));
  await touche("Enter");
  await attendreReglages(d => d.profils[0].motif === "profondeur" && d.profils[0].fond === "emeraude");
  assert.equal(await page.evaluate(() => window.hubFond.motifChoisi()), "profondeur");
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

test("réglages : l'éditeur de profil ouvert depuis Profils passe devant la feuille", async () => {
  const r = deuxProfils();
  await ouvrir({ retour: true, reglages: r });
  await touche("r");
  await page.click('[data-section="profils"]');
  await page.click(`[data-cle="modifier-${r.profils[1].id}"]`);
  assert.deepEqual((await calques()).sort(), ["editeur-profil", "reglages"]);
  // Le point le plus à droite du dialogue est aussi celui que la feuille recouvrait.
  await page.waitForTimeout(700);
  const dessus = await page.evaluate(() => {
    const b = document.querySelector("#editeur-profil .dialogue, #editeur-profil > *").getBoundingClientRect();
    return document.elementFromPoint(b.right - 8, b.top + b.height / 2)?.closest(".calque")?.id;
  });
  assert.equal(dessus, "editeur-profil");
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
  assert.deepEqual(donnees.profils.map(p => p.nom), ["Profil 1", "Camille"]);
  await page.click(`[data-cle="profil-${donnees.profils[1].id}"]`);
  assert.match(await page.textContent("#salut"), /Camille$/);
  await page.waitForFunction(id => window.__messages.filter(m => m.type === "reglages").at(-1)?.donnees.profilActif === id, donnees.profils[1].id, { timeout: 3000 });
});

test("photo de profil : choisie dans l'éditeur, affichée partout, liste rafraîchie", async () => {
  const photo = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="red"/></svg>');
  await ouvrir({ retour: true, avatars: [] });
  await touche("p");
  await page.click('[data-action="gerer-profils"]');
  await page.click('[data-cle="profil-profil-1"]');
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
  await page.addInitScript(installerFauxPont, { reglages: deuxProfils() });
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
  await page.click('[data-cle="profil-profil-1"]');
  await page.click('[data-cle="code-definir"]');
  await page.keyboard.type("2580");
  await page.waitForFunction(() => /seconde fois/.test(document.querySelector("#code-detail").textContent));
  await page.keyboard.type("2580");
  await page.waitForFunction(() => !document.querySelector("#code.ouvert"));
  await page.click('[data-cle="reglagesProteges-true"]');
  await page.click('[data-action="enregistrer-profil"]');
  await attendreReglages(d => !!d.profils[0].pin);
  assert.deepEqual((await messages("pin-creer")).map(m => m.code), ["2580"], "haché par hub-menu, pas par la page");
  const profil = (await messages("reglages")).at(-1).donnees.profils[0];
  assert.ok(!JSON.stringify(profil).includes("2580"));
  assert.deepEqual(profil.pin, { algo: "essai", sel: "00", empreinte: createHash("sha256").update("00:2580").digest("hex") });
  assert.equal(profil.reglagesProteges, true);
});

test("code PIN : la page ne s'ouvre que sur la réponse de hub-menu, et garde l'empreinte qu'il a refaite", async () => {
  await ouvrir({ retour: true, reglages: deuxProfils({ reglagesProteges: true }) });
  await page.evaluate(() => { window.__pinSilencieux = true; });
  await touche("r");
  await page.keyboard.type("1234");
  await page.waitForFunction(() => window.__messages.some(m => m.type === "pin-verifier"));
  const [verif] = await messages("pin-verifier");
  assert.deepEqual({ ...verif, demande: undefined }, { type: "pin-verifier", profils: ["samuel"], code: "1234", demande: undefined });
  await page.waitForTimeout(400);
  assert.deepEqual(await calques(), ["code"], "le bon code ne suffit pas sans la réponse");
  await page.keyboard.type("5");
  assert.equal(await page.locator("#code-points .plein").count(), 4, "pas de saisie pendant la vérification");
  const nouveau = { algo: "pbkdf2-sha256", iterations: 600000, sel: "ab".repeat(16), empreinte: "cd".repeat(32) };
  await page.evaluate(([demande, pin]) => window.hub.recevoir({ type: "pin", demande, resultat: "ok", attente: 0, profil: "samuel", pin }), [verif.demande, nouveau]);
  await page.waitForFunction(() => document.querySelector("#reglages.ouvert"));
  await page.evaluate(() => ACTIONS.fermer());
  await touche("t");
  await attendreReglages(d => d.profils[0].pin?.algo === "pbkdf2-sha256");
  assert.deepEqual((await messages("reglages")).at(-1).donnees.profils[0].pin, nouveau);
});

test("code PIN : un refus avec délai de hub-menu bloque la saisie sans rien redemander", async () => {
  await ouvrir({ retour: true, reglages: deuxProfils({ reglagesProteges: true }) });
  await page.evaluate(() => { window.__pinSilencieux = true; });
  await touche("r");
  await page.keyboard.type("0000");
  await page.waitForFunction(() => window.__messages.some(m => m.type === "pin-verifier"));
  const [verif] = await messages("pin-verifier");
  await page.evaluate(demande => window.hub.recevoir({ type: "pin", demande, resultat: "bloque", attente: 120 }), verif.demande);
  await page.waitForFunction(() => /Réessaie dans 120/.test(document.querySelector("#code-detail").textContent));
  await page.keyboard.type("1");
  assert.equal(await page.locator("#code-points .plein").count(), 0);
});

test("code PIN : sans hub-menu (aperçu), un code PBKDF2 écrit par hub-menu s'ouvre aussi", async () => {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.route(/open-meteo\.com/, route => route.abort());
  // Vecteur produit par hub-menu.py : hacher_pin("2468", sel=bytes(range(16))).
  const pin = { algo: "pbkdf2-sha256", iterations: 600000, sel: "000102030405060708090a0b0c0d0e0f", empreinte: "ac310cc8527c6c3a4e20d2a2246ebd77d59766dae1c5fe843d65ecf6a7e20c65" };
  await page.addInitScript(r => localStorage.setItem("hub-reglages", JSON.stringify(r)),
    { profilActif: "a", profils: [{ id: "a", nom: "A", pin, reglagesProteges: true }], systeme: {} });
  await page.goto(PAGE + "?sans-intro");
  await page.waitForFunction(() => document.querySelector("#code.ouvert"));
  await page.keyboard.type("1357");
  await page.waitForFunction(() => /incorrect/.test(document.querySelector("#code-detail").textContent));
  await page.keyboard.type("2468");
  await page.waitForFunction(() => !document.querySelector("#code.ouvert"), null, { timeout: 5000 });
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
  const etat = { url: "http://192.168.1.50:8790/", code: "482913", expire: Date.now() + 240000, telephones: 0, appairageLe: null, appairageOuvert: true };
  await ouvrir({ retour: true, telecommande: etat });
  await page.evaluate(() => window.hub.recevoir({ type: "commande", nom: "reglages" }));
  await page.click('[data-section="telecommande"]');
  await page.waitForFunction(() => document.querySelector(".qr svg"));
  assert.equal(await page.textContent(".code-appairage"), "482 913");
  assert.equal(await page.locator(".empreinte-appairage").count(), 0, "sans certificat prêt, pas de ligne vide");
  await page.evaluate(e => window.hub.recevoir({ type: "telecommande", etat: { ...e, telephones: 1, appairageLe: Date.now() } }), etat);
  assert.match(await page.textContent("#annonce"), /Téléphone relié/);
  assert.match(await page.textContent(".appairage"), /Téléphones reliés : 1/);
  await page.evaluate(() => window.hub.recevoir({ type: "telecommande", etat: null }));
  assert.match(await page.textContent("#contenu-reglages"), /indisponible/);
});

test("télécommande : les téléphones reliés, leur dernier usage, et en retirer un", async () => {
  const jour = 86400000;
  const liste = [
    { id: "2ab063", nom: "Pixel 8", cree: Date.now() - 30 * jour, vu: Date.now() - 3 * jour },
    { id: "9fe410", nom: "iPhone de Camille", cree: Date.now() - 2 * jour, vu: Date.now() },
  ];
  const etat = { url: "http://192.168.1.50:8790/", code: "482913", expire: Date.now() + 240000, telephones: 2, appairageOuvert: true, listeTelephones: liste };
  await ouvrir({ retour: true, telecommande: etat });
  await page.evaluate(() => ACTIONS.reglages("telecommande"));
  await page.waitForFunction(() => document.querySelector(".telephones"));
  const lignes = await page.locator(".telephones li").allInnerTexts();
  assert.equal(lignes.length, 2, "un téléphone, une ligne — jamais deux fois le même");
  assert.match(lignes[0], /Pixel 8/);
  assert.match(lignes[0], /il y a 3 jours/);
  assert.match(lignes[1], /aujourd'hui/);

  // Retirer demande deux appuis : le premier arme, le second envoie.
  await page.click('[data-cle="retirer-2ab063"]');
  assert.deepEqual(await messages("telecommande-retirer"), []);
  assert.equal(await page.textContent('[data-cle="retirer-2ab063"]'), "Confirmer");
  await page.click('[data-cle="retirer-2ab063"]');
  assert.deepEqual(await messages("telecommande-retirer"), [{ type: "telecommande-retirer", id: "2ab063" }]);

  // hub-menu republie l'état sans lui : la ligne disparaît.
  await page.evaluate(e => window.hub.recevoir({ type: "telecommande", etat: { ...e, telephones: 1, listeTelephones: e.listeTelephones.slice(1) } }), etat);
  assert.equal(await page.locator(".telephones li").count(), 1);
  assert.deepEqual(page.erreurs, []);
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
  assert.equal(await focus(), "maj-auto-true", "le réglage automatique, entre Rechercher et Fermer");
  await touche("ArrowUp");
  assert.equal(await focus(), "maj-verifier");
  assert.equal((await messages("maj-etat")).length >= 1, true, "l'état d'une mise à jour en cours est demandé à l'ouverture");
});

// Audit du 17/09/2026 : un focus sorti du contenu changeait la section affichée (Haut depuis
// « Sombre » ouvrait Arrière-plan ; Gauche depuis GeForce NOW, Enceinte réseau).
test("réglages : sortir du contenu ne change jamais de section", async () => {
  await ouvrir({ retour: true });
  await touche("r");
  assert.equal(await focus(), "section-apparence");
  await touche("ArrowRight");
  assert.equal(await focus(), "theme-sombre");
  await touche("ArrowUp");
  assert.equal(await focus(), "theme-sombre", "Haut s'arrête au bord du contenu");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Apparence");
  await touche("ArrowLeft");
  assert.equal(await focus(), "section-apparence", "Gauche revient sur la section affichée");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Apparence");

  await page.evaluate(() => { fermerTout(); ACTIONS.reglages("services"); });
  await page.evaluate(() => definirFocus(document.querySelector('[data-cle="service-geforcenow-true"]'), true));
  await touche("ArrowLeft");
  assert.equal(await focus(), "section-services");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Streaming et jeux");

  const derniere = await page.evaluate(() => { const l = [...document.querySelectorAll("#contenu-reglages [data-nav]")].at(-1); definirFocus(l, true); return l.dataset.cle; });
  await touche("ArrowDown");
  assert.equal(await focus(), derniere, "Bas s'arrête au bord du contenu");
  assert.equal(await page.textContent("#contenu-reglages h3"), "Streaming et jeux");
});

// Audit du 17/09/2026 : en taille XL, les dernières entrées du sommaire étaient rognées par
// la feuille, et leur focus invisible.
test("réglages : en taille XL, le sommaire défile jusqu'à la dernière entrée", async () => {
  await ouvrir({ retour: true, reglages: { profils: [{ id: "p", nom: "Samuel", animations: "reduites" }], profilActif: "p", systeme: { echelle: 1.2 } } });
  await page.setViewportSize({ width: 1280, height: 720 });
  // Sans la police Ubuntu Sans de la TV, les lignes sont plus basses : on garantit que le
  // sommaire déborde, c'est son défilement qu'on éprouve.
  await page.addStyleTag({ content: "#sommaire .entree { padding-block: .6rem; }" });
  await touche("r");
  assert.ok(await page.evaluate(() => { const s = document.querySelector("#sommaire"); return s.scrollHeight > s.clientHeight + 20; }), "le sommaire déborde");
  const entrees = await page.evaluate(() => [...document.querySelectorAll("#sommaire .entree")].map(e => e.dataset.cle));
  for (let i = 1; i < entrees.length; i++) await touche("ArrowDown");
  assert.equal(await focus(), entrees.at(-1));
  await page.waitForTimeout(100);
  const vue = await page.evaluate(() => {
    const e = document.querySelector("#sommaire .entree.focus").getBoundingClientRect();
    const s = document.querySelector("#sommaire").getBoundingClientRect();
    const f = document.querySelector("#reglages .feuille-corps").getBoundingClientRect();
    return e.top >= Math.max(s.top, f.top) - 1 && e.bottom <= Math.min(s.bottom, f.bottom, innerHeight) + 1;
  });
  assert.ok(vue, "la dernière entrée sélectionnée est entièrement visible");
  await touche("ArrowUp", "ArrowUp");
  for (let i = 2; i < entrees.length; i++) await touche("ArrowUp");
  assert.equal(await focus(), entrees[0]);
  assert.ok(await page.evaluate(() => document.querySelector("#sommaire").scrollTop === 0), "retour en haut du sommaire");
});

test("mise à jour : un état « terminee » ancien ne relance pas le menu", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "terminee", version: "abc" } }));
  await page.waitForTimeout(4600);
  assert.deepEqual(await messages("relancer"), []);
});

test("mise à jour : une version plus récente rend le bouton Installer malgré un « terminee » ancien", async () => {
  await ouvrir({ retour: true });
  // L'état d'une installation réussie reste dans /run jusqu'au redémarrage du HUB.
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "terminee", version: "2c75d626e96d" } }));
  await touche("r");
  await page.click('[data-section="apropos"]');
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: true, distant: "7e3a551abcde", installee: "2c75d62", verifiable: true } }));
  await page.waitForTimeout(150);
  assert.equal(await page.locator('[data-cle="maj-appliquer"]').count(), 1, "bouton Installer affiché");
  assert.ok(!(await page.isHidden("#pastille-maj-apropos")), "pastille affichée");
  // Le même état, mais pour la version que la source propose : rien à installer.
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: true, distant: "2c75d626e96d", installee: "2c75d62", verifiable: true } }));
  await page.waitForTimeout(150);
  assert.equal(await page.locator('[data-cle="maj-appliquer"]').count(), 0, "rien de plus récent : pas de bouton");
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

test("télécommande : le code n'est montré qu'appairage ouvert, avec le début de l'empreinte du certificat", async () => {
  const octets = Array.from({ length: 32 }, (_, i) => i.toString(16).toUpperCase().padStart(2, "0"));
  const etat = { url: "http://192.168.1.50:8790/", code: "482913", expire: Date.now() + 240000, telephones: 0, appairageLe: null,
    appairageOuvert: false, appairageJusque: null, empreinteRacineCourte: "0001 0203 0405 0607", empreinteRacine: octets.join(":") };
  await ouvrir({ retour: true, telecommande: etat });
  await page.evaluate(() => ACTIONS.reglages("telecommande"));
  await page.waitForSelector(".empreinte-courte");
  assert.match(await page.textContent(".code-appairage"), /Ouverture de l'appairage/);
  assert.ok(!(await page.textContent(".appairage")).includes("482"), "pas de code tant que la fenêtre est fermée");
  assert.equal(await page.textContent(".empreinte-courte"), "0001 0203 0405 0607");
  assert.match(await page.textContent(".empreinte-appairage"), /Empreinte du certificat \(début\)/);
  const lignes = await page.$$eval(".empreinte-paires > div", d => d.map(e => e.textContent));
  assert.deepEqual(lignes, [
    "00 01 02 03   04 05 06 07", "08 09 0A 0B   0C 0D 0E 0F",
    "10 11 12 13   14 15 16 17", "18 19 1A 1B   1C 1D 1E 1F",
  ]);
  await page.evaluate(e => window.hub.recevoir({ type: "telecommande", etat: { ...e, appairageOuvert: true } }), etat);
  assert.equal(await page.textContent(".code-appairage"), "482 913");
  await page.evaluate(e => window.hub.recevoir({ type: "telecommande", etat: { ...e, appairageOuvert: true, empreinteRacineCourte: null, empreinteRacine: null } }), etat);
  assert.equal(await page.locator(".empreinte-appairage, .empreinte-paires").count(), 0);
  assert.deepEqual(page.erreurs, []);
});

test("télécommande : hub-menu est prévenu quand l'écran d'appairage apparaît et disparaît", async () => {
  await ouvrir({ retour: true, telecommande: { url: "http://192.168.1.50:8790/", code: "482913", appairageOuvert: false } });
  const affichages = async () => (await messages("appairage")).map(m => m.affiche);
  await page.evaluate(() => ACTIONS.reglages("apropos"));
  assert.deepEqual(await affichages(), [], "les autres sections n'ouvrent rien");
  await page.click('[data-section="telecommande"]');
  assert.deepEqual(await affichages(), [true]);
  await page.click('[data-section="enceinte"]');
  assert.deepEqual(await affichages(), [true, false]);
  await page.click('[data-section="telecommande"]');
  await touche("Escape");
  assert.deepEqual(await affichages(), [true, false, true, false], "fermer les réglages ferme la fenêtre");
  await page.evaluate(() => ACTIONS.reglages("telecommande"));
  await touche("a");
  assert.deepEqual((await affichages()).at(-1), false, "le mode ambiant cache l'écran d'appairage");
});

test("mise à jour signée : sans signataire autorisé, pas de bouton Installer, et les refus sont expliqués", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => ACTIONS.reglages("apropos"));
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: true, verifiable: false, raison: "signataires", distant: "abc1234" }, etat: null }));
  assert.match(await page.textContent("#contenu-reglages"), /aucun signataire autorisé : elle ne peut pas être installée/);
  assert.equal(await page.locator('[data-cle="maj-appliquer"]').count(), 0);
  for (const [raison, attendu] of [["signataires", /Aucun signataire autorisé sur ce HUB/], ["signature", /pas signée par une clé autorisée/], ["inconnue-demain", /L'installation a échoué\./]]) {
    await page.evaluate(r => window.hub.recevoir({ type: "maj", etat: { etape: "echec", raison: r } }), raison);
    assert.match(await page.textContent("#contenu-reglages"), attendu, raison);
  }
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: true, distant: "abc1234" }, etat: null }));
  assert.equal(await page.locator('[data-cle="maj-appliquer"]').count(), 1, "un ancien hub-mise-a-jour sans « verifiable » reste installable");
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "installation", version: "abc1234", signataire: "Parent <parent@example.org>" } }));
  assert.match(await page.textContent("#contenu-reglages"), /signée par Parent <parent@example\.org>/);
  assert.deepEqual(page.erreurs, []);
});

test("enceinte : code de recopie affiché, changé seulement après confirmation", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => ACTIONS.reglages("enceinte"));
  await page.waitForFunction(() => window.__messages.some(m => m.type === "recopie-code"));
  assert.deepEqual(await messages("recopie-code"), [{ type: "recopie-code", nouveau: false }]);
  assert.match(await page.textContent("#contenu-reglages"), /Code de recopie : …/);
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-code", code: "4821", permise: true, nouveau: false }));
  assert.match(await page.textContent("#contenu-reglages"), /Code de recopie : 4821/);
  assert.doesNotMatch(await page.textContent("#contenu-reglages"), /désactivée pour ce profil/);
  await page.click('[data-cle="recopie-code-changer"]');
  assert.match(await page.textContent("#contenu-reglages"), /devront saisir le nouveau code/);
  assert.equal((await messages("recopie-code")).length, 1, "rien n'est changé avant la confirmation");
  await page.click('[data-cle="recopie-code-annuler"]');
  await page.click('[data-cle="recopie-code-changer"]');
  await page.click('[data-cle="recopie-code-oui"]');
  assert.deepEqual((await messages("recopie-code")).at(-1), { type: "recopie-code", nouveau: true });
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-code", code: "0937", permise: false, nouveau: true }));
  assert.match(await page.textContent("#annonce"), /Nouveau code de recopie : 0937/);
  assert.match(await page.textContent("#contenu-reglages"), /Recopie désactivée pour ce profil \(temps d'écran\)/);
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-code", code: "<b>1</b>", permise: true }));
  assert.match(await page.textContent("#contenu-reglages"), /Code de recopie : indisponible/);
  assert.deepEqual(page.erreurs, []);
});

test("recopie d'écran : pendant l'appairage, le code s'affiche en grand, puis disparaît à l'échéance", async () => {
  await ouvrir({ retour: true, recopieCode: { code: "4821", jusqua: Date.now() / 1000 + 60 } });
  assert.ok(await page.isVisible("#recopie-appairage"));
  assert.equal(await page.textContent("#recopie-appairage-code"), "4821");
  assert.match(await page.textContent("#recopie-appairage"), /Recopie d'écran.*Code à saisir sur l'appareil/);
  await touche("a");
  assert.ok(await page.isVisible("#recopie-appairage"), "visible aussi en mode ambiant");
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-appairage", etat: { code: "<img src=x onerror=1>", jusqua: Date.now() / 1000 + 60 } }));
  assert.ok(!(await page.isVisible("#recopie-appairage")), "un code mal formé n'est pas affiché");
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-appairage", etat: { code: "1234", jusqua: Date.now() / 1000 + 1 } }));
  assert.ok(await page.isVisible("#recopie-appairage"));
  await page.waitForFunction(() => document.getElementById("recopie-appairage").hidden, null, { timeout: 4000 });
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-appairage", etat: { code: "5555", jusqua: Date.now() / 1000 + 60 } }));
  await page.evaluate(() => window.hub.recevoir({ type: "recopie-appairage", etat: null }));
  assert.ok(!(await page.isVisible("#recopie-appairage")), "fichier disparu : la recopie a commencé");
  assert.deepEqual(page.erreurs, []);
});

test("profil par défaut neutre ; des réglages existants gardent leurs profils et le profil actif", async () => {
  await ouvrir();
  assert.equal(await page.textContent("#nom-profil"), "Profil 1");
  assert.match(await page.textContent("#salut"), /Profil 1$/);
  await page.close();
  await ouvrir({ reglages: { profilActif: "ancien", profils: [{ id: "autre", nom: "Alix" }, { id: "ancien", nom: "Dominique" }], systeme: { meteo: { active: false } } } });
  assert.equal(await page.textContent("#nom-profil"), "Dominique");
  await page.evaluate(() => { window.hub.recevoir({ type: "commande", nom: "reglages" }); });
  await page.click('[data-section="apparence"]');
  await page.click('[data-cle="theme-clair"]');
  await page.waitForFunction(() => window.__messages.some(m => m.type === "reglages"), null, { timeout: 5000 });
  const donnees = (await messages("reglages")).at(-1).donnees;
  assert.equal(donnees.profilActif, "ancien");
  assert.deepEqual(donnees.profils.map(p => [p.id, p.nom]), [["autre", "Alix"], ["ancien", "Dominique"]]);
});

// Audit du 17/09/2026 : sur l'accueil, Gauche depuis TV menait à YouTube puis au profil, Haut
// depuis Jeux à la météo, Bas depuis Netflix au bouton Raccourcis, et 19 paires de
// déplacements ne revenaient pas au point de départ.
test("accueil : rangées qui s'arrêtent au bout, et chaque déplacement se défait par la flèche opposée", async () => {
  await ouvrir({ retour: true, reprises: [{ titre: "Dune", fichier: "/d.mkv", position: 60, duree: 600 }], reglages: { profils: [{ id: "p", nom: "Samuel", meteo: { active: true, ville: "Lyon", lat: 45.7, lon: 4.8 } }], profilActif: "p" } });
  await page.evaluate(() => { window.hub.recevoir({ type: "meteo", donnees: { current: { temperature_2m: 17, weather_code: 3, is_day: 1 } }, releveLe: new Date().toISOString() }); window.hub.recevoir({ type: "internet", etat: "local" }); recevoirMinuteur(Date.now() + 600000); });
  const aller = async (depart, ...touches) => { await page.evaluate(s => definirFocus(document.querySelector(s), true), depart); await touche(...touches); return focus(); };
  assert.equal(await aller('[data-mode="tv"]', "ArrowLeft"), "tv", "Gauche s'arrête au bout de la rangée des cartes");
  assert.equal(await aller('[data-mode="bureau"]', "ArrowRight"), "bureau");
  assert.equal(await aller('[data-mode="gaming"]', "ArrowUp"), "profils", "Haut depuis les cartes : le profil");
  assert.equal(await aller('[data-cle="service-youtube"]', "ArrowLeft"), "service-youtube");

  const oppose = { ArrowUp: "ArrowDown", ArrowDown: "ArrowUp", ArrowLeft: "ArrowRight", ArrowRight: "ArrowLeft" };
  const cibles = await page.evaluate(() => candidats().map(e => e.dataset.mode || e.dataset.cle || e.dataset.action));
  const irreversibles = [];
  for (const depart of cibles) for (const k of Object.keys(oppose)) {
    const sel = `[data-mode="${depart}"], [data-cle="${depart}"], #accueil [data-action="${depart}"]`;
    await page.evaluate(s => definirFocus(document.querySelector(s), true), sel);
    await page.keyboard.press(k);
    const arrivee = await focus();
    if (arrivee === depart) continue;
    await page.keyboard.press(oppose[k]);
    const retour = await focus();
    if (retour !== depart) irreversibles.push(`${depart} ${k} → ${arrivee} → ${retour}`);
  }
  assert.deepEqual(irreversibles, []);
});

test("réglages : Droite depuis le sommaire va au premier réglage ; Rechercher et Fermer se rejoignent sans détour", async () => {
  await ouvrir({ retour: true });
  await touche("r");
  await page.evaluate(() => definirFocus(document.querySelector('[data-section="apropos"]')));
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: false }, etat: null }));
  await touche("ArrowRight");
  assert.equal(await focus(), "maj-verifier");
  await touche("ArrowDown");
  assert.match(await focus(), /^maj-auto-(true|false)$/, "le réglage automatique, sous Rechercher");
  await touche("ArrowDown");
  assert.equal(await focus(), "fermer-reglages");
  await touche("ArrowUp", "ArrowUp");
  assert.equal(await focus(), "maj-verifier");
  await touche("ArrowDown", "ArrowDown", "ArrowLeft");
  assert.equal(await focus(), "section-apropos", "Gauche depuis Fermer revient à la section, sans en ouvrir une autre");
  assert.equal(await page.evaluate(() => sectionCourante), "apropos");
  await page.evaluate(() => definirFocus(document.querySelector('[data-section="services"]')));
  await touche("ArrowRight");
  assert.equal(await focus(), await page.evaluate(() => document.querySelector("#contenu-reglages [data-nav]").dataset.cle));
});

test("éditeur de profil : la flèche opposée ramène toujours d'où l'on vient", async () => {
  await ouvrir({ retour: true, reglages: { profils: [{ id: "p", nom: "Samuel" }], profilActif: "p" } });
  await page.evaluate(() => ouvrirEditeur(reglages.profils[0]));
  await page.waitForTimeout(200);
  const oppose = { ArrowUp: "ArrowDown", ArrowDown: "ArrowUp", ArrowLeft: "ArrowRight", ArrowRight: "ArrowLeft" };
  const n = await page.evaluate(() => candidats().length);
  const irreversibles = [];
  for (let i = 0; i < n; i++) for (const k of Object.keys(oppose)) {
    const depart = await page.evaluate(i => { const e = candidats()[i]; definirFocus(e, true); return e.dataset.cle || e.dataset.action; }, i);
    await page.keyboard.press(k);
    const arrivee = await focus();
    if (arrivee === depart) continue;
    await page.keyboard.press(oppose[k]);
    if (await focus() !== depart) irreversibles.push(`${depart} ${k} → ${arrivee} → ${await focus()}`);
  }
  assert.deepEqual(irreversibles, []);
});

// ── Internet et mises à jour automatiques ─────────────────────────────────
test("internet : trois états, pictogramme distinct et libellé à la sélection ; OK ouvre À propos", async () => {
  await ouvrir({ retour: true });
  assert.ok(await page.isHidden("#puce-internet"), "rien d'affiché tant que hub-menu n'a rien relevé");
  assert.equal((await messages("internet")).length, 1, "l'état est redemandé à l'ouverture");
  const formes = {};
  for (const [etat, libelle] of [["internet", "Internet"], ["local", "Réseau local, sans Internet"], ["aucun", "Pas de réseau"]]) {
    await page.evaluate(e => { definirFocus(document.querySelector('[data-mode="tv"]'), true); window.hub.recevoir({ type: "internet", etat: e }); }, etat);
    assert.ok(await page.isVisible("#puce-internet"), etat);
    assert.ok(await page.isHidden("#internet-libelle"), `${etat} : libellé caché hors sélection`);
    assert.equal(await page.getAttribute("#puce-internet", "aria-label"), libelle);
    formes[etat] = await page.evaluate(() => [...document.querySelectorAll("#internet-picto svg > *")].map(x => x.getAttribute("class") || x.tagName).join(","));
    await page.evaluate(() => definirFocus(document.querySelector("#puce-internet"), true));
    assert.equal(await page.textContent("#internet-libelle"), libelle);
    assert.ok(await page.isVisible("#internet-libelle"));
  }
  assert.equal(new Set(Object.values(formes)).size, 3, `trois formes : ${JSON.stringify(formes)}`);
  await page.evaluate(() => window.hub.recevoir({ type: "internet", etat: "local", nuance: "portail" }));
  assert.equal(await page.textContent("#internet-libelle"), "Connexion à valider (portail)");
  await touche("Enter");
  await page.waitForFunction(() => sectionCourante === "apropos" && pile.at(-1) === "reglages");
  assert.match(await page.textContent(".reseau-info"), /Connexion à valider/);
  await page.evaluate(() => window.hub.recevoir({ type: "internet", etat: "bizarre" }));
  assert.doesNotMatch(await page.textContent("#contenu-reglages"), /internet\./, "jamais de clé brute");
  assert.deepEqual(page.erreurs, []);
});

test("internet : traduit en anglais, et légende dans l'aide", async () => {
  await ouvrir({ retour: true, reglages: { profils: [{ id: "p", nom: "Sam", langue: "en" }], profilActif: "p" } });
  await page.evaluate(() => window.hub.recevoir({ type: "internet", etat: "aucun" }));
  assert.equal(await page.getAttribute("#puce-internet", "aria-label"), "No network");
  await page.evaluate(() => ACTIONS.aide());
  assert.match(await page.textContent("#contenu-aide"), /Local network, no Internet/);
  assert.equal(await page.locator("#contenu-aide .legende-internet svg").count(), 3);
});

test("mise à jour automatique : pastille sur l'engrenage et À propos, annonce une seule fois par version", async () => {
  await ouvrir({ retour: true });
  assert.ok(await page.isHidden("#pastille-maj-pied"));
  const dispo = v => ({ type: "maj", verification: { disponible: true, verifiable: true, distant: v, installee: "000000" }, auto: true, annoncer: true });
  await page.evaluate(m => window.hub.recevoir(m), dispo("abc123"));
  assert.ok(await page.isVisible("#pastille-maj-pied"));
  assert.equal(await page.textContent("#annonce"), "Nouvelle version du HUB (abc123) : Réglages → À propos.");
  await page.evaluate(() => { document.querySelector("#annonce").textContent = ""; });
  // hub-menu ne redemande pas l'annonce ; et même s'il le faisait, la page ne la répète pas.
  await page.evaluate(m => window.hub.recevoir({ ...m, annoncer: false }), dispo("abc123"));
  await page.evaluate(m => window.hub.recevoir(m), dispo("abc123"));
  assert.equal(await page.textContent("#annonce"), "");
  await page.evaluate(m => window.hub.recevoir(m), dispo("def456"));
  assert.match(await page.textContent("#annonce"), /def456/);
  await touche("r");
  assert.ok(await page.isVisible("#pastille-maj-apropos"));
  // Une version non vérifiable n'a pas de pastille : elle ne pourrait pas s'installer.
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: true, verifiable: false, distant: "fff" }, auto: true, annoncer: false }));
  assert.ok(await page.isHidden("#pastille-maj-apropos"));
});

test("mise à jour automatique : la version trouvée avant un mode garde sa pastille au retour", async () => {
  await ouvrir({ retour: true, majAuto: { disponible: true, distant: "abc123", installee: "000000" } });
  assert.ok(await page.isVisible("#pastille-maj-pied"));
  assert.equal(await page.textContent("#annonce"), "", "pas d'annonce au retour");
  await page.evaluate(() => ACTIONS.reglages("apropos"));
  assert.match(await page.textContent("#contenu-reglages"), /Nouvelle version disponible \(abc123\)/);
  assert.equal(await page.locator('[data-cle="maj-appliquer"]').count(), 1);
});

test("mise à jour automatique : réglage dans À propos, activé par défaut, enregistré dans systeme", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => ACTIONS.reglages("apropos"));
  assert.match(await page.textContent("#contenu-reglages"), /Rechercher automatiquement les mises à jour/);
  assert.equal(await page.getAttribute('[data-cle="maj-auto-true"]', "class"), "option choisie");
  await page.click('[data-cle="maj-auto-false"]');
  await attendreReglages(d => d.systeme.miseAJourAuto === false);
  await page.click('[data-cle="maj-auto-true"]');
  await attendreReglages(d => d.systeme.miseAJourAuto === true);
  // La page ne vérifie jamais d'elle-même : c'est hub-menu qui planifie (Internet, modes, installation).
  assert.deepEqual(await messages("maj-verifier"), []);
});

test("mise à jour : l'échec suivi s'annonce avec son détail, lisible dans la carte", async () => {
  await ouvrir({ retour: true });
  await page.evaluate(() => ACTIONS.reglages("apropos"));
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { disponible: true, distant: "abc1234" }, etat: null }));
  await page.click('[data-cle="maj-appliquer"]');
  const detail = "fatal: unable to access 'https://github.com/x/hub.git/': Could not resolve host: github.com";
  await page.evaluate(d => window.hub.recevoir({ type: "maj", etat: { etape: "echec", raison: "reseau", detail: d, version: "abc1234" } }), detail);
  assert.match(await page.textContent("#annonce"), /Réseau injoignable \(Internet ou DNS\)/);
  assert.match(await page.textContent("#annonce .annonce-detail"), /Could not resolve host: github\.com/);
  assert.match(await page.textContent("#contenu-reglages .detail-maj"), /Could not resolve host: github\.com/);
  const style = await page.evaluate(() => { const c = getComputedStyle(document.querySelector(".detail-maj")); return { selection: c.userSelect || c.webkitUserSelect, taille: parseFloat(c.fontSize) / parseFloat(getComputedStyle(document.documentElement).fontSize) }; });
  assert.equal(style.selection, "text");
  assert.ok(style.taille >= .899, `détail à ${style.taille} rem`);
  // Long : tronqué par le début, la fin du message reste.
  await page.evaluate(() => window.hub.recevoir({ type: "maj", etat: { etape: "echec", raison: "disque", detail: "x".repeat(900) + " No space left on device" } }));
  const texte = await page.textContent("#contenu-reglages .detail-maj");
  assert.ok(texte.length <= 300 && texte.startsWith("…") && texte.endsWith("No space left on device"), texte);
  assert.match(await page.textContent("#contenu-reglages"), /Écriture impossible sur le disque/);
  // Une recherche en erreur dit pourquoi, détail compris.
  await page.evaluate(() => window.hub.recevoir({ type: "maj", verification: { erreur: "reseau", detail: "Could not resolve host: github.com" }, etat: null }));
  assert.match(await page.textContent("#contenu-reglages"), /Réseau injoignable \(Internet ou DNS\)\./);
  assert.match(await page.textContent("#contenu-reglages .detail-maj"), /Could not resolve host/);
});
