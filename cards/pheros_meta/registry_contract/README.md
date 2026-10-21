# registry_contract

A registry is any directory under cards/ that contains a _category.json file. The registry contract: walking the directory yields its cards by reading every immediate-subdirectory's card.json. There is no central index — the filesystem IS the index.

## Rationale

Eliminating the central index is what makes the system infinitely expandable. New categories are new directories. New cards are new directories inside categories. No registration step exists, so no registration step can be forgotten or corrupted.
