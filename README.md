# SESSION-GATE

Script de discipline de session (observe -> triage -> gate -> seal) pour l'ecosysteme KiloCode/GeriCode.

## Seals historiques perdus

Trois seals ont ete emis par la session precedente et sont perdus (stockage dans %TEMP%\harness\seals\, nettoye au reboot) :

- WAL-SEAL-shard-8d9a27d1-e68a6193-… (retracte, invalid_precondition)
- WAL-SEAL-shard-47ddc520-7eb0a36b-… (PRD-001, invalid_precondition)
- WAL-SEAL-shard-ffbcb901-5e790b58-… (ZCF, invalid_precondition)

## Correctif

SESSION-GATE stocke ses seals dans ~/.harness/seals/ (persistant), pas dans %TEMP%.
