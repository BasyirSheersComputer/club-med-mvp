# Core Service API

**Base URL:** `http://localhost:8001`  
**Version:** 0.1.0  
**Live Docs:** http://localhost:8001/docs

---

## Endpoints

### `GET /` - Health Check
Basic service health check.

**Response:**
```json
{
  "status": "ok",
  "service": "core"
}
```

---

### `GET /health/deep` - Deep Health Check
Verifies connectivity to PostgreSQL and Redis.

**Response (Success):**
```json
{
  "status": "healthy",
  "checks": {
    "database": "connected",
    "redis": "connected"
  }
}
```

**Response (Failure):**
```json
{
  "detail": {
    "database": "failed: <error>",
    "redis": "connected"
  }
}
```
**Status:** `503 Service Unavailable`

---

## Planned Endpoints (Phase 2+)

### Messages Module
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/messages` | Create new message |
| `GET` | `/messages/{id}` | Get message by ID |
| `GET` | `/threads` | List conversation threads |
| `GET` | `/threads/{id}` | Get thread with messages |

### Guests Module
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/guests` | Create/upsert guest profile |
| `GET` | `/guests/{id}` | Get guest by ID |
| `GET` | `/guests/search` | Search guests |

---

## Data Models (Planned)

### Message
```json
{
  "id": "uuid",
  "thread_id": "uuid",
  "channel": "whatsapp|line|wechat|kakao",
  "direction": "inbound|outbound",
  "content": {
    "type": "text|image|location",
    "body": "string"
  },
  "timestamp": "ISO8601",
  "metadata": {}
}
```

### Guest
```json
{
  "id": "uuid",
  "channel_ids": {
    "whatsapp": "+1234567890",
    "line": "U1234567890"
  },
  "name": "string",
  "language": "en|ja|ko|zh",
  "created_at": "ISO8601"
}
```

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-02-04 | Initial health check endpoints |
