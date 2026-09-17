"use strict";
// Compteur d'images du menu, pour mesurer la fluidité sur la TV elle-même plutôt que de
// la juger à l'œil (installer/menu/README.md, « Mesurer la fluidité »).
//
// Éteint par défaut. S'allume avec HUB_INITIAL.fps (hub-menu le passe quand HUB_FPS=1
// ou quand $XDG_RUNTIME_DIR/hub/mesurer-fluidite existe) ou avec ?fps dans l'adresse
// (?fps=2 : fenêtre de 2 s au lieu de 5). Toutes les N secondes : images par seconde
// moyennes, la pire seconde, et les images longues (plus de 50 ms, un saut visible).
// Le relevé part aussi vers hub-menu, qui l'écrit dans le journal : on mesure par SSH
// sans lire l'écran de loin.
//
// Ce qu'il mesure : la cadence de requestAnimationFrame dans la page, c'est-à-dire ce
// que WebKit arrive à produire. Pas ce que l'écran affiche : WEBKIT_SHOW_FPS et
// intel_gpu_top complètent.
(() => {
  const demande = parametres.has("fps") ? Number(parametres.get("fps")) || true : INITIAL.fps;
  if (!demande) return;
  const fenetre = (typeof demande === "number" && demande > 0 ? Math.min(demande, 60) : 5) * 1000;
  const IMAGE_LONGUE = 50;

  const panneau = el("div", { class: "compteur-fps", id: "compteur-fps", role: "status" }, "… i/s");
  document.body.append(panneau);

  function releve(intervalles, duree) {
    // La pire seconde pleine : une moyenne sur 5 s cache un accroc d'une demi-seconde.
    const secondes = [];
    let cumul = 0;
    for (const d of intervalles) {
      cumul += d;
      const i = Math.floor(cumul / 1000);
      secondes[i] = (secondes[i] || 0) + 1;
    }
    const pleines = secondes.length > 1 ? secondes.slice(0, Math.floor(cumul / 1000)) : secondes;
    const longues = intervalles.filter(d => d > IMAGE_LONGUE);
    return {
      type: "fps",
      ecran: document.body.classList.contains("ambiant") ? "ambiant" : pile.at(-1),
      fenetre: Math.round(duree / 100) / 10,
      moyenne: Math.round(intervalles.length / duree * 10000) / 10,
      min: Math.min(...pleines.map(n => n || 0)),
      longues: longues.length,
      pire: Math.round(Math.max(0, ...intervalles)),
    };
  }

  let debut = null, precedent = null, intervalles = [];
  function image(t) {
    if (precedent !== null) intervalles.push(t - precedent);
    precedent = t;
    debut ??= t;
    if (t - debut >= fenetre && intervalles.length) {
      const r = releve(intervalles, t - debut);
      window.hubFps = r;
      panneau.textContent = `${r.moyenne} i/s · pire seconde ${r.min} · ${r.longues} > ${IMAGE_LONGUE} ms (pire ${r.pire} ms) · ${r.ecran}`;
      if (PONT) envoyer(r);
      debut = t;
      intervalles = [];
    }
    requestAnimationFrame(image);
  }
  requestAnimationFrame(image);
})();
