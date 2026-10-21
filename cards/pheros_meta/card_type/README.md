# card_type

The Card type itself. A Card is a named, structured record with a metadata extension point. Every directory under cards/ that is not a category is a Card; the directory's card.json instantiates this schema.

## Rationale

Defining the Card type as a card (rather than as a Python class only) is what makes L1 operational. The JSON schema is normative; the python.py / lean.lean / typescript.ts / rust.rs files in this card's directory are variants. Adding a new language variant of Card means dropping a new file here — no edit to any other card.

## Known flaws

- lacking: lean.lean variant is a stub on day 1
- lacking: rust.rs variant is a stub on day 1
- lacking: typescript.ts variant is a stub on day 1
