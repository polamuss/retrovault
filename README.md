# RetroVault Pages 11.0

Site statique pour GitHub Pages, issu de RetroVault 10.4. Collection personnelle et photos privées stockées sur l'appareil, hors dépôt public. Les données du catalogue sont publiées par plateforme et chargées dans la mémoire de session. Les images du catalogue sont chargées exclusivement depuis les fichiers du site, après vérification du cache local. Une image absente ne déclenche pas de recherche externe.

## Publier

1. Créer le dépôt public `retrovault` dans GitHub.
2. Décompresser cette archive et envoyer son contenu à la racine du dépôt (y compris `.github/workflows/pages.yml` et `.nojekyll`). La branche doit s'appeler `main`.
3. Dans Settings > Pages > Build and deployment > Source, sélectionner GitHub Actions.
4. Dans Actions > Publier RetroVault, lancer le workflow si nécessaire. Le workflow télécharge les catalogues de métadonnées référencés, les fusionne, construit les fichiers statiques et publie `dist`. Il ne télécharge aucune ROM.

Alternative pour tester immédiatement la version initiale : choisir Deploy from a branch, `main`, `/(root)`. Le catalogue initial ne contient que les données livrées avec cette archive, et non tous les jeux disponibles sur les sources distantes.

## Données et images

`data/report.json` indique le nombre d'éditions, les doublons exacts retirés, les sources indisponibles et les statistiques d'images. Le regroupement des variantes par titre et plateforme se fait également dans l'interface.

Le constructeur `tools/build.py` utilise les 146 chemins de catalogues répertoriés dans `tools/catalog_paths.json`. Le nombre de téléchargements réussis est indiqué dans le rapport. Vérifier les licences de redistribution des sources avant publication.

L'import LaunchBox est facultatif, réservé au responsable du site, pas au visiteur. Le ZIP n'est pas fourni dans cette archive. Si les droits de redistribution sont établis, lancer :

```sh
python tools/build.py --fetch --launchbox /chemin/Metadata.zip --output dist
```

Le lecteur conserve les titres déjà connus, ajoute uniquement les nouveaux titres reconnus sur une plateforme connue et ne présente pas les données LaunchBox comme des éditions physiques certaines. Les descriptions et les images de LaunchBox ne sont pas automatiquement copiées. Le rapport distingue les correspondances, les titres ajoutés et les plateformes non reconnues.

Le manifeste `tools/approved-images.json` est initialement vide. Il permet d'associer des images autorisées (fichiers dans `tools/approved-assets/`) à des clés précises. Exemple de structure pour une photo dont vous possédez les droits :

```json
[
  {
    "key": ["Nintendo - Super Nintendo Entertainment System", "Super Mario World (Europe)"],
    "file": "exemple.png",
    "kind": "cover",
    "redistribution_authorized": true,
    "credit": "Auteur, source, licence"
  }
]
```

Pour le matériel, la clé est `["hardware", "Super Nintendo"]`. Pour les photos de référence d'une cartouche, utiliser `["pcb", "REFERENCE|02_pcb_front"]`, avec `kind: "pcb"`. Les jaquettes sont converties en AVIF (480 pixels maximum), les PCB en WebP sans perte à leur résolution originale. Les fichiers identiques après encodage ne sont stockés qu'une fois, sous leur SHA-256. Seuls les fichiers déclarés explicitement et autorisés à la redistribution sont inclus. Ne jamais publier de photos privées, d'archives de sauvegarde personnelles ou de métadonnées non autorisées.

```sh
python -m pip install Pillow==11.3.0
python tools/build.py --output dist
```

Le visiteur n'a rien à installer. Le cache d'images du navigateur est configurable de 0 à 500 Mo (100 Mo par défaut). Il évite un nouveau téléchargement pour une image encore en cache. Le préchargement porte sur les deux pages de jeux suivantes. La collection reste locale : pensez à l'exporter depuis l'ancien site puis à l'importer depuis Réglages sur la nouvelle adresse.

La version conserve les outils d'identification et les informations techniques. Certaines descriptions et informations techniques continuent à être consultées auprès des sources de référence à l'ouverture des fiches. Aucune recherche distante d'images du catalogue n'est lancée à la navigation.

## État de validation

Les données initiales ont été construites localement. Le téléchargement complet des sources, l'import du véritable fichier LaunchBox et le déploiement GitHub Pages ne sont pas vérifiés ici. Aucune image publique n'est incluse dans la version initiale. Les photos personnelles importées gardent leurs octets d'origine (formats JPEG, PNG et WebP, limite de 20 Mio par fichier), sauf rotation explicite, réalisée en PNG.

## Sécurité des identifiants API

Ne jamais enregistrer un Client Secret, un jeton OAuth ou une clé API dans le dépôt, le HTML, le cache Actions ou les données publiées. Les identifiants IGDB doivent être gérés par un administrateur éligible aux conditions développeur Twitch. Un secret communiqué dans une conversation ou dans un fichier doit être renouvelé avant utilisation. Les secrets GitHub Actions `IGDB_CLIENT_ID` et `IGDB_CLIENT_SECRET` ne sont actuellement utilisés que par le contrôle de non-divulgation du site généré. L'accès API IGDB n'est pas activé. Les permissions de publication Pages sont limitées au job de déploiement, et les identifiants Git ne sont pas conservés après le checkout.
