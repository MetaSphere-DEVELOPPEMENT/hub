"""Banc de mesure de la commande vocale : les chiffres de voix/README.md, « Mesures ».

    HUB_BANC_DOSSIER=/mnt/ssd/hub-banc python3 banc.py LOGIQUE LANGUE MOT_EVEIL \
        ['{"option": valeur}'] [--voix=v1,v2] [--flux] [--detail]

LOGIQUE : dossier contenant un hub_voix_logique.py (installer/voix, ou une ancienne
version extraite par git show). MOT_EVEIL : ok-hub, salut-hub, dis-hub, hub, ou un prénom.

Chaîne mesurée : Piper synthétise chaque phrase (cache .npy 16 kHz) ; bruit rose
ajouté 20 dB sous la parole pour la seconde condition ; Vosk décode par blocs de
0,1 s avec la grammaire de LOGIQUE, exactement comme hub-voix.py (cache JSON par
grammaire) ; les résultats sont rejoués dans l'Ecoute de LOGIQUE. Une commande est
réussie si elle sort exactement une fois ; une phrase de TV, si rien ne sort. --flux
enchaîne toutes les phrases de TV d'une voix sans pause longue (0,4 s) dans un seul
reconnaisseur : la TV qui parle sans arrêt.

Dans HUB_BANC_DOSSIER (hors dépôt, ~1 Go) :
  venv/        python3 -m venv venv && venv/bin/pip install vosk==0.3.45 piper-tts numpy
  modeles/     sh ../telecharger-modele.sh HUB_BANC_DOSSIER/modeles
  voix/        venv/bin/python -m piper.download_voices --data-dir voix fr_FR-siwis-medium …
Lancer avec venv/bin/python ; ffmpeg doit être installé (rééchantillonnage).
"""
import hashlib, importlib.util, inspect, json, subprocess, sys, collections
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np

import os
ICI = Path(__file__).resolve().parent
RACINE = Path(os.environ.get("HUB_BANC_DOSSIER") or sys.exit("HUB_BANC_DOSSIER non défini (voir en tête du fichier)"))
WAV = RACINE / "cache" / "wav"; WAV.mkdir(parents=True, exist_ok=True)
DEC = RACINE / "cache" / "dec"; DEC.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ICI))
import phrases as P

TAUX = 16000
BLOC = 3200
MODELES = {"fr": RACINE / "modeles/vosk-model-small-fr-0.22", "en": RACINE / "modeles/vosk-model-small-en-us-0.15"}
VOIX = {"fr": ["fr_FR-siwis-medium", "fr_FR-tom-medium", "fr_FR-upmc-medium:0", "fr_FR-gilles-low"],
        "en": ["en_US-lessac-medium", "en_US-ryan-medium", "en_GB-alan-medium"]}
# espeak lit « hub » [ˈœb] : la prononciation française voulue, et la virgule garde sa
# pause (le [[ ˈœb ]] de l'ancien corpus collait « HUB » au mot suivant).
DIT = {"fr": {"hub": "Hub", "ok-hub": "OK hub", "salut-hub": "Salut hub", "dis-hub": "Dis hub"},
       "en": {"hub": "Hub", "ok-hub": "OK hub", "salut-hub": "Hey hub", "dis-hub": "Hey hub"}}
BRUITS = (0, 20)  # propre, et bruit rose 20 dB sous la parole

_voix = {}
def synth(voix, texte):
    cle = hashlib.sha1(f"{voix}|{texte}".encode()).hexdigest()[:16]
    f = WAV / f"{cle}.npy"
    if f.exists():
        return np.load(f)
    from piper import PiperVoice, SynthesisConfig
    voix, _, vitesse = voix.partition("@")
    nom, _, loc = voix.partition(":")
    if nom not in _voix:
        _voix[nom] = PiperVoice.load(str(RACINE / "voix" / f"{nom}.onnx"))
    v = _voix[nom]
    cfg = SynthesisConfig(speaker_id=int(loc) if loc else None, length_scale=float(vitesse) if vitesse else None)
    brut = b"".join(c.audio_int16_bytes for c in v.synthesize(texte, cfg))
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(v.config.sample_rate), "-ac", "1",
                        "-i", "-", "-f", "s16le", "-ar", str(TAUX), "-ac", "1", "-"], input=brut, capture_output=True, check=True)
    a = np.frombuffer(r.stdout, dtype=np.int16)
    np.save(f, a)
    return a

def rose(n, graine):
    rng = np.random.default_rng(graine)
    x = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(x), dtype=float); f[0] = 1
    y = np.fft.irfft(x / np.sqrt(f), n)
    return y / np.sqrt(np.mean(y ** 2))

def assembler(morceaux, bruit, graine=0, avant=0.5, entre=0.8, apres=1.5):
    parties = [np.zeros(int(avant * TAUX))]
    for i, m in enumerate(morceaux):
        parties += [m.astype(np.float64), np.zeros(int((entre if i < len(morceaux) - 1 else apres) * TAUX))]
    s = np.concatenate(parties)
    if bruit:
        parole = np.concatenate([m.astype(np.float64) for m in morceaux])
        s = s + rose(len(s), graine) * np.sqrt(np.mean(parole ** 2)) * 10 ** (-bruit / 20)
    return np.clip(s, -32768, 32767).astype(np.int16)

_modeles = {}
def decoder(langue, grammaire, audio):
    import vosk
    vosk.SetLogLevel(-1)
    if langue not in _modeles:
        _modeles[langue] = vosk.Model(str(MODELES[langue]))
    r = vosk.KaldiRecognizer(_modeles[langue], TAUX, json.dumps(grammaire, ensure_ascii=False))
    r.SetWords(True)
    b = audio.tobytes(); sortie = []; pos = 0.0
    for d in range(0, len(b), BLOC):
        m = b[d:d + BLOC]; pos += len(m) / 2 / TAUX
        if r.AcceptWaveform(m):
            sortie.append((pos, json.loads(r.Result())))
    sortie.append((pos, json.loads(r.FinalResult())))
    return sortie

def tache(args):
    langue, voix, textes, bruit, grammaire, gcle, graine = args
    cle = hashlib.sha1(json.dumps([langue, voix, textes, bruit, gcle, graine]).encode()).hexdigest()[:20]
    f = DEC / f"{cle}.json"
    if f.exists():
        return json.loads(f.read_text())
    res = decoder(langue, grammaire, assembler([synth(voix, t) for t in textes], bruit, graine))
    f.write_text(json.dumps(res, ensure_ascii=False))
    return res

def tache_flux(args):
    """Toutes les phrases négatives d'une voix à la suite, 0,4 s entre elles : la TV qui parle."""
    langue, voix, bruit, grammaire, gcle = args
    cle = hashlib.sha1(json.dumps(["flux", langue, voix, bruit, gcle, len(P.NEGATIFS_FR)]).encode()).hexdigest()[:20]
    f = DEC / f"{cle}.json"
    if f.exists():
        return json.loads(f.read_text())
    negs = P.NEGATIFS_FR if langue == "fr" else P.NEGATIFS_EN
    audio = assembler([synth(voix, n) for n in negs], bruit, 7, entre=0.4)
    res = decoder(langue, grammaire, audio)
    f.write_text(json.dumps(res, ensure_ascii=False))
    return res

def charger_logique(dossier):
    spec = importlib.util.spec_from_file_location(f"logique_{abs(hash(str(dossier)))}", Path(dossier) / "hub_voix_logique.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def cas(langue, mot):
    dit = DIT[langue].get(mot, mot.capitalize())
    cmds = (P.COMMANDES_FR + P.WEB_FR) if langue == "fr" else (P.COMMANDES_EN + P.WEB_EN)
    negs = P.NEGATIFS_FR if langue == "fr" else P.NEGATIFS_EN
    c = [(tuple(x.format(E=dit) for x in (t if isinstance(t, tuple) else (t,))), a) for t, a in cmds]
    return c + [((n,), None) for n in negs]

def grammaire(L, langue, mot, options=None):
    params = inspect.signature(L.grammaire).parameters
    if len(params) == 1:
        return L.grammaire(langue)
    return L.grammaire(langue, mot, **{k: v for k, v in (options or {}).items() if k in params})

def cle_grammaire(g):
    return hashlib.sha1(json.dumps(g, ensure_ascii=False).encode()).hexdigest()[:12]

def rejouer(L, langue, mot, resultats, options):
    params = inspect.signature(L.Ecoute).parameters
    kw = {"mot_eveil": mot} if "mot_eveil" in params else {}
    kw.update({k: v for k, v in options.items() if k in params})
    e = L.Ecoute(langue, **kw)
    ev = []
    for pos, r in resultats:
        ev += e.entendre(r.get("text", ""), pos)
    ev += e.tic(resultats[-1][0] + 100) if resultats else []
    return ev

def mesurer(dossier, langue, mot, options=None, voix=None, flux=False, jobs=4):
    L = charger_logique(dossier)
    options = options or {}
    liste = cas(langue, mot)
    voix = voix or VOIX[langue]
    g = grammaire(L, langue, mot, options); gc = cle_grammaire(g)
    travaux = [(langue, v, list(t), b, g, gc, i) for v in voix for b in BRUITS for i, (t, _a) in enumerate(liste)]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(tache, travaux, chunksize=4))
        flux_res = list(ex.map(tache_flux, [(langue, v, b, g, gc) for v in voix for b in BRUITS])) if flux else []
    total = collections.Counter(); echecs = []
    for t, r in zip(travaux, res):
        v, b, textes = t[1], t[3], tuple(t[2])
        attendu = dict(liste)[textes]
        ev = rejouer(L, langue, mot, r, options)
        cmds = [x for x in ev if not x.startswith("voix:")]
        entendu = " | ".join(x[1].get("text", "") for x in r if x[1].get("text"))
        web = bool(attendu and attendu.startswith("web:"))
        if attendu:
            k = "web" if web else "cmd"
            total[k] += 1; total[f"{k}_{v}"] += 1
            if cmds == [attendu]:
                total[k + "_ok"] += 1; total[f"{k}_ok_{v}"] += 1
            else:
                echecs.append((v, b, " / ".join(textes), attendu, entendu, cmds))
        else:
            total["neg"] += 1
            if cmds:
                total["fp"] += 1; echecs.append((v, b, textes[0], None, entendu, cmds))
            total["eveil_neg"] += "voix:eveil" in ev
    for (v, b), r in zip([(v, b) for v in voix for b in BRUITS], flux_res):
        ev = rejouer(L, langue, mot, r, options)
        cmds = [x for x in ev if not x.startswith("voix:")]
        total["flux_cmd"] += len(cmds); total["flux_eveil"] += ev.count("voix:eveil")
        if cmds:
            echecs.append((v, b, "FLUX", None, "", cmds))
    return total, echecs

def resume(t, langue, voix=None):
    s = (f"commandes {t['cmd_ok']}/{t['cmd']} ({100*t['cmd_ok']/max(t['cmd'],1):.1f} %), "
         f"web {t['web_ok']}/{t['web']}, faux positifs {t['fp']}/{t['neg']}, éveils sur négatifs {t['eveil_neg']}")
    if "flux_cmd" in t:
        s += f", flux TV : {t['flux_cmd']} commandes, {t['flux_eveil']} éveils"
    s += "\n" + "\n".join(f"   {v}: {t['cmd_ok_'+v]}/{t['cmd_'+v]} + web {t['web_ok_'+v]}/{t['web_'+v]}" for v in (voix or VOIX[langue]))
    return s

if __name__ == "__main__":
    dossier, langue, mot = sys.argv[1:4]
    options = next((json.loads(a) for a in sys.argv[4:] if a.startswith("{")), {})
    voix = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--voix=")), None)
    t, e = mesurer(dossier, langue, mot, options, voix=voix, flux="--flux" in sys.argv)
    print(dossier, langue, mot, options, resume(t, langue, voix))
    if "--detail" in sys.argv:
        for x in e:
            print("  ", x)
