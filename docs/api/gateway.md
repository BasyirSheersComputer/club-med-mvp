# Gateway Service API

**Base URL:** `http://localhost:8000`  
**Version:** 0.1.0  
**Live Docs:** http://localhost:8000/docs

---

## Endpoints

### `GET /` - Health Check
Basic service health check.

**Response:**
```json
{
  "status": "ok",
  "service": "gateway"
}
```

---

### `GET /health/upstream` - Upstream Health Check
Verifies Gateway can reach Core service.

**Response (Success):**
```json
{
  "status": "ok",
  "upstream": "core_reachable",
  "details": {
    "status": "ok",
    "service": "core"
  }
}
```

**Response (Failure):**
```json
{
  "detail": "Core unreachable: <error>"
}
```
**Status:** `503 Service Unavailable`

---

### `POST /webhook/whatsapp` - WhatsApp Webhook
*Coming in Phase 2*

Receives incoming WhatsApp messages from Meta/Twilio.

**Request Body:** TBD  
**Response:** TBD

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-02-04 | Initial health check endpoints |
