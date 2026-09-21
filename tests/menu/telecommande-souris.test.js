// L'interrupteur « Souris et clavier depuis le téléphone » (Réglages → Télécommande).
// C'est lui qui ouvre, ou non, le plus gros pouvoir de la télécommande téléphone
// (installer/telecommande, classe Pointeur) : il doit être éteint tant qu'on ne l'a pas
// allumé devant la TV, dire en une phrase ce qu'il permet, et rester hors de portée
// d'un profil restreint.
//
//   cd tests/menu && npm install && npm test

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { chromium, webkit } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const PAGE = pathToFileURL(path.join(ici, "../../installer/menu/index.html")).href;
const ETAT = { url: "http://192.168.1.50:8790/", code: "482913", expire: Date.now() + 240000, telephones: 0, appairageOuvert: true };

let navigateur;
before(async () => {
  navigateur = process.env.HUB_NAVIGATEUR === "webkit" ? await webkit.launch()
    : await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });
});
after(async () => { await navigateur?.close(); });

async function ouvrir(initial) {
  const page = await navigateur.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.route(/open-meteo\.com/, route => route.abort());
  await page.addInitScript(i => {
    window.__messages = [];
    window.webkit = { messageHandlers: { hub: { postMessage: texte => window.__messages.push(JSON.parse(texte)) } } };
    window.HUB_INITIAL = i;
  }, { retour: true, telecommande: ETAT, ...initial });
  await page.goto(PAGE);
  await page.waitForTimeout(200);
  await page.evaluate(() => ACTIONS.reglages("telecommande"));
  await page.waitForFunction(() => document.querySelector("#contenu-reglages .appairage"));
  return page;
}
const dernierReglage = page => page.evaluate(() => window.__messages.filter(m => m.type === "reglages").at(-1)?.donnees.systeme.telecommandeSouris);

test("souris du téléphone : éteinte par défaut, une phrase dit ce qu'elle permet, et le choix est enregistré", async () => {
  const page = await ouvrir({});
  assert.match(await page.getAttribute('[data-cle="telecommande-souris-false"]', "class"), /\bchoisie\b/,
    "éteinte tant que personne ne l'a allumée devant la TV");
  const texte = await page.textContent("#contenu-reglages");
  assert.match(texte, /Souris et clavier depuis le téléphone/);
  assert.match(texte, /déplacer le pointeur, cliquer et taper du texte sur le bureau et dans les services web/);
  await page.click('[data-cle="telecommande-souris-true"]');
  await page.waitForFunction(() => window.__messages.some(m => m.type === "reglages" && m.donnees.systeme.telecommandeSouris === true));
  assert.match(await page.getAttribute('[data-cle="telecommande-souris-true"]', "class"), /\bchoisie\b/);
  await page.click('[data-cle="telecommande-souris-false"]');
  await page.waitForFunction(() => window.__messages.filter(m => m.type === "reglages").at(-1).donnees.systeme.telecommandeSouris === false);
  assert.strictEqual(await dernierReglage(page), false, "un booléen strict : hub-telecommande refuse tout le reste");
  await page.close();
});

test("souris du téléphone : un réglage enregistré bizarre ne vaut pas « allumé »", async () => {
  const page = await ouvrir({ reglages: { systeme: { telecommandeSouris: "true" } } });
  assert.match(await page.getAttribute('[data-cle="telecommande-souris-false"]', "class"), /\bchoisie\b/);
  assert.doesNotMatch(await page.getAttribute('[data-cle="telecommande-souris-true"]', "class"), /\bchoisie\b/);
  await page.close();
});

test("souris du téléphone : en anglais aussi", async () => {
  const page = await ouvrir({ reglages: { profilActif: "a", profils: [{ id: "a", nom: "Sam", langue: "en" }] } });
  assert.match(await page.textContent("#contenu-reglages"), /Mouse and keyboard from the phone/);
  await page.close();
});

test("souris du téléphone : un profil restreint ne voit pas l'interrupteur", async () => {
  const page = await ouvrir({ reglages: { profilActif: "alix", profils: [{ id: "alix", nom: "Alix", modes: { tv: true, gaming: true, bureau: false } }] } });
  assert.equal(await page.locator('[data-cle^="telecommande-souris-"]').count(), 0);
  assert.doesNotMatch(await page.textContent("#contenu-reglages"), /Souris et clavier/);
  await page.close();
});
