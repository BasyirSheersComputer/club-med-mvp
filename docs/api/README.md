# ResortOS API Documentation

**Version:** 0.1.0 (Phase 1 - Skeleton)  
**Last Updated:** 2026-02-04

## Overview

This directory contains modular API documentation for all ResortOS services. Each service has its own file for easy maintenance as the system evolves through development phases.

## Services

| Service | Port | Documentation | Status |
|---------|------|---------------|--------|
| **Gateway** | 8000 | [gateway.md](gateway.md) | ✅ Active |
| **Core** | 8001 | [core.md](core.md) | ✅ Active |
| **Web** | 3000 | N/A (Frontend) | ✅ Active |

## Live API Docs (Swagger UI)

FastAPI provides built-in interactive documentation:

- **Gateway:** http://localhost:8000/docs
- **Core:** http://localhost:8001/docs

## API Versioning Strategy

| Phase | Version | Changes |
|-------|---------|---------|
| Phase 1 | v0.1.0 | Health checks, basic structure |
| Phase 2 | v0.2.0 | Channel webhooks, message endpoints |
| Phase 3 | v0.3.0 | AI Copilot endpoints |
| Phase 4 | v1.0.0 | Production-ready APIs |

## Quick Reference

### Health Check Endpoints
```
GET /                    # Basic health (all services)
GET /health/deep         # DB/Redis connectivity (Core)
GET /health/upstream     # Inter-service check (Gateway)
```

### Adding New Endpoints
1. Update the relevant service file (`gateway.md` or `core.md`)
2. Add OpenAPI spec snippet if applicable
3. Update version and changelog
