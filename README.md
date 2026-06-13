# Pharmacies de garde de Niamey

Ce dépôt publie `pharmacies_garde_current.json`, consommé par l'application mobile.

## Mise à jour automatique

Le workflow GitHub Actions `.github/workflows/update-pharmacies-garde.yml` s'exécute chaque heure et peut aussi être lancé manuellement depuis l'onglet **Actions**.

Le script `scripts/update_duty_pharmacies.py` :

- consulte la liste publique de 2424PharmaNiger ;
- conserve uniquement les pharmacies de Niamey ;
- publie les noms, adresses, téléphones et coordonnées GPS disponibles ;
- refuse une liste vide, trop petite ou datée d'un autre jour ;
- conserve le fichier actuel lorsque la source est indisponible ou invalide ;
- ne crée aucun commit lorsque la liste n'a pas changé.

Les informations de garde peuvent évoluer. Les utilisateurs doivent toujours appeler la pharmacie avant de se déplacer.
