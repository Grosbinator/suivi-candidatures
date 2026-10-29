"""Lit la boîte mail Free, repère les mails liés aux candidatures et met à jour
candidatures.csv (entreprise, poste, date de candidature, réponse et sa date).

Usage : python trier_candidatures.py (ou double-clic sur le fichier)

Tout se fait par fenêtres : connexion, lecture, puis tri des mails douteux.
Le premier lancement lit les 180 derniers jours ; les suivants reprennent à la
dernière exécution (moins une semaine de marge). Options facultatives :
    --depuis 2026-01-01        forcer la date de départ
    --dossiers INBOX Sent      lire d'autres dossiers
    --lister-dossiers          afficher les dossiers de la boîte
    --oublier-mot-de-passe     effacer le mot de passe mémorisé

Le mot de passe peut être mémorisé dans le Gestionnaire d'identification
Windows (module keyring) ; il n'est jamais écrit dans un fichier.
La boîte est ouverte en lecture seule : aucun mail n'est modifié ni marqué lu.
"""

import argparse
import csv
import hashlib
import html
import imaplib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from email import message_from_bytes
from email.policy import default
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path

import fenetres

try:
    import keyring
except ImportError:
    keyring = None

SERVEUR = "imap.free.fr"
PORT = 993
TAILLE_LOT = 50
SERVICE_KEYRING = "trier_candidatures_free"
JOURS_PREMIER_LANCEMENT = 180
JOURS_MARGE = 7

RACINE = Path(__file__).resolve().parent
FICHIER_CSV = RACINE / "candidatures.csv"
DOSSIER_EMAILS = RACINE / "Candidatures"
FICHIER_A_VERIFIER = RACINE / "a_verifier.csv"
FICHIER_ETAT = RACINE / ".etat.json"
COLONNES = [
    "id",
    "entreprise",
    "poste",
    "date_candidature",
    "confirmation_recue",
    "statut",
    "date_reponse",
    "reponse",
    "dossier_emails",
]

# Les expressions sont comparées à un texte en minuscules et sans accents.
MOTS_CONTEXTE = [
    "candidature", "postul", "application", "applied", "applying",
    "recrutement", "recruitment", "poste", "position",
]
MOTS_ALERTE = [
    "alerte emploi", "alertes emploi", "offres qui pourraient vous interesser",
    "offres d'emploi qui pourraient", "nouvelles offres", "offres recommandees",
    "jobs you may be interested", "recommended jobs", "job alert",
    "emplois recommandes", "offres similaires", "newsletter",
]
MOTS_NEGATIF = [
    "malheureusement", "ne pas donner suite", "ne pouvons pas donner suite",
    "ne pas pouvoir donner suite", "pas donner une suite favorable",
    "ne donnerons pas suite", "pas pu donner suite", "suite defavorable",
    "reponse negative", "pas ete retenue", "pas ete retenu", "pas retenue",
    "n'avons pas retenu", "pas ete selectionne", "autre candidat",
    "d'autres candidats", "d'autres profils", "regret de vous informer",
    "au regret de", "pas en mesure de donner suite", "ne correspond pas",
    "unfortunately", "not to move forward", "not moving forward",
    "will not be moving forward", "decided to pursue other candidates",
    "pursue other candidates", "regret to inform", "not been selected",
    "position has been filled", "not been successful", "were not selected",
]
MOTS_CONFIRMATION = [
    "bien recu votre candidature", "avons bien recu", "accuse de reception",
    "candidature a bien ete", "candidature a ete envoyee", "candidature envoyee",
    "candidature a ete transmise", "candidature transmise",
    "merci pour votre candidature", "merci de votre candidature",
    "remercions pour votre candidature", "remercions de votre candidature",
    "remercions de l'interet", "thank you for applying",
    "thank you for your application", "thanks for applying",
    "application has been received", "we have received your application",
    "received your application", "application was sent",
    "your application has been submitted", "candidature est en cours",
]
MOTS_POSITIF = [
    "entretien", "vous rencontrer", "echange telephonique", "echanger avec vous",
    "vos disponibilites", "votre disponibilite", "creneau", "test technique",
    "cas pratique", "visioconference", "prochaine etape", "next step",
    "interview", "schedule a call", "your availability", "meet you",
    "proposition d'embauche", "promesse d'embauche", "offer letter",
    "heureux de vous annoncer", "pleased to inform", "happy to inform",
]

# Domaines qui ne disent rien sur l'entreprise (plateformes, ATS, messageries).
DOMAINES_GENERIQUES = {
    "linkedin", "indeed", "indeedemail", "welcometothejungle", "wttj", "hellowork",
    "apec", "francetravail", "pole-emploi", "jobteaser", "meteojob", "monster",
    "cadremploi", "glassdoor", "regionsjob", "jobijoba", "workday", "myworkday",
    "myworkdayjobs", "smartrecruiters", "lever", "greenhouse", "teamtailor",
    "taleo", "successfactors", "sapsf", "recruitee", "flatchr", "jobaffinity",
    "beetween", "cornerstoneondemand", "csod", "icims", "jobvite", "softgarden",
    "talentsoft", "talent-soft", "digitalrecruiters", "werecruit", "breezy",
    "workable", "personio", "ashbyhq", "jazzhr", "bamboohr", "kelio", "gmail",
    "googlemail", "hotmail", "outlook", "live", "yahoo", "free", "orange",
    "wanadoo", "sfr", "laposte", "icloud", "me", "protonmail", "proton",
    "sendgrid", "mailgun", "amazonses", "mailchimp", "mandrillapp",
}
PLATEFORMES = {
    "linkedin": "LinkedIn", "indeed": "Indeed", "indeedemail": "Indeed",
    "welcometothejungle": "Welcome to the Jungle", "wttj": "Welcome to the Jungle",
    "hellowork": "HelloWork", "apec": "Apec", "francetravail": "France Travail",
    "pole-emploi": "France Travail", "jobteaser": "JobTeaser",
    "meteojob": "Meteojob", "monster": "Monster", "cadremploi": "Cadremploi",
}
MOTS_PARASITES_EXPEDITEUR = re.compile(
    r"\b(no[-_ ]?reply|ne[-_ ]pas[-_ ]repondre|recrutements?|recruitment|recruiting|"
    r"careers?|carrieres?|jobs?|emplois?|talents?|talent acquisition|rh|hr|"
    r"human resources|ressources humaines|team|equipe|service|notifications?|"
    r"candidates?|candidats?|hiring|via [\w .-]+)\b",
    re.I,
)

FIN_TITRE = r"(?=\s+chez\s|\s+at\s|\s+au sein\s|\s+pour\s+(?:la|le|l')\s|\s+[-–|]\s|[\n,.;!«»\"“”()\[\]]|$)"
MOTIFS_POSTE = [
    re.compile(r"\bposte\s+(?:de\s+|d['’]\s*|:\s*)?[«\"“]?\s*(?P<p>[^\n]+?)" + FIN_TITRE, re.I),
    re.compile(r"\boffre\s+(?:d['’]emploi\s+)?(?:de\s+|d['’]\s*|:\s*)?[«\"“]?\s*(?P<p>[^\n]+?)" + FIN_TITRE, re.I),
    re.compile(r"\b(?:position|role|job)\s+(?:of\s+|as\s+|:\s*)?[«\"“]?\s*(?P<p>[^\n]+?)" + FIN_TITRE, re.I),
    re.compile(r"\bcandidature\s+(?:envoy[ée]e|transmise)\s*:\s*(?P<p>[^\n]+?)" + FIN_TITRE, re.I),
    re.compile(r"^(?:(?:re|tr|fw|fwd)\s*:\s*)*(?:votre\s+)?candidature\s*[:\-–]\s*(?P<p>[^\n]+?)" + FIN_TITRE, re.I),
    re.compile(r"\bapplication\s+for\s+(?:the\s+)?(?P<p>[^\n]+?)" + FIN_TITRE, re.I),
]
MOTIFS_ENTREPRISE = [
    re.compile(r"\benvoy[ée]e\s+(?:à|a)\s+(?P<e>[^\n,.!:;]+?)(?=\s*$|[\n,.!:;]|\s+pour\s)", re.I),
    re.compile(r"\bchez\s+(?P<e>[A-Z0-9][^\n,.!:;()]{1,50}?)(?=\s*$|[\n,.!:;()]|\s+(?:a|à|pour|et)\s)"),
    re.compile(r"\bau sein (?:de\s+|d['’]\s*)(?:la société\s+|l['’]entreprise\s+)?(?P<e>[A-Z0-9][^\n,.!:;()]{1,50}?)(?=\s*$|[\n,.!:;()]|\s+(?:a|à|pour|et)\s)"),
    re.compile(r"\b(?:sent|submitted)\s+to\s+(?P<e>[A-Z0-9][^\n,.!:;()]{1,50}?)(?=\s*$|[\n,.!:;()])"),
    re.compile(r"\bapplication\s+(?:to|at|with)\s+(?P<e>[A-Z0-9][^\n,.!:;()]{1,50}?)(?=\s*$|[\n,.!:;()]|\s+for\s)"),
]
DEBUTS_INVALIDES = ("nous ", "vous ", "qui ", "que ", "le ", "la ", "les ", "un ", "une ", "votre ", "notre ", "ce ", "cette ")
COUPURES_CITATION = re.compile(
    r"^(?:le .{5,80} a [ée]crit\s*:|on .{5,80} wrote:|-{2,}\s*(?:message d'origine|original message)|de\s*:\s.+@|from:\s.+@)",
    re.I | re.M,
)


@dataclass
class Mail:
    uid: str
    dossier: str
    date: date
    expediteur: str
    destinataires: str
    sujet: str
    texte: str
    brut: bytes
    categorie: str = ""
    entreprise: str = ""
    poste: str = ""
    plateforme: str = ""

    @property
    def empreinte(self):
        return hashlib.sha1(self.brut).hexdigest()


@dataclass
class Candidature:
    entreprise: str
    poste: str = ""
    mails: list = field(default_factory=list)


def normaliser(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.replace("’", "'").lower()
    return re.sub(r"\s+", " ", texte).strip()


def cle(texte):
    return re.sub(r"[^a-z0-9]", "", normaliser(texte))


def contient(texte, expressions):
    return any(e in texte for e in expressions)


def texte_du_message(message):
    try:
        corps = message.get_body(preferencelist=("plain", "html"))
        contenu = corps.get_content() if corps else ""
        if corps is not None and corps.get_content_type() == "text/html":
            contenu = re.sub(r"(?is)<(script|style).*?</\1>", " ", contenu)
            contenu = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", contenu)
            contenu = html.unescape(re.sub(r"<[^>]+>", " ", contenu))
    except (KeyError, LookupError, ValueError):
        contenu = ""
    contenu = re.sub(r"[ \t\xa0]+", " ", contenu)
    return re.sub(r"\n\s*\n+", "\n", contenu).strip()


def sans_citation(texte):
    """Garde seulement le nouveau texte d'une réponse (sans le message cité)."""
    coupure = COUPURES_CITATION.search(texte)
    if coupure:
        texte = texte[: coupure.start()]
    return "\n".join(l for l in texte.splitlines() if not l.lstrip().startswith(">"))


def domaine_principal(adresse):
    domaine = adresse.rpartition("@")[2].lower()
    morceaux = [m for m in domaine.split(".") if m]
    if len(morceaux) >= 3 and morceaux[-2] in {"co", "com"}:
        return morceaux[-3]
    return morceaux[-2] if len(morceaux) >= 2 else domaine


def nettoyer_nom(nom):
    nom = re.sub(r"[«»\"“”]", "", nom or "").strip(" -–|:")
    return re.sub(r"\s+", " ", nom)


def classer(mail, adresse_utilisateur):
    contenu = normaliser(mail.sujet + "\n" + sans_citation(mail.texte)[:6000])
    if not contient(contenu, MOTS_CONTEXTE) or contient(contenu, MOTS_ALERTE):
        return ""
    if adresse_utilisateur and adresse_utilisateur in normaliser(mail.expediteur):
        return "envoi" if "candidature" in contenu or "postul" in contenu or "application" in contenu else ""
    if contient(contenu, MOTS_NEGATIF):
        return "negative"
    if contient(contenu, MOTS_CONFIRMATION):
        return "confirmation"
    if contient(contenu, MOTS_POSITIF):
        return "positive"
    return "inconnu"


def extraire_poste(mail):
    sujet = re.sub(r"^(?:\s*(?:re|tr|fw|fwd)\s*:\s*)+", "", mail.sujet, flags=re.I)
    for source in (sujet, sans_citation(mail.texte)[:3000]):
        for motif in MOTIFS_POSTE:
            for trouve in motif.finditer(source):
                poste = nettoyer_nom(trouve.group("p"))
                if 3 <= len(poste) <= 80 and not normaliser(poste).startswith(DEBUTS_INVALIDES):
                    return poste
    # Notifications LinkedIn : le titre du poste est sur la ligne sous « envoyée à ».
    lignes = [l.strip() for l in mail.texte.splitlines() if l.strip()]
    for rang, ligne in enumerate(lignes[:-1]):
        if re.search(r"envoy[ée]e\s+(?:à|a)\s|was sent to\s", ligne, re.I):
            poste = nettoyer_nom(lignes[rang + 1])
            if 3 <= len(poste) <= 80:
                return poste
    return ""


def extraire_entreprise(mail):
    nom_affiche, adresse = parseaddr(mail.expediteur)
    if mail.categorie == "envoi":
        destinataires = getaddresses([mail.destinataires])
        nom_affiche, adresse = destinataires[0] if destinataires else ("", "")
    domaine = domaine_principal(adresse)
    plateforme = PLATEFORMES.get(domaine, "")

    for source in (mail.sujet, sans_citation(mail.texte)[:3000]):
        for motif in MOTIFS_ENTREPRISE:
            trouve = motif.search(source)
            if trouve:
                entreprise = nettoyer_nom(trouve.group("e"))
                if 2 <= len(entreprise) <= 50 and not normaliser(entreprise).startswith(DEBUTS_INVALIDES):
                    return entreprise, plateforme

    if not plateforme:
        # Le domaine de l'entreprise est plus fiable que le nom affiché, qui est
        # souvent celui du recruteur ; sauf pour les ATS et messageries.
        if domaine and domaine not in DOMAINES_GENERIQUES:
            return domaine.capitalize(), plateforme
        nom = nettoyer_nom(MOTS_PARASITES_EXPEDITEUR.sub(" ", nom_affiche))
        if len(nom) >= 2 and "@" not in nom:
            return nom, plateforme
    return "", plateforme


def lire_mails(connexion, dossier, depuis, signaler=print):
    statut, _ = connexion.select(f'"{dossier}"', readonly=True)
    if statut != "OK":
        signaler(f"Dossier introuvable : {dossier}")
        return []
    statut, resultats = connexion.uid("search", None, "SINCE", depuis.strftime("%d-%b-%Y"))
    if statut != "OK":
        raise RuntimeError(f"Impossible de rechercher les messages dans {dossier}.")
    identifiants = resultats[0].split()
    signaler(f"{dossier} : {len(identifiants)} mails depuis le {depuis:%d/%m/%Y}")

    mails = []
    for debut in range(0, len(identifiants), TAILLE_LOT):
        lot = b",".join(identifiants[debut : debut + TAILLE_LOT])
        statut, donnees = connexion.uid("fetch", lot, "(UID BODY.PEEK[])")
        if statut != "OK":
            signaler(f"Lot illisible ({debut}–{debut + TAILLE_LOT}), ignoré.")
            continue
        for element in donnees:
            if not isinstance(element, tuple):
                continue
            uid = re.search(rb"UID (\d+)", element[0])
            message = message_from_bytes(element[1], policy=default)
            try:
                date_mail = parsedate_to_datetime(message.get("date", "")).date()
            except (TypeError, ValueError):
                continue
            mails.append(
                Mail(
                    uid=uid.group(1).decode() if uid else "",
                    dossier=dossier,
                    date=date_mail,
                    expediteur=str(message.get("from", "")),
                    destinataires=str(message.get("to", "")),
                    sujet=str(message.get("subject", "")),
                    texte=texte_du_message(message),
                    brut=element[1],
                )
            )
        signaler(f"{dossier} : {min(debut + TAILLE_LOT, len(identifiants))}/{len(identifiants)} mails lus")
    return mails


def regrouper(mails):
    """Associe chaque mail à une candidature (même entreprise, et même poste si connu)."""
    candidatures = []
    for mail in sorted(mails, key=lambda m: m.date):
        cle_entreprise, cle_poste = cle(mail.entreprise), cle(mail.poste)
        meme_entreprise = [c for c in candidatures if cle(c.entreprise) == cle_entreprise]
        cible = next((c for c in meme_entreprise if cle_poste and cle(c.poste) == cle_poste), None)
        if cible is None:
            # Sans poste précis, on rattache à la candidature la plus récente chez
            # cette entreprise ; un poste différent ou un nouvel envoi en crée une autre.
            ouvertes = [
                c for c in meme_entreprise
                if not cle_poste or not c.poste
            ]
            nouvelle_demande = mail.categorie in ("envoi", "confirmation") and any(
                m.categorie in ("negative", "positive") for c in ouvertes for m in c.mails
            )
            if ouvertes and not nouvelle_demande:
                cible = ouvertes[-1]
        if cible is None:
            cible = Candidature(entreprise=mail.entreprise, poste=mail.poste)
            candidatures.append(cible)
        if not cible.poste and mail.poste:
            cible.poste = mail.poste
        cible.mails.append(mail)
    return candidatures


def resumer(candidature):
    mails = candidature.mails
    demandes = [m for m in mails if m.categorie in ("envoi", "confirmation")]
    reponses = [m for m in mails if m.categorie in ("negative", "positive")]
    premier = demandes[0] if demandes else mails[0]
    plateformes = sorted({m.plateforme for m in mails if m.plateforme})
    resume = {
        "entreprise": candidature.entreprise,
        "poste": candidature.poste,
        "date_candidature": premier.date.isoformat() if demandes else "",
        "confirmation_recue": "oui" if any(m.categorie == "confirmation" for m in mails) else "non",
        "statut": "en attente",
        "date_reponse": "",
        "reponse": "",
    }
    if reponses:
        derniere = reponses[-1]
        resume["statut"] = derniere.categorie
        resume["date_reponse"] = derniere.date.isoformat()
        resume["reponse"] = derniere.sujet.strip()
    if plateformes:
        resume["reponse"] = (resume["reponse"] + f" (via {', '.join(plateformes)})").strip()
    return resume


def charger_csv():
    if not FICHIER_CSV.exists():
        return []
    with FICHIER_CSV.open(encoding="utf-8-sig", newline="") as fichier:
        return [dict(ligne) for ligne in csv.DictReader(fichier, delimiter=";")]


def ecrire_csv(chemin, colonnes, lignes):
    with chemin.open("w", encoding="utf-8-sig", newline="") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=colonnes, delimiter=";", extrasaction="ignore")
        ecrivain.writeheader()
        ecrivain.writerows(lignes)


def fusionner(lignes, candidature, resume):
    """Met à jour la ligne existante sans écraser ce qui a été rempli à la main."""
    cle_entreprise, cle_poste = cle(resume["entreprise"]), cle(resume["poste"])
    ligne = next(
        (l for l in lignes if cle(l["entreprise"]) == cle_entreprise and cle(l["poste"]) == cle_poste),
        None,
    ) or next(
        (l for l in lignes if cle(l["entreprise"]) == cle_entreprise and not (cle_poste and l["poste"])),
        None,
    )
    if ligne is None:
        prochain_id = max((int(l["id"]) for l in lignes if l.get("id", "").isdigit()), default=0) + 1
        ligne = {colonne: "" for colonne in COLONNES}
        ligne["id"] = str(prochain_id)
        lignes.append(ligne)

    for colonne, valeur in resume.items():
        if valeur and not ligne.get(colonne):
            ligne[colonne] = valeur
    if resume["confirmation_recue"] == "oui":
        ligne["confirmation_recue"] = "oui"
    if resume["statut"] != "en attente" and ligne.get("statut") in ("", "en attente"):
        ligne["statut"] = resume["statut"]
        ligne["date_reponse"] = resume["date_reponse"]
        ligne["reponse"] = resume["reponse"]

    if not ligne.get("dossier_emails"):
        nom = re.sub(r"[^\w-]+", "_", normaliser(ligne["entreprise"] or "inconnue")).strip("_")[:40]
        ligne["dossier_emails"] = f"Candidatures/{int(ligne['id']):03d}_{nom}"
    dossier = RACINE / ligne["dossier_emails"]
    dossier.mkdir(parents=True, exist_ok=True)
    for mail in candidature.mails:
        chemin = dossier / f"{mail.date.isoformat()}_{mail.categorie}_{mail.empreinte[:8]}.eml"
        if not chemin.exists():
            chemin.write_bytes(mail.brut)


def charger_etat():
    try:
        return json.loads(FICHIER_ETAT.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def sauver_etat(etat):
    FICHIER_ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")


# keyring peut lever des erreurs propres à chaque coffre-fort : on les ignore toutes,
# l'utilisateur retape simplement son mot de passe.
def mot_de_passe_memorise(adresse):
    if keyring is None or not adresse:
        return None
    try:
        return keyring.get_password(SERVICE_KEYRING, adresse)
    except Exception:
        return None


def memoriser_mot_de_passe(adresse, mot_de_passe):
    if keyring is not None:
        try:
            keyring.set_password(SERVICE_KEYRING, adresse, mot_de_passe)
        except Exception:
            pass


def oublier_mot_de_passe(adresse):
    if keyring is not None and adresse:
        try:
            keyring.delete_password(SERVICE_KEYRING, adresse)
        except Exception:
            pass


def se_connecter(etat):
    """Ouvre la connexion IMAP ; redemande les identifiants tant qu'ils sont refusés."""
    adresse = os.environ.get("FREE_EMAIL") or etat.get("adresse", "")
    mot_de_passe = os.environ.get("FREE_PASSWORD") or mot_de_passe_memorise(adresse)
    erreur = ""
    while True:
        saisie = None
        if not (adresse and mot_de_passe):
            saisie = fenetres.demander_identifiants(adresse, keyring is not None, erreur)
            if saisie is None:
                return None
            adresse, mot_de_passe = saisie["adresse"], saisie["mot_de_passe"]
        connexion = imaplib.IMAP4_SSL(SERVEUR, PORT, timeout=60)
        try:
            connexion.login(adresse, mot_de_passe)
        except imaplib.IMAP4.error:
            connexion.shutdown()
            oublier_mot_de_passe(adresse)
            mot_de_passe = None
            erreur = "Connexion refusée : adresse ou mot de passe incorrect."
            continue
        etat["adresse"] = adresse
        if saisie and saisie["souvenir"]:
            memoriser_mot_de_passe(adresse, mot_de_passe)
        return connexion


def date_de_depart(etat):
    """Reprend une semaine avant la dernière exécution, ou plus tôt s'il reste des mails à vérifier."""
    if "derniere_execution" not in etat:
        return date.today() - timedelta(days=JOURS_PREMIER_LANCEMENT)
    depuis = date.fromisoformat(etat["derniere_execution"]) - timedelta(days=JOURS_MARGE)
    if etat.get("plus_ancien_en_attente"):
        depuis = min(depuis, date.fromisoformat(etat["plus_ancien_en_attente"]))
    return depuis


def appliquer(mail, decision, retenus):
    if decision is None:
        return
    mail.categorie = decision["categorie"]
    mail.entreprise = decision["entreprise"]
    mail.poste = decision["poste"] or mail.poste
    retenus.append(mail)


def main():
    parametres = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parametres.add_argument("--depuis", type=date.fromisoformat,
                            help="date AAAA-MM-JJ à partir de laquelle lire (défaut : automatique)")
    parametres.add_argument("--dossiers", nargs="+", default=["INBOX"],
                            help="dossiers IMAP à lire (ex. INBOX Sent)")
    parametres.add_argument("--lister-dossiers", action="store_true",
                            help="affiche les dossiers de la boîte puis s'arrête")
    parametres.add_argument("--oublier-mot-de-passe", action="store_true",
                            help="efface le mot de passe mémorisé puis s'arrête")
    options = parametres.parse_args()

    etat = charger_etat()
    if options.oublier_mot_de_passe:
        oublier_mot_de_passe(etat.get("adresse"))
        print("Mot de passe oublié.")
        return

    try:
        connexion = se_connecter(etat)
    except OSError as erreur:
        fenetres.signaler_erreur("Connexion impossible", f"Impossible de joindre {SERVEUR} :\n{erreur}")
        return
    if connexion is None:
        return
    sauver_etat(etat)
    depuis = options.depuis or date_de_depart(etat)

    def lire(signaler):
        try:
            if options.lister_dossiers:
                return [ligne.decode(errors="replace") for ligne in connexion.list()[1]]
            mails = []
            for dossier in options.dossiers:
                mails.extend(lire_mails(connexion, dossier, depuis, signaler))
            return mails
        finally:
            try:
                connexion.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    try:
        mails = fenetres.executer_avec_progression("Lecture des mails", lire)
    except (imaplib.IMAP4.error, OSError, RuntimeError) as erreur:
        fenetres.signaler_erreur("Lecture impossible", str(erreur))
        return
    if options.lister_dossiers:
        print("\n".join(mails))
        fenetres.informer("Dossiers de la boîte", "\n".join(mails))
        return

    retenus, a_verifier = [], []
    for mail in mails:
        mail.categorie = classer(mail, normaliser(etat["adresse"]))
        if not mail.categorie:
            continue
        mail.entreprise, mail.plateforme = extraire_entreprise(mail)
        mail.poste = extraire_poste(mail)
        if mail.categorie == "inconnu" or not mail.entreprise:
            a_verifier.append(mail)
        else:
            retenus.append(mail)

    # Les mails déjà tranchés lors d'un lancement précédent ne sont pas reproposés.
    decisions = etat.setdefault("decisions", {})
    en_attente = []
    for mail in sorted(a_verifier, key=lambda m: m.date):
        if mail.empreinte in decisions:
            appliquer(mail, decisions[mail.empreinte], retenus)
        else:
            en_attente.append(mail)
    restants = en_attente
    if en_attente:
        entreprises = {l["entreprise"] for l in charger_csv() if l["entreprise"]}
        entreprises |= {m.entreprise for m in retenus if m.entreprise}
        choix = fenetres.verifier_mails(en_attente, entreprises)
        for indice, decision in choix.items():
            decisions[en_attente[indice].empreinte] = decision
            appliquer(en_attente[indice], decision, retenus)
        restants = [m for indice, m in enumerate(en_attente) if indice not in choix]
        sauver_etat(etat)

    lignes = charger_csv()
    candidatures = regrouper(retenus)
    for candidature in candidatures:
        fusionner(lignes, candidature, resumer(candidature))
    lignes.sort(key=lambda l: int(l["id"]) if l.get("id", "").isdigit() else 0)
    ecrire_csv(FICHIER_CSV, COLONNES, lignes)

    ecrire_csv(
        FICHIER_A_VERIFIER,
        ["date", "dossier", "uid", "categorie", "entreprise", "poste", "expediteur", "sujet"],
        [
            {
                "date": m.date.isoformat(), "dossier": m.dossier, "uid": m.uid,
                "categorie": m.categorie, "entreprise": m.entreprise, "poste": m.poste,
                "expediteur": m.expediteur, "sujet": m.sujet,
            }
            for m in restants
        ],
    )

    etat["derniere_execution"] = date.today().isoformat()
    etat["plus_ancien_en_attente"] = restants[0].date.isoformat() if restants else ""
    sauver_etat(etat)

    compte = {c: sum(m.categorie == c for m in retenus) for c in ("envoi", "confirmation", "positive", "negative")}
    bilan = (
        f"{len(mails)} mails lus depuis le {depuis:%d/%m/%Y}.\n"
        f"{len(retenus)} liés à des candidatures : {compte['envoi']} envois, "
        f"{compte['confirmation']} accusés de réception, {compte['positive']} réponses positives, "
        f"{compte['negative']} négatives.\n"
        f"{len(lignes)} candidatures au total dans {FICHIER_CSV.name}."
    )
    if restants:
        bilan += f"\n\n{len(restants)} mail(s) passé(s), reproposé(s) au prochain lancement."
    print(bilan)
    if fenetres.informer("Candidatures à jour", bilan, proposer_ouverture=True):
        os.startfile(FICHIER_CSV)


if __name__ == "__main__":
    main()
