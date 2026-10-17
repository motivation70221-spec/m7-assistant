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
    """Normalise un texte pour faciliter la reconnaissance des messages."""
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
    """Charge les connaissances présentes dans les fichiers JSON."""
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

            if isinstance(content, list):
                for item in content:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("patterns"), list)
                        and isinstance(item.get("response"), str)
                    ):
                        knowledge.append(item)

        except (OSError, json.JSONDecodeError) as error:
            app.logger.warning(
                "Impossible de charger %s : %s",
                filename,
                error
            )

    return knowledge


def get_words(text):
    """Extrait les mots significatifs d'un texte."""
    ignored_words = {
        "a", "au", "aux", "avec", "ce", "ces", "dans",
        "de", "des", "du", "elle", "en", "et", "il",
        "je", "la", "le", "les", "ma", "mais", "me",
        "mes", "moi", "mon", "ne", "nos", "notre",
        "nous", "on", "ou", "par", "pas", "pour",
        "que", "qui", "sa", "se", "ses", "son",
        "sur", "ta", "te", "tes", "toi", "ton",
        "tu", "un", "une", "vos", "votre", "vous"
    }

    return {
        word for word in normalize_text(text).split()
        if len(word) > 2 and word not in ignored_words
    }


def similarity_score(message, pattern):
    """Calcule un score de ressemblance entre un message et une phrase."""
    message = normalize_text(message)
    pattern = normalize_text(pattern)

    if not message or not pattern:
        return 0.0

    # Une correspondance exacte est prioritaire.
    if message == pattern:
        return 1.0

    # Une expression connue présente dans le message est intéressante.
    if len(pattern) >= 5:
        if re.search(
            r"(?<!\w)" + re.escape(pattern) + r"(?!\w)",
            message
        ):
            return 0.90

    # Comparaison des mots communs.
    message_words = get_words(message)
    pattern_words = get_words(pattern)

    if message_words and pattern_words:
        common_words = message_words.intersection(pattern_words)

        coverage = len(common_words) / len(pattern_words)
        precision = len(common_words) / len(message_words)

        if common_words:
            word_score = (
                0.75 * coverage
                + 0.25 * precision
            )
        else:
            word_score = 0.0
    else:
        word_score = 0.0

    # Tolérance limitée aux petites fautes de frappe.
    typo_score = SequenceMatcher(
        None,
        message,
        pattern
    ).ratio()

    # On privilégie les mots communs aux ressemblances approximatives.
    return max(
        word_score * 0.85,
        typo_score * 0.65
    )


def find_response(message):
    """Recherche la réponse connue la plus adaptée."""
    normalized = normalize_text(message)

    if not normalized:
        return None

    knowledge = load_knowledge()
    candidates = []

    for item in knowledge:
        for pattern in item.get("patterns", []):
            if not isinstance(pattern, str):
                continue

            score = similarity_score(message, pattern)

            candidates.append({
                "score": score,
                "pattern": pattern,
                "response": item["response"]
            })

    if not candidates:
        return None

    # Les correspondances les plus fortes passent en premier.
    candidates.sort(
        key=lambda candidate: (
            candidate["score"],
            len(candidate["pattern"])
        ),
        reverse=True
    )

    best = candidates[0]

    # On évite de répondre sur la base d'une ressemblance trop faible.
    if best["score"] < 0.48:
        return None

    return best["response"]


def get_topics():
    """Retourne les sujets proposés par M7."""
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


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({
            "reply": (
                "Écris-moi un petit message pour que "
                "nous puissions commencer. ❤️"
            ),
            "topics": get_topics()
        })

    response = find_response(message)

    if response is None:
        response = (
            "Merci de me parler. ❤️ Je n'ai pas encore "
            "de réponse suffisamment fiable à cette question. "
            "Je préfère être honnête plutôt que d'inventer.\n\n"
            "Tu peux choisir un sujet proposé ci-dessous, "
            "ou reformuler ta question autrement."
        )

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
