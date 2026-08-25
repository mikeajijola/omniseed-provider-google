# Working on the OmniSeed Google Provider

- Provider organisation and canonical Provider ID: Google / `google`.
- Gemini API, Gemini models, Google AI Studio, SDKs, and model endpoints are products or implementation choices beneath Google, never separate Providers.
- This Provider implements only the canonical `inference` primitive family.
- An inference binding is not an Agent identity, Agent runtime, Skill, or Connector.
- Never expose API keys in protocol messages, errors, observations, evidence, or tests.
- Plan is deterministic and side-effect free. Apply establishes only the approved model binding. Observe independently verifies the selected model through Google.
- Live tests are read-only and must be explicitly enabled.

Run `npm test` before proposing a change.
