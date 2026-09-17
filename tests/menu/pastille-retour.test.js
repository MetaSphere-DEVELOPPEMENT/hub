// La pastille « ← HUB » que hub-web injecte dans les pages de streaming, éprouvée dans
// Chromium sur une page factice : le script est celui de installer/hub-web, tel quel.
// Ni Netflix ni la télécommande CEC : ce test vérifie les règles d'apparition et le
// message envoyé, pas le comportement des vrais sites (à éprouver sur la TV).
//
//   cd tests/menu && npm test
//   HUB_CAPTURES=/un/dossier : captures 1920×1080 et 3840×2160 de la pastille

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ici = path.dirname(fileURLToPath(import.meta.url));
const HUB_WEB = path.join(ici, "../../installer/hub-web");
const SCRIPT = execFileSync("python3", ["-c", `
import importlib.machinery, importlib.util, sys
chargeur = importlib.machinery.SourceFileLoader("hub_web", sys.argv[1])
module = importlib.util.module_from_spec(importlib.util.spec_from_loader("hub_web", chargeur))
chargeur.exec_module(module)
print(module.script_injecte(module.SERVICES["netflix"]))`, HUB_WEB], { encoding: "utf8" });

// Une page qui ressemble à un service : fond sombre plein écran, CSS agressif sur les
// boutons et un écouteur Échap, pour voir ce que la pastille leur laisse.
const FAUX_SITE = `<!doctype html><html><head><style>
  html, body { margin: 0; height: 100%; background: linear-gradient(135deg, #3a0d12, #111 60%); color: #fff; font-family: sans-serif; }
  button { background: red !important; font-size: 6px !important; }
  [popover] { border: 10px solid lime; }
  .affiche { position: absolute; left: 12vw; top: 30vh; width: 76vw; height: 40vh; background: #222; display: grid; place-items: center; font-size: 5vh; }
  video { position: absolute; inset: 0; width: 100vw; height: 100vh; }
</style></head><body>
  <input id="recherche" placeholder="recherche du site">
  <div class="affiche">Service factice</div>
  <script>
    window.__echap = [];
    window.__empecherEchap = false;
    document.addEventListener("keydown", e => {
      if (e.key !== "Escape") return;
      if (window.__empecherEchap) e.preventDefault();
      window.__echap.push(e.defaultPrevented);
    });
  </script>
</body></html>`;

let navigateur;
before(async () => {
  navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });
});
after(async () => { await navigateur?.close(); });

async function ouvrir({ largeur = 1920, hauteur = 1080, reduire = false } = {}) {
  const page = await navigateur.newPage({ viewport: { width: largeur, height: hauteur }, deviceScaleFactor: 1,
                                          reducedMotion: reduire ? "reduce" : "no-preference" });
  const appels = [];
  await page.exposeFunction("hubHub", texte => { appels.push(JSON.parse(texte)); });
  await page.addInitScript(SCRIPT);
  await page.route("http://service.test/", r => r.fulfill({ contentType: "text/html", body: FAUX_SITE }));
  await page.goto("http://service.test/");
  return { page, appels };
}

// Ce qu'on peut savoir d'une ombre fermée depuis la page : quel élément reçoit le
// pointeur à un endroit donné. La pastille est visible et cliquable là où elle le reçoit.
const auPoint = (page, x, y) => page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.localName, [x, y]);
const pointPastille = (largeur, hauteur) => [Math.round(largeur * .05) + 30, Math.round(hauteur * .05) + 25];
const pastilleVisible = async (page, largeur = 1920, hauteur = 1080) =>
  (await auPoint(page, ...pointPastille(largeur, hauteur))) === "hub-retour";
const focusSurPastille = page => page.evaluate(() => document.activeElement?.localName === "hub-retour");
// Le message « retour » repart par une fonction exposée : il arrive un peu après le geste,
// pas avec lui. Lu tout de suite, « appels » était encore vide dès que la machine était
// chargée (la suite complète lance dix fichiers en parallèle).
const attendreAppels = async (appels, n = 1) => {
  for (let i = 0; i < 40 && appels.length < n; i++) await new Promise(fin => setTimeout(fin, 50));
  return appels;
};

test("visible 5 s au chargement, masquée ensuite, sans gêner le site autour", async () => {
  const { page } = await ouvrir();
  assert.ok(await pastilleVisible(page), "visible au chargement");
  assert.notEqual(await auPoint(page, 1000, 60), "hub-retour", "hors de la pastille, le pointeur va au site");
  assert.equal(await page.evaluate(() => document.querySelector("hub-retour").shadowRoot), null, "ombre fermée");
  await page.waitForTimeout(3500);
  assert.ok(await pastilleVisible(page), "encore là à 3,5 s");
  await page.waitForTimeout(2000);
  assert.ok(!(await pastilleVisible(page)), "masquée après 5 s");
  await page.close();
});

test("réapparaît au mouvement de la souris, puis se masque", async () => {
  const { page } = await ouvrir();
  await page.waitForTimeout(5400);
  assert.ok(!(await pastilleVisible(page)));
  await page.mouse.move(900, 600, { steps: 3 });
  assert.ok(await pastilleVisible(page), "souris → visible");
  await page.waitForTimeout(5400);
  assert.ok(!(await pastilleVisible(page)));
  // Un mouvement factice (movementX/Y nuls), comme Chrome en envoie quand la page défile.
  await page.evaluate(() => window.dispatchEvent(new MouseEvent("mousemove", { clientX: 5, clientY: 5 })));
  assert.ok(!(await pastilleVisible(page)), "pas de réapparition sans vrai mouvement");
  await page.close();
});

test("Échap court : montrée avec l'aide et focalisée ; second Échap : masquée, focus rendu au site", async () => {
  const { page, appels } = await ouvrir();
  await page.focus("#recherche");
  await page.waitForTimeout(5400);
  await page.keyboard.press("Escape");
  assert.ok(await pastilleVisible(page), "Échap → visible");
  assert.ok(await focusSurPastille(page), "focus sur la pastille après un Échap court");
  assert.deepEqual(await page.evaluate(() => window.__echap), [false], "Échap arrivé au site, non empêché");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(250); // fondu de sortie
  assert.ok(!(await pastilleVisible(page)), "second Échap → masquée");
  assert.equal(await page.evaluate(() => document.activeElement.id), "recherche", "focus rendu au site");
  assert.deepEqual(await page.evaluate(() => window.__echap), [false, false]);
  assert.deepEqual(appels, []);
  // OK sur la pastille focalisée : retour.
  await page.keyboard.press("Escape");
  await page.keyboard.press("Enter");
  assert.deepEqual(await attendreAppels(appels), [{ type: "retour" }]);
  await page.close();
});

test("une flèche rend le focus au site ; Échap consommé par le site ne donne pas le focus", async () => {
  const { page } = await ouvrir();
  await page.focus("#recherche");
  await page.keyboard.press("Escape");
  assert.ok(await focusSurPastille(page));
  await page.keyboard.press("ArrowDown");
  assert.equal(await page.evaluate(() => document.activeElement.id), "recherche");
  await page.evaluate(() => { window.__empecherEchap = true; });
  await page.keyboard.press("Escape");
  assert.ok(await pastilleVisible(page), "montrée quand même, avec l'aide");
  assert.ok(!(await focusSurPastille(page)), "le focus reste au site qui a utilisé Échap");
  await page.close();
});

test("Échap maintenue 2 s : retour, comme avant", async () => {
  const { page, appels } = await ouvrir();
  await page.keyboard.down("Escape");
  const debut = Date.now();
  // Playwright n'émet pas de répétition : on la simule comme le ferait le clavier.
  while (Date.now() - debut < 2300) {
    await page.evaluate(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", repeat: true, bubbles: true })));
    await page.waitForTimeout(100);
  }
  await page.keyboard.up("Escape");
  assert.deepEqual(await attendreAppels(appels), [{ type: "retour" }]);
  assert.ok(!(await focusSurPastille(page)), "un appui long ne donne pas le focus");
  await page.close();
});

test("clic sur la pastille : message « retour », le clic n'atteint pas le site", async () => {
  const { page, appels } = await ouvrir();
  await page.evaluate(() => { window.__clics = 0; document.addEventListener("click", () => window.__clics++); });
  await page.mouse.click(...pointPastille(1920, 1080));
  assert.deepEqual(await attendreAppels(appels), [{ type: "retour" }]);
  assert.equal(await page.evaluate(() => window.__clics), 0);
  await page.close();
});

test("vidéo en pause : visible tant qu'elle l'est ; lecture : masquée", async () => {
  const { page } = await ouvrir();
  await page.evaluate(() => document.body.append(document.createElement("video")));
  await page.waitForTimeout(5400);
  await page.evaluate(() => document.querySelector("video").dispatchEvent(new Event("pause")));
  await page.waitForTimeout(5400);
  assert.ok(await pastilleVisible(page), "reste visible pendant la pause");
  await page.evaluate(() => document.querySelector("video").dispatchEvent(new Event("play")));
  await page.waitForTimeout(300);
  assert.ok(!(await pastilleVisible(page)), "masquée à la reprise");
  await page.close();
});

test("au-dessus d'un élément en plein écran", async () => {
  const { page, appels } = await ouvrir();
  await page.evaluate(() => {
    const b = document.createElement("div");
    b.id = "plein";
    b.style.cssText = "position:absolute;right:0;bottom:0;width:50px;height:50px;background:#333";
    b.onclick = () => document.querySelector(".affiche").requestFullscreen();
    document.body.append(b);
  });
  await page.click("#plein");
  await page.waitForFunction(() => !!document.fullscreenElement);
  await page.waitForTimeout(300);
  assert.ok(!(await pastilleVisible(page)), "le passage en plein écran la masque");
  await page.mouse.move(700, 500, { steps: 3 });
  // Attendre qu'elle soit revenue plutôt que 100 ms fixes : la suite complète charge la
  // machine (dix fichiers en parallèle) et le fondu arrivait après le clic.
  for (let i = 0; i < 40 && !(await pastilleVisible(page)); i++) await page.waitForTimeout(50);
  assert.ok(await pastilleVisible(page), "revenue au mouvement de la souris");
  // Un clic plutôt qu'elementFromPoint : en plein écran, Chromium rend inerte tout ce
  // qui est hors de l'élément plein écran, même dessiné devant (vu : visible, clic perdu).
  await page.mouse.click(...pointPastille(1920, 1080));
  assert.deepEqual(await attendreAppels(appels), [{ type: "retour" }], "réapparaît et reçoit le clic au-dessus du plein écran");
  await page.close();
});

test("mouvement réduit : masquée sans fondu", async () => {
  const { page } = await ouvrir({ reduire: true });
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  assert.ok(!(await pastilleVisible(page)), "masquée tout de suite");
  await page.close();
});

test("un site qui réécrit son document : la pastille est reposée", async () => {
  const { page } = await ouvrir();
  await page.evaluate(() => { document.documentElement.innerHTML = "<body style='background:#111'></body>"; });
  await page.waitForTimeout(200);
  await page.mouse.move(800, 400, { steps: 3 });
  assert.ok(await pastilleVisible(page));
  await page.close();
});

test("captures 1920×1080 et 3840×2160", { skip: !process.env.HUB_CAPTURES }, async () => {
  for (const [largeur, hauteur] of [[1920, 1080], [3840, 2160]]) {
    const { page } = await ouvrir({ largeur, hauteur });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(process.env.HUB_CAPTURES, `pastille-retour-${largeur}x${hauteur}-chargement.png`) });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    assert.ok(await pastilleVisible(page, largeur, hauteur));
    await page.screenshot({ path: path.join(process.env.HUB_CAPTURES, `pastille-retour-${largeur}x${hauteur}-echap.png`) });
    await page.close();
  }
});
