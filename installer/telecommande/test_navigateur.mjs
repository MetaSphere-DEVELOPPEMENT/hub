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
  const banc = spawn(process.env.HUB_PYTHON || "python3", [path.join(ici, "banc_essai.py"), dossier, ...options],
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
    // Ce que le faux /dev/uinput a reçu : un lot par ligne, [[type, code, valeur], …].
    pointeur: () => {
      try { return readFileSync(path.join(dossier, "pointeur.jsonl"), "utf8").split("\n").filter(Boolean).map(l => JSON.parse(l)); }
      catch { return []; }
    },
    // Ce qui est « à l'écran » du HUB : menu, web, bureau.
    contexte: c => writeFileSync(path.join(dossier, "contexte"), c),
    souris: oui => {
      mkdirSync(path.join(dossier, "config"), { recursive: true });
      writeFileSync(path.join(dossier, "config/reglages.json"), JSON.stringify({ systeme: { telecommandeSouris: oui } }));
    },
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
  // HUB_NAVIGATEUR=chromium : le Chromium de Playwright, là où Chrome n'est pas installé.
  navigateur = await chromium.launch(process.env.HUB_NAVIGATEUR === "chromium" ? {} : { channel: "chrome" });
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
  // 390×844 (iPhone 13 à 16) : l'audit du 17/09/2026 y trouvait Retour et Accueil sous le
  // pli, l'encart ouvert, et « Téléphone relié » posé sur le pavé tactile.
  const page = await ouvrir(navigateur, `http://127.0.0.1:${banc.ports.http}/`, { ...IPHONE, viewport: { width: 390, height: 844 } });
  await page.locator("#code").focus();
  // L'anneau apparaît par une transition de 0,2 s : on attend son état final.
  const anneauVisible = a => a.contour !== "none" || (a.ombre !== "none" && a.alpha >= .5);
  let anneau;
  try {
    await attendre(async () => anneauVisible(anneau = await page.evaluate(() => {
      const cs = getComputedStyle(document.getElementById("code"));
      const alpha = cs.boxShadow.match(/rgba?\(([^)]+)\)/)?.[1].split(",")[3] ?? "1";
      return { contour: cs.outlineStyle, ombre: cs.boxShadow, alpha: parseFloat(alpha) };
    })), 1500);
  } catch { assert.fail(`focus du code invisible : ${JSON.stringify(anneau)}`); }
  await appairer(page, banc);
  await page.locator("#encart-ios").waitFor({ state: "visible" });
  const texte = await page.locator("#encart-ios").innerText();
  assert.match(texte, /Sur l'écran d'accueil/);
  assert.match(texte, /retapez un code/);

  const g = await page.evaluate(() => {
    const r = s => document.querySelector(s).getBoundingClientRect();
    const m = document.getElementById("message");
    return {
      hauteur: innerHeight, retour: r('[data-cmd="retour"]').bottom, accueil: r('[data-cmd="accueil"]').bottom,
      pave: r("#pave-tactile"), message: m.classList.contains("visible") ? r("#message") : null,
      cibles: [...document.querySelectorAll('[data-action="disposition"], [data-action="encart-fermer"]')]
        .map(e => { const b = e.getBoundingClientRect(); return [e.dataset.action, Math.round(b.width), Math.round(b.height)]; }),
    };
  });
  assert.ok(g.retour <= g.hauteur && g.accueil <= g.hauteur, `Retour/Accueil sous le pli : ${g.retour} > ${g.hauteur}`);
  assert.ok(g.pave.height >= 200, `pavé écrasé : ${g.pave.height} px`);
  assert.ok(g.message, "« Téléphone relié » attendu à l'écran");
  assert.ok(g.message.bottom <= g.pave.top || g.message.top >= g.pave.bottom, "le message recouvre le pavé");
  for (const [nom, l, h] of g.cibles) assert.ok(l >= 44 && h >= 44, `${nom} : ${l}×${h} < 44 px`);

  // Au clavier (Tab), le bouton atteint porte un contour visible.
  await page.focus('[data-cmd="retour"]');
  await page.keyboard.press("Tab");
  const contour = await page.evaluate(() => { const cs = getComputedStyle(document.activeElement); return [cs.outlineStyle, parseFloat(cs.outlineWidth)]; });
  assert.ok(contour[0] !== "none" && contour[1] >= 2, `contour de focus : ${contour}`);
  assert.deepEqual(page.erreurs, []);
  // iPhone SE (375×667), encart toujours ouvert : Retour et Accueil encore dans l'écran.
  await page.setViewportSize({ width: 375, height: 667 });
  await page.waitForTimeout(300);
  const se = await page.evaluate(() => ({ h: innerHeight, retour: document.querySelector('[data-cmd="retour"]').getBoundingClientRect().bottom, encart: !!document.getElementById("encart").getClientRects().length }));
  assert.ok(se.encart && se.retour <= se.h, `375×667 : Retour à ${se.retour} pour ${se.h}`);
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

// ── Rester relié pendant un mode ────────────────────────────────────────────
// Entrer dans un mode peut couper la télécommande quelques secondes (le mode Bureau
// change de session, une mise à jour relance le service). Le jeton reste valable :
// la page doit revenir toute seule, sans jamais renvoyer à l'écran d'appairage — un
// code retapé, c'était un téléphone de plus dans la liste du HUB.
test("coupure réseau : la page annonce la reconnexion, revient seule, sans redemander de code", async () => {
  const page = await remoteAppairee();
  const pastille = page.locator("#contexte");
  await page.context().setOffline(true);
  const avant = banc.menu().length;
  await page.locator("#rangee-retour [data-cmd=retour]").tap();
  await attendre(async () => (await pastille.innerText()).includes("Reconnexion"));
  assert.equal(await page.locator("#telecommande").isVisible(), true,
    "une coupure ne délie pas le téléphone");
  assert.equal(await page.locator("#appairage").isVisible(), false);
  await page.context().setOffline(false);
  // Sans rien toucher : la relance suivante retrouve le HUB (1 s, puis 2, 4, 8, 15).
  await attendre(async () => !(await pastille.innerText()).includes("Reconnexion"), 12000);
  const apres = banc.menu().length;
  await page.locator("#rangee-retour [data-cmd=retour]").tap();
  assert.deepEqual(await recus(apres, 1), ["retour"], "la télécommande repilote le HUB");
  assert.equal(avant, apres, "rien n'est parti pendant la coupure");
  assert.deepEqual(page.erreurs, []);
  await page.context().close();
});

test("un seul 401 ne délie pas le téléphone, deux d'affilée oui", async () => {
  const page = await remoteAppairee();
  let refus = 1;
  await page.route("**/api/etat", route => refus-- > 0
    ? route.fulfill({ status: 401, contentType: "application/json", body: '{"erreur":"jeton"}' })
    : route.continue());
  // lireEtat est la fonction que la page appelle toutes les six secondes : on la
  // déclenche pour ne pas faire attendre le tour de sondage.
  await page.evaluate(() => lireEtat(true));
  await attendre(async () => (await page.locator("#contexte").innerText()).includes("Reconnexion"));
  await attendre(async () => !(await page.locator("#contexte").innerText()).includes("Reconnexion"), 12000);
  assert.equal(await page.locator("#telecommande").isVisible(), true,
    "un refus isolé (service qui redémarre) ne renvoie pas à l'appairage");

  // Révoqué pour de bon : la page revient à l'appairage au refus suivant.
  await page.route("**/api/etat", route => route.fulfill(
    { status: 401, contentType: "application/json", body: '{"erreur":"jeton"}' }));
  await page.locator("#appairage").waitFor({ state: "visible", timeout: 15000 });
  assert.deepEqual(page.erreurs, []);
  await page.context().close();
});

test("ré-appairer le même téléphone ne l'ajoute pas une seconde fois au HUB", async () => {
  const b = await lancerBanc();
  const url = `http://127.0.0.1:${b.ports.http}/`;
  const page = await ouvrir(navigateur, url);
  await appairer(page, b);
  const premier = b.etat().listeTelephones;
  assert.equal(premier.length, 1);

  // Le jeton disparaît (icône d'écran d'accueil sur iPhone, stockage nettoyé) mais
  // l'identifiant d'appareil, lui, reste : on retape le code de la TV.
  const appareil = await page.evaluate(() => {
    localStorage.removeItem("hub-telecommande-jeton");
    return localStorage.getItem("hub-telecommande-appareil");
  });
  assert.match(appareil, /^[0-9a-f]{32}$/);
  await page.reload();
  await page.locator("#appairage").waitFor({ state: "visible" });
  await appairer(page, b);

  const apres = b.etat().listeTelephones;
  assert.equal(apres.length, 1, "le même téléphone compte encore pour un");
  assert.equal(apres[0].id, premier[0].id, "même entrée, renouvelée");
  assert.equal(apres[0].cree, premier[0].cree, "la date d'appairage d'origine est gardée");
  assert.deepEqual(page.erreurs, []);
  await page.context().close();
  b.arreter();
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
    // L'empreinte ne vient que de la TV : la page, servie en http comme le certificat,
    // ne la montre pas (elle serait remplacée avec lui).
    assert.equal(await page.locator("#empreinte").count(), 0);
    assert.doesNotMatch(await page.locator("#securite").innerText(), /[0-9A-F]{2}(:[0-9A-F]{2}){7}/);
    assert.match(b.etat().empreinteRacineCourte, /^[0-9A-F]{4}( [0-9A-F]{4}){3}$/);
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

// ── Souris et clavier : le pavé change de rôle avec ce qui est à l'écran ────
// Le service est en https réel (la souris est refusée en http). Le certificat n'est pas
// installé dans ce navigateur d'essai : `ignoreHTTPSErrors` le fait accepter, WebSocket
// compris. La chaîne de confiance, elle, a ses propres tests plus haut.
const EV_KEY = 1, EV_REL = 2, REL_X = 0, REL_Y = 1, REL_WHEEL_FIN = 11, BTN_GAUCHE = 0x110, BTN_DROIT = 0x111;
const KEY_ESC = 1, KEY_2 = 3, KEY_Q = 16, KEY_ENTER = 28, KEY_BACKSPACE = 14;

async function bancSouris() {
  const b = await lancerBanc(["--https"]);
  b.souris(true);
  const page = await ouvrir(navigateur, `https://127.0.0.1:${b.ports.https}/`, PIXEL, { ignoreHTTPSErrors: true });
  await appairer(page, b);
  return { b, page };
}
const modeAffiche = (page, attendu) => attendre(async () => {
  await page.evaluate(() => lireEtat());
  return (await page.locator("#mode-pave").innerText()) === attendu;
}, 8000);
const lots = (b, depuis) => b.pointeur().slice(depuis);
const evenements = (b, depuis, type, code) => lots(b, depuis).flat().filter(e => e[0] === type && e[1] === code);

test("souris : « Navigation » dans le menu, « Souris » sur le bureau, et retour — la page bascule seule et le dit", async () => {
  const { b, page } = await bancSouris();
  try {
    // Dans le menu : rien ne change. Des flèches, par le socket, et pas de témoin.
    await modeAffiche(page, "Navigation");
    assert.equal(await page.locator("#temoin").isVisible(), false);
    const d = await doigts(page);
    await d.glisser(90, 4);
    await attendre(() => b.menu().includes("droite"));
    assert.deepEqual(b.pointeur(), [], "dans le menu, le clavier virtuel n'est même pas créé");

    // Le bureau s'ouvre : le même pavé devient une souris, et la page le dit.
    b.contexte("bureau");
    await modeAffiche(page, "Souris");
    assert.equal(await page.locator("#temoin").isVisible(), true, "témoin visible tant que la souris est active");
    assert.match(await page.locator("#temoin").innerText(), /Souris et clavier actifs/);
    assert.equal(await page.locator("#contexte").innerText(), "Bureau");
    assert.equal(await page.locator("#rangee-souris").isVisible(), true);
    const flechesAvant = b.menu().length;

    let depuis = b.pointeur().length;
    const d2 = await doigts(page);
    await d2.glisser(90, 0);
    await attendre(() => evenements(b, depuis, EV_REL, REL_X).length > 0);
    await d2.pause(150);
    const dx = evenements(b, depuis, EV_REL, REL_X).reduce((s, e) => s + e[2], 0);
    assert.ok(dx >= 90, `le pointeur suit le doigt, accéléré : ${dx} points pour 90`);
    assert.equal(evenements(b, depuis, EV_KEY, BTN_GAUCHE).length, 0, "un glissement n'est pas un clic");
    for (const lot of lots(b, depuis)) assert.deepEqual(lot.at(-1), [0, 0, 0], "chaque lot finit par EV_SYN");

    depuis = b.pointeur().length;
    await d2.toucher();
    await attendre(() => evenements(b, depuis, EV_KEY, BTN_GAUCHE).length === 2);
    depuis = b.pointeur().length;
    await d2.appuiLong();
    await attendre(() => evenements(b, depuis, EV_KEY, BTN_DROIT).length === 2);
    await d2.pause(200);
    assert.equal(evenements(b, depuis, EV_KEY, BTN_GAUCHE).length, 0, "l'appui long ne clique pas à gauche en se levant");

    // Deux doigts qui descendent : défilement fin, dans le sens des doigts.
    depuis = b.pointeur().length;
    await d2.envoyer("touchStart", [[d2.cx - 40, d2.cy]]);
    await d2.envoyer("touchStart", [[d2.cx - 40, d2.cy], [d2.cx + 40, d2.cy]]);
    for (let i = 1; i <= 6; i++) { await d2.envoyer("touchMove", [[d2.cx - 40, d2.cy + 10 * i], [d2.cx + 40, d2.cy + 10 * i]]); await d2.pause(16); }
    await d2.envoyer("touchEnd", []);
    await attendre(() => evenements(b, depuis, EV_REL, REL_WHEEL_FIN).length > 0);
    await d2.pause(150);
    const molette = evenements(b, depuis, EV_REL, REL_WHEEL_FIN).reduce((s, e) => s + e[2], 0);
    assert.ok(molette > 100 && molette <= 260, `60 points de doigts ≈ 240 unités de molette : ${molette}`);
    assert.equal(evenements(b, depuis, EV_REL, REL_X).length + evenements(b, depuis, EV_REL, REL_Y).length, 0,
      "deux doigts défilent, ils ne déplacent pas le pointeur");
    assert.equal(evenements(b, depuis, EV_KEY, BTN_GAUCHE).length, 0);

    // Texte : « a » part comme KEY_Q (clavier français du banc), « é » comme KEY_2.
    depuis = b.pointeur().length;
    await page.locator("#texte").fill("aé");
    await page.locator("#form-texte button").tap();
    await attendre(() => evenements(b, depuis, EV_KEY, KEY_2).length === 2);
    assert.equal(evenements(b, depuis, EV_KEY, KEY_Q).length, 2);
    await attendre(async () => /Texte tapé/.test(await page.locator("#message").innerText()));

    // Retour = Échap, et les touches propres au mode souris.
    depuis = b.pointeur().length;
    await page.locator('#rangee-retour [data-cmd="retour"]').tap();
    await page.locator('[data-touche="effacer"]').tap();
    await attendre(() => evenements(b, depuis, EV_KEY, KEY_BACKSPACE).length === 2);
    assert.equal(evenements(b, depuis, EV_KEY, KEY_ESC).length, 2);
    assert.equal(b.menu().length, flechesAvant, "rien n'est parti au menu pendant le mode souris");

    // Retour au menu : la session tombe côté HUB, la page revient seule à « Navigation ».
    b.contexte("menu");
    await modeAffiche(page, "Navigation");
    assert.equal(await page.locator("#temoin").isVisible(), false);
    depuis = b.pointeur().length;
    const d3 = await doigts(page);
    const avantMenu = b.menu().length;
    await d3.glisser(0, 90);
    await attendre(() => b.menu().slice(avantMenu).includes("bas"));
    assert.deepEqual(lots(b, depuis), []);
    assert.deepEqual(page.erreurs, [], "aucune violation CSP (wss: compris)");
  } finally { await page.context().close(); b.arreter(); }
});

test("souris : un geste vif va plus loin qu'un geste lent de même longueur (accélération douce, bornée)", async () => {
  const { b, page } = await bancSouris();
  try {
    b.contexte("web");
    await modeAffiche(page, "Souris");
    assert.equal(await page.locator("#contexte").innerText(), "Web");
    const d = await doigts(page);
    // 120 points de doigt dans les deux cas : douze petits pas espacés, ou trois grands d'affilée.
    const parcourir = async (pas, pauseMs) => {
      const depuis = b.pointeur().length;
      await d.envoyer("touchStart", [[d.cx - 60, d.cy]]);
      for (let i = 1; i <= 120 / pas; i++) { await d.envoyer("touchMove", [[d.cx - 60 + pas * i, d.cy]]); await d.pause(pauseMs); }
      await d.envoyer("touchEnd", []);
      await d.pause(200);
      return evenements(b, depuis, EV_REL, REL_X).reduce((s, e) => s + e[2], 0);
    };
    const lent = await parcourir(10, 100), vif = await parcourir(40, 0);
    assert.ok(lent >= 120 && lent <= 200, `120 points lents : entre ×1 et ×1,6 : ${lent}`);
    assert.ok(vif >= lent * 1.5, `vif ${vif} contre lent ${lent}`);
    assert.ok(vif <= 120 * 4 + 12, `borné à ×4 : ${vif}`);
  } finally { await page.context().close(); b.arreter(); }
});

test("souris indisponible : la page reste en « Navigation » et dit pourquoi, avec le remède", async () => {
  const { b, page } = await bancSouris();
  try {
    b.souris(false);
    b.contexte("bureau");
    await attendre(async () => { await page.evaluate(() => lireEtat()); return page.locator("#pourquoi").isVisible(); }, 8000);
    assert.match(await page.locator("#pourquoi").innerText(), /allumez-les sur la TV/);
    assert.equal(await page.locator("#mode-pave").innerText(), "Navigation");
    assert.equal(await page.locator("#temoin").isVisible(), false);
    // Une flèche dit la même chose, au lieu du vieux « seul Accueil agit ».
    await page.locator('[data-action="disposition"][data-valeur="boutons"]').tap();
    await page.locator('#zone-croix [data-cmd="ok"]').tap();
    await attendre(async () => /allumez-les sur la TV/.test(await page.locator("#message").innerText()));
    assert.deepEqual(b.pointeur(), []);

    // Écran verrouillé : autre raison, autre phrase. Et dans le menu, plus de reproche.
    b.souris(true);
    writeFileSync(path.join(b.dossier, "verrou"), "");
    await attendre(async () => { await page.evaluate(() => lireEtat()); return /verrouillé/.test(await page.locator("#pourquoi").innerText()); }, 8000);
    b.contexte("menu");
    await attendre(async () => { await page.evaluate(() => lireEtat()); return !(await page.locator("#pourquoi").isVisible()); }, 8000);

    // La même télécommande en http : jamais de souris, et la page envoie vers la version sécurisée.
    const http = await ouvrir(navigateur, `http://127.0.0.1:${b.ports.http}/`);
    await appairer(http, b);
    rmSync(path.join(b.dossier, "verrou"));
    b.contexte("bureau");
    await attendre(async () => { await http.evaluate(() => lireEtat()); return http.locator("#pourquoi").isVisible(); }, 8000);
    assert.match(await http.locator("#pourquoi").innerText(), /connexion sécurisée/);
    assert.equal(await http.locator("#mode-pave").innerText(), "Navigation");
    assert.deepEqual(b.pointeur(), []);
    assert.deepEqual([...page.erreurs, ...http.erreurs], []);
    await http.context().close();
  } finally { await page.context().close(); b.arreter(); }
});
