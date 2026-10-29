import getpass
import imaplib
from email import message_from_bytes
from email.policy import default

SERVEUR = "imap.free.fr"
PORT = 993
NOMBRE_DE_MESSAGES = 10


def main():
    adresse = input("Adresse mail Free : ").strip()
    mot_de_passe = getpass.getpass("Mot de passe : ")

    connexion = imaplib.IMAP4_SSL(SERVEUR, PORT, timeout=30)

    try:
        connexion.login(adresse, mot_de_passe)

        # Lecture seule : les messages ne sont pas marqués comme lus.
        statut, _ = connexion.select("INBOX", readonly=True)
        if statut != "OK":
            raise RuntimeError("Impossible d'ouvrir la boîte de réception.")

        statut, resultats = connexion.uid("search", None, "ALL")
        if statut != "OK":
            raise RuntimeError("Impossible de rechercher les messages.")

        identifiants = resultats[0].split()[-NOMBRE_DE_MESSAGES:]

        for identifiant in reversed(identifiants):
            statut, donnees = connexion.uid(
                "fetch", identifiant, "(BODY.PEEK[HEADER])"
            )
            if statut != "OK":
                print(f"Impossible de lire l'en-tête du message {identifiant.decode()}.")
                continue

            contenu = next(
                (element[1] for element in donnees if isinstance(element, tuple)),
                None,
            )
            if contenu is None:
                continue

            message = message_from_bytes(contenu, policy=default)
            print(
                f"Date : {message.get('date', '')}\n"
                f"De : {message.get('from', '')}\n"
                f"Sujet : {message.get('subject', '')}\n"
                "---"
            )

    finally:
        connexion.logout()


if __name__ == "__main__":
    main()