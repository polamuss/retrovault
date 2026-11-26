# RetroVault Pages 12.4 (préparation)

RetroVault est un catalogue statique de matériel et de jeux rétro, publié avec GitHub Pages. L'interface conserve la collection personnelle et ses photos sur l'appareil du visiteur. Les catalogues publics, index d'images et corrections validées sont générés côté serveur par GitHub Actions.

## Publication

1. Définir GitHub Pages sur **GitHub Actions** dans les paramètres du dépôt.
2. La branche `main` déclenche le workflow de publication.
3. Le workflow télécharge les catalogues de métadonnées, génère les fichiers JSON et les index d'images, vérifie l'absence de secrets dans le dossier public, puis déploie `dist`.
4. Le visiteur n'a rien à télécharger ni à installer.

La génération ne télécharge aucune ROM. Les index d'images conservent des références vers les sources et ne copient pas les illustrations commerciales.

## Données et statistiques

Les fichiers générés se trouvent dans `dist/data/` :

- `index.json` : index des plateformes, images et sources.
- `report.json` : compteurs de plateformes, éditions, groupes de titres, couverture d'images, erreurs et taille du site.
- `catalog/` : instantané consolidé du catalogue.
- `catalog-overrides.json` : corrections et exclusions publiées.

Les compteurs distinguent les éditions et les groupes de titres. La couverture est calculée à partir des références réellement présentes dans les index générés, et non à partir du nombre de lignes ou d'images uniques.

## Modération du catalogue

Les fiches de jeux proposent des actions de signalement : faux jeu, image incorrecte ou titre à corriger. Dans la liste globale des jeux, plusieurs titres peuvent être sélectionnés pour proposer une exclusion groupée. La liste des jeux exclus permet également de demander leur restauration.

GitHub Pages étant un hébergement statique, l'interface publique ne peut pas écrire directement dans le dépôt sans exposer un jeton d'écriture. Les actions de l'interface préparent donc une proposition GitHub à examiner par un mainteneur. **Une proposition n'est pas appliquée automatiquement.** Après vérification, le mainteneur modifie `data/catalog-overrides.json`, puis la prochaine génération applique la correction à tous les visiteurs.

Structure du fichier :

```json
{
  "version": 1,
  "excluded": [
    {
      "system": "Emerson - Arcadia 2001",
      "title": "Geometrydash",
      "reason": "Titre signalé comme faux jeu"
    }
  ],
  "title_overrides": [
    {
      "system": "Nintendo - Nintendo Entertainment System",
      "title": "Ancien titre",
      "replacement": "Titre corrigé"
    }
  ],
  "image_exclusions": [
    {
      "system": "Nintendo - Nintendo Entertainment System",
      "title": "Jeu",
      "source": "libretro"
    }
  ]
}
```

Les exclusions et corrections de titre utilisent le couple exact plateforme/titre. Les exclusions d'images acceptent `all`, `fixed`, `libretro`, `launchbox`, `gametdb`, `openvgdb`, `steamgriddb` ou `igdb`. Retirer une image ne supprime pas le jeu. Une correction de titre est appliquée avant la construction des index de sources.

## Sources d'images

- Libretro : jaquettes, écrans-titres et captures, avec priorité aux jaquettes.
- LaunchBox : références d'images, avec correspondances contrôlées.
- GameTDB : jaquettes identifiées par plateforme et code de jeu.
- OpenVGDB : import SQLite en lecture seule et références de jaquettes.
- SteamGridDB : recherche facultative et limitée, déclenchée manuellement.
- Photos fixes : uniquement les fichiers explicitement autorisés à la redistribution.

OpenVGDB est téléchargé depuis la publication GitHub officielle. Le nom de l'archive est résolu depuis les métadonnées de la release, puis le fichier SQLite est contrôlé et ses tables/colonnes inspectées avant la requête. Le cache local n'est remplacé qu'après un import exploitable. Une erreur de cette source n'interrompt pas la génération et les autres sources continuent de fonctionner.

Les références externes sont validées par liste blanche HTTPS. Le navigateur met les images en cache localement et conserve le préchargement limité aux deux pages suivantes. Les images IGDB, si l'intégration est autorisée ultérieurement, restent référencées sur leur CDN et ne sont pas copiées dans le dépôt.

## IGDB : verrouillage d'activation

L'indexeur `tools/igdb_index.py` est préparé mais **désactivé par défaut**. Aucun appel IGDB ne doit être effectué avant confirmation explicite de l'administrateur responsable concernant :

- l'éligibilité de l'application Twitch et du compte utilisé ;
- les conditions applicables à l'usage de l'API ;
- la conservation des données et l'affichage des images IGDB dans RetroVault.

La présence de `IGDB_CLIENT_ID` et `IGDB_CLIENT_SECRET` dans GitHub Secrets ne vaut pas validation. Deux conditions indépendantes sont nécessaires pour activer l'étape :

1. L'administrateur responsable définit la variable de dépôt `RV_IGDB_APPROVED=true après avoir confirmé les points ci-dessus.
2. Une exécution manuelle du workflow demande explicitement `igdb=true`.

Sans ces deux conditions, l'étape IGDB est ignorée. L'indexeur vérifie également les deux variables avant de lire les identifiants ou d'effectuer une requête. Les identifiants restent dans GitHub Secrets, les jetons OAuth ne sont jamais enregistrés dans le cache ni dans les fichiers publics, et les appels API sont effectués uniquement pendant la génération serveur. Les titres déjà couverts par une jaquette ne sont pas recherchés. Les titres courts ne sont pas exclus par leur longueur ; les correspondances ambiguës ou sur une mauvaise plateforme sont rejetées.

## Sécurité et maintenance

- Ne jamais ajouter de clé API, secret OAuth ou jeton dans le HTML, le dépôt, les fichiers JSON publics ou les journaux.
- Le contrôle `tools/check_public_secrets.py` est conservé et exécuté avant publication.
- Les erreurs de sources facultatives ne doivent pas effacer les résultats déjà en cache.
- Les tests hors ligne sont lancés avant la génération avec `python -m unittest discover -s tools -p 'test_*.py'`.
- Les intégrations existantes, la collection personnelle, l'identification, les photos fixes, les regroupements et le cache navigateur doivent rester fonctionnels.

## Développement local

```sh
python -m pip install Pillow==11.3.0
python -m unittest discover -s tools -p 'test_*.py'
python tools/build.py --fetch --output dist
```

L'option SteamGridDB se lance uniquement via le workflow manuel, après validation des conditions de cette source. IGDB reste désactivé tant que l'administrateur n'a pas confirmé son éligibilité et les conditions applicables.
