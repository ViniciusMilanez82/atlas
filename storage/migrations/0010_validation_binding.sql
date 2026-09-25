-- Contract v2 A3-29: a validation vouches only for the exact credential, endpoint, model and capability
-- version it tested. Earlier rows carry no binding, so they no longer make the model "ready": the
-- owner must run 'Testar inteligência' again after upgrading (honest, and billed through the ledger).
ALTER TABLE intelligence_validations ADD COLUMN credential_ref TEXT REFERENCES credential_refs(id);
ALTER TABLE intelligence_validations ADD COLUMN endpoint TEXT;
ALTER TABLE intelligence_validations ADD COLUMN capability_version TEXT;
CREATE INDEX idx_intel_binding ON intelligence_validations(provider, model_id, credential_ref, endpoint);
