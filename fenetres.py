"""Fenêtres Tkinter : connexion, progression et vérification des mails douteux."""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

DECISIONS = [
    ("J'ai postulé", "envoi"),
    ("Accusé de réception", "confirmation"),
    ("Réponse positive", "positive"),
    ("Réponse négative", "negative"),
]
LIBELLES = {
    "envoi": "candidature envoyée",
    "confirmation": "accusé de réception",
    "positive": "réponse positive",
    "negative": "réponse négative",
    "inconnu": "lié à une candidature, type inconnu",
}


def centrer(fenetre):
    fenetre.update_idletasks()
    largeur, hauteur = fenetre.winfo_width(), fenetre.winfo_height()
    x = (fenetre.winfo_screenwidth() - largeur) // 2
    y = (fenetre.winfo_screenheight() - hauteur) // 3
    fenetre.geometry(f"+{x}+{y}")


def demander_identifiants(adresse="", proposer_souvenir=False, erreur=""):
    """Retourne {adresse, mot_de_passe, souvenir} ou None si l'utilisateur annule."""
    fenetre = tk.Tk()
    fenetre.title("Connexion à la boîte Free")
    fenetre.resizable(False, False)
    resultat = {}

    cadre = ttk.Frame(fenetre, padding=16)
    cadre.grid()
    if erreur:
        ttk.Label(cadre, text=erreur, foreground="#b00020", wraplength=300).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
    ttk.Label(cadre, text="Adresse mail Free").grid(row=1, column=0, columnspan=2, sticky="w")
    champ_adresse = ttk.Entry(cadre, width=40)
    champ_adresse.insert(0, adresse)
    champ_adresse.grid(row=2, column=0, columnspan=2, sticky="we", pady=(2, 8))
    ttk.Label(cadre, text="Mot de passe").grid(row=3, column=0, columnspan=2, sticky="w")
    champ_mot_de_passe = ttk.Entry(cadre, width=40, show="•")
    champ_mot_de_passe.grid(row=4, column=0, columnspan=2, sticky="we", pady=(2, 8))
    souvenir = tk.BooleanVar(value=proposer_souvenir)
    if proposer_souvenir:
        ttk.Checkbutton(
            cadre, text="Se souvenir de moi (Gestionnaire d'identification Windows)", variable=souvenir
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 8))

    def valider(_evenement=None):
        if not champ_adresse.get().strip() or not champ_mot_de_passe.get():
            return
        resultat.update(
            adresse=champ_adresse.get().strip(),
            mot_de_passe=champ_mot_de_passe.get(),
            souvenir=souvenir.get(),
        )
        fenetre.destroy()

    ttk.Button(cadre, text="Annuler", command=fenetre.destroy).grid(row=6, column=0, sticky="w")
    ttk.Button(cadre, text="Se connecter", command=valider).grid(row=6, column=1, sticky="e")
    fenetre.bind("<Return>", valider)
    (champ_mot_de_passe if adresse else champ_adresse).focus_set()
    centrer(fenetre)
    fenetre.mainloop()
    return resultat or None


def executer_avec_progression(titre, travail):
    """Lance travail(signaler) dans un fil séparé en affichant ses messages."""
    fenetre = tk.Tk()
    fenetre.title(titre)
    fenetre.resizable(False, False)
    texte = tk.StringVar(value="Connexion…")
    cadre = ttk.Frame(fenetre, padding=16)
    cadre.grid()
    ttk.Label(cadre, textvariable=texte, width=50).grid(row=0, column=0, sticky="w", pady=(0, 8))
    barre = ttk.Progressbar(cadre, mode="indeterminate", length=360)
    barre.grid(row=1, column=0)
    barre.start(12)
    fenetre.protocol("WM_DELETE_WINDOW", lambda: None)

    messages = queue.Queue()
    issue = {}

    def fil():
        try:
            issue["resultat"] = travail(messages.put)
        except Exception as erreur:  # renvoyée au fil principal ci-dessous
            issue["erreur"] = erreur
        finally:
            messages.put(None)

    def relever():
        try:
            while True:
                message = messages.get_nowait()
                if message is None:
                    barre.stop()
                    fenetre.destroy()
                    return
                texte.set(message)
        except queue.Empty:
            fenetre.after(100, relever)

    centrer(fenetre)
    threading.Thread(target=fil, daemon=True).start()
    fenetre.after(100, relever)
    fenetre.mainloop()
    if "erreur" in issue:
        raise issue["erreur"]
    return issue.get("resultat")


def verifier_mails(mails, entreprises_connues):
    """Affiche les mails un par un.

    Retourne {indice: décision} ; une décision vaut None (pas une candidature)
    ou {categorie, entreprise, poste}. Les mails passés n'y figurent pas.
    """
    fenetre = tk.Tk()
    fenetre.title("Mails à vérifier")
    fenetre.geometry("900x680")
    fenetre.minsize(700, 500)
    decisions = {}
    position = [0]

    entete = ttk.Frame(fenetre, padding=(12, 12, 12, 4))
    entete.pack(fill="x")
    compteur = ttk.Label(entete, font=("Segoe UI", 10, "bold"))
    compteur.pack(anchor="w")
    infos = ttk.Label(entete, justify="left", wraplength=860)
    infos.pack(anchor="w", pady=(4, 0))

    cadre_texte = ttk.Frame(fenetre, padding=(12, 4))
    cadre_texte.pack(fill="both", expand=True)
    defilement = ttk.Scrollbar(cadre_texte)
    defilement.pack(side="right", fill="y")
    texte = tk.Text(cadre_texte, wrap="word", yscrollcommand=defilement.set, font=("Segoe UI", 10), padx=8, pady=8)
    texte.pack(fill="both", expand=True)
    defilement.config(command=texte.yview)

    formulaire = ttk.Frame(fenetre, padding=(12, 8))
    formulaire.pack(fill="x")
    ttk.Label(formulaire, text="Entreprise").grid(row=0, column=0, sticky="w")
    champ_entreprise = ttk.Combobox(formulaire, values=sorted(entreprises_connues, key=str.lower), width=40)
    champ_entreprise.grid(row=1, column=0, sticky="we", padx=(0, 12))
    ttk.Label(formulaire, text="Poste").grid(row=0, column=1, sticky="w")
    champ_poste = ttk.Entry(formulaire, width=50)
    champ_poste.grid(row=1, column=1, sticky="we")
    formulaire.columnconfigure(0, weight=1)
    formulaire.columnconfigure(1, weight=1)

    boutons = ttk.Frame(fenetre, padding=(12, 4, 12, 12))
    boutons.pack(fill="x")
    for libelle, categorie in DECISIONS:
        ttk.Button(boutons, text=libelle, command=lambda c=categorie: decider(c)).pack(side="left", padx=(0, 6))
    ttk.Button(boutons, text="Pas une candidature", command=lambda: decider(None)).pack(side="left", padx=(12, 6))
    ttk.Button(boutons, text="Passer ▶", command=lambda: aller(1)).pack(side="right")
    ttk.Button(boutons, text="◀ Précédent", command=lambda: aller(-1)).pack(side="right", padx=6)

    def remplir(champ, valeur):
        champ.delete(0, "end")
        champ.insert(0, valeur)

    def afficher():
        mail = mails[position[0]]
        decision = decisions.get(position[0], "")
        compteur.config(text=f"Mail {position[0] + 1} / {len(mails)} — {len(decisions)} traité(s)")
        etat = "déjà traité" if position[0] in decisions else f"proposition : {LIBELLES.get(mail.categorie, mail.categorie)}"
        infos.config(text=f"{mail.date:%d/%m/%Y} · De : {mail.expediteur}\nObjet : {mail.sujet}\n({etat})")
        remplir(champ_entreprise, (decision or {}).get("entreprise", mail.entreprise))
        remplir(champ_poste, (decision or {}).get("poste", mail.poste))
        texte.config(state="normal")
        texte.delete("1.0", "end")
        texte.insert("1.0", mail.texte or "(mail sans texte)")
        texte.config(state="disabled")

    def aller(pas):
        nouvelle = position[0] + pas
        if nouvelle >= len(mails):
            fermer()
        elif nouvelle >= 0:
            position[0] = nouvelle
            afficher()

    def decider(categorie):
        if categorie is None:
            decisions[position[0]] = None
        else:
            entreprise = champ_entreprise.get().strip()
            if not entreprise:
                messagebox.showwarning("Entreprise manquante", "Indique l'entreprise avant de valider.", parent=fenetre)
                champ_entreprise.focus_set()
                return
            decisions[position[0]] = {
                "categorie": categorie,
                "entreprise": entreprise,
                "poste": champ_poste.get().strip(),
            }
        aller(1)

    def fermer():
        restants = len(mails) - len(decisions)
        if restants and not messagebox.askyesno(
            "Terminer la vérification",
            f"{restants} mail(s) non traité(s) : ils te seront reproposés au prochain lancement.\nTerminer ?",
            parent=fenetre,
        ):
            return
        fenetre.destroy()

    fenetre.protocol("WM_DELETE_WINDOW", fermer)
    afficher()
    centrer(fenetre)
    fenetre.mainloop()
    return decisions


def informer(titre, message, proposer_ouverture=False):
    """Boîte de fin ; retourne True si l'utilisateur veut ouvrir le fichier."""
    racine = tk.Tk()
    racine.withdraw()
    if proposer_ouverture:
        reponse = messagebox.askyesno(titre, message + "\n\nOuvrir le fichier des candidatures ?", parent=racine)
    else:
        messagebox.showinfo(titre, message, parent=racine)
        reponse = False
    racine.destroy()
    return reponse


def signaler_erreur(titre, message):
    racine = tk.Tk()
    racine.withdraw()
    messagebox.showerror(titre, message, parent=racine)
    racine.destroy()
