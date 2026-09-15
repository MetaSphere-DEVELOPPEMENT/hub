// La télécommande dans Chrome en vue téléphone, contre le vrai service (banc_essai.py).
//
//   PATH=~/.nvm/versions/node/v22.18.0/bin:$PATH node --test installer/telecommande/test_navigateur.mjs
//
// playwright-core est pris dans tests/menu/node_modules (cd tests/menu && npm install) ;
// Chrome est celui du système (channel "chrome"). Rien ne sort de la machine : le
// service écoute sur 127.0.0.1 et son « menu » est un socket qui note ce qu'il reçoit.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ici = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(ici, "../../tests/menu/package.json"));
const { chromium } = require("playwright-core");

// Un Pixel en portrait : écran tactile, UA Android (l'encart en dépend).
const PIXEL = {
  viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.6, isMobile: true, hasTouch: true,
  userAgent: "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36",
  locale: "fr-FR",
};
const IPHONE = {
  ...PIXEL, viewport: { width: 393, height: 852 }, deviceScaleFactor: 3,
  userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
};

export async function lancerBanc(options = []) {
  const dossier = mkdtempSync(path.join(tmpdir(), "hub-tel-"));
  const banc = spawn("python3", [path.join(ici, "banc_essai.py"), dossier, ...options],
    { stdio: ["pipe", "pipe", "inherit"], env: { ...process.env, ...(options.env || {}) } });
  const ports = await new Promise((ok, ko) => {
    let tampon = "";
    banc.stdout.on("data", d => {
      tampon += d;
      if (tampon.includes("\n")) ok(JSON.parse(tampon.split("\n")[0]));
    });
    banc.on("exit", c => ko(new Error(`banc arrêté (${c})`)));
  });
  return {
    dossier, ports, banc,
    code: () => JSON.parse(readFileSync(path.join(dossier, "run/telecommande.json"), "utf8")).code,
    etat: () => JSON.parse(readFileSync(path.join(dossier, "run/telecommande.json"), "utf8")),
    menu: () => readFileSync(path.join(dossier, "menu.txt"), "utf8").split("\n").filter(Boolean),
    arreter: () => { banc.stdin.end(); banc.kill(); rmSync(dossier, { recursive: true, force: true }); },
  };
}

// On attend un état, jamais une durée fixe : la machine de test peut être chargée.
export async function attendre(verifie, delai = 5000) {
  const fin = Date.now() + delai;
  for (;;) {
    const r = await verifie();
    if (r) return r;
    if (Date.now() > fin) throw new Error("délai dépassé");
    await new Promise(ok => setTimeout(ok, 30));
  }
}

export async function ouvrir(navigateur, url, appareil = PIXEL, contexteOptions = {}) {
  const contexte = await navigateur.newContext({ ...appareil, ...contexteOptions });
  const page = await contexte.newPage();
  page.erreurs = [];
  page.on("pageerror", e => page.erreurs.push(e.message));
  page.on("console", m => { if (/Content.Security.Policy|Refused to/i.test(m.text())) page.erreurs.push(m.text()); });
  await page.goto(url);
  return page;
}

export async function appairer(page, banc) {
  await page.locator("#code").fill(banc.code());
  await page.locator("#telecommande").waitFor({ state: "visible" });
}

let navigateur, banc;
before(async () => {
  navigateur = await chromium.launch({ channel: "chrome" });
  banc = await lancerBanc();
});
after(async () => { await navigateur?.close(); banc?.arreter(); });

test("manifeste et icônes chargés sans violation CSP, encart Android puis masqué pour de bon", async () => {
  const url = `http://127.0.0.1:${banc.ports.http}/`;
  const page = await ouvrir(navigateur, url);
  const manifeste = await page.evaluate(async () => {
    const lien = document.querySelector('link[rel="manifest"]');
    const r = await fetch(lien.href);
    return r.json();
  });
  assert.equal(manifeste.display, "standalone");
  const tailles = await page.evaluate(async () => Promise.all(
    ["/icone-192.png", "/icone-512.png", "/apple-touch-icon.png"].map(async src => {
      const i = new Image(); i.src = src; await i.decode(); return i.naturalWidth;
    })));
  assert.deepEqual(tailles, [192, 512, 180]);

  await appairer(page, banc);
  await page.locator("#encart").waitFor({ state: "visible" });
  assert.equal(await page.locator("#encart-android").isVisible(), true);
  assert.equal(await page.locator("#encart-ios").isVisible(), false);
  assert.match(await page.locator("#encart-android").innerText(), /Ajouter à l'écran d'accueil/);
  await page.locator('[data-action="encart-fermer"]').tap();
  assert.equal(await page.locator("#encart").isVisible(), false);
  await page.reload();
  await page.locator("#telecommande").waitFor({ state: "visible" });
  assert.equal(await page.locator("#encart").isVisible(), false, "l'encart fermé ne revient pas");
  assert.deepEqual(page.erreurs, []);
  await page.context().close();
});

test("encart iPhone : gestes de Safari et avertissement sur le code à retaper", async () => {
  const page = await ouvrir(navigateur, `http://127.0.0.1:${banc.ports.http}/`, IPHONE);
  await appairer(page, banc);
  await page.locator("#encart-ios").waitFor({ state: "visible" });
  const texte = await page.locator("#encart-ios").innerText();
  assert.match(texte, /Sur l'écran d'accueil/);
  assert.match(texte, /retapez un code/);
  assert.deepEqual(page.erreurs, []);
  await page.context().close();
});

// ── Pavé tactile ────────────────────────────────────────────────────────────
// De vrais événements tactiles envoyés à Chrome par le protocole DevTools : ils
// passent par le même chemin qu'un doigt (touch-action, pointer events), à la
// différence d'un dispatchEvent fabriqué dans la page.
async function doigts(page) {
  const cdp = await page.context().newCDPSession(page);
  const boite = await page.locator("#pave-tactile").boundingBox();
  const cx = boite.x + boite.width / 2, cy = boite.y + boite.height / 2;
  const envoyer = (type, points) => cdp.send("Input.dispatchTouchEvent", {
    type, touchPoints: points.map(([x, y], id) => ({ x, y, id, radiusX: 8, radiusY: 8, force: 1 })),
  });
  const pause = ms => new Promise(ok => setTimeout(ok, ms));
  return {
    cx, cy, envoyer, pause,
    async toucher() { await envoyer("touchStart", [[cx, cy]]); await pause(60); await envoyer("touchEnd", []); },
    async glisser(dx, dy, { tenir = 0 } = {}) {
      await envoyer("touchStart", [[cx, cy]]);
      for (let i = 1; i <= 6; i++) { await envoyer("touchMove", [[cx + dx * i / 6, cy + dy * i / 6]]); await pause(12); }
      if (tenir) await pause(tenir);
      await envoyer("touchEnd", []);
    },
    async appuiLong(ms = 750) { await envoyer("touchStart", [[cx, cy]]); await pause(ms); await envoyer("touchEnd", []); },
    async deuxDoigts() {
      await envoyer("touchStart", [[cx - 40, cy]]);
      await pause(25);
      await envoyer("touchStart", [[cx - 40, cy], [cx + 40, cy]]);
      await pause(60);
      await envoyer("touchEnd", []);
    },
  };
}

// Un seul appairage pour tous les tests du pavé : le service limite à 5 essais par
// minute par adresse, et c'est voulu. Le jeton passe d'un contexte à l'autre.
let stockageAppaire = null;
async function remoteAppairee(appareil = PIXEL) {
  const url = `http://127.0.0.1:${banc.ports.http}/`;
  if (!stockageAppaire) {
    const page = await ouvrir(navigateur, url, appareil);
    await appairer(page, banc);
    stockageAppaire = await page.context().storageState();
    await page.context().close();
  }
  const page = await ouvrir(navigateur, url, appareil, { storageState: stockageAppaire });
  await page.locator("#pave-tactile").waitFor({ state: "visible" });
  return page;
}

const recus = async (depuis, combien) => attendre(() => {
  const r = banc.menu().slice(depuis);
  return r.length >= combien && r;
});

test("pavé : toucher = OK, glissements = flèches, appui long = retour, deux doigts = accueil", async () => {
  const page = await remoteAppairee();
  const d = await doigts(page);
  const cas = [
    ["toucher", () => d.toucher(), "ok"],
    ["glisser à droite", () => d.glisser(90, 6), "droite"],
    ["glisser à gauche", () => d.glisser(-90, -4), "gauche"],
    ["glisser en haut", () => d.glisser(5, -90), "haut"],
    ["glisser en bas", () => d.glisser(-3, 90), "bas"],
    ["appui long", () => d.appuiLong(), "retour"],
    ["deux doigts", () => d.deuxDoigts(), "accueil"],
  ];
  for (const [nom, geste, attendu] of cas) {
    const avant = banc.menu().length;
    await geste();
    const r = await recus(avant, 1);
    await d.pause(250);  // rien d'autre ne doit suivre (pas de OK après un glissement)
    // accueil devient « retour » au menu (protocole du menu) : le banc a un menu ouvert.
    assert.deepEqual(banc.menu().slice(avant), [attendu === "accueil" ? "retour" : attendu], nom);
    assert.ok(r);
  }
  assert.deepEqual(page.erreurs, []);
  await page.context().close();
});

test("pavé : glisser puis rester posé répète la flèche, lever l'arrête", async () => {
  const page = await remoteAppairee();
  const d = await doigts(page);
  const avant = banc.menu().length;
  await d.glisser(0, 90, { tenir: 1100 });
  await d.pause(400);
  const apres = banc.menu().slice(avant);
  assert.ok(apres.length >= 4, `répétitions : ${apres.length}`);
  assert.ok(apres.every(c => c === "bas"), apres.join(","));
  const fige = banc.menu().length;
  await d.pause(400);
  assert.equal(banc.menu().length, fige, "plus rien après le relâcher");
  await page.context().close();
});

test("pavé : un long glissement enchaîne plusieurs flèches, un glissement court une seule", async () => {
  const page = await remoteAppairee();
  const d = await doigts(page);
  let avant = banc.menu().length;
  await d.glisser(260, 0);
  await d.pause(300);
  const long = banc.menu().slice(avant);
  assert.ok(long.length >= 3 && long.every(c => c === "droite"), long.join(","));
  avant = banc.menu().length;
  await d.glisser(40, 0);
  await d.pause(300);
  assert.deepEqual(banc.menu().slice(avant), ["droite"]);
  await page.context().close();
});

test("réactivité : la flèche part pendant le glissement, avant de lever le doigt", async () => {
  const page = await remoteAppairee();
  const d = await doigts(page);
  const avant = banc.menu().length;
  const t0 = Date.now();
  await d.envoyer("touchStart", [[d.cx, d.cy]]);
  for (let i = 1; i <= 4; i++) await d.envoyer("touchMove", [[d.cx, d.cy + 20 * i]]);
  await recus(avant, 1);
  const delai = Date.now() - t0;
  await d.envoyer("touchEnd", []);
  assert.ok(delai < 300, `commande reçue par le menu en ${delai} ms, doigt encore posé`);
  await page.context().close();
});

test("boutons conservés, et gaucher/droitier place Retour et le volume sous le pouce", async () => {
  const page = await remoteAppairee();
  const cote = async sel => {
    const b = await page.locator(sel).first().boundingBox();
    return b.x + b.width / 2 > PIXEL.viewport.width / 2 ? "droite" : "gauche";
  };
  assert.equal(await cote("#rangee-retour [data-cmd=retour]"), "droite");
  assert.equal(await cote("#zone-tactile [data-cmd='volume:+']"), "droite");
  await page.locator('[data-action="options"]').tap();
  await page.locator('[data-action="main"]').tap();
  await page.locator("#options [data-action=fermer]").tap();
  assert.equal(await cote("#rangee-retour [data-cmd=retour]"), "gauche");
  assert.equal(await cote("#zone-tactile [data-cmd='volume:+']"), "gauche");

  await page.locator('.bascule [data-valeur="boutons"]').tap();
  assert.equal(await page.locator("#pave-tactile").isVisible(), false);
  const avant = banc.menu().length;
  const croix = await page.locator("#zone-croix .pave").boundingBox();
  await page.touchscreen.tap(croix.x + croix.width / 2, croix.y + croix.height * 0.12);
  await page.locator("#zone-croix .ok").tap();
  assert.deepEqual(await recus(avant, 2), ["haut", "ok"]);
  await page.reload();
  await page.locator("#zone-croix").waitFor({ state: "visible" });
  assert.equal(await cote("#rangee-retour [data-cmd=retour]"), "gauche", "préférences gardées");
  assert.deepEqual(page.erreurs, []);
  await page.context().close();
});

export { PIXEL, IPHONE };
