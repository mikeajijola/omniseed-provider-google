import json
import unittest

from provider.google_provider import GoogleProvider, PROTOCOL, ProviderError


class FakeClient:
    def __init__(self, model="gemini-2.5-flash", methods=None, fail=False):
        self.model_name = model
        self.methods = methods or ["generateContent", "countTokens"]
        self.fail = fail
        self.calls = []

    def model(self, api_base, api_key, model, timeout):
        self.calls.append({"apiBase": api_base, "credentialPresent": bool(api_key), "model": model, "timeout": timeout})
        if self.fail:
            raise ProviderError("unavailable", "remote_unreachable")
        return 200, {
            "name": "models/" + self.model_name,
            "displayName": "Gemini",
            "supportedGenerationMethods": self.methods,
            "inputTokenLimit": 1048576,
            "outputTokenLimit": 65536
        }


def action(model="gemini-2.5-flash"):
    return {
        "id": "action_1",
        "family": "inference",
        "resourceId": "lily_inference",
        "desired": {"spec": {"product": "Gemini API", "model": model, "credentialReference": "GEMINI_API_KEY"}}
    }


class GoogleProviderTest(unittest.TestCase):
    def provider(self, client=None, environment=None):
        return GoogleProvider(
            {"credentialReferenceEnvironment": {"GEMINI_API_KEY": "TEST_GEMINI_KEY"}},
            client or FakeClient(),
            environment if environment is not None else {"TEST_GEMINI_KEY": "test-only-value"}
        )

    def test_manifest_and_runtime_identity_are_organisational(self):
        result = self.provider().initialize({"protocolVersion": PROTOCOL, "configuration": {"credentialReferenceEnvironment": {"GEMINI_API_KEY": "TEST_GEMINI_KEY"}}, "context": {"companyId": "example", "desiredResources": []}})
        with open("provider-package.json", encoding="utf-8") as source:
            manifest = json.load(source)
        self.assertEqual(manifest["id"], "google")
        self.assertEqual(manifest["organisation"], "Google")
        self.assertEqual(manifest["primitiveFamilies"], ["inference"])
        self.assertEqual(manifest["implementations"], [{"family": "inference", "products": ["Gemini API", "Gemini models"]}])
        self.assertEqual(result["provider"]["id"], manifest["id"])
        self.assertEqual(result["primitiveFamilies"], manifest["primitiveFamilies"])

    def test_validate_accepts_inference_and_rejects_actor_or_product_provider_shapes(self):
        self.assertTrue(self.provider().validate(action())["valid"])
        wrong_family = {**action(), "family": "agents"}
        self.assertFalse(self.provider().validate(wrong_family)["valid"])
        wrong_product = action()
        wrong_product["desired"]["spec"]["product"] = "LiteLLM"
        self.assertFalse(self.provider().validate(wrong_product)["valid"])

    def test_plan_is_deterministic_redacted_and_side_effect_free(self):
        client = FakeClient()
        provider = self.provider(client)
        first, second = provider.plan(action()), provider.plan(action())
        self.assertEqual(first, second)
        self.assertEqual(client.calls, [])
        self.assertEqual(first["provider"], "google")
        self.assertEqual(first["product"], "Gemini API")
        self.assertEqual(first["model"], "gemini-2.5-flash")
        self.assertNotIn("test-only-value", json.dumps(first))

    def test_apply_binds_exact_model_and_never_returns_credentials(self):
        client = FakeClient()
        result = self.provider(client).apply(action())
        self.assertEqual(result["providerResourceId"], "google://gemini/models/gemini-2.5-flash")
        self.assertEqual(result["attributes"]["spec"]["credentialReference"], "GEMINI_API_KEY")
        self.assertNotIn("test-only-value", json.dumps(result))
        self.assertTrue(client.calls[0]["credentialPresent"])

    def test_apply_fails_closed_on_model_identity_drift(self):
        with self.assertRaises(ProviderError) as raised:
            self.provider(FakeClient(model="gemini-other")).apply(action())
        self.assertEqual(raised.exception.code, "model_identity_mismatch")

    def test_observe_produces_redacted_model_evidence(self):
        provider = self.provider()
        deployed = provider.apply(action())
        result = provider.observe({"id": "lily_inference", **deployed})
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["evidence"][0]["source"], "google")
        self.assertEqual(result["evidence"][0]["model"], "gemini-2.5-flash")
        self.assertNotIn("test-only-value", json.dumps(result))

    def test_missing_or_unmapped_credential_fails_without_exposing_values(self):
        provider = GoogleProvider({"credentialReferenceEnvironment": {}}, FakeClient(), {})
        with self.assertRaises(ProviderError) as raised:
            provider.apply(action())
        self.assertEqual(raised.exception.code, "not_configured")
        self.assertNotIn("key", str(raised.exception).lower())

    def test_status_distinguishes_configuration_and_connectivity(self):
        desired = [{"family": "inference", "id": "lily_inference", "spec": action()["desired"]["spec"]}]
        healthy = self.provider()
        healthy.initialize({"protocolVersion": PROTOCOL, "configuration": healthy.configuration, "context": {"companyId": "example", "desiredResources": desired}})
        self.assertEqual(healthy.status(), {"implementation_available": True, "configured": True, "connected": True, "healthy": True})
        unavailable = self.provider(FakeClient(fail=True))
        unavailable.initialize({"protocolVersion": PROTOCOL, "configuration": unavailable.configuration, "context": {"companyId": "example", "desiredResources": desired}})
        self.assertEqual(unavailable.status(), {"implementation_available": True, "configured": True, "connected": False, "healthy": False})

    def test_invoke_requires_persisted_resource_binding(self):
        with self.assertRaises(ProviderError) as raised:
            self.provider().invoke("inference.model.observe", {}, {"actorId": "lily"})
        self.assertEqual(raised.exception.code, "resource_binding_required")


if __name__ == "__main__":
    unittest.main()
