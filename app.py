from flask import Flask, render_template, request, jsonify
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def normalize_text(text):
    """Normalise le texte pour faciliter sa reconnaissance."""
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFD", text)

    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )

    text = re.sub(r"[^\w\s']", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def load_knowledge():
    """Charge les connaissances depuis les fichiers JSON."""
    knowledge = []

    if not os.path.isdir(DATA_DIR):
        return knowledge

    for filename in sorted(os.listdir(DATA_DIR)):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(DATA_DIR, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as file:
                content = json.load(file)

            if not isinstance(content, list):
                continue

            for item in content:
                if not isinstance(item, dict):
                    continue

                patterns = item.get("patterns", [])
                response = item.get("response")

                if not isinstance(patterns, list):
                    continue

                if not isinstance(response, str):
                    continue

                knowledge.append({
                    "patterns": [
                        normalize_text(pattern)
                        for pattern in patterns
                        if isinstance(pattern, str)
                        and normalize_text(pattern)
                    ],
                    "response": response
                })

        except (OSError, json.JSONDecodeError) as error:
            app.logger.warning(
                "Erreur de lecture du fichier %s : %s",
                filename,
                error
            )

    return knowledge


def get_words(text):
    """Extrait les mots utiles d'un message."""
    ignored_words = {
        "alors", "avec", "chez", "dans", "des", "est",
        "et", "moi", "mon", "pour", "que", "qui",
        "sur", "toi", "une", "les", "aux", "par",
        "mais", "donc", "comment", "pourquoi",
        "peux", "peut", "veux", "voudrais"
    }

    return {
        word
        for word in normalize_text(text).split()
        if len(word) >= 3 and word not in ignored_words
    }


def score_pattern(message, pattern):
    """Évalue la pertinence d'une phrase connue."""
    message = normalize_text(message)
    pattern = normalize_text(pattern)

    if not message or not pattern:
        return 0.0

    # Une phrase identique est une correspondance certaine.
    if message == pattern:
        return 1.0

    # Une expression complète présente dans le message
    # constitue une bonne correspondance.
    if len(pattern) >= 5:
        expression = (
            r"(?<!\w)"
            + re.escape(pattern)
            + r"(?!\w)"
        )

        if re.search(expression, message):
            return 0.96

    message_words = get_words(message)
    pattern_words = get_words(pattern)

    if not message_words or not pattern_words:
        return 0.0

    common_words = message_words.intersection(pattern_words)

    if not common_words:
        # La tolérance aux fautes n'est utilisée que pour
        # des phrases de longueur suffisante.
        if len(message) >= 12 and len(pattern) >= 12:
            ratio = SequenceMatcher(
                None, message, pattern
            ).ratio()

            if ratio >= 0.82:
                return ratio * 0.75

        return 0.0

    # La correspondance doit couvrir une partie significative
    # des mots de la phrase connue.
    coverage = len(common_words) / len(pattern_words)
    precision = len(common_words) / len(message_words)

    score = 0.70 * coverage + 0.30 * precision

    # Une correspondance sur un seul mot générique est insuffisante.
    if len(common_words) == 1:
        word = next(iter(common_words))

        if len(word) < 5:
            return 0.0

        score = min(score, 0.55)

    return score


def find_response(message):
    """Choisit la réponse correspondant le mieux à la demande."""
    normalized = normalize_text(message)

    if not normalized:
        return None

    knowledge = load_knowledge()
    candidates = []

    for item in knowledge:
        best_item_score = 0.0

        for pattern in item["patterns"]:
            score = score_pattern(normalized, pattern)

            if score > best_item_score:
                best_item_score = score

        if best_item_score > 0:
            candidates.append({
                "score": best_item_score,
                "response": item["response"]
            })

    if not candidates:
        return None

    candidates.sort(
        key=lambda candidate: candidate["score"],
        reverse=True
    )

    best = candidates[0]

    # Une ressemblance trop faible ne suffit pas.
    if best["score"] < 0.60:
        return None

    # En cas d'ambiguïté, on préfère demander une précision
    # plutôt que choisir arbitrairement une réponse.
    if len(candidates) > 1:
        second = candidates[1]

        if (
            best["score"] - second["score"] < 0.03
            and best["score"] < 0.90
        ):
            return None

    return best["response"]


def get_topics():
    """Retourne les sujets proposés dans l'interface."""
    return [
        {
            "label": "❤️ Motivation",
            "message": "Je veux de la motivation"
        },
        {
            "label": "💪 Confiance en soi",
            "message": "Comment avoir confiance en moi ?"
        },
        {
            "label": "🧠 Leçons de vie",
            "message": "Raconte-moi une leçon de vie"
        },
        {
            "label": "🤝 Amitié",
            "message": "Parlons de l'amitié"
        },
        {
            "label": "🕌 Foi et patience",
            "message": "Parlons de la foi et de la patience"
        },
        {
            "label": "🎬 Histoires M7",
            "message": "Raconte-moi une histoire M7"
        },
        {
            "label": "👤 Mon créateur",
            "message": "Qui t'a créé ?"
        }
    ]


def fallback_response():
    """Répond honnêtement lorsqu'aucune réponse fiable n'est trouvée."""
    return (
        "Je veux bien en discuter avec toi. ❤️ "
        "Mais je ne suis pas encore certain de comprendre "
        "exactement ce que tu souhaites.\n\n"
        "Peux-tu préciser ta question ou choisir un sujet "
        "parmi ceux proposés ?"
    )


def get_suggestion_response():
    """Présente les sujets que M7 peut aborder."""
    return (
        "Avec plaisir ! ❤️ Voici quelques sujets que nous "
        "pouvons explorer ensemble :\n\n"
        "💪 Motivation : retrouver le courage et avancer.\n"
        "🌟 Confiance en soi : apprendre à reconnaître ta valeur.\n"
        "🤝 Amitié : comprendre ce qui fait une relation sincère.\n"
        "🧠 Leçons de vie : réfléchir à nos choix et à nos erreurs.\n"
        "🙏 Foi et patience : garder espoir pendant les épreuves.\n"
        "❤️ Amour : parler des relations, des déceptions et "
        "de la reconstruction après une blessure.\n"
        "🎬 Histoires M7 : découvrir des histoires inspirantes.\n\n"
        "Quel sujet aimerais-tu découvrir en premier ?"
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}

    message = str(data.get("message", "")).strip()
    normalized = normalize_text(message)

    if not normalized:
        return jsonify({
            "reply": (
                "Écris-moi un petit message pour que "
                "nous puissions commencer. ❤️"
            ),
            "topics": get_topics()
        })

    # Demandes générales de suggestions.
    suggestion_phrases = {
        "que proposes tu",
        "qu'est ce que tu proposes",
        "qu est ce que tu proposes",
        "que puis je faire",
        "que peut on faire",
        "de quoi peut on parler",
        "de quoi pouvons nous parler",
        "propose moi un sujet",
        "donne moi un sujet"
    }

    if normalized in suggestion_phrases:
        response = get_suggestion_response()
    else:
        response = find_response(message)

    if response is None:
        response = fallback_response()

    return jsonify({
        "reply": response,
        "topics": get_topics()
    })


@app.route("/api/topics", methods=["GET"])
def topics():
    return jsonify({
        "topics": get_topics()
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
