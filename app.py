from flask import Flask, render_template, request, jsonify, session
import json
import os
import re
import unicodedata
import random
from difflib import SequenceMatcher
# ==========================================================
# CONFIGURATION DE M7
# ==========================================================
app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "m7-cle-temporaire-a-remplacer-en-production"
)
MAX_MESSAGE_LENGTH = 2000
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
        char for char in text
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
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
# CHARGEMENT DES CONNAISSANCES JSON
# ==========================================================
def load_knowledge():
    """
    Charge les fichiers JSON situés à la racine
    et dans le dossier data.
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
    for filepath in sorted(set(files_to_read)):
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
                if clean_patterns:
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
        "M7 a chargé %s connaissances JSON.",
        len(knowledge)
    )
    return knowledge
# ==========================================================
# CORRESPONDANCE ENTRE UN MESSAGE ET LES CONNAISSANCES
# ==========================================================
def score_pattern(message, pattern):
    """Évalue la ressemblance entre un message et un exemple."""
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
                None, message, pattern
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
def find_response(message):
    """Recherche la réponse connue la plus pertinente."""
    normalized = normalize_text(message)
    if not normalized:
        return None
    candidates = []
    for item in load_knowledge():
        best_score = max(
            (
                score_pattern(normalized, pattern)
                for pattern in item["patterns"]
            ),
            default=0.0
        )
        if best_score > 0:
            candidates.append({
                "score": best_score,
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
# MÉMOIRE CONVERSATIONNELLE
# ==========================================================
def remember_bot_question(reply):
    """Mémorise la dernière question posée par M7."""
    if not isinstance(reply, str):
        return
    questions = re.findall(
        r"([^?]{1,300}\?)",
        reply,
        flags=re.DOTALL
    )
    if questions:
        session["last_bot_question"] = questions[-1].strip()
    else:
        session.pop("last_bot_question", None)
def remember_topic(message):
    """Actualise le sujet quand un nouveau sujet est détecté."""
    normalized = normalize_text(message)
    words = set(normalized.split())
    topic_keywords = {
        "amour": {
            "amour", "aimer", "amoureux", "amoureuse",
            "couple", "rupture", "coeur", "ex"
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
            "timide", "timidite", "estime"
        },
        "patience": {
            "patience", "patient", "patiente",
            "foi", "epreuve", "epreuves"
        },
        "histoires": {
            "histoire", "histoires", "inspirante"
        },
        "lecons": {
            "lecon", "lecons"
        }
    }
    # Les messages très courts ne doivent pas effacer
    # automatiquement le sujet de la conversation.
    if normalized in {
        "oui", "non", "ok", "okay", "merci",
        "continue", "suivant", "la suite",
        "d accord", "bien sur"
    }:
        return
    # Un sujet n'est modifié que si un indice est détecté.
    for topic, keywords in topic_keywords.items():
        if words.intersection(keywords):
            session["last_topic"] = topic
            return
def create_chat_response(reply, message=None):
    """Prépare la réponse et conserve le contexte utile."""
    if not isinstance(reply, str) or not reply.strip():
        reply = (
            "Je suis là, mon ami ! ❤️ "
            "Peux-tu m'expliquer ce que tu souhaites partager ?"
        )
    if isinstance(message, str) and message.strip():
        session["last_user_message"] = message.strip()[:MAX_MESSAGE_LENGTH]
        remember_topic(message)
    remember_bot_question(reply)
    session.modified = True
    return jsonify({"reply": reply})
# ==========================================================
# SUJETS DE DISCUSSION
# ==========================================================
def get_suggestion_response():
    return (
        "Avec plaisir ! ❤️ Voici quelques sujets à explorer :\n\n"
        "💪 Motivation : retrouver le courage et avancer.\n"
        "🌟 Confiance en soi : reconnaître ta valeur.\n"
        "🤝 Amitié : comprendre les relations sincères.\n"
        "🧠 Leçons de vie : réfléchir à nos choix.\n"
        "🙏 Foi et patience : garder espoir pendant les épreuves.\n"
        "❤️ Amour : parler des relations et des déceptions.\n"
        "🎬 Histoires M7 : découvrir des histoires inspirantes.\n\n"
        "Quel sujet aimerais-tu découvrir en premier ?"
    )
# ==========================================================
# IDENTITÉ DE M7 ET SON CRÉATEUR
# ==========================================================
def get_identity_response():
    response = find_response("qui es tu")
    if response:
        return response
    return (
        "Salut mon ami ! ❤️ Je suis M7, l'assistant de Motivation7. "
        "Je suis là pour discuter avec toi, partager des conseils "
        "et réfléchir ensemble à des leçons de vie.\n\n"
        "Je fonctionne grâce à mon code et aux connaissances "
        "qui m'ont été ajoutées. Je suis encore en développement "
        "et je peux parfois mal comprendre un message."
    )
def get_creator_response():
    response = find_response("qui est cheikh")
    if response:
        return response
    return (
        "M7 est un projet de Motivation7 créé par Cheikh "
        "avec l'aide de ChatGPT. ❤️ Il a été construit "
        "progressivement grâce aux idées, aux essais et au travail "
        "de son créateur.\n\n"
        "M7 continue d'évoluer à mesure que son code et "
        "ses connaissances sont améliorés."
    )
# ==========================================================
# SALUTATIONS ET EMOJIS
# ==========================================================
def get_emoji_response(message):
    """Reconnaît certains messages constitués d'emojis."""
    emoji_responses = {
        "❤️": (
            "❤️ Merci pour cette belle attention, mon ami ! "
            "De quoi aimerais-tu parler aujourd'hui ?"
        ),
        "❤": "❤️ Je t'envoie une pensée bienveillante, mon ami.",
        "🥰": "🥰 Quel joli message ! Je te souhaite beaucoup de douceur.",
        "😊": "😊 Ton sourire fait plaisir ! Quoi de beau aujourd'hui ?",
        "😂": "😂 Un peu de joie fait du bien ! Qu'est-ce qui te fait rire ?",
        "😢": "❤️ Je suis là pour t'écouter. Veux-tu me dire ce qui te rend triste ?",
        "😭": "❤️ Prends ton temps. Tu peux me parler de ce que tu traverses.",
        "💔": "💔 Les blessures du cœur peuvent faire mal. Tu peux en parler sans jugement.",
        "🙏": "🙏 Que la patience et l'espoir t'accompagnent dans les moments difficiles.",
        "💪": "💪 Continue d'avancer pas à pas. Même les petits progrès comptent.",
        "👍": "👍 Merci, mon ami ! On continue ensemble.",
        "😘": "❤️ Je t'envoie une pensée bienveillante !"
    }
    return emoji_responses.get(message.strip())
def get_simple_response(message):
    """Gère les salutations et les réponses courantes."""
    normalized = normalize_text(message)
    if normalized in {
        "bonjour", "bonsoir", "salut", "coucou",
        "salam", "hello", "bon matin"
    }:
        return (
            "Salut mon ami ! ❤️ Heureux de discuter avec toi. "
            "Comment vas-tu aujourd'hui ?"
        )
    if normalized in {
        "merci", "merci beaucoup", "je te remercie"
    }:
        return "Avec plaisir, mon ami ! ❤️ Je t'écoute."
    if normalized in {
        "ca va", "comment ca va", "comment vas tu"
    }:
        return (
            "Je suis prêt à discuter avec toi ! 😊 "
            "Et toi, comment te sens-tu aujourd'hui ?"
        )
    if normalized in {
        "je vais bien", "je vais bien merci",
        "ca va bien", "ca va bien merci",
        "je vais bien et toi", "ca va bien et toi",
        "cv", "cv je vais bien et toi"
    }:
        return (
            "Content de savoir que tu vas bien ! ❤️ "
            "De quoi aimerais-tu parler aujourd'hui ?"
        )
    if normalized in {
        "c est cool", "c est genial", "c est super",
        "super", "genial", "j aime bien",
        "c est interessant"
    }:
        return (
            "Content que cela te plaise ! 😊 "
            "Qu'est-ce qui t'a le plus intéressé ?"
        )
    return None
# ==========================================================
# COMPRÉHENSION DES RÉPONSES COURTES
# ==========================================================
def get_contextual_response(message):
    """Interprète une réponse courte dans son contexte."""
    normalized = normalize_text(message)
    last_topic = session.get("last_topic")
    last_question = normalize_text(
        session.get("last_bot_question", "")
    )
    positive_answers = {
        "oui", "oui merci", "d accord", "ok", "okay",
        "bien sur", "exactement", "tout a fait"
    }
    negative_answers = {
        "non", "pas vraiment", "pas trop", "non merci"
    }
    continuation_messages = {
        "continue", "continue stp", "continue s il te plait",
        "et apres", "ensuite", "raconte la suite",
        "la suite", "suivant"
    }
    if normalized in continuation_messages:
        if session.get("current_story_id"):
            return None
        if last_topic == "amour":
            return (
                "Bien sûr, mon ami ! ❤️ Continuons à parler d'amour. "
                "Une relation saine se construit avec le respect, "
                "le dialogue et des actes sincères. "
                "Quel aspect aimerais-tu approfondir ?"
            )
        if last_topic == "amitie":
            return (
                "Avec plaisir ! 🤝 Une amitié sincère se reconnaît "
                "souvent dans les actes, particulièrement quand "
                "la vie devient difficile. Quel aspect de l'amitié "
                "voudrais-tu explorer davantage ?"
            )
        if last_topic == "motivation":
            return (
                "Continuons ! 💪 Les progrès viennent souvent "
                "de petites actions répétées. Quel objectif "
                "aimerais-tu atteindre ?"
            )
        return (
            "Bien sûr, mon ami ! ❤️ Continuons notre discussion. "
            "Dis-moi ce que tu aimerais approfondir."
        )
    if normalized in positive_answers:
        # Si M7 vient de poser une question précise,
        # on évite de faire comme si l'utilisateur avait
        # donné une longue réponse.
        if last_question:
            if any(word in last_question.split() for word in {
                "aide", "ecouter", "ecoute", "penses",
                "crois", "selon", "veux", "prefere"
            }):
                if last_topic == "amitie":
                    return (
                        "Je comprends, mon ami ! ❤️ "
                        "Ton avis compte dans cette réflexion sur "
                        "l'amitié. Une relation sincère demande "
                        "de l'écoute, du respect et de la présence.\n\n"
                        "Qu'est-ce qui te paraît le plus important "
                        "dans une amitié : l'écoute, la loyauté "
                        "ou le soutien dans les moments difficiles ?"
                    )
        return None
    if normalized in negative_answers:
        return (
            "D'accord, mon ami. ❤️ Nous pouvons voir les choses "
            "autrement ou changer de sujet. Qu'est-ce qui te "
            "correspondrait le mieux ?"
        )
    if normalized in {
        "raconte une histoire", "raconte moi une histoire",
        "une histoire", "donne un exemple", "un exemple"
    }:
        if last_topic == "amour":
            response = find_response("raconte une histoire d amour")
        elif last_topic == "amitie":
            response = find_response("raconte une histoire d amitie")
        else:
            response = find_response("raconte une histoire inspirante")
        if response:
            return response
    return None
# ==========================================================
# RÉPONSES QUI SUIVENT LES IDÉES DE L'UTILISATEUR
# ==========================================================
def get_followup_response(message):
    """Rebondit sur les idées exprimées par l'utilisateur."""
    normalized = normalize_text(message)
    words = set(normalized.split())
    last_topic = session.get("last_topic")
    if not last_topic:
        return None
    if last_topic == "amitie":
        staying_keywords = {
            "reste", "rester", "restez", "toujours",
            "abandonne", "abandonner", "cote", "present",
            "presence", "difficile", "difficultes",
            "moment", "moments", "epreuve", "epreuves"
        }
        support_keywords = {
            "aide", "aider", "soutien", "soutenir",
            "ecoute", "ecouter", "conseil", "conseiller",
            "comprendre", "comprend", "respect",
            "sincere", "sincerite", "loyaute", "fidele"
        }
        if words.intersection(staying_keywords):
            return (
                "Je comprends ce que tu veux dire, mon ami. ❤️ "
                "Pour toi, l'amitié se révèle surtout quand la vie "
                "devient difficile. C'est souvent dans ces moments "
                "que l'on découvre qui reste présent, qui écoute "
                "et qui nous soutient sincèrement. 🤝\n\n"
                "Mais un véritable ami n'est pas obligé d'avoir "
                "toutes les solutions. Parfois, sa présence suffit "
                "déjà à nous donner du courage.\n\n"
                "Selon toi, comment peut-on distinguer un ami "
                "sincère d'une personne qui reste seulement "
                "quand tout va bien ?"
            )
        if words.intersection(support_keywords):
            return (
                "Tu soulèves quelque chose d'important ! ❤️ "
                "L'aide, l'écoute et le respect peuvent être "
                "des preuves d'une amitié sincère. Un ami ne "
                "résout pas toujours nos problèmes, mais il peut "
                "nous aider à nous sentir moins seuls. 🤝\n\n"
                "Selon toi, lorsqu'un ami traverse une épreuve, "
                "est-il parfois plus important de l'écouter "
                "que de lui donner immédiatement un conseil ?"
            )
    if last_topic == "amour":
        love_keywords = {
            "respect", "sincere", "sincerite", "fidele",
            "fidelite", "confiance", "ecoute", "dialogue",
            "honnete", "comprendre", "compris", "aime",
            "aimer", "soutien", "trahison", "mensonge"
        }
        if words.intersection(love_keywords):
            return (
                "Tu évoques un élément important dans une relation. ❤️ "
                "Le respect, la confiance et le dialogue aident "
                "deux personnes à mieux se comprendre. L'amour "
                "ne repose pas seulement sur les paroles : il "
                "se voit aussi dans les actes.\n\n"
                "À ton avis, lorsqu'une confiance a été blessée, "
                "quels actes peuvent aider à la reconstruire ?"
            )
    if last_topic == "motivation":
        motivation_keywords = {
            "objectif", "reussir", "reussite", "courage",
            "effort", "efforts", "travail", "perseverer",
            "abandonner", "continuer", "avancer",
            "discipline", "patience", "espoir"
        }
        if words.intersection(motivation_keywords):
            return (
                "C'est une idée intéressante ! 💪 La motivation "
                "peut nous aider à commencer, tandis que la "
                "discipline nous aide à continuer même lorsque "
                "l'envie diminue.\n\n"
                "Quel petit pas réaliste pourrais-tu faire "
                "aujourd'hui pour avancer vers ton objectif ?"
            )
    if last_topic == "confiance":
        confidence_keywords = {
            "peur", "timide", "timidite", "courage", "oser",
            "erreur", "erreurs", "qualite", "qualites",
            "capacite", "capacites", "confiance",
            "progresser", "apprendre"
        }
        if words.intersection(confidence_keywords):
            return (
                "Je comprends ton idée. 🌟 La confiance en soi "
                "se construit avec le temps. Tu peux reconnaître "
                "tes qualités tout en continuant à apprendre. "
                "Faire une erreur ne signifie pas que tu es incapable.\n\n"
                "Dans quelle situation aimerais-tu te sentir "
                "plus à l'aise ou plus sûr de toi ?"
            )
    if last_topic == "patience":
        patience_keywords = {
            "attendre", "attente", "temps", "difficile",
            "epreuve", "epreuves", "calme", "espoir",
            "foi", "patient", "patience", "perseverer"
        }
        if words.intersection(patience_keywords):
            return (
                "Tu soulèves un point important. 🙏 La patience "
                "ne signifie pas rester sans rien faire. Elle "
                "peut consister à poursuivre ses efforts tout en "
                "acceptant que certains résultats prennent du temps.\n\n"
                "Qu'est-ce qui t'aide à garder espoir lorsque "
                "la situation devient difficile ?"
            )
    return None
# ==========================================================
# RECONNAISSANCE DES SUJETS
# ==========================================================
def get_topic_response(message):
    """Dirige le message vers le sujet ou la connaissance adaptée."""
    normalized = normalize_text(message)
    words = set(normalized.split())
    if normalized in {
        "qui es tu", "qui es tu m7", "tu es qui",
        "tu es quoi", "quel est ton nom",
        "comment tu t appelles", "presente toi",
        "parle moi de toi", "dis moi qui tu es", "m7"
    }:
        return get_identity_response()
    if normalized in {
        "qui t a cree", "qui est ton createur",
        "qui est derriere m7", "qui a cree m7",
        "qui a fait m7", "qui a construit m7",
        "qui est cheikh", "parle moi de cheikh", "cheikh"
    }:
        return get_creator_response()
    suggestion_terms = {
        "propose", "proposes", "sujet", "sujets",
        "interesser", "interesse", "idee", "idees"
    }
    if words.intersection(suggestion_terms):
        return get_suggestion_response()
    if words.intersection({
        "confiance", "confiant", "confiante",
        "timide", "timidite", "estime"
    }):
        response = find_response(message)
        if response:
            return response
        return (
            "🌟 La confiance en soi se construit progressivement. "
            "Tu n'as pas besoin d'être parfait pour reconnaître "
            "ta valeur. Commence par identifier tes qualités et "
            "avance à ton rythme. ❤️\n\n"
            "Dans quelle situation aimerais-tu avoir davantage "
            "confiance en toi ?"
        )
    topic_routes = [
        ({"amitie", "ami", "amis", "amie"}, "parlons de l amitie"),
        ({"motivation", "motive", "motiver", "courage"}, "je veux de la motivation"),
        ({"patience", "patient", "patiente", "foi"}, "parlons de la patience"),
        ({"respect", "respecter"}, "parlons du respect"),
        ({"honnetete", "honnete"}, "parlons de l honnetete"),
        ({"pardon", "pardonner", "blessure"}, "parlons du pardon"),
        ({"choix", "decision", "decider"}, "parlons des choix"),
        ({"lecon", "lecons"}, "raconte moi une lecon de vie"),
        ({"discipline", "discipliner"}, "parle moi de discipline"),
        ({"amour", "aimer", "amoureux", "amoureuse", "couple"}, "parle moi d amour"),
        ({"rupture", "separation", "coeur", "ex"}, "comment oublier mon ex"),
        ({"solitude", "seul", "seule", "triste", "emotions"}, "je me sens seul"),
        ({"perseverance", "abandonner", "espoir"}, "perseverance"),
        ({"histoire", "histoires", "inspirante"}, "raconte une histoire inspirante")
    ]
    for topic_words, canonical_question in topic_routes:
        if words.intersection(topic_words):
            response = find_response(canonical_question)
            if response:
                return response
    return find_response(message)
# ==========================================================
# HISTOIRES M7 EN ÉPISODES
# ==========================================================
def load_stories():
    """Charge les histoires depuis data/stories.json."""
    filepath = os.path.join(DATA_DIR, "stories.json")
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            stories = json.load(file)
        if isinstance(stories, list):
            return [
                story for story in stories
                if isinstance(story, dict)
                and isinstance(story.get("episodes"), list)
                and story["episodes"]
            ]
    except (OSError, json.JSONDecodeError) as error:
        app.logger.warning(
            "Impossible de charger les histoires M7 : %s",
            error
        )
    return []
def format_story_episode(story, episode):
    """Présente un épisode et les choix de continuation."""
    text = episode.get("text", "")
    number = episode.get("number", 1)
    total = len(story.get("episodes", []))
    if number < total:
        return (
            text
            + '\n\n➡️ Pour continuer, écris "Suivant" ou "Continue".'
            + '\n📚 Pour changer d’histoire, écris "Une autre histoire".'
        )
    return (
        text
        + "\n\n🎉 Tu as terminé cette histoire ! ❤️"
        + "\nTu peux discuter avec M7 de cette leçon de vie."
    )
def get_story_response(message):
    """Gère les demandes et la progression des histoires."""
    normalized = normalize_text(message)
    continue_messages = {
        "continue", "encore", "suivant", "la suite",
        "continue stp", "continue s il te plait",
        "continue l histoire", "raconte la suite",
        "episode suivant", "episode 2", "episode 3"
    }
    another_story_messages = {
        "une autre", "une autre histoire", "autre histoire",
        "raconte une autre histoire", "je veux une autre histoire",
        "histoire suivante"
    }
    story_requests = {
        "histoire m7", "raconte une histoire",
        "raconte moi une histoire", "raconte moi une histoire m7",
        "rencontre moi une histoire", "une histoire", "histoires m7"
    }
    stories = load_stories()
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
    current_id = session.get("current_story_id")
    current_story = next(
        (
            story for story in stories
            if story.get("id") == current_id
        ),
        None
    )
    if normalized in another_story_messages:
        other_stories = [
            story for story in stories
            if story.get("id") != current_id
        ]
        if other_stories:
            current_story = other_stories[0]
            session["current_story_id"] = current_story["id"]
            session["current_episode"] = current_story["episodes"][0].get("number", 1)
            return format_story_episode(
                current_story,
                current_story["episodes"][0]
            )
        return (
            "❤️ Pour le moment, je n'ai qu'une histoire disponible. "
            "Veux-tu continuer cette histoire ou la recommencer ?"
        )
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
            session["current_episode"] = next_episode.get("number", current_number + 1)
            return format_story_episode(
                current_story,
                next_episode
            )
        session.pop("current_story_id", None)
        session.pop("current_episode", None)
        return (
            "🎉 Nous avons terminé cette histoire ensemble, "
            "mon ami ! ❤️\n\nVeux-tu découvrir une autre histoire M7 ?"
        )
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
        first_episode = current_story["episodes"][0]
        session["current_story_id"] = current_story.get("id")
        session["current_episode"] = first_episode.get("number", 1)
        return format_story_episode(
            current_story,
            first_episode
        )
    return None
# ==========================================================
# PAGE D'ACCUEIL
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
            return app.response_class(
                file.read(),
                mimetype="text/html"
            )
    return (
        "M7 Assistant : fichier index.html introuvable.",
        404
    )
# ==========================================================
# API DE DISCUSSION
# ==========================================================
@app.route("/api/chat", methods=["POST"])
def chat_api():
    """Reçoit un message et renvoie une réponse JSON."""
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", "")
        if not isinstance(message, str):
            return jsonify({
                "reply": "Envoie-moi un message écrit, s'il te plaît. ❤️"
            }), 400
        message = message.strip()
        if not message:
            return create_chat_response(
                "Je suis là, mon ami. ❤️ "
                "Écris-moi ce que tu souhaites partager."
            )
        if len(message) > MAX_MESSAGE_LENGTH:
            return create_chat_response(
                "Ton message est un peu long, mon ami. ❤️ "
                "Peux-tu le raccourcir pour que je puisse mieux "
                "le comprendre ?"
            )
        normalized = normalize_text(message)
        # 1. Histoires et épisodes.
        story_reply = get_story_response(message)
        if story_reply:
            return create_chat_response(story_reply, message)
        # 2. Identité et créateur.
        if normalized in {
            "qui es tu", "qui es tu m7", "tu es qui",
            "quel est ton nom", "comment tu t appelles",
            "presente toi", "parle moi de toi", "m7"
        }:
            return create_chat_response(
                get_identity_response(), message
            )
        if normalized in {
            "qui t a cree", "qui est ton createur",
            "qui est derriere m7", "qui a cree m7",
            "qui est cheikh", "cheikh"
        }:
            return create_chat_response(
                get_creator_response(), message
            )
        # 3. Emojis envoyés seuls.
        emoji_reply = get_emoji_response(message)
        if emoji_reply:
            return create_chat_response(emoji_reply, message)
        # 4. Salutations et réponses courantes.
        simple_reply = get_simple_response(message)
        if simple_reply:
            return create_chat_response(simple_reply, message)
        # 5. Réponses courtes et contexte.
        contextual_reply = get_contextual_response(message)
        if contextual_reply:
            return create_chat_response(
                contextual_reply, message
            )
        # 6. Réactions liées au sujet de discussion.
        followup_reply = get_followup_response(message)
        if followup_reply:
            return create_chat_response(
                followup_reply, message
            )
        # 7. Recherche d'une réponse adaptée aux connaissances.
        reply = get_topic_response(message)
        if not reply:
            reply = find_response(message)
        # 8. Réponse de secours.
        if not reply:
            reply = fallback_response()
        return create_chat_response(reply, message)
    except Exception:
        app.logger.exception(
            "Erreur inattendue pendant le traitement d'un message M7."
        )
        return jsonify({
            "reply": (
                "Je rencontre un petit problème en préparant "
                "ma réponse, mon ami. ❤️ Réessaie dans un instant."
            )
        }), 500
def fallback_response():
    """Répond lorsque M7 ne trouve pas de correspondance fiable."""
    return (
        "Je veux bien en discuter avec toi. ❤️ "
        "Je ne suis pas encore certain de comprendre exactement "
        "ce que tu souhaites.\n\n"
        "Peux-tu me donner un peu plus de détails ? "
        "Je vais essayer de mieux comprendre ton idée."
    )
# ==========================================================
# VÉRIFICATION DU SERVEUR
# ==========================================================
@app.route("/health", methods=["GET"])
def health_check():
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
