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
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, mkdirSync, writeFileSync } from "node:fs";
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
  // La preuve est l'ordre : reçue par le menu AVANT le relâcher. Le délai n'est qu'une
  // borne large (CDP, fichier relu toutes les 30 ms, machine de test chargée).
  assert.ok(delai < 1000, `commande reçue par le menu en ${delai} ms, doigt encore posé`);
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

// ── HTTPS local ─────────────────────────────────────────────────────────────
// Sans raccourci : Chrome vérifie la chaîne avec son propre vérificateur, la racine
// du HUB étant installée dans le magasin NSS d'un HOME jetable (ce que fait un
// téléphone en l'installant). Ni --ignore-certificate-errors, ni ignoreHTTPSErrors.
// Le nom hub.local est dirigé sur 127.0.0.1 : l'origine http://hub.local N'EST PAS
// un contexte sécurisé, exactement comme http://192.168.1.50 sur le téléphone.
export async function chromeAvecRacine(racine, extra = []) {
  const maison = mkdtempSync(path.join(tmpdir(), "hub-nss-"));
  const nss = path.join(maison, ".pki", "nssdb");
  mkdirSync(nss, { recursive: true });
  if (racine) {
    execFileSync("certutil", ["-d", `sql:${nss}`, "-N", "--empty-password"]);
    execFileSync("certutil", ["-d", `sql:${nss}`, "-A", "-t", "C,,", "-n", "HUB autorite locale", "-i", racine]);
  }
  const nav = await chromium.launch({
    channel: "chrome",
    env: { ...process.env, HOME: maison },
    args: ["--host-resolver-rules=MAP hub.local 127.0.0.1", ...extra],
  });
  nav.on("disconnected", () => rmSync(maison, { recursive: true, force: true }));
  return nav;
}

test("HTTPS : certificat racine installé, chaîne acceptée par Chrome, passage http → https sans code", async () => {
  const b = await lancerBanc(["--https"]);
  const nav = await chromeAvecRacine(b.ports.racine);
  try {
    const page = await ouvrir(nav, `http://hub.local:${b.ports.http}/`);
    assert.equal(await page.evaluate(() => isSecureContext), false, "http://hub.local n'est pas sécurisé");
    await appairer(page, b);
    // Le certificat servi en http est bien la racine, octet pour octet.
    const der = await page.evaluate(async () => [...new Uint8Array(await (await fetch("/hub-racine.crt")).arrayBuffer())]);
    const pem = readFileSync(b.ports.racine, "utf8").replace(/-----[^-]+-----|\s/g, "");
    assert.equal(Buffer.from(der).toString("base64"), pem);

    await page.locator('[data-action="options"]').tap();
    await page.locator('[data-action="securite"]').tap();
    await page.locator("#securite-statut", { hasText: "reconnu" }).waitFor();
    const empreinte = await page.locator("#empreinte").innerText();
    assert.equal(empreinte, b.etat().empreinteRacine, "la page montre l'empreinte que la TV affiche");
    await page.locator("#ouvrir-https").tap();
    await page.waitForURL(u => u.origin === `https://hub.local:${b.ports.https}`);
    await page.locator("#telecommande").waitFor({ state: "visible" });
    assert.equal(await page.evaluate(() => location.hash), "", "le ticket ne reste pas dans l'adresse");
    assert.equal(await page.evaluate(() => isSecureContext), true);
    assert.equal(await page.evaluate(() => !!navigator.mediaDevices?.getUserMedia), true, "micro disponible");
    const avant = b.menu().length;
    await page.locator("#rangee-retour [data-cmd=retour]").tap();
    await attendre(() => b.menu().length > avant);
    assert.deepEqual(page.erreurs, []);
  } finally {
    await nav.close();
    b.arreter();
  }
});

test("HTTPS : sans la racine, Chrome refuse la connexion et la page le dit", async () => {
  const b = await lancerBanc(["--https"]);
  const nav = await chromeAvecRacine(null);
  try {
    const page = await ouvrir(nav, `http://hub.local:${b.ports.http}/`);
    await appairer(page, b);
    await page.locator('[data-action="options"]').tap();
    await page.locator('[data-action="securite"]').tap();
    await page.locator("#securite-statut", { hasText: "pas encore installé" }).waitFor();
    assert.equal(await page.locator("#etapes-android").getAttribute("open"), "");
    const erreur = await page.goto(`https://hub.local:${b.ports.https}/`).then(() => null, e => e.message);
    assert.match(erreur || "", /ERR_CERT_AUTHORITY_INVALID/);
  } finally {
    await nav.close();
    b.arreter();
  }
});

// ── Dictée ──────────────────────────────────────────────────────────────────
// Le micro de Chrome est remplacé par un fichier son (option de Chrome pour les
// tests), et la page tourne en https vérifié, comme sur le téléphone. Avec
// HUB_VOIX_PYTHON, HUB_VOIX_MODELES et HUB_TEST_DICTEE_WAV (« Télé. » enregistré),
// c'est le vrai Vosk qui reconnaît ; sinon le banc répond « télé » à tout son assez
// fort, et le test prouve la capture, le format et le chemin jusqu'au menu.
function sonDeSecours() {
  const taux = 48000, duree = 3, n = taux * duree;
  const b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n * 2, 4); b.write("WAVE", 8); b.write("fmt ", 12);
  b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(taux, 24);
  b.writeUInt32LE(taux * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36);
  b.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) b.writeInt16LE(Math.round(12000 * Math.sin(2 * Math.PI * 220 * i / taux)), 44 + i * 2);
  const f = path.join(mkdtempSync(path.join(tmpdir(), "hub-son-")), "son.wav");
  writeFileSync(f, b);
  return f;
}

test("dictée : maintenir, parler, relâcher → commande reconnue → datagrammes au menu", async () => {
  const vrai = process.env.HUB_VOIX_PYTHON && process.env.HUB_VOIX_MODELES && process.env.HUB_TEST_DICTEE_WAV;
  const son = vrai ? process.env.HUB_TEST_DICTEE_WAV : sonDeSecours();
  const b = await lancerBanc(["--https"]);
  const nav = await chromeAvecRacine(b.ports.racine, [
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${son}`,
  ]);
  try {
    const page = await ouvrir(nav, `https://hub.local:${b.ports.https}/`);
    await appairer(page, b);
    const micro = await page.locator("#micro").boundingBox();
    const cdp = await page.context().newCDPSession(page);
    const point = [{ x: micro.x + micro.width / 2, y: micro.y + micro.height / 2, id: 0 }];
    const avant = b.menu().length;
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: point });
    await page.locator("#micro.ecoute").waitFor();
    await new Promise(ok => setTimeout(ok, 2900));
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    const recu = await attendre(() => { const r = b.menu().slice(avant); return r.includes("voix:repos") && r; }, 40000);
    assert.match(recu[0], /^voix:entendu:(télé ?)+$/, recu.join(" | "));
    assert.deepEqual(recu.slice(1), ["tv", "voix:repos"]);
    await page.locator("#message", { hasText: "→ TV" }).waitFor();
    if (!vrai) {
      const d = JSON.parse(readFileSync(path.join(b.dossier, "dictee.json"), "utf8"));
      assert.ok(d.secondes > 2 && d.secondes < 4, `durée envoyée ${d.secondes} s`);
    }
    assert.equal(await page.locator("#micro").getAttribute("class"), "touche micro");
    assert.deepEqual(page.erreurs, []);
    console.log(`# dictée prouvée avec ${vrai ? "le vrai Vosk" : "le reconnaisseur par énergie (Vosk non fourni)"}`);
  } finally {
    await nav.close();
    b.arreter();
  }
});

test("dictée : en http (non sécurisé), le micro ouvre la marche à suivre au lieu d'échouer", async () => {
  const b = await lancerBanc(["--https"]);
  const nav = await chromeAvecRacine(null);
  try {
    const page = await ouvrir(nav, `http://hub.local:${b.ports.http}/`);
    await appairer(page, b);
    await page.locator("#micro").tap();
    await page.locator("#securite").waitFor({ state: "visible" });
    assert.equal(b.menu().length, 0);
  } finally {
    await nav.close();
    b.arreter();
  }
});

export { PIXEL, IPHONE };
