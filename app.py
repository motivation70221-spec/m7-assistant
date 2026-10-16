from flask import Flask, render_template, request, jsonify
import json
import os
import re
import unicodedata

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def normalize_text(text):
    """Prépare un texte pour faciliter la reconnaissance des messages."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^\w\s']", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def load_knowledge():
    """Charge les connaissances disponibles dans les fichiers JSON."""
    knowledge = []

    if not os.path.isdir(DATA_DIR):
        return knowledge

    for filename in os.listdir(DATA_DIR):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(DATA_DIR, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as file:
                content = json.load(file)

            if isinstance(content, list):
                knowledge.extend(content)

        except (OSError, json.JSONDecodeError):
            continue

    return knowledge


def find_response(message):
    """Recherche une réponse connue à partir du message reçu."""
    normalized = normalize_text(message)
    knowledge = load_knowledge()

    # Recherche d'abord les expressions complètes.
    for item in knowledge:
        patterns = item.get("patterns", [])
        response = item.get("response")

        for pattern in patterns:
            normalized_pattern = normalize_text(pattern)

            if normalized == normalized_pattern:
                return response

    # Recherche ensuite les mots et expressions significatifs.
    for item in knowledge:
        patterns = item.get("patterns", [])
        response = item.get("response")

        for pattern in patterns:
            normalized_pattern = normalize_text(pattern)

            if len(normalized_pattern) < 4:
                continue

            if normalized_pattern in normalized:
                return response

    return None


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({
            "reply": "Écris-moi un petit message pour que nous puissions commencer. ❤️",
            "topics": get_topics()
        })

    response = find_response(message)

    if response is None:
        response = (
            "Merci de me parler. ❤️ Je ne comprends pas encore "
            "parfaitement cette question, mais je vais essayer de "
            "mieux te guider.\n\n"
            "Choisis un sujet pour continuer notre conversation."
        )

    return jsonify({
        "reply": response,
        "topics": get_topics()
    })


def get_topics():
    return [
        {"label": "❤️ Motivation", "message": "Je veux de la motivation"},
        {"label": "💪 Confiance en soi", "message": "Comment avoir confiance en moi ?"},
        {"label": "🧠 Leçons de vie", "message": "Raconte-moi une leçon de vie"},
        {"label": "🤝 Amitié", "message": "Parlons de l'amitié"},
        {"label": "🕌 Foi et patience", "message": "Parlons de la foi et de la patience"},
        {"label": "🎬 Histoires M7", "message": "Raconte-moi une histoire M7"},
        {"label": "👤 Mon créateur", "message": "Qui t'a créé ?"}
    ]


@app.route("/api/topics", methods=["GET"])
def topics():
    return jsonify({"topics": get_topics()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
