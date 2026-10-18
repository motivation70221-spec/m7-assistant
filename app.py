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

    # Harmonise les apostrophes typographiques.
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("`", "'").replace("´", "'")

    # Supprime les accents.
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )

    # Supprime la ponctuation inutile.
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def load_knowledge():
    """Charge les connaissances disponibles dans les fichiers JSON."""
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
        "peux", "peut", "veux", "voudrais", "quoi",
        "quel", "quelle", "quels", "quelles", "pourrait",
        "pourrais", "faire", "parle", "parlons"
    }

    return {
        word
        for word in normalize_text(text).split()
        if len(word) >= 3 and word not in ignored_words
    }


def score_pattern(message, pattern):
    """Évalue la correspondance entre un message et une phrase connue."""
    message = normalize_text(message)
    pattern = normalize_text(pattern)

    if not message or not pattern:
        return 0.0

    # Correspondance exacte.
    if message == pattern:
        return 1.0

    # Une phrase connue présente intégralement dans le message.
    expression = r"(?<!\w)" + re.escape(pattern) + r"(?!\w)"

    if len(pattern) >= 5 and re.search(expression, message):
        return 0.96

    message_words = get_words(message)
    pattern_words = get_words(pattern)

    if not message_words or not pattern_words:
        return 0.0

    common_words = message_words.intersection(pattern_words)

    if not common_words:
        # Tolérance limitée aux petites fautes de frappe.
        if len(message) >= 12 and len(pattern) >= 12:
            ratio = SequenceMatcher(
                None, message, pattern
            ).ratio()

            if ratio >= 0.84:
                return ratio * 0.75

        return 0.0

    coverage = len(common_words) / len(pattern_words)
    precision = len(common_words) / len(message_words)

    score = 0.70 * coverage + 0.30 * precision

    # Un seul mot partagé ne suffit pas à choisir une réponse.
    if len(common_words) == 1:
        word = next(iter(common_words))

        if len(word) < 5:
            return 0.0

        score = min(score, 0.55)

    return score


def find_response(message):
    """Choisit la réponse connue la plus pertinente."""
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

    if best["score"] < 0.60:
        return None

    # Évite les choix arbitraires entre réponses presque équivalentes.
    if len(candidates) > 1:
        second = candidates[1]

        if (
            best["score"] - second["score"] < 0.03
            and best["score"] < 0.90
        ):
            return None

    return best["response"]


def get_topics():
    """Retourne les sujets affichés dans l'interface."""
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
            "message": "Parlons de la patience"
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
    """Présente les sujets disponibles dans M7."""
    return (
        "Avec plaisir ! ❤️ Voici quelques sujets que nous "
        "pouvons explorer ensemble :\n\n"
        "💪 Motivation : retrouver le courage et avancer.\n"
        "🌟 Confiance en soi : apprendre à reconnaître ta valeur.\n"
        "🤝 Amitié : comprendre ce qui fait une relation sincère.\n"
        "🧠 Leçons de vie : réfléchir à nos choix et à nos erreurs.\n"
        "🙏 Foi et patience : garder espoir pendant les épreuves.\n"
        "❤️ Amour : parler des relations et des déceptions.\n"
        "🎬 Histoires M7 : découvrir des histoires inspirantes.\n\n"
        "Quel sujet aimerais-tu découvrir en premier ?"
    )


def get_topic_response(message):
    """
    Reconnaît quelques intentions fréquentes et les relie
    aux connaissances déjà présentes dans les fichiers JSON.
    """
    normalized = normalize_text(message)
    words = set(normalized.split())

    # Identité de M7 et informations sur son créateur.
    identity_questions = {
        "qui es tu",
        "qui es tu m7",
        "tu es qui",
        "toi tu es qui",
        "tu es quoi",
        "quel est ton nom",
        "comment tu t appelles",
        "presente toi",
        "presente toi m7",
        "parle moi de toi",
        "dis moi qui tu es",
        "qui etes vous",
        "qui t a cree",
        "qui est ton createur",
        "qui est derriere m7",
        "c est quoi m7"
    }

    if normalized in identity_questions:
        return find_response("qui es tu")

    if normalized == "m7":
        return find_response("qui es tu")

    if normalized == "cheikh":
        return find_response("qui est cheikh")
        
     creator_terms = {
        "cheikh", "createur", "cree", "creation"
    }
  identity_terms = {
    "qui", "identite", "presente", "nom"
}

if (
    words.intersection(creator_terms)
    and (
        words.intersection(identity_terms)
        or "parle" in words
        or "raconte" in words
    )
):
    if "cheikh" in words or "motivation7" in words:
        return find_response("qui est cheikh")

    return find_response("qui t'a créé")
        if "cheikh" in words or "motivation7" in words:
            return find_response("qui est cheikh")

        return find_response("qui t'a créé")

    # Reconnaissance des demandes de suggestions, même formulées
    # avec des mots supplémentaires.
    suggestion_terms = {
        "propose", "proposes", "sujet", "sujets",
        "interesser", "interesse", "interesserait",
        "idee", "idees"
    }

    if (
        words.intersection(suggestion_terms)
        and (
            "propose" in words
            or "proposes" in words
            or "sujet" in words
            or "sujets" in words
            or "interesser" in words
            or "interesserait" in words
        )
    ):
        return get_suggestion_response()

    # Le message doit évoquer une demande de discussion,
    # ou être simplement le nom d'un sujet.
    request_terms = {
        "parle", "parlons", "raconte", "explique",
        "dis", "discussion", "parler", "parlons",
        "aborder", "decouvrir"
    }

    is_topic_request = bool(words.intersection(request_terms))

    # Confiance en soi : réponse dédiée, car ce sujet n'a pas
    # encore sa propre réponse dans les fichiers JSON actuels.
    confidence_terms = {
        "confiance", "confiant", "confiante",
        "timide", "timidite", "estime"
    }

    if words.intersection(confidence_terms) and (
        is_topic_request or len(words) <= 4
    ):
        return (
            "🌟 La confiance en soi se construit progressivement. "
            "Tu n'as pas besoin d'être parfait pour reconnaître "
            "ta valeur. Commence par identifier tes qualités, "
            "avance à ton rythme et apprends à voir les erreurs "
            "comme des occasions de progresser. ❤️\n\n"
            "Dans quelle situation aimerais-tu avoir davantage "
            "confiance en toi ?"
        )

    # Relie les sujets aux formulations présentes
    # dans la bibliothèque de connaissances.
    topic_routes = [
        (
            {"amitie", "ami", "amis", "amie"},
            "parlons de l'amitie"
        ),
        (
            {"motivation", "motive", "motiver", "courage"},
            "je veux de la motivation"
        ),
        (
            {"patience", "patient", "patiente"},
            "parlons de la patience"
        ),
        (
            {"respect", "respecter"},
            "parlons du respect"
        ),
        (
            {"honnetete", "honnete", "honnetes"},
            "parlons de l'honnetete"
        ),
        (
            {"pardon", "pardonner", "blessure"},
            "parlons du pardon"
        ),
        (
            {"choix", "decision", "decider"},
            "parlons des choix"
        ),
        (
            {"lecon", "lecons", "vie"},
            "raconte-moi une leçon de vie"
        ),
        (
            {"discipline", "disciplinee", "discipliner"},
            "parle-moi de discipline"
        ),
        (
            {"amour", "aimer", "amoureux", "amoureuse", "couple"},
            "parle-moi d'amour"
        ),
        (
            {"rupture", "ex", "separation", "coeur"},
            "comment oublier mon ex"
        ),
        (
            {"solitude", "seul", "seule", "triste", "emotions"},
            "je me sens seul"
        ),
        (
            {"perseverance", "abandonner", "espoir"},
            "perseverance"
        ),
        (
            {"histoire", "histoires", "inspirante", "inspirantes"},
            "raconte une histoire inspirante"
        )
    ]

    for topic_words, canonical_question in topic_routes:
        if words.intersection(topic_words):
            if is_topic_request or len(words) <= 4:
                response = find_response(canonical_question)

                if response:
                    return response

    return None
 # ==========================================================
# ROUTES FLASK — M7 ASSISTANT
# ==========================================================

@app.route("/", methods=["GET"])
def home():
    """Affiche l'interface de M7."""

    template_path = os.path.join(
        BASE_DIR, "templates", "index.html"
    )

    root_html_path = os.path.join(
        BASE_DIR, "index.html"
    )

    if os.path.isfile(template_path):
        return render_template("index.html")

    if os.path.isfile(root_html_path):
        with open(root_html_path, "r", encoding="utf-8") as file:
            html = file.read()

        return app.response_class(
            html,
            mimetype="text/html"
        )

    return (
        "M7 Assistant : fichier index.html introuvable. "
        "Vérifie son emplacement dans le dépôt GitHub.",
        404
    )


@app.route("/api/chat", methods=["POST"])
def chat_api():
    """Reçoit un message et renvoie une réponse à l'interface."""

    data = request.get_json(silent=True) or {}
    message = data.get("message", "")

    if not isinstance(message, str):
        return jsonify({
            "reply": "Envoie-moi un message écrit, s'il te plaît. ❤️"
        }), 400

    message = message.strip()

    if not message:
        return jsonify({
            "reply": "Je suis là, mon ami. ❤️ Écris-moi ce que tu souhaites partager."
        })

    # Reconnaissance des emojis envoyés seuls.
    emoji_responses = {
        "❤️": "❤️ Je t'envoie beaucoup de bonnes pensées, mon ami.",
        "❤": "❤️ Je t'envoie beaucoup de bonnes pensées, mon ami.",
        "🥰": "🥰 Quel joli message ! Je te souhaite beaucoup de douceur.",
        "😊": "😊 Ton sourire fait plaisir ! De quoi aimerais-tu parler ?",
        "😂": "😂 Un peu de joie fait du bien ! Raconte-moi.",
        "😢": "❤️ Je suis là pour t'écouter. Veux-tu me dire ce qui te rend triste ?",
        "😭": "❤️ Prends ton temps. Tu peux me parler de ce que tu traverses.",
        "💔": "💔 Les blessures du cœur peuvent faire mal. Tu n'es pas obligé de tout porter seul.",
        "🙏": "🙏 Que la patience et l'espoir t'accompagnent dans les moments difficiles.",
        "💪": "💪 Continue d'avancer pas à pas. Même les petits progrès comptent.",
        "👍": "👍 Merci, mon ami ! On continue ensemble.",
        "😘": "❤️ Je t'envoie une pensée bienveillante !"
    }

    if message in emoji_responses:
        return jsonify({"reply": emoji_responses[message]})

    # Réponses simples aux salutations et aux politesses.
    normalized = normalize_text(message)

    greetings = {
        "bonjour", "bonsoir", "salut", "coucou",
        "salam", "hello", "bon matin"
    }

    if normalized in greetings:
        return jsonify({
            "reply": (
                "Salut mon ami ! ❤️ Heureux de discuter avec toi. "
                "Comment vas-tu aujourd'hui ?"
            )
        })

    if normalized in {"merci", "merci beaucoup", "je te remercie"}:
        return jsonify({
            "reply": (
                "Avec plaisir, mon ami ! ❤️ Je suis là pour échanger "
                "avec toi. Tu peux continuer."
            )
        })

    if normalized in {"ca va", "comment ca va", "comment vas tu"}:
        return jsonify({
            "reply": (
                "Je suis prêt à discuter avec toi ! 😊 "
                "Et toi, comment te sens-tu aujourd'hui ?"
            )
        })

    # Cherche d'abord une réponse liée au sujet du message.
    reply = get_topic_response(message)

    # Si aucune réponse n'a été trouvée, consulte les fichiers JSON.
    if not reply:
        reply = find_response(message)

    # Réponse de secours si la bibliothèque ne connaît pas la question.
    if not reply:
        reply = fallback_response()

    return jsonify({"reply": reply})


@app.route("/health", methods=["GET"])
def health_check():
    """Vérifie que le serveur M7 fonctionne."""

    return jsonify({
        "status": "ok",
        "application": "M7 Assistant"
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
