# Suivi de candidatures

Outil Python qui suit automatiquement les candidatures à partir de la boîte mail Free.

Le script lit les mails en IMAP, repère ceux qui concernent une candidature
(envoi, accusé de réception, réponse positive ou négative), devine l'entreprise
et le poste, puis tient à jour un tableau `candidatures.csv`. Les mails
douteux sont présentés un par un dans une fenêtre pour être triés à la main.

## Fonctionnalités

- Lecture de la boîte **en lecture seule** : aucun mail n'est modifié ni marqué lu.
- Classement des mails : `envoi`, `confirmation`, `positive`, `negative`.
- Détection de l'entreprise (texte du mail, domaine de l'expéditeur) et du poste.
- Reconnaissance des plateformes (LinkedIn, Indeed, Welcome to the Jungle, HelloWork, Apec…).
- Regroupement des mails par candidature et archivage des `.eml` dans `Candidatures/<id>_<entreprise>/`.
- Fenêtre de vérification pour les cas incertains ; les décisions sont mémorisées.
- Lancements incrémentaux : reprise à la dernière exécution (avec une semaine de marge).
- Les modifications faites à la main dans le CSV ne sont jamais écrasées.

## Prérequis

- Windows (ouverture du CSV et Gestionnaire d'identification Windows)
- Python 3.10 ou plus récent, avec Tkinter (inclus dans l'installateur python.org)
- Une adresse mail Free avec l'accès IMAP activé
- Facultatif : [`keyring`](https://pypi.org/project/keyring/) pour mémoriser le mot de passe

```powershell
pip install keyring
```

## Utilisation

```powershell
python trier_candidatures.py
```

Un double-clic sur `trier_candidatures.py` fonctionne aussi.

1. Une fenêtre demande l'adresse et le mot de passe Free.
2. Les mails sont lus (180 derniers jours au premier lancement).
3. Les mails douteux s'affichent un par un : choisir le type, corriger l'entreprise
   ou le poste, ou indiquer « Pas une candidature ».
4. Un bilan s'affiche et propose d'ouvrir `candidatures.csv`.

### Options

| Option | Effet |
| --- | --- |
| `--depuis 2026-01-01` | Force la date de départ de la lecture |
| `--dossiers INBOX Sent` | Lit d'autres dossiers IMAP (par défaut `INBOX`) |
| `--lister-dossiers` | Affiche les dossiers de la boîte puis s'arrête |
| `--oublier-mot-de-passe` | Efface le mot de passe mémorisé |

Les identifiants peuvent aussi être fournis par les variables d'environnement
`FREE_EMAIL` et `FREE_PASSWORD`.

### Tester la connexion

```powershell
python tester_imap.py
```

Affiche l'en-tête des 10 derniers mails de la boîte de réception.

## Fichiers produits

| Fichier | Contenu |
| --- | --- |
| `candidatures.csv` | Une ligne par candidature (séparateur `;`, UTF-8) |
| `Candidatures/<id>_<entreprise>/` | Mails `.eml` rattachés à chaque candidature |
| `a_verifier.csv` | Mails passés lors de la vérification, reproposés au prochain lancement |
| `.etat.json` | Adresse, date de dernière exécution et décisions déjà prises |

Colonnes de `candidatures.csv` :
`id`, `entreprise`, `poste`, `date_candidature`, `confirmation_recue`, `statut`,
`date_reponse`, `reponse`, `dossier_emails`.

## Structure du projet

```
.
├── trier_candidatures.py   # Script principal : lecture IMAP, classement, mise à jour du CSV
├── fenetres.py             # Fenêtres Tkinter : connexion, progression, vérification
├── tester_imap.py          # Test rapide de la connexion IMAP
└── Candidatures/           # Archives .eml (non versionnées)
```

## Confidentialité

Le mot de passe n'est jamais écrit dans un fichier : il est soit saisi à chaque
lancement, soit stocké dans le Gestionnaire d'identification Windows.
Les mails archivés, l'état et les fichiers de travail sont exclus du dépôt
par le `.gitignore`.
