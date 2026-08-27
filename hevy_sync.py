#!/usr/bin/env python3
"""
hevy_sync.py — met à jour les objectifs de poids du programme depuis l'API Hevy.

Ce que fait le script, à chaque exécution :
  1. Récupère tes dernières séances via l'API Hevy (clé dans la variable
     d'environnement HEVY_API_KEY — jamais en dur ici).
  2. Pour chaque jour du programme (Upper 1 / Upper 2 / Lower), retrouve ta
     séance Hevy la plus récente portant ce titre.
  3. Applique la DOUBLE PROGRESSION : si tu as validé le haut de la fourchette
     de reps sur ta série de travail la plus lourde, l'objectif monte d'un cran ;
     sinon il reste sur ce que tu as fait.
  4. Lit la note de séance ET la note de chaque exercice. Si une DOULEUR est
     mentionnée, l'exercice est marqué "prudence" : on ne monte pas la charge et
     on propose une réduction ~10 %.
  5. Écrit data.json, que le site lit pour afficher les objectifs à jour.

Aucune dépendance externe (urllib de la lib standard).
"""

import os, json, sys, unicodedata, urllib.request, urllib.error
from datetime import datetime, timezone

API_BASE = "https://api.hevyapp.com/v1"
API_KEY  = os.environ.get("HEVY_API_KEY", "").strip()

# ------------------------------------------------------------------
# PROGRAMME — la source de vérité des fourchettes de reps et incréments.
# 'name'    : doit correspondre EXACTEMENT au nom affiché dans le site (WEEK[].exos[].n)
# 'hevy'    : le(s) titre(s) d'exercice tels qu'ils apparaissent dans Hevy
# 'lo'/'hi' : fourchette de reps
# 'inc'     : incrément de charge quand tu valides le haut de la fourchette
# 'prefix'  : '+' pour les exos lestés (tractions), sinon ''
# ------------------------------------------------------------------
PROGRAM = {
    "Upper 1": [
        {"name": "Développé couché barre",     "hevy": ["Développé Couché (Barre)"],            "lo": 4,  "hi": 6,  "inc": 2.5},
        {"name": "Tractions lestées",          "hevy": ["Tractions (Lesté)"],                   "lo": 6,  "hi": 8,  "inc": 2.5, "prefix": "+"},
        {"name": "Développé incliné barre",    "hevy": ["Développé Couché Incliné (Barre)"],    "lo": 6,  "hi": 8,  "inc": 2.5},
        {"name": "Rowing assis machine",       "hevy": ["Rowing Assis (Machine)"],              "lo": 8,  "hi": 10, "inc": 2.5},
        {"name": "Élévation latérale haltère", "hevy": ["Élévation Latérale (Haltère)"],        "lo": 10, "hi": 15, "inc": 1},
        {"name": "Extension triceps poulie",   "hevy": ["Extension Triceps Poulie Haute", "Extension Triceps (Poulie)"], "lo": 8, "hi": 12, "inc": 2.5},
        {"name": "Curl pupitre",               "hevy": ["Curl Pupitre (Barre)"],                "lo": 8,  "hi": 12, "inc": 2.5},
        {"name": "Tirage vers le visage",      "hevy": ["Tirage vers Visage"],                  "lo": 12, "hi": 15, "inc": 2.5},
    ],
    "Lower": [
        {"name": "Squat barre",                "hevy": ["Squat (Barre)"],                       "lo": 5,  "hi": 6,  "inc": 2.5},
        {"name": "Soulevé de terre roumain",   "hevy": ["Soulevé de Terre Roumain (Barre)", "Soulevé de Terre Roumain"], "lo": 8, "hi": 10, "inc": 2.5},
        {"name": "Presse à cuisses",           "hevy": ["Presse à Cuisses Horizontal", "Presse à Cuisses"], "lo": 8, "hi": 10, "inc": 5},
        {"name": "Leg curl allongé",           "hevy": ["Leg Curl Allongé (Machine)"],          "lo": 10, "hi": 12, "inc": 2.5},
        {"name": "Extension jambes",           "hevy": ["Extension Jambes"],                    "lo": 12, "hi": 15, "inc": 2.5},
        {"name": "Presse à mollets",           "hevy": ["Presse Mollets (Machine)"],            "lo": 10, "hi": 15, "inc": 2.5},
    ],
    "Upper 2": [
        {"name": "Développé militaire (Smith/barre)", "hevy": ["Développé Militaire (Machine Smith)", "Développé Militaire Assis (Barre)"], "lo": 6, "hi": 8, "inc": 2.5},
        {"name": "Développé couché barre",     "hevy": ["Développé Couché (Barre)"],            "lo": 8,  "hi": 10, "inc": 2.5},
        {"name": "Tirage poitrine prise serrée","hevy": ["Tirage Poitrine - Prise Serrée (Poulie)"], "lo": 8, "hi": 10, "inc": 2.5},
        {"name": "Écarté machine",             "hevy": ["Écarté (Machine)"],                    "lo": 10, "hi": 12, "inc": 2.5},
        {"name": "Rowing poulie assis",        "hevy": ["Rowing Poulie Assis"],                 "lo": 8,  "hi": 10, "inc": 2.5},
        {"name": "Élévation latérale haltère", "hevy": ["Élévation Latérale (Haltère)"],        "lo": 12, "hi": 15, "inc": 1},
        {"name": "Oiseau machine",             "hevy": ["Oiseau (Machine)"],                    "lo": 12, "hi": 15, "inc": 2.5},
        {"name": "Curl pupitre machine",       "hevy": ["Curl Pupitre (Machine)"],              "lo": 8,  "hi": 12, "inc": 2.5},
        {"name": "Extension triceps poulie",   "hevy": ["Extension Triceps (Poulie)", "Extension Triceps Poulie Haute"], "lo": 10, "hi": 12, "inc": 2.5},
    ],
}

# Titres de séance Hevy -> jour du programme (insensible à la casse / espaces)
DAY_TITLES = {
    "upper 1": "Upper 1", "upper1": "Upper 1", "haut 1": "Upper 1",
    "upper 2": "Upper 2", "upper2": "Upper 2", "haut 2": "Upper 2",
    "lower": "Lower", "jambes": "Lower", "bas": "Lower",
}

# Mots-clés de douleur (recherchés sans accents, en minuscules)
PAIN_WORDS = ["douleur", "douloureux", "mal a", "mal au", "gene", "epaule",
              "tendinite", "tendino", "blessure", "elance", "lancinant",
              "inconfort", "pincement", "pain", "twinge"]


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def api_get(path):
    req = urllib.request.Request(API_BASE + path, headers={"api-key": API_KEY, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_recent_workouts(max_pages=5):
    """Récupère les séances récentes (les plus récentes d'abord)."""
    out = []
    for page in range(1, max_pages + 1):
        try:
            data = api_get(f"/workouts?page={page}&pageSize=10")
        except urllib.error.HTTPError as e:
            print(f"[erreur API] page {page}: HTTP {e.code} — {e.read().decode('utf-8', 'ignore')[:200]}", file=sys.stderr)
            break
        workouts = data.get("workouts", data if isinstance(data, list) else [])
        if not workouts:
            break
        out.extend(workouts)
        if page >= data.get("page_count", page):
            break
    return out


def has_pain(*texts):
    blob = strip_accents(" ".join(t for t in texts if t))
    return any(w in blob for w in PAIN_WORDS)


def round_step(x, step=0.5):
    return round(x / step) * step


def working_sets(exercise):
    """Séries de travail (hors échauffement) avec poids et reps valides."""
    res = []
    for s in exercise.get("sets", []):
        if s.get("type") == "warmup":
            continue
        w, reps = s.get("weight_kg"), s.get("reps")
        if w is None or reps is None:
            continue
        res.append((float(w), int(reps)))
    return res


def compute_target(slot, exercise):
    """Applique la double progression sur la série de travail la plus lourde."""
    sets = working_sets(exercise)
    if not sets:
        return None
    top_w = max(w for w, _ in sets)
    reps_at_top = [reps for w, reps in sets if abs(w - top_w) < 1e-6]
    min_reps = min(reps_at_top)
    pain = has_pain(exercise.get("notes", ""))
    last_str = f"{top_w:g} kg × " + ",".join(str(r) for r in reps_at_top)

    if pain:
        return {"wt": _fmt(slot, top_w), "status": "prudence", "caution": True,
                "cautionMsg": "Note de douleur détectée — charge maintenue. Réduis ~10 % "
                              f"(≈ {_fmt(slot, round_step(top_w*0.9, slot.get('inc',2.5)))}) ou passe en variante plus douce si ça tire.",
                "last": last_str}
    if min_reps >= slot["hi"]:
        return {"wt": _fmt(slot, top_w + slot["inc"]), "status": "progression", "caution": False, "last": last_str}
    return {"wt": _fmt(slot, top_w), "status": "maintien", "caution": False, "last": last_str}


def _fmt(slot, value):
    v = round_step(value, 0.5)
    v = int(v) if abs(v - int(v)) < 1e-9 else v
    return f'{slot.get("prefix","")}{v}'


def find_exercise(workout, hevy_titles):
    wanted = {strip_accents(t) for t in hevy_titles}
    for ex in workout.get("exercises", []):
        if strip_accents(ex.get("title", "")) in wanted:
            return ex
    return None


def main():
    if not API_KEY:
        print("HEVY_API_KEY manquante. Renseigne-la (secret GitHub / variable d'env).", file=sys.stderr)
        sys.exit(1)

    workouts = fetch_recent_workouts()
    print(f"{len(workouts)} séances récupérées.", file=sys.stderr)

    # dernière séance par jour de programme
    latest_by_day = {}
    for w in workouts:  # déjà du plus récent au plus ancien
        day = DAY_TITLES.get(strip_accents(w.get("title", "")).strip())
        if day and day not in latest_by_day:
            latest_by_day[day] = w

    updates, flags = {}, []
    for day, slots in PROGRAM.items():
        w = latest_by_day.get(day)
        if not w:
            continue
        day_pain = has_pain(w.get("description", ""))
        updates[day] = {}
        for slot in slots:
            ex = find_exercise(w, slot["hevy"])
            if not ex:
                continue
            res = compute_target(slot, ex)
            if not res:
                continue
            # douleur mentionnée au niveau de la séance -> prudence sur tout le jour
            if day_pain and not res["caution"]:
                res["caution"] = True
                res["cautionMsg"] = "Douleur mentionnée dans la note de séance — charge maintenue par prudence."
                res["status"] = "prudence"
            updates[day][slot["name"]] = res
            if res.get("caution"):
                flags.append({"day": day, "exercise": slot["name"], "note": (ex.get("notes") or w.get("description") or "").strip()[:160]})

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "hevy",
        "updates": updates,
        "flags": flags,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"data.json écrit — {sum(len(v) for v in updates.values())} objectifs mis à jour, {len(flags)} alerte(s) douleur.", file=sys.stderr)


if __name__ == "__main__":
    main()
