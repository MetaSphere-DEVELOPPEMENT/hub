"use strict";
// Menu du HUB — temps d'écran par profil.
//
// Le décompte n'est PAS fait ici : le menu est fermé pendant les modes. Il est tenu par
// hub-temps-ecran autour de chaque mode ; la page reçoit l'état (INITIAL.tempsEcran,
// puis { type: "temps-ecran", etat }) et n'en fait que l'affichage : jauge sur la puce
// du profil, historique de sept jours, refus de lancer un mode quand le temps est
// écoulé, et prolongation par code parent (→ { type: "temps-prolonger", profil, minutes }).
//
// Qui règle quoi, dans la logique des profils existante : les limites se règlent
// seulement depuis un profil SANS restriction, PROTÉGÉ par un code et déverrouillé, et
// jamais sur soi-même. Un profil limité devient « restreint » : il ne peut plus modifier
// les autres profils ni se retirer sa limite.
//
// Le calcul du temps restant recopie celui de hub-temps-ecran (restant()) : c'est lui qui
// coupe, la page ne fait qu'annoncer. Les deux sont testés sur les mêmes cas.

Object.assign(TEXTES.fr, {
  "section.temps": "Temps d'écran",
  "temps.aujourdhui": "{d} aujourd'hui",
  "temps.restant": "reste {d}",
  "temps.illimite": "Sans limite",
  "temps.ecoule": "Temps d'écran terminé pour aujourd'hui",
  "temps.ecoule.detail": "Un parent peut accorder un peu plus de temps avec son code.",
  "temps.plus": "Plus de temps",
  "temps.parent": "Code d'un parent",
  "temps.accorde": "{m} min accordées à {nom}",
  "temps.sans.parent": "Aucun profil parent protégé par un code : impossible d'accorder du temps.",
  "temps.modifier": "Régler",
  "temps.reserve": "Les limites se règlent depuis un profil sans restriction, protégé par un code et déverrouillé.",
  "temps.semaine": "En semaine",
  "temps.weekend": "Le week-end",
  "temps.debut": "Pas avant",
  "temps.fin": "Pas après",
  "temps.aucune": "Aucune",
  "temps.regles.de": "Limites de {nom}",
  "temps.regles.detail": "Compté dans TV, Jeux, streaming et bureau, pas dans ce menu. Prévenu 5 minutes avant la fin, puis retour au menu.",
  "temps.historique": "Sept derniers jours",
});
Object.assign(TEXTES.en, {
  "section.temps": "Screen time",
  "temps.aujourdhui": "{d} today",
  "temps.restant": "{d} left",
  "temps.illimite": "No limit",
  "temps.ecoule": "Screen time is up for today",
  "temps.ecoule.detail": "A parent can grant a little more time with their PIN.",
  "temps.plus": "More time",
  "temps.parent": "A parent's PIN",
  "temps.accorde": "{m} min granted to {nom}",
  "temps.sans.parent": "No parent profile with a PIN: extra time can't be granted.",
  "temps.modifier": "Set",
  "temps.reserve": "Limits are set from an unrestricted profile protected by a PIN and unlocked.",
  "temps.semaine": "Weekdays",
  "temps.weekend": "Weekends",
  "temps.debut": "Not before",
  "temps.fin": "Not after",
  "temps.aucune": "None",
  "temps.regles.de": "{nom}'s limits",
  "temps.regles.detail": "Counted in TV, Games, streaming and desktop, not in this menu. Warned 5 minutes before the end, then back to the menu.",
  "temps.historique": "Last seven days",
});

let tempsEtat = INITIAL.tempsEcran || { profils: {} };
let tempsProfilRegle = null;

function cleJour(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function minutesHeure(texte) {
  const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(texte || "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}
function reglesTemps(p) { return p?.tempsEcran && typeof p.tempsEcran === "object" ? p.tempsEcran : null; }
function tempsLimite(p) {
  const r = reglesTemps(p);
  return !!r && ((Array.isArray(r.limites) && r.limites.some(v => typeof v === "number")) || minutesHeure(r.debut) !== null || minutesHeure(r.fin) !== null);
}
// Le lundi d'abord, comme datetime.weekday() côté Python.
function indexJour(d) { return (d.getDay() + 6) % 7; }
function jourTemps(id, d = new Date()) { return tempsEtat.profils?.[id]?.[cleJour(d)] || {}; }

function limiteDuJour(r, d) {
  const v = Array.isArray(r?.limites) && r.limites.length === 7 ? r.limites[indexJour(d)] : null;
  return typeof v === "number" && v >= 0 ? v : null;
}

function tempsRestant(p, d = new Date()) {
  const r = reglesTemps(p);
  if (!r) return null;
  const jour = jourTemps(p.id, d);
  const maintenant = d.getTime() / 1000;
  const bornes = [];
  const limite = limiteDuJour(r, d);
  if (limite !== null) bornes.push(limite * 60 + (jour.bonus || 0) - (jour.secondes || 0));
  const debut = minutesHeure(r.debut), fin = minutesHeure(r.fin);
  if (debut !== null || fin !== null) {
    const minuit = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
    const dans = (debut === null || maintenant >= minuit + debut * 60) && (fin === null || maintenant < minuit + fin * 60);
    let plage = !dans ? 0 : fin === null ? Infinity : minuit + fin * 60 - maintenant;
    plage = Math.max(plage, (jour.horsPlageJusqua || 0) - maintenant);
    if (plage !== Infinity) bornes.push(plage);
  }
  return bornes.length ? Math.max(0, Math.floor(Math.min(...bornes))) : null;
}

function dureeTexte(secondes) {
  const minutes = Math.round(secondes / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

// ── Jauge sur la puce du profil ───────────────────────────────────────────
function majJaugeTemps() {
  const puce = $("puce-profil");
  if (!puce) return;
  let jauge = $("jauge-temps");
  if (!jauge) {
    jauge = el("span", { class: "jauge-temps", id: "jauge-temps", hidden: true },
      el("span", { class: "barre" }, el("i")), el("span", { class: "reste", id: "jauge-temps-texte" }));
    puce.append(jauge);
  }
  const p = profil();
  const reste = tempsRestant(p);
  jauge.hidden = reste === null;
  if (reste === null) return;
  const limite = limiteDuJour(reglesTemps(p), new Date());
  const total = limite !== null ? limite * 60 + (jourTemps(p.id).bonus || 0) : 3 * 3600;
  jauge.querySelector("i").style.width = `${borne(reste / (total || 1) * 100, 0, 100)}%`;
  jauge.classList.toggle("bas", reste > 0 && reste <= 15 * 60);
  jauge.classList.toggle("epuise", reste === 0);
  $("jauge-temps-texte").textContent = reste === 0 ? "0 min" : dureeTexte(reste);
}

// ── Prolongation par code parent ──────────────────────────────────────────
// parentsAvecCode() vient de hub.js : le menu d'arrêt s'en sert aussi.
function accorderTemps(p, minutes) {
  const parents = parentsAvecCode();
  if (!parents.length) { son("erreur"); return annoncer(t("temps.sans.parent")); }
  const gardien = { id: "parents", nom: t("temps.parent"), couleur: "ambre" };
  demanderCode(gardien, () => {
    if (PONT) envoyer({ type: "temps-prolonger", profil: p.id, minutes });
    else {
      // Aperçu sans hub-menu : même effet, en mémoire.
      const d = new Date(), maintenant = d.getTime() / 1000;
      const jours = (tempsEtat.profils ||= {})[p.id] ||= {};
      const jour = jours[cleJour(d)] ||= { secondes: 0 };
      jour.bonus = (jour.bonus || 0) + minutes * 60;
      jour.horsPlageJusqua = Math.max(jour.horsPlageJusqua || 0, maintenant) + minutes * 60;
      recevoirTempsEcran({ etat: tempsEtat });
    }
    annoncer(t("temps.accorde", { m: minutes, nom: p.nom }));
    // Le code d'un parent ne déverrouille pas le profil « parents » fictif pour la suite.
    deverrouilles.delete("parents");
  }, { detail: t("temps.accorde", { m: minutes, nom: p.nom }) });
  demande.profils = parents.map(x => x.id);
}

function ouvrirPlusDeTemps(p) {
  let dialogue = $("temps-plus");
  if (!dialogue) {
    dialogue = el("div", { class: "calque voile", id: "temps-plus" },
      el("div", { class: "dialogue" },
        el("h2", { id: "temps-plus-titre" }),
        el("p", { id: "temps-plus-detail" }),
        el("div", { class: "choix", id: "temps-plus-choix" })));
    document.body.append(dialogue);
  }
  $("temps-plus-titre").textContent = tempsRestant(p) === 0 ? t("temps.ecoule") : t("temps.plus");
  $("temps-plus-detail").textContent = t("temps.ecoule.detail");
  const choix = $("temps-plus-choix");
  choix.innerHTML = "";
  choix.append(el("button", { class: "bouton", "data-nav": true, "data-cle": "temps-annuler", "data-action": "fermer" }, el("span", {}, t("annuler"))),
    ...[15, 30, 60].map(m => el("button", {
      class: "bouton", "data-nav": true, "data-cle": `temps-plus-${m}`,
      onclick: () => {
        // Sans parent, le dialogue reste ouvert : l'annonce explique pourquoi rien ne se passe.
        if (!parentsAvecCode().length) { son("erreur"); return annoncer(t("temps.sans.parent")); }
        fermerCalque();
        accorderTemps(p, m);
      },
    }, el("span", {}, `+ ${m} min`))));
  ouvrirCalque("temps-plus", false);
  definirFocus(choix.querySelector('[data-cle="temps-plus-15"]'), true);
}

function recevoirTempsEcran(message) {
  if (message.etat && typeof message.etat === "object") tempsEtat = message.etat;
  majJaugeTemps();
  if (pile.at(-1) === "reglages" && sectionCourante === "temps") rendreSection();
}

// ── Réglages → Temps d'écran ──────────────────────────────────────────────
function peutReglerTemps() {
  return !estRestreint() && !!profil().pin && deverrouilles.has(profil().id);
}

function historiqueTemps(x) {
  const aujourdhui = new Date();
  const jours = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(aujourdhui.getFullYear(), aujourdhui.getMonth(), aujourdhui.getDate() - i);
    jours.push({ d, secondes: tempsEtat.profils?.[x.id]?.[cleJour(d)]?.secondes || 0, limite: limiteDuJour(reglesTemps(x), d) });
  }
  const echelle = Math.max(3600, ...jours.map(j => Math.max(j.secondes, (j.limite || 0) * 60)));
  return el("div", { class: "histo-temps", "aria-label": t("temps.historique") }, jours.map(j =>
    el("div", { class: "jour-temps", title: dureeTexte(j.secondes) },
      el("div", { class: "colonne" },
        j.limite !== null && el("span", { class: "limite", style: `bottom:${j.limite * 60 / echelle * 100}%` }),
        el("i", { class: j.limite !== null && j.secondes > j.limite * 60 ? "depasse" : null, style: `height:${Math.max(j.secondes ? 3 : 0, j.secondes / echelle * 100)}%` })),
      el("div", { class: "etiquette-jour" }, j.d.toLocaleDateString(locale(), { weekday: "narrow" })))));
}

function contenuTemps(zone) {
  const regler = peutReglerTemps();
  for (const x of reglages.profils) {
    const reste = tempsRestant(x);
    const utilise = jourTemps(x.id).secondes || 0;
    const aide = [t("temps.aujourdhui", { d: dureeTexte(utilise) }), reste === null ? t("temps.illimite") : t("temps.restant", { d: dureeTexte(reste) })].join(" · ");
    zone.append(el("div", { class: "rangee large temps-profil" },
      el("div", {},
        el("div", { class: "titre", style: "display:flex;align-items:center;gap:.68rem" }, avatar(x), x.nom),
        el("div", { class: "aide" }, aide)),
      historiqueTemps(x),
      el("div", { class: "options" },
        tempsLimite(x) && el("button", { class: "option", "data-nav": true, "data-cle": `temps-plus-${x.id}`, onclick: () => ouvrirPlusDeTemps(x) }, t("temps.plus")),
        regler && x.id !== profil().id && el("button", {
          class: `option${tempsProfilRegle === x.id ? " choisie" : ""}`, "data-nav": true, "data-cle": `temps-regler-${x.id}`,
          onclick: () => { tempsProfilRegle = tempsProfilRegle === x.id ? null : x.id; rendreSection(); },
        }, t("temps.modifier")))));
  }
  if (!regler) {
    zone.append(el("div", { class: "aide" }, t("temps.reserve")));
    return;
  }
  const cible = reglages.profils.find(x => x.id === tempsProfilRegle && x.id !== profil().id);
  if (!cible) return;
  const r = cible.tempsEcran = { limites: [null, null, null, null, null, null, null], debut: null, fin: null, ...reglesTemps(cible) };
  if (!Array.isArray(r.limites) || r.limites.length !== 7) r.limites = [null, null, null, null, null, null, null];
  const duree = m => m === null ? t("temps.aucune") : dureeTexte(m * 60);
  const heure = h => h === null ? t("temps.aucune") : h;
  // Enregistré seulement s'il reste une limite : un profil sans limite n'a pas de tempsEcran.
  const nettoyer = () => { if (!tempsLimite(cible)) delete cible.tempsEcran; };
  zone.append(
    el("div", { class: "sous-titre" }, t("temps.regles.de", { nom: cible.nom })),
    el("div", { class: "aide" }, t("temps.regles.detail")),
    rangee(t("temps.semaine"), null, options("temps-semaine", [null, 60, 90, 120, 180].map(m => [m, duree(m)]), r.limites[0],
      v => { for (let i = 0; i < 5; i++) r.limites[i] = v; nettoyer(); })),
    rangee(t("temps.weekend"), null, options("temps-weekend", [null, 60, 120, 180, 240].map(m => [m, duree(m)]), r.limites[5],
      v => { r.limites[5] = r.limites[6] = v; nettoyer(); })),
    rangee(t("temps.debut"), null, options("temps-debut", [null, "07:00", "08:00", "09:00"].map(h => [h, heure(h)]), r.debut,
      v => { r.debut = v; nettoyer(); })),
    rangee(t("temps.fin"), null, options("temps-fin", [null, "20:00", "21:00", "22:00"].map(h => [h, heure(h)]), r.fin,
      v => { r.fin = v; nettoyer(); })));
  nettoyer();
}

// ── Accroches ─────────────────────────────────────────────────────────────
extensions.restrictions.push(p => tempsLimite(p));
extensions.apparence.push(majJaugeTemps);
extensions.avantLancer.push(mode => {
  if (!["tv", "gaming", "bureau", "web"].includes(mode) || tempsRestant(profil()) !== 0) return true;
  son("erreur");
  annoncer(t("temps.ecoule"));
  ouvrirPlusDeTemps(profil());
  return false;
});
extensions.sections.push({ id: "temps", apres: "profils", icone: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5M9.5 2.5h5"/>' });
extensions.contenus.temps = contenuTemps;
extensions.messages["temps-ecran"] = recevoirTempsEcran;
// La plage horaire se franchit sans que rien ne change dans la page : on réévalue.
setInterval(majJaugeTemps, 30000);
majJaugeTemps();
