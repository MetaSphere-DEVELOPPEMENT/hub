// Temps d'écran, allumage programmé, cadre photo : ce que la page affiche et ce qu'elle
// envoie à hub-menu. Le pont WebKit est un faux qui note chaque message.
//
//   cd tests/menu && npm test

import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { chromium, webkit } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import { createHash } from "node:crypto";

// Le moteur : « chrome » par défaut, « chromium » celui de Playwright, « webkit » celui de
// la famille de la TV. Un rendu peut n'exister que dans l'un d'eux — la WebKitGTK du HUB
// ignorait les `mask-image` en dégradé que Chromium applique, et ça ne s'est vu que sur une
// photo du salon (18/09/2026). HUB_NAVIGATEUR=webkit rejoue toute la suite dans WebKit.
const lancerNavigateur = () => process.env.HUB_NAVIGATEUR === "webkit" ? webkit.launch()
  : chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;
const PIN_1234 = { sel: "abc", empreinte: createHash("sha256").update("abc:1234").digest("hex") };
const PHOTO = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

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
before(async () => {
  navigateur = await lancerNavigateur();
});
after(async () => { await navigateur?.close(); });
beforeEach(async () => { await page?.close(); });

function aujourdhui() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function ouvrir(initial = {}, requete = "?sans-intro") {
  page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  const erreurs = [];
  page.on("pageerror", e => erreurs.push(e.message));
  page.erreurs = erreurs;
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(installerFauxPont, initial);
  await page.goto(PAGE + requete);
  await page.waitForTimeout(250);
}

const messages = type => page.evaluate(t => window.__messages.filter(m => m.type === t), type);
const attendreMessage = (type, verifie = "() => true") => page.waitForFunction(([type, v]) =>
  window.__messages.some(m => m.type === type && new Function("m", `return (${v})(m)`)(m)), [type, verifie.toString()], { timeout: 5000 });
const focus = () => page.evaluate(() => document.querySelector(".focus")?.dataset.cle || document.querySelector(".focus")?.dataset.mode);
const touche = async (...touches) => { for (const k of touches) { await page.keyboard.press(k); await page.waitForTimeout(60); } };
const calques = () => page.evaluate(() => [...document.querySelectorAll(".calque.ouvert")].map(c => c.id));

// Deux profils : Samuel, parent protégé par 1234 ; Camille, deux heures par jour.
function famille({ utiliseCamille = 3600, actif = "camille", camilleExtra = {} } = {}) {
  return {
    retour: true,
    reglages: {
      profilActif: actif,
      profils: [
        { id: "sam", nom: "Samuel", pin: PIN_1234 },
        { id: "camille", nom: "Camille", couleur: "rose", tempsEcran: { limites: [120, 120, 120, 120, 120, 120, 120], debut: null, fin: null }, ...camilleExtra },
      ],
      systeme: { meteo: { active: false } },
    },
    tempsEcran: { aujourdhui: aujourdhui(), profils: { camille: { [aujourdhui()]: { secondes: utiliseCamille, modes: { tv: utiliseCamille } } } } },
  };
}

test("jauge : le temps restant du profil s'affiche sur sa puce", async () => {
  await ouvrir(famille({ utiliseCamille: 3600 }));
  assert.ok(await page.isVisible("#jauge-temps"));
  assert.equal(await page.textContent("#jauge-temps-texte"), "1 h");
  const largeur = await page.evaluate(() => $("jauge-temps").querySelector("i").style.width);
  assert.equal(largeur, "50%");
  assert.deepEqual(page.erreurs, []);
});

test("jauge : absente pour un profil sans limite", async () => {
  await ouvrir(famille({ actif: "sam" }));
  assert.equal(await page.isVisible("#jauge-temps"), false);
});

test("temps écoulé : le mode ne se lance pas, un parent accorde 15 min avec son code", async () => {
  await ouvrir(famille({ utiliseCamille: 7200 }));
  assert.match(await page.getAttribute("#jauge-temps", "class"), /epuise/);
  await touche("1");
  await page.waitForTimeout(800);
  assert.deepEqual(await messages("choix"), [], "hub-temps-ecran refuserait aussi, mais le menu ne doit pas partir");
  assert.deepEqual(await calques(), ["temps-plus"]);
  assert.equal(await focus(), "temps-plus-15");
  await touche("ArrowRight");
  assert.equal(await focus(), "temps-plus-30", "navigation spatiale dans le dialogue");
  await touche("Enter");
  assert.deepEqual(await calques(), ["code"]);
  await page.keyboard.type("9999");
  await page.waitForTimeout(400);
  assert.deepEqual(await messages("temps-prolonger"), [], "un mauvais code n'accorde rien");
  await page.keyboard.type("1234");
  await attendreMessage("temps-prolonger");
  assert.deepEqual(await messages("temps-prolonger"), [{ type: "temps-prolonger", profil: "camille", minutes: 30 }]);
  assert.deepEqual(await calques(), []);
  // hub-menu répond avec l'état écrit : la jauge repart.
  await page.evaluate(j => window.hub.recevoir({ type: "temps-ecran", etat: { profils: { camille: { [j]: { secondes: 7200, bonus: 1800 } } } } }), aujourdhui());
  assert.equal(await page.textContent("#jauge-temps-texte"), "30 min");
  await touche("1");
  await attendreMessage("choix");
});

test("sans parent protégé par un code, on ne peut pas accorder de temps", async () => {
  const initial = famille({ utiliseCamille: 7200 });
  initial.reglages.profils[0].pin = null;
  await ouvrir(initial);
  await touche("1");
  await touche("Enter");
  assert.match(await page.textContent("#annonce"), /Aucun profil parent/);
  assert.deepEqual(await calques(), ["temps-plus"]);
});

test("écran Temps d'écran : historique de 7 jours, limites réglables par le parent déverrouillé seulement", async () => {
  // Le parent, sans « retour » : son code est demandé au démarrage.
  const initial = { ...famille({ actif: "sam" }), retour: false };
  await ouvrir(initial);
  assert.deepEqual(await calques(), ["code"]);
  await page.keyboard.type("1234");
  await page.waitForTimeout(400);
  await page.evaluate(() => ACTIONS.reglages("temps"));
  await page.waitForTimeout(200);
  assert.equal(await page.textContent("#contenu-reglages h3"), "Temps d'écran");
  assert.equal(await page.locator(".histo-temps").count(), 2, "un historique par profil");
  assert.equal(await page.locator(".histo-temps").first().locator(".jour-temps").count(), 7);
  assert.equal(await page.locator('[data-cle="temps-regler-sam"]').count(), 0, "on ne se limite pas soi-même");
  await page.click('[data-cle="temps-regler-camille"]');
  await page.click('[data-cle="temps-semaine-180"]');
  await page.click('[data-cle="temps-fin-21:00"]');
  await page.waitForFunction(() => {
    const m = window.__messages.filter(x => x.type === "reglages").at(-1);
    const r = m?.donnees.profils.find(p => p.id === "camille").tempsEcran;
    return r && r.limites.join() === "180,180,180,180,180,120,120" && r.fin === "21:00";
  }, null, { timeout: 5000 });
  // Au clavier, depuis le sommaire, la section est atteignable.
  await page.evaluate(() => definirFocus(document.querySelector('[data-section="profils"]')));
  await touche("ArrowDown");
  assert.equal(await focus(), "section-temps");
  assert.deepEqual(page.erreurs, []);
});

test("écran Temps d'écran : un profil limité ne règle rien, il voit seulement", async () => {
  await ouvrir(famille());
  await page.evaluate(() => ACTIONS.reglages("temps"));
  await page.waitForTimeout(200);
  assert.equal(await page.locator('[data-cle^="temps-regler-"]').count(), 0);
  assert.match(await page.textContent("#contenu-reglages"), /se règlent depuis un profil sans restriction/);
  assert.ok(await page.locator('[data-cle="temps-plus-camille"]').count());
});

test("réglages Allumage : jours et heure du réveil, service réarmé, adresse MAC affichée", async () => {
  await ouvrir({ ...famille({ actif: "sam" }), allumage: { reveil: null, extinction: null, ethernet: [{ interface: "enp0s31f6", adresse: "8c:16:45:aa:bb:cc" }] } });
  await page.evaluate(() => ACTIONS.reglages("allumage"));
  await page.waitForTimeout(200);
  assert.equal(await page.textContent("#contenu-reglages h3"), "Allumage");
  assert.match(await page.textContent("#contenu-reglages"), /8c:16:45:aa:bb:cc/);
  assert.match(await page.textContent("#contenu-reglages"), /ne peut pas allumer le HUB/);
  await page.click('[data-cle="reveil-jour-0"]');
  await page.click('[data-cle="reveil-jour-6"]');
  await page.click('[data-cle="reveil-heure-06:30"]');
  await page.waitForFunction(() => {
    const m = window.__messages.filter(x => x.type === "reglages").at(-1);
    return m?.donnees.systeme.allumage.reveils.join() === "06:30,,,,,,06:30";
  }, null, { timeout: 5000 });
  await attendreMessage("allumage-appliquer");
  const reveil = Math.floor(new Date(2026, 8, 21, 6, 30).getTime() / 1000);
  await page.evaluate(r => window.hub.recevoir({ type: "allumage", lance: true, reveil: r, extinction: null, ethernet: [] }), reveil);
  assert.match(await page.textContent("#etat-allumage"), /Prochain allumage : lundi 06:30/);
});

test("allumage : un profil restreint ne voit pas le programme", async () => {
  await ouvrir(famille());
  await page.evaluate(() => ACTIONS.reglages("allumage"));
  await page.waitForTimeout(200);
  assert.equal(await page.locator('[data-cle^="reveil-jour-"]').count(), 0);
});

test("allumé par le réveil programmé : le menu s'ouvre en mode ambiant", async () => {
  await ouvrir({ ...famille({ actif: "sam" }), retour: false, reglages: { profils: [{ id: "sam", nom: "Samuel" }] }, reveilProgramme: true });
  await page.waitForFunction(() => document.body.classList.contains("ambiant"), null, { timeout: 5000 });
});

test("cadre photo : diaporama en mode ambiant, souvenirs d'abord, horloge en surimpression", async () => {
  await ouvrir({ ...famille({ actif: "sam" }), reglages: { profils: [{ id: "sam", nom: "Samuel", cadre: { actif: true, souvenirs: true, duree: 10 } }], systeme: { meteo: { active: false } } } });
  await touche("a");
  await attendreMessage("cadre");
  assert.deepEqual(await messages("cadre"), [{ type: "cadre", album: null, souvenirs: true }]);
  const souvenir = PHOTO + "#souvenir";
  await page.evaluate(([photo, souvenir]) => window.hub.recevoir({
    type: "cadre", albums: ["Vacances"], photos: [photo + "#1", photo + "#2", souvenir], souvenirs: [{ uri: souvenir, annee: new Date().getFullYear() - 7 }],
  }), [PHOTO, souvenir]);
  await page.waitForSelector("#cadre .cadre-photo.visible", { timeout: 5000 });
  assert.ok(await page.evaluate(() => document.body.classList.contains("cadre-actif")));
  assert.match(await page.evaluate(() => document.querySelector("#cadre .cadre-photo.visible").style.getPropertyValue("--photo")), /souvenir/);
  assert.equal(await page.textContent("#cadre-souvenir"), "Il y a 7 ans");
  assert.ok(await page.locator("#cadre .cadre-photo.travelling").count(), "travelling lent avec les animations complètes");
  await touche("ArrowLeft");
  assert.ok(await page.evaluate(() => document.querySelector("#cadre").hidden), "une touche réveille et arrête le diaporama");
  assert.deepEqual(page.erreurs, []);
});

// Audit du 17/09/2026 : en animations complètes, le travelling faisait passer la copie floutée
// et assombrie AU-DESSUS de la photo nette. Une mire de bandes noires et blanches de 48 px doit
// rester nette au centre de l'écran, travelling en cours.
test("cadre photo : la photo reste nette par-dessus son fond flouté, travelling en cours", async () => {
  await ouvrir({ ...famille({ actif: "sam" }), reglages: { profils: [{ id: "sam", nom: "Samuel", cadre: { actif: true } }], systeme: { meteo: { active: false } } } });
  await page.setViewportSize({ width: 1920, height: 1080 });
  const mire = await page.evaluate(() => {
    const c = document.createElement("canvas"); c.width = 1920; c.height = 1080;
    const x = c.getContext("2d");
    for (let i = 0; i < 40; i++) { x.fillStyle = i % 2 ? "#fff" : "#000"; x.fillRect(i * 48, 0, 48, 1080); }
    return c.toDataURL("image/png");
  });
  await touche("a");
  await attendreMessage("cadre");
  await page.evaluate(photo => window.hub.recevoir({ type: "cadre", albums: [], photos: [photo], souvenirs: [] }), mire);
  await page.waitForSelector("#cadre .cadre-photo.visible.travelling", { timeout: 5000 });
  // Le fondu d'entrée dure 2,4 s ; ensuite seul le travelling (6 % en 30 s) bouge.
  await page.waitForTimeout(2800);
  const png = await page.screenshot({ clip: { x: 760, y: 440, width: 400, height: 200 } });
  const extremes = await page.evaluate(async b64 => {
    const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode();
    const c = document.createElement("canvas"); c.width = i.width; c.height = i.height;
    const x = c.getContext("2d"); x.drawImage(i, 0, 0);
    const d = x.getImageData(0, 100, i.width, 1).data;
    let min = 255, max = 0;
    for (let k = 0; k < d.length; k += 4) { const v = (d[k] + d[k + 1] + d[k + 2]) / 3; min = Math.min(min, v); max = Math.max(max, v); }
    return { min, max };
  }, png.toString("base64"));
  assert.ok(extremes.min < 30 && extremes.max > 225, `bandes nettes attendues, lu min ${extremes.min} max ${extremes.max}`);
});

test("cadre photo : animations réduites, ni fondu ni travelling", async () => {
  await ouvrir({ ...famille({ actif: "sam" }), reglages: { profils: [{ id: "sam", nom: "Samuel", animations: "reduites", cadre: { actif: true } }], systeme: { meteo: { active: false } } } });
  await touche("a");
  await attendreMessage("cadre");
  await page.evaluate(photo => window.hub.recevoir({ type: "cadre", albums: [], photos: [photo], souvenirs: [] }), PHOTO);
  await page.waitForSelector("#cadre .cadre-photo.visible", { timeout: 5000 });
  assert.ok(await page.evaluate(() => document.querySelector("#cadre").classList.contains("reduit")));
  assert.equal(await page.locator("#cadre .cadre-photo.travelling").count(), 0);
});

test("cadre photo : réglages par profil (album, durée, souvenirs) dans Veille", async () => {
  await ouvrir({ ...famille({ actif: "sam" }), reglages: { profils: [{ id: "sam", nom: "Samuel" }], systeme: { meteo: { active: false } } } });
  await page.evaluate(() => ACTIONS.reglages("veille"));
  await page.waitForTimeout(200);
  await page.click('[data-cle="cadre-true"]');
  await attendreMessage("cadre");
  await page.evaluate(() => window.hub.recevoir({ type: "cadre", albums: ["Noël", "Vacances 2024"], photos: [], souvenirs: [] }));
  await page.click('[data-cle="cadre-album-Vacances 2024"]');
  await page.click('[data-cle="cadre-duree-60"]');
  await page.click('[data-cle="cadre-souvenirs-true"]');
  await page.waitForFunction(() => {
    const c = window.__messages.filter(x => x.type === "reglages").at(-1)?.donnees.profils[0].cadre;
    return c && c.actif === true && c.album === "Vacances 2024" && c.duree === 60 && c.souvenirs === true;
  }, null, { timeout: 5000 });
});

test("anglais : les nouveaux écrans sont traduits", async () => {
  const initial = famille({ utiliseCamille: 7200 });
  initial.reglages.profils[1].langue = "en";
  await ouvrir(initial);
  await page.evaluate(() => ACTIONS.reglages("temps"));
  await page.waitForTimeout(200);
  assert.equal(await page.textContent("#contenu-reglages h3"), "Screen time");
  assert.match(await page.textContent("#sommaire"), /Power schedule/);
  await page.evaluate(() => fermerTout());
  await touche("1");
  assert.equal(await page.textContent("#temps-plus-titre"), "Screen time is up for today");
});
