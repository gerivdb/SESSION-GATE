# GAS REST Pipeline (ENV2)

Pipeline de déploiement Apps Script depuis ENV2, sans interaction navigateur (sauf auth initiale).

## Prérequis
- Node.js installé (npm disponible)
- `clasp` installé globalement (`npm install -g @google/clasp`)
- `.clasprc.json` présent dans `%USERPROFILE%` après `clasp login`

## Actions
- `-Action info` : vérifie présence auth, longueur refresh token, préfixe client_id
- `-Action create -ProjectTitle "X"` : crée un projet GAS, retourne scriptId
- `-Action push -ScriptId "<id>" -SourceFile "<path>"` : pousse le contenu .gs
- `-Action deploy -ScriptId "<id>"` : crée version + déploiement webapp
- `-Action test -ScriptId "<id>"` : vérifie accessibilité du projet

## Sécurité
- Aucun token n'est écrit dans les logs
- Le refresh token reste dans `.clasprc.json` (jamais copié)
- Le pipeline ne fait que le lire pour échanger un access_token éphémère

## Blocages connus
- `BLOCKED:NO_CLASPRC` : pas d'auth, lancer `clasp login` manuellement
- `BLOCKED:NO_REFRESH_TOKEN` : .clasprc.json corrompu, relancer `clasp login`
- `BLOCKED:INTERACTIVE_REQUIRED_AUTH` : auth initiale impossible en headless
