"use strict";
// Menu du HUB — cadre photo du mode ambiant.
//
// Quand le HUB passe en mode ambiant (veille, ou réveil programmé le matin), il peut
// devenir un cadre photo : diaporama des photos d'Images/HUB (ou d'un de ses
// sous-dossiers, un album), horloge et météo discrètes dans un coin. L'option
// « souvenirs » met en tête les photos prises le même jour les années précédentes :
// hub-menu lit leur date EXIF (lecture maison, sans Pillow) et répond à
// → { type: "cadre", album, souvenirs } par { type: "cadre", albums, photos, souvenirs }.
//
// Réglages par profil (Réglages → Veille) : p.cadre = { actif, album, duree, souvenirs }.
// Animations réduites : les photos changent sans fondu ni travelling.

Object.assign(TEXTES.fr, {
  "cadre": "Cadre photo",
  "cadre.detail": "En mode ambiant, les photos d'Images/HUB défilent sous l'horloge.",
  "cadre.album": "Album",
  "cadre.album.detail": "Un album est un sous-dossier d'Images/HUB.",
  "cadre.tous": "Toutes les photos",
  "cadre.duree": "Durée par photo",
  "cadre.souvenirs": "Souvenirs",
  "cadre.souvenirs.detail": "D'abord les photos prises ce jour-là, les années précédentes.",
  "cadre.il.y.a": "Il y a {n} ans",
  "cadre.il.y.a.un": "Il y a un an",
  "cadre.aucune": "Aucune photo dans Images/HUB : le mode ambiant garde son fond.",
});
Object.assign(TEXTES.en, {
  "cadre": "Photo frame",
  "cadre.detail": "In ambient mode, photos from Pictures/HUB play behind the clock.",
  "cadre.album": "Album",
  "cadre.album.detail": "An album is a subfolder of Pictures/HUB.",
  "cadre.tous": "All photos",
  "cadre.duree": "Time per photo",
  "cadre.souvenirs": "Memories",
  "cadre.souvenirs.detail": "Photos taken on this day in previous years come first.",
  "cadre.il.y.a": "{n} years ago",
  "cadre.il.y.a.un": "One year ago",
  "cadre.aucune": "No photos in Pictures/HUB: ambient mode keeps its background.",
});

const DEFAUT_CADRE = { actif: false, album: null, duree: 20, souvenirs: false };
const cadreEtat = { albums: null, liste: [], index: 0, minuterie: null, actif: false, recu: 0 };

function reglageCadre(p = profil()) { return { ...DEFAUT_CADRE, ...(p.cadre || {}) }; }
function animationsReduites() { return profil().animations === "reduites" || matchMedia("(prefers-reduced-motion: reduce)").matches; }

function calqueCadre() {
  let cadre = $("cadre");
  if (!cadre) {
    cadre = el("div", { id: "cadre", hidden: true },
      el("div", { class: "cadre-photo" }), el("div", { class: "cadre-photo" }),
      el("div", { class: "cadre-souvenir", id: "cadre-souvenir", hidden: true }));
    $("ambiant").prepend(cadre);
  }
  return cadre;
}

function melanger(liste) {
  const copie = [...liste];
  for (let i = copie.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copie[i], copie[j]] = [copie[j], copie[i]];
  }
  return copie;
}

function demanderCadre() {
  const r = reglageCadre();
  if (PONT) return envoyer({ type: "cadre", album: r.album, souvenirs: !!r.souvenirs });
  // Aperçu dans un navigateur : les photos passées au démarrage, sans EXIF.
  recevoirCadre({ albums: [], photos: INITIAL.photos || [], souvenirs: [] });
}

function recevoirCadre(message) {
  cadreEtat.albums = Array.isArray(message.albums) ? message.albums : [];
  cadreEtat.recu = Date.now();
  const souvenirs = Array.isArray(message.souvenirs) ? message.souvenirs : [];
  const dejaVues = new Set(souvenirs.map(s => s.uri));
  const photos = (Array.isArray(message.photos) ? message.photos : []).filter(u => !dejaVues.has(u));
  cadreEtat.liste = [...souvenirs.map(s => ({ uri: s.uri, annee: s.annee })), ...melanger(photos).map(uri => ({ uri }))];
  cadreEtat.index = 0;
  if (pile.at(-1) === "reglages" && sectionCourante === "veille") rendreSection();
  if (cadreEtat.actif) demarrerDiaporama();
}

function montrerPhoto() {
  const cadre = calqueCadre();
  const element = cadreEtat.liste[cadreEtat.index % cadreEtat.liste.length];
  cadreEtat.index += 1;
  // Charger avant de montrer : un fondu vers une image pas encore décodée clignote.
  const image = new Image();
  image.onload = () => {
    if (!cadreEtat.actif) return;
    const [a, b] = cadre.querySelectorAll(".cadre-photo");
    const visible = a.classList.contains("visible") ? a : b;
    const suivante = visible === a ? b : a;
    suivante.style.backgroundImage = `url("${encodeURI(decodeURI(element.uri))}")`;
    // Relancer le lent travelling sur la nouvelle photo.
    suivante.classList.remove("travelling");
    void suivante.offsetWidth;
    if (!animationsReduites()) suivante.classList.add("travelling");
    suivante.classList.add("visible");
    visible.classList.remove("visible");
    const legende = $("cadre-souvenir");
    const ans = element.annee ? new Date().getFullYear() - element.annee : 0;
    legende.hidden = !ans;
    if (ans) legende.textContent = ans === 1 ? t("cadre.il.y.a.un") : t("cadre.il.y.a", { n: ans });
  };
  image.onerror = () => { if (cadreEtat.liste.length > 1 && cadreEtat.actif) setTimeout(montrerPhoto, 0); };
  image.src = element.uri;
}

function demarrerDiaporama() {
  clearInterval(cadreEtat.minuterie);
  const cadre = calqueCadre();
  const avecPhotos = cadreEtat.liste.length > 0;
  cadre.hidden = !avecPhotos;
  cadre.classList.toggle("reduit", animationsReduites());
  document.body.classList.toggle("cadre-actif", avecPhotos);
  if (!avecPhotos) return;
  montrerPhoto();
  if (cadreEtat.liste.length > 1) cadreEtat.minuterie = setInterval(montrerPhoto, borne(Number(reglageCadre().duree) || 20, 5, 3600) * 1000);
}

function arreterDiaporama() {
  clearInterval(cadreEtat.minuterie);
  cadreEtat.actif = false;
  document.body.classList.remove("cadre-actif");
  const cadre = $("cadre");
  if (cadre) {
    cadre.hidden = true;
    cadre.querySelectorAll(".cadre-photo").forEach(d => d.classList.remove("visible", "travelling"));
  }
}

function surAmbiant(entre) {
  if (!entre || !reglageCadre().actif) return arreterDiaporama();
  cadreEtat.actif = true;
  // Relire le dossier au plus toutes les dix minutes : une photo envoyée depuis le
  // téléphone apparaît au prochain passage, sans rescanner à chaque veille.
  if (!cadreEtat.recu || Date.now() - cadreEtat.recu > 10 * 60000) demanderCadre();
  else demarrerDiaporama();
}

function contenuCadre(zone) {
  const p = profil();
  const r = reglageCadre(p);
  const changer = champ => v => {
    p.cadre = { ...reglageCadre(p), [champ]: v === "true" ? true : v === "false" ? false : v };
    if (champ === "album" || champ === "souvenirs") cadreEtat.recu = 0;
  };
  zone.append(el("div", { class: "sous-titre" }, t("cadre")),
    rangee(t("cadre"), t("cadre.detail"), options("cadre", [[true, t("oui")], [false, t("non")]], r.actif, changer("actif"))));
  if (!r.actif) return;
  if (cadreEtat.albums === null) demanderCadre();
  const albums = cadreEtat.albums || [];
  if (cadreEtat.recu && !cadreEtat.liste.length && !albums.length) zone.append(el("div", { class: "aide" }, t("cadre.aucune")));
  zone.append(
    rangee(t("cadre.album"), t("cadre.album.detail"),
      options("cadre-album", [[null, t("cadre.tous")], ...albums.map(a => [a, a])], r.album, changer("album")), true),
    rangee(t("cadre.duree"), null, options("cadre-duree", [[10, "10 s"], [20, "20 s"], [60, "1 min"], [300, "5 min"]], r.duree, v => changer("duree")(Number(v)))),
    rangee(t("cadre.souvenirs"), t("cadre.souvenirs.detail"), options("cadre-souvenirs", [[true, t("oui")], [false, t("non")]], r.souvenirs, changer("souvenirs"))));
}

extensions.ambiant.push(surAmbiant);
extensions.contenus.veille = contenuCadre;
extensions.messages.cadre = recevoirCadre;
// Changer de profil ou d'album pendant l'ambiant (voix, téléphone) : repartir de zéro.
extensions.apparence.push(() => { if (cadreEtat.actif && !reglageCadre().actif) arreterDiaporama(); });
