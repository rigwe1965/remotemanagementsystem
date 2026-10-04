from marshmallow import Schema, fields, validate, EXCLUDE

_PLATFORMS = ("windows", "linux", "mac", "android", "ios", "unknown")
_DEVICE_TYPES = ("laptop", "desktop", "mobile", "server", "unknown")


class DeviceCreateSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    hostname = fields.String(required=True, validate=validate.Length(min=1, max=255))
    ip_address = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=45))
    mac_address = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=100))
    platform = fields.String(load_default="unknown", validate=validate.OneOf(_PLATFORMS))
    device_type = fields.String(load_default="unknown", validate=validate.OneOf(_DEVICE_TYPES))
    vendor = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=255))
    customer_id = fields.String(load_default=None, allow_none=True)


class DeviceUpdateSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    display_name = fields.String(allow_none=True, validate=validate.Length(max=255))
    group_id = fields.String(allow_none=True)
    customer_id = fields.String(allow_none=True)
    hostname = fields.String(validate=validate.Length(min=1, max=255))
    platform = fields.String(validate=validate.OneOf(_PLATFORMS))
    device_type = fields.String(validate=validate.OneOf(_DEVICE_TYPES))
    vendor = fields.String(allow_none=True, validate=validate.Length(max=255))


class QueueTaskSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    task_type = fields.String(required=True, validate=validate.Length(min=1))
    timeout_seconds = fields.Integer(load_default=300, validate=validate.Range(min=10, max=3600))


class DeployPatchesSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    patch_ids = fields.List(
        fields.String(validate=validate.Length(min=1)),
        required=True,
        validate=validate.Length(min=1),
    )
