from marshmallow import Schema, fields, validate, EXCLUDE

_PLATFORMS = ("windows", "linux", "macos", "android", "ios", "unknown")


class AgentRegisterSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    org_token = fields.String(required=True, validate=validate.Length(min=1))
    customer_id = fields.String(load_default="", validate=validate.Length(max=36))
    hostname = fields.String(required=True, validate=validate.Length(min=1, max=255))
    mac_address = fields.String(load_default="", validate=validate.Length(max=100))
    serial_number = fields.String(load_default="", validate=validate.Length(max=255))
    platform = fields.String(load_default="windows", validate=validate.OneOf(_PLATFORMS))
    os_name = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    os_version = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    os_build = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=100))
    architecture = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=50))
    cpu_model = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    cpu_cores = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=1, max=256))
    ram_gb = fields.Float(load_default=None, allow_none=True, validate=validate.Range(min=0))
    agent_version = fields.String(load_default="1.0.0", validate=validate.Length(max=50))


class AgentHeartbeatSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    cpu_pct = fields.Float(load_default=0, validate=validate.Range(min=0, max=100))
    ram_pct = fields.Float(load_default=0, validate=validate.Range(min=0, max=100))
    disk_pct = fields.Float(load_default=0, validate=validate.Range(min=0, max=100))
    ram_used_gb = fields.Float(load_default=None, allow_none=True)
    disk_used_gb = fields.Float(load_default=None, allow_none=True)
    disk_total_gb = fields.Float(load_default=None, allow_none=True)
    network_bytes_sent = fields.Integer(load_default=None, allow_none=True)
    network_bytes_recv = fields.Integer(load_default=None, allow_none=True)
    battery_pct = fields.Float(load_default=None, allow_none=True, validate=validate.Range(min=0, max=100))
    battery_plugged = fields.Boolean(load_default=None, allow_none=True)
    uptime_seconds = fields.Integer(load_default=None, allow_none=True)
    top_processes = fields.List(fields.Dict(), load_default=None, allow_none=True)
    disks = fields.List(fields.Dict(), load_default=None, allow_none=True)
    agent_version = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=50))
    cpu_model = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))


class AgentTaskResultSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    task_id = fields.String(required=True, validate=validate.Length(min=1))
    type = fields.String(required=True, validate=validate.Length(min=1))
    exit_code = fields.Integer(load_default=None, allow_none=True)
    stdout = fields.String(load_default="")
    stderr = fields.String(load_default="")


class _SoftwareItemSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name = fields.String(required=True, validate=validate.Length(min=1, max=500))
    version = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    publisher = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    install_date = fields.String(load_default=None, allow_none=True)
    source = fields.String(load_default="registry", validate=validate.Length(max=50))


class AgentSoftwareSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    software = fields.List(fields.Nested(_SoftwareItemSchema), required=True)


class _PatchItemSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name = fields.String(required=True, validate=validate.Length(min=1, max=500))
    kb_id = fields.String(load_default=None, allow_none=True)
    patch_type = fields.String(load_default="feature")


class AgentPatchesSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    patches = fields.List(fields.Nested(_PatchItemSchema), required=True)
