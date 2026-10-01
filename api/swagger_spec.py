"""
OpenAPI 3.0 spec for the RMM API.
Served at GET /api/openapi.json — consumed by SwaggerUI at GET /api/docs.
"""

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "RMM Platform API",
        "version": "1.0.0",
        "description": (
            "Remote Monitoring & Management API. All endpoints (except agent registration "
            "and auth login) require a Bearer JWT in the Authorization header. "
            "Roles: superadmin > admin > technician > viewer > client."
        ),
        "contact": {"email": "support@rmm.local"},
    },
    "servers": [{"url": "/", "description": "Current server"}],
    "components": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        },
        "schemas": {
            "Error": {
                "type": "object",
                "properties": {"error": {"type": "string"}},
            },
            "Pagination": {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": {}},
                    "total": {"type": "integer"},
                    "page": {"type": "integer"},
                    "pages": {"type": "integer"},
                },
            },
        },
    },
    "security": [{"BearerAuth": []}],
    "paths": {
        # ── Auth ──────────────────────────────────────────────────────────────
        "/api/auth/login": {
            "post": {
                "tags": ["Auth"],
                "summary": "Login",
                "description": "Authenticate user. Returns access + refresh JWT.",
                "security": [],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["email", "password"],
                        "properties": {
                            "email": {"type": "string", "format": "email"},
                            "password": {"type": "string"},
                        },
                    }}},
                },
                "responses": {
                    "200": {"description": "Login successful", "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "access_token": {"type": "string"},
                            "refresh_token": {"type": "string"},
                            "user": {"type": "object"},
                        },
                    }}}},
                    "401": {"description": "Invalid credentials"},
                    "403": {"description": "Account disabled"},
                },
            }
        },
        "/api/auth/refresh": {
            "post": {
                "tags": ["Auth"],
                "summary": "Refresh access token",
                "description": "Use the refresh JWT to obtain a new access token.",
                "responses": {
                    "200": {"description": "New access token issued"},
                    "401": {"description": "Invalid or expired refresh token"},
                },
            }
        },
        "/api/auth/me": {
            "get": {
                "tags": ["Auth"],
                "summary": "Current user profile",
                "responses": {
                    "200": {"description": "User object"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/auth/me/password": {
            "put": {
                "tags": ["Auth"],
                "summary": "Change password",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["current_password", "new_password"],
                        "properties": {
                            "current_password": {"type": "string"},
                            "new_password": {"type": "string", "minLength": 8},
                        },
                    }}},
                },
                "responses": {
                    "200": {"description": "Password changed"},
                    "400": {"description": "Weak password or validation error"},
                    "401": {"description": "Wrong current password"},
                },
            }
        },
        "/api/auth/me/force-change-password": {
            "post": {
                "tags": ["Auth"],
                "summary": "Force-change password (first login)",
                "description": "Only callable when must_change_password flag is set on the account.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["new_password"],
                        "properties": {"new_password": {"type": "string", "minLength": 8}},
                    }}},
                },
                "responses": {
                    "200": {"description": "Password updated"},
                    "403": {"description": "Flag not set — use /me/password instead"},
                },
            }
        },

        # ── Agents ────────────────────────────────────────────────────────────
        "/api/agents/register": {
            "post": {
                "tags": ["Agents"],
                "summary": "Register agent",
                "description": (
                    "Called by the RMM agent on first boot. Returns device_id + agent_token. "
                    "Pass customer_id to enroll into a specific customer (required in multi-customer setups)."
                ),
                "security": [],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["org_token", "hostname"],
                        "properties": {
                            "org_token": {"type": "string"},
                            "customer_id": {"type": "string", "format": "uuid", "description": "Optional. Enroll to specific customer."},
                            "hostname": {"type": "string"},
                            "mac_address": {"type": "string"},
                            "serial_number": {"type": "string"},
                            "platform": {"type": "string", "enum": ["windows", "linux", "macos", "android", "ios", "unknown"]},
                            "os_name": {"type": "string"},
                            "os_version": {"type": "string"},
                            "cpu_model": {"type": "string"},
                            "cpu_cores": {"type": "integer"},
                            "ram_gb": {"type": "number"},
                            "agent_version": {"type": "string"},
                        },
                    }}},
                },
                "responses": {
                    "201": {"description": "Registered. Returns device_id and agent_token."},
                    "400": {"description": "Missing hostname or invalid customer_id"},
                    "403": {"description": "Invalid org_token"},
                    "429": {"description": "Rate limited (10/min)"},
                },
            }
        },
        "/api/agents/{device_id}/heartbeat": {
            "post": {
                "tags": ["Agents"],
                "summary": "Send heartbeat / metrics",
                "description": "Agent posts metrics every 60s. Returns server_time and optional new_agent_token on rotation.",
                "security": [{"BearerAuth": []}],
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "cpu_pct": {"type": "number"},
                            "ram_pct": {"type": "number"},
                            "disk_pct": {"type": "number"},
                            "ram_used_gb": {"type": "number"},
                            "disk_used_gb": {"type": "number"},
                            "uptime_seconds": {"type": "integer"},
                        },
                    }}},
                },
                "responses": {
                    "200": {"description": "Heartbeat received. May include new_agent_token."},
                    "401": {"description": "Invalid agent token"},
                },
            }
        },
        "/api/agents/{device_id}/tasks": {
            "get": {
                "tags": ["Agents"],
                "summary": "Poll pending tasks",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {"description": "List of pending tasks"},
                    "401": {"description": "Unauthorized"},
                },
            }
        },
        "/api/agents/{device_id}/task_result": {
            "post": {
                "tags": ["Agents"],
                "summary": "Post task result",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["task_id", "type"],
                        "properties": {
                            "task_id": {"type": "string"},
                            "type": {"type": "string"},
                            "exit_code": {"type": "integer"},
                            "stdout": {"type": "string"},
                            "stderr": {"type": "string"},
                        },
                    }}},
                },
                "responses": {"200": {"description": "Result recorded"}},
            }
        },
        "/api/agents/{device_id}/patches": {
            "put": {
                "tags": ["Agents"],
                "summary": "Report pending patches",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Patches recorded"}},
            }
        },
        "/api/agents/{device_id}/software": {
            "put": {
                "tags": ["Agents"],
                "summary": "Report installed software",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Software list updated"}},
            }
        },

        # ── Devices ───────────────────────────────────────────────────────────
        "/api/devices": {
            "get": {
                "tags": ["Devices"],
                "summary": "List devices",
                "parameters": [
                    {"name": "customer_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "platform", "in": "query", "schema": {"type": "string"}},
                    {"name": "status", "in": "query", "schema": {"type": "string"}},
                    {"name": "q", "in": "query", "schema": {"type": "string"}, "description": "Search by hostname"},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {"200": {"description": "Paginated device list"}},
            }
        },
        "/api/devices/{device_id}": {
            "get": {
                "tags": ["Devices"],
                "summary": "Get device",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {"description": "Device object with latest metrics"},
                    "404": {"description": "Not found"},
                },
            },
            "delete": {
                "tags": ["Devices"],
                "summary": "Delete device",
                "description": "Requires admin role.",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {"description": "Deleted"},
                    "403": {"description": "Insufficient permissions"},
                },
            },
        },
        "/api/devices/{device_id}/metrics": {
            "get": {
                "tags": ["Devices"],
                "summary": "Device metric history",
                "parameters": [
                    {"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "hours", "in": "query", "schema": {"type": "integer", "default": 24}},
                ],
                "responses": {"200": {"description": "List of metric snapshots"}},
            }
        },
        "/api/devices/platform_counts": {
            "get": {
                "tags": ["Devices"],
                "summary": "Device count by OS platform",
                "responses": {"200": {"description": "Counts per platform"}},
            }
        },
        "/api/devices/{device_id}/ping_check": {
            "post": {
                "tags": ["Devices"],
                "summary": "Ping agentless device",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Ping result"}},
            }
        },

        # ── Customers ─────────────────────────────────────────────────────────
        "/api/customers/": {
            "get": {
                "tags": ["Customers"],
                "summary": "List customers",
                "parameters": [
                    {"name": "q", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {"200": {"description": "Paginated customer list"}},
            },
            "post": {
                "tags": ["Customers"],
                "summary": "Create customer",
                "description": "Requires admin or technician.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string"},
                            "email": {"type": "string", "format": "email"},
                            "phone": {"type": "string"},
                            "address": {"type": "string"},
                            "tier": {"type": "string", "enum": ["basic", "standard", "premium"]},
                            "notes": {"type": "string"},
                        },
                    }}},
                },
                "responses": {
                    "201": {"description": "Customer created"},
                    "400": {"description": "Validation error"},
                    "403": {"description": "Insufficient permissions"},
                },
            },
        },
        "/api/customers/{customer_id}": {
            "get": {
                "tags": ["Customers"],
                "summary": "Get customer",
                "parameters": [{"name": "customer_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Customer object with device/alert/ticket counts"}},
            },
            "put": {
                "tags": ["Customers"],
                "summary": "Update customer",
                "parameters": [{"name": "customer_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Updated"}},
            },
            "delete": {
                "tags": ["Customers"],
                "summary": "Deactivate customer",
                "description": "Soft-delete (sets is_active=False). Requires admin.",
                "parameters": [{"name": "customer_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Deactivated"}},
            },
        },
        "/api/customers/groups": {
            "get": {
                "tags": ["Customers"],
                "summary": "List device groups",
                "responses": {"200": {"description": "Array of device groups"}},
            },
            "post": {
                "tags": ["Customers"],
                "summary": "Create device group",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["name", "customer_id"],
                        "properties": {
                            "name": {"type": "string"},
                            "customer_id": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    }}},
                },
                "responses": {"201": {"description": "Group created"}},
            },
        },

        # ── Alerts ────────────────────────────────────────────────────────────
        "/api/alert_rules": {
            "get": {
                "tags": ["Alerts"],
                "summary": "List alert rules",
                "parameters": [
                    {"name": "customer_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                ],
                "responses": {"200": {"description": "Paginated alert rules"}},
            },
            "post": {
                "tags": ["Alerts"],
                "summary": "Create alert rule",
                "description": "Requires admin or technician.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["name", "metric", "operator"],
                        "properties": {
                            "name": {"type": "string"},
                            "customer_id": {"type": "string"},
                            "metric": {"type": "string", "enum": ["cpu", "ram", "disk", "offline"]},
                            "operator": {"type": "string", "enum": ["gt", "lt", "gte", "lte", "eq"]},
                            "threshold": {"type": "number"},
                            "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                            "cooldown_minutes": {"type": "integer", "default": 15},
                            "auto_create_ticket": {"type": "boolean"},
                        },
                    }}},
                },
                "responses": {"201": {"description": "Rule created"}},
            },
        },
        "/api/alerts": {
            "get": {
                "tags": ["Alerts"],
                "summary": "List triggered alerts",
                "parameters": [
                    {"name": "device_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["open", "acknowledged", "resolved"]}},
                    {"name": "severity", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                ],
                "responses": {"200": {"description": "Paginated alerts"}},
            }
        },
        "/api/alerts/{alert_id}/acknowledge": {
            "put": {
                "tags": ["Alerts"],
                "summary": "Acknowledge alert",
                "parameters": [{"name": "alert_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Acknowledged"}},
            }
        },
        "/api/alerts/{alert_id}/resolve": {
            "put": {
                "tags": ["Alerts"],
                "summary": "Resolve alert",
                "parameters": [{"name": "alert_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Resolved"}},
            }
        },

        # ── Tickets ───────────────────────────────────────────────────────────
        "/api/tickets/": {
            "get": {
                "tags": ["Tickets"],
                "summary": "List tickets",
                "parameters": [
                    {"name": "customer_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "status", "in": "query", "schema": {"type": "string"}},
                    {"name": "priority", "in": "query", "schema": {"type": "string"}},
                    {"name": "assignee_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {"200": {"description": "Paginated tickets"}},
            },
            "post": {
                "tags": ["Tickets"],
                "summary": "Create ticket",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["title", "customer_id"],
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "customer_id": {"type": "string"},
                            "device_id": {"type": "string"},
                            "assignee_id": {"type": "string"},
                            "priority": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                    }}},
                },
                "responses": {"201": {"description": "Ticket created"}},
            },
        },
        "/api/tickets/{ticket_id}": {
            "get": {
                "tags": ["Tickets"],
                "summary": "Get ticket",
                "parameters": [{"name": "ticket_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Ticket with comments"}},
            },
            "put": {
                "tags": ["Tickets"],
                "summary": "Update ticket",
                "parameters": [{"name": "ticket_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Updated"}},
            },
            "delete": {
                "tags": ["Tickets"],
                "summary": "Delete ticket",
                "description": "Requires admin.",
                "parameters": [{"name": "ticket_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Deleted"}},
            },
        },
        "/api/tickets/{ticket_id}/comments": {
            "post": {
                "tags": ["Tickets"],
                "summary": "Add comment",
                "parameters": [{"name": "ticket_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["body"],
                        "properties": {
                            "body": {"type": "string"},
                            "is_internal": {"type": "boolean", "default": False},
                        },
                    }}},
                },
                "responses": {"201": {"description": "Comment added"}},
            }
        },

        # ── AI Triage ─────────────────────────────────────────────────────────
        "/api/tickets/{ticket_id}/triage/approve": {
            "post": {
                "tags": ["AI Triage"],
                "summary": "Approve a staged (shadow-mode) AI-drafted reply",
                "description": "Admin/technician only. Sends the AI's draft (or reply_override, "
                               "re-scanned for danger patterns) to the customer and resolves the ticket.",
                "parameters": [{"name": "ticket_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": False,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {"reply_override": {"type": "string"}},
                    }}},
                },
                "responses": {
                    "200": {"description": "Approved — resolved and reply sent"},
                    "400": {"description": "No reply text, or it was flagged by the safety scan"},
                    "409": {"description": "Ticket is not currently staged for approval"},
                },
            }
        },
        "/api/tickets/{ticket_id}/triage/reject": {
            "post": {
                "tags": ["AI Triage"],
                "summary": "Reject a staged AI suggestion and escalate to a human",
                "description": "Admin/technician only. Leaves ticket status untouched; optionally assigns it.",
                "parameters": [{"name": "ticket_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": False,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {"assignee_id": {"type": "string"}},
                    }}},
                },
                "responses": {
                    "200": {"description": "Rejected — escalated to human review"},
                    "409": {"description": "Ticket is not currently staged for approval"},
                },
            }
        },
        "/api/triage/categories/": {
            "get": {
                "tags": ["AI Triage"],
                "summary": "List triage categories",
                "description": "The curated whitelist of categories AI triage can classify tickets into, "
                               "each with its own auto_resolve_enabled/shadow_mode/confidence_threshold gate.",
                "responses": {"200": {"description": "Array of category objects"}},
            }
        },
        "/api/triage/categories/{category_id}": {
            "put": {
                "tags": ["AI Triage"],
                "summary": "Update a triage category's gate settings",
                "description": "Admin only.",
                "parameters": [{"name": "category_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "is_active": {"type": "boolean"},
                            "auto_resolve_enabled": {"type": "boolean"},
                            "shadow_mode": {"type": "boolean"},
                            "confidence_threshold": {"type": "number", "minimum": 0, "maximum": 1},
                            "auto_close_days": {"type": "integer", "minimum": 1, "nullable": True},
                        },
                    }}},
                },
                "responses": {
                    "200": {"description": "Updated"},
                    "400": {"description": "Invalid field value"},
                },
            }
        },

        # ── Scripts ───────────────────────────────────────────────────────────
        "/api/scripts/": {
            "get": {
                "tags": ["Scripts"],
                "summary": "List scripts",
                "responses": {"200": {"description": "Script list"}},
            },
            "post": {
                "tags": ["Scripts"],
                "summary": "Create script",
                "description": "Requires admin or technician.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["name", "file_type", "content"],
                        "properties": {
                            "name": {"type": "string"},
                            "file_type": {"type": "string", "enum": ["ps1", "bat", "py", "sh"]},
                            "content": {"type": "string"},
                            "description": {"type": "string"},
                            "os_target": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                    }}},
                },
                "responses": {"201": {"description": "Script created"}},
            },
        },
        "/api/scripts/{script_id}/run": {
            "post": {
                "tags": ["Scripts"],
                "summary": "Run script on device(s)",
                "description": "Requires admin or technician.",
                "parameters": [{"name": "script_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["device_ids"],
                        "properties": {
                            "device_ids": {"type": "array", "items": {"type": "string"}},
                            "timeout_seconds": {"type": "integer", "default": 300},
                        },
                    }}},
                },
                "responses": {
                    "202": {"description": "Run queued"},
                    "403": {"description": "Insufficient permissions"},
                },
            }
        },

        # ── Patches ───────────────────────────────────────────────────────────
        "/api/patches/{device_id}/patches": {
            "get": {
                "tags": ["Patches"],
                "summary": "List pending patches for device",
                "parameters": [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Patch list"}},
            }
        },
        "/api/patches/approve": {
            "post": {
                "tags": ["Patches"],
                "summary": "Approve patches for installation",
                "description": "Queues patch installation task on device. Requires admin or technician.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["patch_ids"],
                        "properties": {
                            "patch_ids": {"type": "array", "items": {"type": "string"}},
                        },
                    }}},
                },
                "responses": {"202": {"description": "Patches queued for installation"}},
            }
        },

        # ── Automation ────────────────────────────────────────────────────────
        "/api/automation/profiles": {
            "get": {
                "tags": ["Automation"],
                "summary": "List automation profiles",
                "responses": {"200": {"description": "Profile list"}},
            },
            "post": {
                "tags": ["Automation"],
                "summary": "Create automation profile",
                "description": "Requires admin or technician.",
                "responses": {"201": {"description": "Profile created"}},
            },
        },
        "/api/automation/profiles/{profile_id}/run": {
            "post": {
                "tags": ["Automation"],
                "summary": "Run profile immediately",
                "parameters": [{"name": "profile_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"202": {"description": "Enqueued"}},
            }
        },

        # ── Dashboard ─────────────────────────────────────────────────────────
        "/api/dashboard/summary": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Overview KPIs",
                "description": "Device/alert/ticket counts. Client role sees only their tenant.",
                "responses": {"200": {"description": "Summary object"}},
            }
        },
        "/api/dashboard/health_map": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Device health map",
                "description": "Up to 500 devices with status/online state for the health grid.",
                "responses": {"200": {"description": "Array of device health objects"}},
            }
        },
        "/api/dashboard/recent_alerts": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "20 most recent alerts",
                "responses": {"200": {"description": "Alert array"}},
            }
        },
        "/api/dashboard/activity_feed": {
            "get": {
                "tags": ["Dashboard"],
                "summary": "Audit activity feed",
                "description": "MSP staff only. Returns last 100 audit events.",
                "responses": {"200": {"description": "Audit log entries"}},
            }
        },

        # ── Network ───────────────────────────────────────────────────────────
        "/api/network/scan": {
            "post": {
                "tags": ["Network"],
                "summary": "Start LAN network scan",
                "description": "Requires admin or technician. ICMP sweep of specified subnet.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["subnet"],
                        "properties": {"subnet": {"type": "string", "example": "192.168.1.0/24"}},
                    }}},
                },
                "responses": {"202": {"description": "Scan started. Poll GET /api/network/scan/{scan_id}"}},
            }
        },
        "/api/network/scan/{scan_id}": {
            "get": {
                "tags": ["Network"],
                "summary": "Get scan results",
                "parameters": [{"name": "scan_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Scan status and discovered hosts"}},
            }
        },

        # ── Terminal ──────────────────────────────────────────────────────────
        "/api/terminal/sessions": {
            "post": {
                "tags": ["Terminal"],
                "summary": "Open terminal session",
                "description": "Requires technician+. Opens an interactive shell session on a device.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["device_id"],
                        "properties": {"device_id": {"type": "string"}},
                    }}},
                },
                "responses": {"201": {"description": "Session created. Use session_id to send commands."}},
            }
        },
        "/api/terminal/sessions/{session_id}/command": {
            "post": {
                "tags": ["Terminal"],
                "summary": "Send command to session",
                "parameters": [{"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["command"],
                        "properties": {"command": {"type": "string"}},
                    }}},
                },
                "responses": {"200": {"description": "Command queued"}},
            }
        },

        # ── Admin ─────────────────────────────────────────────────────────────
        "/api/admin/users": {
            "get": {
                "tags": ["Admin"],
                "summary": "List users",
                "description": "Requires admin or superadmin.",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 20}},
                ],
                "responses": {"200": {"description": "Paginated user list"}},
            },
            "post": {
                "tags": ["Admin"],
                "summary": "Create user",
                "description": "Requires admin.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["email", "password", "role"],
                        "properties": {
                            "email": {"type": "string", "format": "email"},
                            "password": {"type": "string", "minLength": 8},
                            "full_name": {"type": "string"},
                            "role": {"type": "string", "enum": ["admin", "technician", "viewer", "client"]},
                            "customer_id": {"type": "string", "description": "Required for client role"},
                            "must_change_password": {"type": "boolean", "default": False},
                        },
                    }}},
                },
                "responses": {
                    "201": {"description": "User created"},
                    "409": {"description": "Email already exists"},
                },
            },
        },
        "/api/admin/users/{user_id}": {
            "put": {
                "tags": ["Admin"],
                "summary": "Update user",
                "description": "Requires admin.",
                "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Updated"}},
            },
            "delete": {
                "tags": ["Admin"],
                "summary": "Delete user",
                "description": "Requires admin. Cannot delete superadmin.",
                "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {"description": "Deleted"},
                    "403": {"description": "Cannot delete superadmin"},
                },
            },
        },
        "/api/admin/org-token": {
            "get": {
                "tags": ["Admin"],
                "summary": "Get org registration token",
                "description": "Requires admin. Returns the ORG_REGISTRATION_TOKEN for agent enrollment.",
                "responses": {"200": {"description": "Org token"}},
            }
        },

        # ── Billing ───────────────────────────────────────────────────────────
        "/api/billing/invoices": {
            "get": {
                "tags": ["Billing"],
                "summary": "List invoices",
                "parameters": [
                    {"name": "customer_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["draft", "sent", "paid", "overdue"]}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                ],
                "responses": {"200": {"description": "Paginated invoice list"}},
            },
            "post": {
                "tags": ["Billing"],
                "summary": "Create invoice",
                "description": "Requires admin.",
                "responses": {"201": {"description": "Invoice created"}},
            },
        },

        # ── Reports ───────────────────────────────────────────────────────────
        "/api/reports/": {
            "get": {
                "tags": ["Reports"],
                "summary": "List reports",
                "responses": {"200": {"description": "Report list"}},
            },
            "post": {
                "tags": ["Reports"],
                "summary": "Generate report",
                "description": "Requires admin or technician.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["report_type"],
                        "properties": {
                            "report_type": {"type": "string", "enum": ["device_summary", "patch_status", "alert_summary", "billing"]},
                            "customer_id": {"type": "string"},
                            "format": {"type": "string", "enum": ["pdf", "xlsx", "csv"], "default": "pdf"},
                        },
                    }}},
                },
                "responses": {"201": {"description": "Report generated. Download via GET /api/reports/{id}/download"}},
            },
        },
        "/api/reports/{report_id}/download": {
            "get": {
                "tags": ["Reports"],
                "summary": "Download report file",
                "parameters": [{"name": "report_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "File download (application/pdf or application/vnd.ms-excel)"}},
            }
        },

        # ── Usage Monitoring (superadmin only) ───────────────────────────────
        "/api/admin/usage/summary": {
            "get": {
                "tags": ["Usage Monitoring"],
                "summary": "Per-service usage totals + live anomaly flags",
                "description": "Superadmin only — 403 for every other role, including admin.",
                "parameters": [
                    {"name": "range", "in": "query", "schema": {"type": "string", "enum": ["today", "7d", "30d"], "default": "7d"}},
                ],
                "responses": {
                    "200": {"description": "Per-service calls/tokens/estimated cost/error rate + totals + anomalies"},
                    "403": {"description": "Not superadmin"},
                },
            }
        },
        "/api/admin/usage/timeseries": {
            "get": {
                "tags": ["Usage Monitoring"],
                "summary": "Bucketed usage series for charts",
                "description": "Superadmin only.",
                "parameters": [
                    {"name": "range", "in": "query", "schema": {"type": "string", "enum": ["today", "7d", "30d"], "default": "7d"}},
                    {"name": "service", "in": "query", "schema": {"type": "string"}},
                    {"name": "metric", "in": "query", "schema": {"type": "string", "enum": ["calls", "tokens", "cost"], "default": "calls"}},
                ],
                "responses": {"200": {"description": "Time-bucketed points"}, "403": {"description": "Not superadmin"}},
            }
        },
        "/api/admin/usage/by-feature": {
            "get": {
                "tags": ["Usage Monitoring"],
                "summary": "Top features/pages/users by usage",
                "description": "Superadmin only.",
                "parameters": [
                    {"name": "range", "in": "query", "schema": {"type": "string", "enum": ["today", "7d", "30d"], "default": "7d"}},
                    {"name": "service", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "Feature/user breakdown"}, "403": {"description": "Not superadmin"}},
            }
        },
        "/api/admin/usage/events": {
            "get": {
                "tags": ["Usage Monitoring"],
                "summary": "Paginated raw usage event drill-down",
                "description": "Superadmin only. error_message is a truncated exception message only — never a raw response body or secret.",
                "parameters": [
                    {"name": "service", "in": "query", "schema": {"type": "string"}},
                    {"name": "status", "in": "query", "schema": {"type": "string"}},
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 50}},
                ],
                "responses": {"200": {"description": "Paginated event list", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pagination"}}}}, "403": {"description": "Not superadmin"}},
            }
        },
        "/api/admin/usage/alert-config": {
            "get": {
                "tags": ["Usage Monitoring"],
                "summary": "Read the usage spike-alert configuration",
                "description": "Superadmin only.",
                "responses": {"200": {"description": "is_enabled, spike_multiplier, notification_channels"}, "403": {"description": "Not superadmin"}},
            },
            "put": {
                "tags": ["Usage Monitoring"],
                "summary": "Update the usage spike-alert configuration",
                "description": "Superadmin only. Fires real email/Slack/Teams/webhook notifications hourly when enabled and a service exceeds spike_multiplier times its 7-day baseline.",
                "responses": {"200": {"description": "Updated config"}, "403": {"description": "Not superadmin"}},
            },
        },

        # ── Health ────────────────────────────────────────────────────────────
        "/api/health": {
            "get": {
                "tags": ["System"],
                "summary": "Health check",
                "description": "No auth required. Returns DB + Redis status.",
                "security": [],
                "responses": {
                    "200": {"description": "All services healthy"},
                    "503": {"description": "One or more services degraded"},
                },
            }
        },
    },
    "tags": [
        {"name": "Auth", "description": "Authentication and user session management"},
        {"name": "Agents", "description": "Agent registration, heartbeat, task queue"},
        {"name": "Devices", "description": "Managed device inventory and metrics"},
        {"name": "Customers", "description": "Customer accounts and device groups"},
        {"name": "Alerts", "description": "Alert rules and triggered alert management"},
        {"name": "Tickets", "description": "Helpdesk ticket tracking"},
        {"name": "AI Triage", "description": "AI ticket categorization, auto-resolve approval, and the category whitelist"},
        {"name": "Scripts", "description": "Script library and remote execution"},
        {"name": "Patches", "description": "Patch inventory and approval"},
        {"name": "Automation", "description": "Scheduled automation profiles"},
        {"name": "Dashboard", "description": "KPI summary endpoints"},
        {"name": "Network", "description": "LAN discovery and agentless device management"},
        {"name": "Terminal", "description": "Remote shell session management"},
        {"name": "Admin", "description": "User management and org configuration"},
        {"name": "Billing", "description": "Invoice and subscription management"},
        {"name": "Reports", "description": "Report generation and download"},
        {"name": "System", "description": "Infrastructure health checks"},
        {"name": "Usage Monitoring", "description": "API/AI-token usage, cost estimates, and spike alerts — superadmin only"},
    ],
}
