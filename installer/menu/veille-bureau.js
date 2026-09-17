"use strict";
// Menu du HUB — le mode ambiant seul, par-dessus le bureau Ubuntu.
//
// Sur le bureau, le menu est fermé : c'est hub-veille-bureau qui, après l'inactivité
// réglée (Réglages → Mode ambiant), lance « hub-menu --ambiant ». La page s'ouvre alors
// avec INITIAL.ambiantSeul : directement l'horloge, la météo et le cadre photo, jamais
// l'accueil. Le premier geste referme la fenêtre et rend le bureau tel qu'il était.
//
// Qui ferme quoi. Clavier et souris n'arrivent jamais ici : hub-menu les arrête dans GTK
// avant WebKit, pour qu'une touche de réveil ne soit pas lue comme un raccourci (« 3 »
// lancerait le bureau, Entrée la carte sélectionnée). Restent la manette (API Gamepad
// de la page) et tout ce qui appelle reveiller() : sortir du mode ambiant envoie
// { type: "ambiant-fin" }, et hub-menu se ferme. Python refuse de toute façon les
// choix de mode dans cette fenêtre ; le refus ci-dessous évite seulement une animation
// de lancement pour rien.

if (INITIAL.ambiantSeul) {
  document.documentElement.classList.add("ambiant-seul");
  extensions.avantLancer.push(() => false);
  extensions.ambiant.push(actif => { if (!actif) envoyer({ type: "ambiant-fin" }); });
  entrerAmbiant();
}
