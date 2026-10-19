from flask import Flask, render_template, request, jsonify, session
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
# ==========================================================
# CONFIGURATION DE M7
# ==========================================================
app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
# En production, définir SECRET_KEY dans les variables
# d'environnement de Render.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "m7-cle-temporaire-a-remplacer-en-production"
)
# ==========================================================
# NORMALISATION DU TEXTE
# ==========================================================
def normalize_text(text):
    """Normalise le texte pour faciliter sa reconnaissance."""
    text = str(text).lower().strip()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("`", "'").replace("´", "'")
    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char
        for char in text
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
# ==========================================================
# CHARGEMENT DES CONNAISSANCES JSON
# ==========================================================
def load_knowledge():
    """
    Charge les connaissances JSON situées :
    - à la racine du projet ;
    - dans le dossier data, s'il existe.
    Format attendu :
    [
        {
            "patterns": ["bonjour", "salut"],
            "response": "Bonjour mon ami !"
        }
    ]
    """
    knowledge = []
    files_to_read = []
    # Cherche les fichiers JSON à la racine.
    try:
        for filename in os.listdir(BASE_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(BASE_DIR, filename)
                if os.path.isfile(filepath):
                    files_to_read.append(filepath)
    except OSError as error:
        app.logger.warning(
            "Impossible de parcourir la racine : %s",
            error
        )
    # Cherche aussi les fichiers JSON dans data.
    if os.path.isdir(DATA_DIR):
        try:
            for filename in os.listdir(DATA_DIR):
                if filename.endswith(".json"):
                    filepath = os.path.join(DATA_DIR, filename)
                    if os.path.isfile(filepath):
                        files_to_read.append(filepath)
        except OSError as error:
            app.logger.warning(
                "Impossible de parcourir data : %s",
                error
            )
    # Évite de lire deux fois le même fichier.
    files_to_read = sorted(set(files_to_read))
    for filepath in files_to_read:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                content = json.load(file)
            if not isinstance(content, list):
                app.logger.warning(
                    "Le fichier %s ne contient pas une liste JSON.",
                    filename
                )
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
                clean_patterns = [
                    normalize_text(pattern)
                    for pattern in patterns
                    if isinstance(pattern, str)
                    and normalize_text(pattern)
                ]
                if not clean_patterns:
                    continue
                knowledge.append({
                    "patterns": clean_patterns,
                    "response": response
                })
        except (OSError, json.JSONDecodeError) as error:
            app.logger.warning(
                "Erreur de lecture de %s : %s",
                filename,
                error
            )
    app.logger.info(
        "M7 a chargé %s connaissances depuis les fichiers JSON.",
        len(knowledge)
    )
    return knowledge
# ==========================================================
# RECONNAISSANCE DES MOTS
# ==========================================================
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
# ==========================================================
# ÉVALUATION DES CORRESPONDANCES
# ==========================================================
def score_pattern(message, pattern):
    """Évalue la correspondance entre deux textes."""
    message = normalize_text(message)
    pattern = normalize_text(pattern)
    if not message or not pattern:
        return 0.0
    if message == pattern:
        return 1.0
    expression = (
        r"(?<!\w)"
        + re.escape(pattern)
        + r"(?!\w)"
    )
    if len(pattern) >= 5 and re.search(expression, message):
        return 0.96
    message_words = get_words(message)
    pattern_words = get_words(pattern)
    if not message_words or not pattern_words:
        return 0.0
    common_words = message_words.intersection(pattern_words)
    if not common_words:
        if len(message) >= 12 and len(pattern) >= 12:
            ratio = SequenceMatcher(
                None,
                message,
                pattern
            ).ratio()
            if ratio >= 0.84:
                return ratio * 0.75
        return 0.0
    coverage = len(common_words) / len(pattern_words)
    precision = len(common_words) / len(message_words)
    score = 0.70 * coverage + 0.30 * precision
    if len(common_words) == 1:
        word = next(iter(common_words))
        if len(word) < 5:
            return 0.0
        score = min(score, 0.55)
    return score
# ==========================================================
# RECHERCHE DANS LA BIBLIOTHÈQUE
# ==========================================================
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
    if len(candidates) > 1:
        second = candidates[1]
        if (
            best["score"] - second["score"] < 0.03
            and best["score"] < 0.90
        ):
            return None
    return best["response"]
# ==========================================================
# SUJETS PROPOSÉS DANS L'INTERFACE
# ==========================================================
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
            "label": "🙏 Foi et patience",
            "message": "Parlons de la patience"
        },
        {
            "label": "❤️ Amour",
            "message": "Parlons d'amour"
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
# ==========================================================
# SUGGESTIONS DE DISCUSSION
# ==========================================================
def get_suggestion_response():
    """Présente les sujets disponibles dans M7."""
    return (
        "Avec plaisir ! ❤️ Voici quelques sujets que nous "
        "pouvons explorer ensemble :\n\n"
        "💪 Motivation : retrouver le courage et avancer.\n"
        "🌟 Confiance en soi : apprendre à reconnaître ta valeur.\n"
        "🤝 Amitié : comprendre les relations sincères.\n"
        "🧠 Leçons de vie : réfléchir à nos choix et à nos erreurs.\n"
        "🙏 Foi et patience : garder espoir pendant les épreuves.\n"
        "❤️ Amour : parler des relations et des déceptions.\n"
        "🎬 Histoires M7 : découvrir des histoires inspirantes.\n\n"
        "Quel sujet aimerais-tu découvrir en premier ?"
    )
# ==========================================================
# RÉPONSES DE BASE
# ==========================================================
def get_identity_response():
    """Répond aux questions courantes sur l'identité de M7."""
    response = find_response("qui es tu")
    if response:
        return response
    return (
        "Salut mon ami ! ❤️ Je suis M7, l'assistant de "
        "Motivation7. Je suis là pour discuter avec toi, "
        "partager des conseils, parler de motivation, "
        "d'amitié, d'amour et de leçons de vie.\n\n"
        "Je m'améliore grâce aux connaissances qui me sont "
        "fournies et au code qui me permet de fonctionner."
    )
def get_creator_response():
    """Répond aux questions sur le créateur de M7."""
    response = find_response("qui est cheikh")
    if response:
        return response
    return (
        "M7 est un projet de Motivation7 créé par Cheikh "
        "avec l'aide de ChatGPT. ❤️ Le projet a été construit "
        "progressivement grâce aux idées, aux essais et au "
        "travail de son créateur.\n\n"
        "M7 est encore en développement et ses capacités "
        "dépendent du code et des connaissances qui lui sont "
        "ajoutés."
    )
def fallback_response():
    """Répond lorsqu'aucune réponse fiable n'est trouvée."""
    return (
        "Je veux bien en discuter avec toi. ❤️ "
        "Je ne suis pas encore certain de comprendre "
        "exactement ce que tu souhaites.\n\n"
        "Peux-tu reformuler ta question ou me donner "
        "un peu plus de détails ? Je vais essayer de "
        "mieux comprendre."
    )
# ==========================================================
# RECONNAISSANCE DES SUJETS
# ==========================================================
def get_topic_response(message):
    """
    Reconnaît les intentions fréquentes et les relie
    aux connaissances présentes dans les fichiers JSON.
    """
    normalized = normalize_text(message)
    words = set(normalized.split())
    # Identité de M7.
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
        "c est quoi m7"
    }
    if normalized in identity_questions or normalized == "m7":
        return get_identity_response()
    # Questions sur le créateur.
    creator_questions = {
        "qui t a cree",
        "qui est ton createur",
        "qui est derriere m7",
        "qui a cree m7",
        "qui a fait m7",
        "qui a construit m7",
        "qui est cheikh",
        "parle moi de cheikh"
    }
    if normalized in creator_questions:
        return get_creator_response()
    if normalized == "cheikh":
        return get_creator_response()
    creator_terms = {
        "createur", "cree", "creation", "cheikh",
        "motivation7"
    }
    identity_terms = {
        "qui", "identite", "presente", "nom",
        "parle", "raconte"
    }
    if (
        words.intersection(creator_terms)
        and words.intersection(identity_terms)
    ):
        if "cheikh" in words or "motivation7" in words:
            return get_creator_response()
        response = find_response("qui t a cree")
        if response:
            return response
        return get_creator_response()
    # Demandes de suggestions.
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
            or "idee" in words
            or "idees" in words
        )
    ):
        return get_suggestion_response()
    # Confiance en soi.
    confidence_terms = {
        "confiance", "confiant", "confiante",
        "timide", "timidite", "estime"
    }
    if words.intersection(confidence_terms):
        response = find_response(message)
        if response:
            return response
        return (
            "🌟 La confiance en soi se construit progressivement. "
            "Tu n'as pas besoin d'être parfait pour reconnaître "
            "ta valeur. Commence par identifier tes qualités, "
            "avance à ton rythme et apprends à voir les erreurs "
            "comme des occasions de progresser. ❤️\n\n"
            "Dans quelle situation aimerais-tu avoir davantage "
            "confiance en toi ?"
        )
    # Sujets reliés aux fichiers JSON.
    topic_routes = [
        (
            {"amitie", "ami", "amis", "amie"},
            "parlons de l amitie"
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
            "parlons de l honnetete"
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
            "raconte moi une lecon de vie"
        ),
        (
            {"discipline", "disciplinee", "discipliner"},
            "parle moi de discipline"
        ),
        (
            {"amour", "aimer", "amoureux", "amoureuse", "couple"},
            "parle moi d amour"
        ),
        (
            {"rupture", "separation", "coeur", "ex"},
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
            response = find_response(canonical_question)
            if response:
                return response
    # Dernière tentative : la phrase complète.
    return find_response(message)
# ==========================================================
# EMOJIS ET ÉMOTIONS
# ==========================================================
def get_emoji_response(message):
    """Reconnaît certains emojis envoyés seuls."""
    emoji_responses = {
        "❤️": (
            "❤️ Je t'envoie beaucoup de bonnes pensées, mon ami. "
            "De quoi aimerais-tu parler aujourd'hui ?"
        ),
        "❤": (
            "❤️ Je t'envoie beaucoup de bonnes pensées, mon ami."
        ),
        "🥰": (
            "🥰 Quel joli message ! Je te souhaite beaucoup "
            "de douceur et de bonheur."
        ),
        "😊": (
            "😊 Ton sourire fait plaisir ! Quoi de beau "
            "aujourd'hui ?"
        ),
        "😂": (
            "😂 Un peu de joie fait du bien ! "
            "Raconte-moi ce qui te fait rire."
        ),
        "😢": (
            "❤️ Je suis là pour t'écouter. Veux-tu me dire "
            "ce qui te rend triste ?"
        ),
        "😭": (
            "❤️ Prends ton temps. Tu peux me parler de "
            "ce que tu traverses."
        ),
        "💔": (
            "💔 Les blessures du cœur peuvent faire mal. "
            "Tu peux parler de ce que tu ressens, sans jugement."
        ),
        "🙏": (
            "🙏 Que la patience et l'espoir t'accompagnent "
            "dans les moments difficiles."
        ),
        "💪": (
            "💪 Continue d'avancer pas à pas. "
            "Même les petits progrès comptent."
        ),
        "👍": (
            "👍 Merci, mon ami ! On continue ensemble."
        ),
        "😘": (
            "❤️ Je t'envoie une pensée bienveillante !"
        )
    }
    return emoji_responses.get(message)
# ==========================================================
# SALUTATIONS ET PETITS MESSAGES
# ==========================================================
def get_simple_response(message):
    """Gère les salutations et les messages courants."""
    normalized = normalize_text(message)
    greetings = {
        "bonjour", "bonsoir", "salut", "coucou",
        "salam", "hello", "bon matin"
    }
    if normalized in greetings:
        return (
            "Salut mon ami ! ❤️ Heureux de discuter avec toi. "
            "Comment vas-tu aujourd'hui ?"
        )
    if normalized in {
        "merci",
        "merci beaucoup",
        "je te remercie"
    }:
        return (
            "Avec plaisir, mon ami ! ❤️ "
            "Tu peux continuer, je t'écoute."
        )
     # Comprend les réponses positives sur l'état de la personne.
    if normalized in {
        "cv je vais bien et toi",
        "cv ca va et toi",
        "je vais bien et toi",
        "je vais bien et vous",
        "ca va bien et toi",
        "ca va bien merci",
        "ca va merci",
        "je vais bien merci",
        "cv",
        "ca va bien"
    }:
        return (
            "Content de savoir que tu vas bien, mon ami ! ❤️ "
            "De mon côté, je suis là et prêt à discuter avec toi. 😊 "
            "De quoi aimerais-tu parler aujourd'hui ?"
        )
    if normalized in {
        "ca va",
        "comment ca va",
        "comment vas tu"
    }:
        return (
            "Je suis prêt à discuter avec toi ! 😊 "
            "Et toi, comment te sens-tu aujourd'hui ?"
        )
     # Réactions positives et appréciations.
    if normalized in {
        "c est cool",
        "c est genial",
        "c est super",
        "super",
        "genial",
        "j aime bien",
        "c est interessant"
    }:
        return (
            "Content que cela te plaise, mon ami ! 😊 "
            "Qu'est-ce qui t'a le plus plu ou fait réfléchir ?"
        )
    if normalized in {
        "oui", "oui merci", "d accord", "ok", "okay"
    }:
        return (
            "D'accord, mon ami ! ❤️ Continuons ensemble. "
            "Tu préfères parler de motivation, d'amitié, "
            "d'amour ou découvrir une histoire M7 ?"
        )
    if normalized in {
        "non", "pas vraiment"
    }:
        return (
            "Pas de problème, mon ami. ❤️ "
            "Dis-moi simplement ce que tu préfères."
        )
    return None
# ==========================================================
# MÉMOIRE DE SESSION
# ==========================================================
def get_contextual_response(message):
    """
    Utilise le sujet précédent pour mieux répondre aux
    messages courts comme 'raconte-moi une histoire'.
    Cette mémoire appartient à la session du navigateur.
    """
    normalized = normalize_text(message)
    last_topic = session.get("last_topic")
    if not last_topic:
        return None
    if normalized in {
        "continue",
        "continue stp",
        "continue s il te plait",
        "et apres",
        "ensuite",
        "raconte la suite",
        "la suite"
    }:
        return (
            "Bien sûr, mon ami ! ❤️ Je veux continuer avec toi. "
            "Peux-tu me rappeler la dernière idée ou la dernière "
            "partie dont nous parlions, pour que je poursuive "
            "dans la bonne direction ?"
        )
    if normalized in {
        "raconte une histoire",
        "raconte moi une histoire",
        "une histoire",
        "donne un exemple",
        "un exemple"
    }:
        if last_topic == "amour":
            question = "raconte une histoire d amour"
        elif last_topic == "amitie":
            question = "raconte une histoire d amitie"
        elif last_topic == "motivation":
            question = "raconte une histoire inspirante"
        else:
            question = "raconte une histoire inspirante"
        response = find_response(question)
        if response:
            return response
    return None
# ==========================================================
# COMPRENDRE LES RÉPONSES QUI SUIVENT UNE QUESTION
# ==========================================================
def get_followup_response(message):
    """
    Comprend les réponses qui suivent une discussion
    sur l'amitié et rebondit sur les valeurs exprimées.
    """
    normalized = normalize_text(message)
    words = set(normalized.split())

    last_topic = session.get("last_topic")

    if last_topic != "amitie":
        return None

    values = {
        "respect": "le respect",
        "ecoute": "l'écoute",
        "bienveillance": "la bienveillance",
        "sincerite": "la sincérité",
        "confiance": "la confiance",
        "soutien": "le soutien",
        "fidelite": "la fidélité",
        "honnetete": "l'honnêteté"
    }

    recognized_values = [
        description
        for keyword, description in values.items()
        if keyword in words
    ]

    if not recognized_values:
        return None

    if len(recognized_values) == 1:
        joined_values = recognized_values[0]
    elif len(recognized_values) == 2:
        joined_values = (
            recognized_values[0]
            + " et "
            + recognized_values[1]
        )
    else:
        joined_values = (
            ", ".join(recognized_values[:-1])
            + " et "
            + recognized_values[-1]
        )

    return (
        "Tu soulèves une valeur importante, mon ami ! ❤️ "
        "Pour toi, une vraie amitié repose notamment sur "
        + joined_values
        + ". Cette valeur contribue à construire une relation "
        "sincère dans laquelle chacun peut se sentir écouté, "
        "respecté et soutenu. 🤝\n\n"
        "Selon toi, comment reconnaît-on un véritable ami "
        "lorsqu'on traverse une période difficile ?"
    )
def remember_topic(message):
    """Enregistre le sujet principal de la discussion."""
    normalized = normalize_text(message)
    words = set(normalized.split())
    topic_keywords = {
        "amour": {
            "amour", "aimer", "amoureux",
            "amoureuse", "couple", "rupture", "coeur"
        },
        "amitie": {
            "amitie", "ami", "amis", "amie"
        },
        "motivation": {
            "motivation", "motive", "motiver",
            "courage", "perseverance", "espoir"
        },
        "confiance": {
            "confiance", "confiant", "confiante",
            "timide", "timidite"
        },
        "patience": {
            "patience", "patient", "patiente", "foi"
        },
        "histoires": {
            "histoire", "histoires", "inspirante"
        },
        "lecons": {
            "lecon", "lecons", "vie"
        }
    }
    for topic, keywords in topic_keywords.items():
        if words.intersection(keywords):
            session["last_topic"] = topic
            return
# ==========================================================
# HISTOIRES M7 EN PLUSIEURS ÉPISODES
# ==========================================================
def load_stories():
    """Charge les histoires organisées en épisodes."""
    filepath = os.path.join(DATA_DIR, "stories.json")
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            stories = json.load(file)
        if isinstance(stories, list):
            return [
                story for story in stories
                if isinstance(story, dict)
                and isinstance(story.get("episodes"), list)
                and len(story["episodes"]) > 0
            ]
    except (OSError, json.JSONDecodeError) as error:
        app.logger.warning(
            "Impossible de charger les histoires M7 : %s",
            error
        )
    return []
# ==========================================================
# PRÉSENTER LES CHOIX À LA FIN DE CHAQUE ÉPISODE
# ==========================================================
def format_story_episode(story, episode):
    """Affiche un épisode avec des indications adaptées."""
    text = episode.get("text", "")
    number = episode.get("number", 1)
    total = len(story.get("episodes", []))
    if number < total:
        return (
            text
            + "\n\n➡️ Pour continuer l'histoire, écris "
            + "\"Suivant\" ou \"Continue\".\n"
            + "📚 Pour choisir une autre histoire, écris "
            + "\"Une autre histoire\"."
        )
    return (
        text
        + "\n\n🎉 Tu as terminé cette histoire ! ❤️\n"
        + "Tu peux discuter avec M7 de cette leçon de vie."
    )
# ==========================================================
# GÉRER LE DÉBUT, LA SUITE ET LE CHANGEMENT D'HISTOIRE
# ==========================================================
def get_story_response(message):
    """Gère le début, la suite et le changement d'histoire."""
    normalized = normalize_text(message)
    continue_messages = {
        "continue",
        "encore",
        "suivant",
        "la suite",
        "continue stp",
        "continue s il te plait",
        "continue l histoire",
        "raconte la suite",
        "episode suivant",
        "episode 2",
        "episode 3"
    }
    another_story_messages = {
        "une autre",
        "une autre histoire",
        "autre histoire",
        "raconte une autre histoire",
        "je veux une autre histoire",
        "histoire suivante"
    }
    story_requests = {
        "histoire m7",
        "raconte une histoire",
        "raconte moi une histoire",
        "raconte moi une histoire m7",
        "rencontre moi une histoire",
        "une histoire",
        "histoires m7"
    }
    stories = load_stories()
    # Vérifier si la bibliothèque d'histoires est disponible.
    if not stories:
        if (
            normalized in continue_messages
            or normalized in another_story_messages
            or normalized in story_requests
        ):
            return (
                "Je voudrais te raconter une histoire, mon ami ! ❤️ "
                "Mais je n'arrive pas à charger ma bibliothèque "
                "d'histoires pour le moment."
            )
        return None
    # Retrouver l'histoire actuellement racontée.
    current_id = session.get("current_story_id")
    current_story = next(
        (
            story for story in stories
            if story.get("id") == current_id
        ),
        None
    )
    # L'utilisateur demande une autre histoire.
    if normalized in another_story_messages:
        other_stories = [
            story for story in stories
            if story.get("id") != current_id
        ]
        if other_stories:
            current_story = other_stories[0]
            session["current_story_id"] = current_story["id"]
            session["current_episode"] = 1
            return format_story_episode(
                current_story,
                current_story["episodes"][0]
            )
        return (
            "❤️ Pour le moment, je n'ai qu'une histoire en "
            "plusieurs épisodes : Le rêve de Moussa.\n\n"
            "Veux-tu continuer cette histoire ou la recommencer ?"
        )
    # L'utilisateur veut poursuivre l'histoire actuelle.
    if normalized in continue_messages and current_story:
        current_number = session.get("current_episode", 1)
        next_episode = next(
            (
                episode for episode in current_story["episodes"]
                if episode.get("number") == current_number + 1
            ),
            None
        )
        if next_episode:
            session["current_episode"] = next_episode["number"]
            return format_story_episode(
                current_story,
                next_episode
            )
        # L'histoire est terminée.
        session.pop("current_story_id", None)
        session.pop("current_episode", None)
        return (
            "🎉 Nous avons terminé cette histoire ensemble, "
            "mon ami ! ❤️\n\n"
            "Veux-tu découvrir une autre histoire M7 ?"
        )
    # L'utilisateur demande une nouvelle histoire.
    is_story_request = (
        normalized in story_requests
        or (
            "histoire" in normalized.split()
            and any(
                word in normalized.split()
                for word in {"raconte", "raconter", "propose"}
            )
        )
    )
    if is_story_request:
        current_story = stories[0]
        session["current_story_id"] = current_story["id"]
        session["current_episode"] = 1
        return format_story_episode(
            current_story,
            current_story["episodes"][0]
        )
    return None
# ==========================================================
# PAGE D'ACCUEIL
# ==========================================================
@app.route("/", methods=["GET"])
def home():
    """Affiche l'interface de M7."""
    template_path = os.path.join(
        BASE_DIR,
        "templates",
        "index.html"
    )
    root_html_path = os.path.join(
        BASE_DIR,
        "index.html"
    )
    if os.path.isfile(template_path):
        return render_template("index.html")
    if os.path.isfile(root_html_path):
        with open(
            root_html_path,
            "r",
            encoding="utf-8"
        ) as file:
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
# ==========================================================
# API DE DISCUSSION
# ==========================================================
@app.route("/api/chat", methods=["POST"])
def chat_api():
    """Reçoit un message et renvoie une réponse."""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str):
        return jsonify({
            "reply": (
                "Envoie-moi un message écrit, "
                "s'il te plaît. ❤️"
            )
        }), 400
    message = message.strip()
    if not message:
        return jsonify({
            "reply": (
                "Je suis là, mon ami. ❤️ "
                "Écris-moi ce que tu souhaites partager."
            )
        })
    # 0. Gestion des histoires M7 en épisodes.
    story_reply = get_story_response(message)
    if story_reply:
        return jsonify({"reply": story_reply})
    # 1. Reconnaissance des emojis envoyés seuls.
    emoji_reply = get_emoji_response(message)
    if emoji_reply:
        return jsonify({"reply": emoji_reply})
    # 2. Salutations et petits messages.
    simple_reply = get_simple_response(message)
    if simple_reply:
        return jsonify({"reply": simple_reply})
    # 3. Réponses sur l'identité et le créateur.
    normalized = normalize_text(message)
    if normalized in {
        "qui es tu",
        "qui es tu m7",
        "tu es qui",
        "quel est ton nom",
        "comment tu t appelles",
        "presente toi",
        "parle moi de toi"
    }:
        reply = get_identity_response()
        return jsonify({"reply": reply})
    if normalized in {
        "qui t a cree",
        "qui est ton createur",
        "qui est derriere m7",
        "qui est cheikh"
    }:
        reply = get_creator_response()
        return jsonify({"reply": reply})
    # 4. Comprend les réponses qui suivent une question.
    followup_reply = get_followup_response(message)
    if followup_reply:
        remember_topic(message)
        return jsonify({"reply": followup_reply})
    # 5. Essaie de comprendre un message lié au contexte.
    contextual_reply = get_contextual_response(message)
    if contextual_reply:
        return jsonify({"reply": contextual_reply})
    # 5. Cherche une réponse liée au sujet.
    reply = get_topic_response(message)
    # 6. Dernière recherche dans la bibliothèque.
    if not reply:
        reply = find_response(message)
    # 7. Si aucune réponse n'est disponible.
    if not reply:
        reply = fallback_response()
    # 8. Mémorise le sujet pour la prochaine réponse.
    remember_topic(message)
    return jsonify({"reply": reply})
# ==========================================================
# VÉRIFICATION DU SERVEUR
# ==========================================================
@app.route("/health", methods=["GET"])
def health_check():
    """Vérifie que le serveur fonctionne."""
    return jsonify({
        "status": "ok",
        "application": "M7 Assistant"
    })
# ==========================================================
# DÉMARRAGE LOCAL
# ==========================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
