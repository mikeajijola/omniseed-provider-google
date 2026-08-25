#!/usr/bin/env python3
"""Google Provider for independently provisioned Gemini inference bindings."""

import datetime
import hashlib
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL = "omniseed.provider.protocol/1.0"
PROVIDER_ID = "google"
VERSION = "0.1.0-alpha.1"
FAMILIES = ["inference"]
OPERATIONS = ["inference.model.observe"]
METHODS = [
    "provider.initialize", "provider.status", "provider.validate", "provider.plan",
    "provider.apply", "provider.observe", "provider.invoke", "provider.shutdown"
]
DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def evidence_id(resource_id, model):
    material = json.dumps([PROVIDER_ID, "inference", resource_id, model], separators=(",", ":"))
    return "google_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


class ProviderError(RuntimeError):
    def __init__(self, message, code="provider_error", details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class NetworkClient:
    def model(self, api_base, api_key, model, timeout):
        quoted = urllib.parse.quote(model, safe="-._")
        request = urllib.request.Request(
            api_base.rstrip("/") + "/models/" + quoted,
            headers={"Accept": "application/json", "x-goog-api-key": api_key, "User-Agent": "omniseed-provider-google/0.1"},
            method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ProviderError("Google Gemini API rejected the model observation", "remote_http_error", {"status": error.code, "host": "generativelanguage.googleapis.com"}) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ProviderError("Google Gemini API is unreachable", "remote_unreachable", {"host": "generativelanguage.googleapis.com"}) from error
        except json.JSONDecodeError as error:
            raise ProviderError("Google Gemini API returned invalid JSON", "invalid_remote_response", {"host": "generativelanguage.googleapis.com"}) from error


class GoogleProvider:
    def __init__(self, configuration=None, client=None, environment=None):
        self.configuration = configuration or {}
        self.client = client or NetworkClient()
        self.environment = environment if environment is not None else os.environ
        self.company_id = None
        self.desired_resources = []

    def initialize(self, params):
        if params.get("protocolVersion") != PROTOCOL:
            raise ProviderError("Unsupported protocol version", "protocol_mismatch", {"supported": PROTOCOL})
        self.configuration = params.get("configuration") or {}
        context = params.get("context") or {}
        self.company_id = context.get("companyId")
        self.desired_resources = context.get("desiredResources") or []
        return {
            "protocolVersion": PROTOCOL,
            "provider": {"id": PROVIDER_ID, "name": "Google", "version": VERSION},
            "primitiveFamilies": FAMILIES,
            "configurationSchema": "./provider-configuration.schema.json",
            "observationTypes": ["google_gemini_model_binding"],
            "evidenceTypes": ["google_gemini_model_metadata"],
            "offerings": [{"family": "inference", "id": "language_reasoning", "products": ["Gemini API", "Gemini models"]}],
            "operations": OPERATIONS,
            "methods": METHODS
        }

    def _spec(self, value):
        raw = ((value or {}).get("desired") or {}).get("spec") or (value or {}).get("spec") or {}
        return {
            "product": raw.get("product"),
            "model": raw.get("model"),
            "credentialReference": raw.get("credentialReference"),
            "apiBase": self.configuration.get("apiBase") or DEFAULT_API_BASE,
            "timeoutSeconds": self.configuration.get("timeoutSeconds", 10)
        }

    def _issues(self, action):
        spec = self._spec(action)
        issues = []
        if action.get("family") != "inference":
            issues.append({"code": "unsupported_family", "message": "Only inference is supported"})
        if not action.get("resourceId"):
            issues.append({"code": "missing_field", "field": "resourceId", "message": "resourceId is required"})
        if spec.get("product") != "Gemini API":
            issues.append({"code": "unsupported_product", "field": "product", "message": "product must be Gemini API"})
        if not isinstance(spec.get("model"), str) or not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", spec.get("model") or ""):
            issues.append({"code": "invalid_model", "field": "model", "message": "model must be a Gemini API model identifier"})
        reference = spec.get("credentialReference")
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", reference or ""):
            issues.append({"code": "invalid_credential_reference", "field": "credentialReference", "message": "credentialReference must be an environment reference name"})
        parsed = urllib.parse.urlparse(spec.get("apiBase") or "")
        if parsed.scheme != "https" or parsed.hostname != "generativelanguage.googleapis.com":
            issues.append({"code": "invalid_api_boundary", "field": "apiBase", "message": "apiBase must use the Google Gemini API host"})
        return issues

    def _environment_name(self, reference):
        aliases = self.configuration.get("credentialReferenceEnvironment") or {}
        if reference not in aliases:
            raise ProviderError("Declared credential reference is not configured", "not_configured", {"reference": reference})
        return aliases[reference]

    def _credential(self, reference):
        environment_name = self._environment_name(reference)
        value = self.environment.get(environment_name)
        if not value:
            raise ProviderError("Configured credential is unavailable", "not_configured", {"reference": reference})
        return value

    def status(self):
        candidates = []
        for resource in self.desired_resources:
            if resource.get("family") == "inference":
                candidates.append({"family": "inference", "resourceId": resource.get("id"), "desired": {"spec": resource.get("spec") or {}}})
        if not candidates:
            return {"implementation_available": True, "configured": False, "connected": False, "healthy": False}
        action = candidates[0]
        if self._issues(action):
            return {"implementation_available": True, "configured": False, "connected": False, "healthy": False}
        try:
            spec = self._spec(action)
            self.client.model(spec["apiBase"], self._credential(spec["credentialReference"]), spec["model"], spec["timeoutSeconds"])
            return {"implementation_available": True, "configured": True, "connected": True, "healthy": True}
        except ProviderError:
            configured = False
            try:
                configured = bool(self._credential(self._spec(action)["credentialReference"]))
            except ProviderError:
                pass
            return {"implementation_available": True, "configured": configured, "connected": False, "healthy": False}

    def validate(self, action):
        issues = self._issues(action)
        return {"valid": not issues, "issues": issues}

    def plan(self, action):
        validation, spec = self.validate(action), self._spec(action)
        return {
            "deterministic": True,
            "actionId": action.get("id"),
            "valid": validation["valid"],
            "issues": validation["issues"],
            "mode": "bind_google_gemini_inference",
            "mutationSupported": True,
            "family": action.get("family"),
            "resourceId": action.get("resourceId"),
            "provider": PROVIDER_ID,
            "product": spec.get("product"),
            "model": spec.get("model"),
            "credentialReference": spec.get("credentialReference"),
            "expectedEvidence": ["google_gemini_model_metadata"]
        }

    def _snapshot(self, spec):
        _, model = self.client.model(spec["apiBase"], self._credential(spec["credentialReference"]), spec["model"], spec["timeoutSeconds"])
        actual_name = str(model.get("name") or "").removeprefix("models/")
        return {
            "model": actual_name,
            "displayName": model.get("displayName"),
            "supportedGenerationMethods": model.get("supportedGenerationMethods") or [],
            "inputTokenLimit": model.get("inputTokenLimit"),
            "outputTokenLimit": model.get("outputTokenLimit"),
            "matchesDesired": actual_name == spec["model"]
        }

    def apply(self, action):
        validation = self.validate(action)
        if not validation["valid"]:
            raise ProviderError("Action is invalid", "invalid_action", {"issues": validation["issues"]})
        spec = self._spec(action)
        snapshot = self._snapshot(spec)
        if not snapshot["matchesDesired"]:
            raise ProviderError("Google returned a different model identity", "model_identity_mismatch", {"model": snapshot["model"]})
        return {
            "providerResourceId": f"google://gemini/models/{spec['model']}",
            "status": "bound",
            "attributes": {
                "family": "inference",
                "resourceId": action["resourceId"],
                "spec": spec,
                "boundAt": now()
            }
        }

    def observe(self, resource):
        attributes = resource.get("attributes") or {}
        spec = attributes.get("spec") or resource.get("spec") or {}
        resource_id = attributes.get("resourceId") or resource.get("id")
        snapshot = self._snapshot(spec)
        checked_at = now()
        evidence = {
            "id": evidence_id(resource_id, spec["model"]),
            "type": "google_gemini_model_metadata",
            "source": PROVIDER_ID,
            "product": "Gemini API",
            "model": snapshot["model"],
            "supportedGenerationMethods": snapshot["supportedGenerationMethods"],
            "matchesDesired": snapshot["matchesDesired"],
            "observedAt": checked_at
        }
        return {
            "status": "healthy" if snapshot["matchesDesired"] and "generateContent" in snapshot["supportedGenerationMethods"] else "degraded",
            "checkedAt": checked_at,
            "providerResourceId": f"google://gemini/models/{spec['model']}",
            "snapshot": snapshot,
            "evidence": [evidence]
        }

    def invoke(self, operation, input_value, actor):
        if operation != "inference.model.observe":
            raise ProviderError("Unsupported operation", "unsupported_operation", {"operation": operation})
        binding = (input_value or {}).get("resourceBinding")
        if not binding:
            raise ProviderError("Inference observation requires an Engine resource binding", "resource_binding_required")
        result = self.observe(binding)
        return {**result, "requestedBy": (actor or {}).get("actorId")}


def respond(request_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": request_id}
    message["error" if error is not None else "result"] = error if error is not None else result
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def internal_error(error):
    frames = traceback.extract_tb(error.__traceback__)[-4:]
    return {
        "code": -32603,
        "message": "Provider encountered an unexpected internal error",
        "data": {"code": "provider_internal_error", "exceptionType": type(error).__name__, "frames": [{"function": frame.name, "line": frame.lineno} for frame in frames]}
    }


def main():
    provider = GoogleProvider()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            request_id, method, params = request.get("id"), request.get("method"), request.get("params") or {}
            try:
                if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
                    raise ProviderError("Invalid Request", "invalid_request")
                if method == "provider.initialize": result = provider.initialize(params)
                elif method == "provider.status": result = provider.status()
                elif method == "provider.validate": result = provider.validate(params.get("action") or {})
                elif method == "provider.plan": result = provider.plan(params.get("action") or {})
                elif method == "provider.apply": result = provider.apply(params.get("action") or {})
                elif method == "provider.observe": result = provider.observe(params.get("resource") or {})
                elif method == "provider.invoke": result = provider.invoke(params.get("operation"), params.get("input"), params.get("actor"))
                elif method == "provider.shutdown": result = {"shutdown": True}
                else: raise ProviderError("Method not found", "method_not_found")
                respond(request_id, result=result)
                if method == "provider.shutdown": break
            except ProviderError as error:
                respond(request_id, error={"code": -32010, "message": str(error), "data": {"code": error.code, **error.details}})
            except Exception as error:
                respond(request_id, error=internal_error(error))
        except json.JSONDecodeError:
            respond(None, error={"code": -32700, "message": "Parse error"})


if __name__ == "__main__":
    main()
