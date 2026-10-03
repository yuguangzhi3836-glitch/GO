def test_consumer_registration_accepts_only_account_terms_and_defers_vault(client):
    response=client.post('/v1/consumer/auth/register',json={
        "email":"terms@example.com",
        "password":"StrongPass123!",
        "display_name":"Terms Traveler",
        "accepted_terms":True,
        "term_versions":{
            "consumer_service_terms":"2026-08-25-v1",
            "privacy_policy":"2026-08-25-v1",
        },
    })
    assert response.status_code==200,response.text
    data=response.json()["data"]
    assert data["terms"]=={
        "consumer_service_terms":"2026-08-25-v1",
        "privacy_policy":"2026-08-25-v1",
    }
    assert data["deferred_terms"]=={"personal_vault_terms":"2026-08-25-v1"}
    assert data["personal_vault_opt_in"] is False


def test_consumer_registration_rejects_vault_terms_as_account_terms(client):
    response=client.post('/v1/consumer/auth/register',json={
        "email":"mixed-terms@example.com",
        "password":"StrongPass123!",
        "display_name":"Mixed Terms",
        "accepted_terms":True,
        "term_versions":{
            "consumer_service_terms":"2026-08-25-v1",
            "privacy_policy":"2026-08-25-v1",
            "personal_vault_terms":"2026-08-25-v1",
        },
    })
    assert response.status_code==409
    assert response.json()["detail"]=="CONSUMER_TERMS_VERSION_MISMATCH"
