// Temps entre deux images du menu en 3840×2160, dans le Chromium de Playwright.
// INDICATIF SEULEMENT : rendu logiciel sur la machine de développement, ni WebKitGTK ni
// l'UHD 630. Sert à comparer deux versions du menu entre elles, jamais à prédire la TV.
//
//   cd tests/menu && node mesurer-rendu.mjs [racine d'une copie du dépôt]
//   Avant/après : mkdir /tmp/avant && git archive <commit> installer/menu | tar -x -C /tmp/avant
//                 node mesurer-rendu.mjs /tmp/avant ; node mesurer-rendu.mjs
import { chromium, webkit } from "playwright-core";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

// Le moteur : « chrome » par défaut, « chromium » celui de Playwright, « webkit » celui de
// la famille de la TV. Un rendu peut n'exister que dans l'un d'eux — la WebKitGTK du HUB
// ignorait les `mask-image` en dégradé que Chromium applique, et ça ne s'est vu que sur une
// photo du salon (18/09/2026). HUB_NAVIGATEUR=webkit rejoue toute la suite dans WebKit.
const lancerNavigateur = () => process.env.HUB_NAVIGATEUR === "webkit" ? webkit.launch()
  : chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });

const racine = process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), "../..");
const PAGE = pathToFileURL(path.join(racine, "installer/menu/index.html")).href;
const navigateur = await lancerNavigateur();

async function scenario(nom, preparer) {
  const page = await navigateur.newPage({ viewport: { width: 3840, height: 2160 }, deviceScaleFactor: 1 });
  await page.addInitScript(() => {
    window.HUB_INITIAL = { retour: true, reglages: { profilActif: "a", profils: [{ id: "a", nom: "A", fond: "ocean" }], systeme: { meteo: { active: false } } } };
  });
  await page.route(/open-meteo/, r => r.abort());
  await page.goto(PAGE + "?sans-intro");
  await page.waitForTimeout(1500);
  await preparer(page);
  await page.waitForTimeout(1500);
  const d = await page.evaluate(() => new Promise(fin => {
    const intervalles = [];
    let avant = performance.now();
    const debut = avant;
    (function image(t) {
      intervalles.push(t - avant);
      avant = t;
      if (t - debut < 5000) requestAnimationFrame(image); else fin(intervalles.slice(1));
    })(avant);
  }));
  const tries = [...d].sort((a, b) => a - b);
  const moyenne = d.reduce((a, b) => a + b, 0) / d.length;
  console.log(`${nom.padEnd(18)} ${(1000 / moyenne).toFixed(1).padStart(5)} images/s  p95 ${tries[Math.floor(tries.length * .95)].toFixed(0)} ms  pire ${tries.at(-1).toFixed(0)} ms`);
  await page.close();
}

console.log(`${racine} — ${new Date().toISOString().slice(0, 10)} — Chromium ${navigateur.version()} headless, 3840×2160, fond océan`);
await scenario("accueil", async () => {});
await scenario("réglages ouverts", p => p.keyboard.press("r"));
await scenario("ambiant", p => p.keyboard.press("a"));
await navigateur.close();
