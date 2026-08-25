# OmniSeed Google Provider

This is the Provider package for the supplying organisation Google, with canonical Provider ID `google`. It implements only the `inference` primitive family through the Gemini API and Gemini models.

Google is the Provider. Gemini API and individual Gemini models are products and implementation choices beneath Google. LiteLLM, Google SDKs, and other client libraries are integration frameworks beneath the binding; they are not Providers. Lily or another governed actor remains an `agents` primitive and is never collapsed into its inference binding.

The Provider accepts a desired inference Resource containing the selected product, exact model identifier, and a credential reference. Process configuration maps that public reference to a server environment name. Secret values never enter Omniform, plans, deployed state, observations, evidence, errors, or browser output.

`plan` returns the exact proposed Provider/product/model binding without network calls. `apply` establishes that binding only after Google independently returns the requested model identity. `observe` repeats the model-metadata request and records redacted evidence of identity and supported generation methods. A declaration alone never establishes installation, connection, health, or inference capability.

This package does not host an Agent loop and does not import LiteLLM. A self-hosted Agent implementation may consume the bound Gemini model through LiteLLM while OmniSeed retains the desired binding and Provider observations.

Run the protocol process with `python provider/google_provider.py` and tests with `npm test`.
